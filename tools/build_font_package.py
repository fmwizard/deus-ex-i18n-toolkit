"""Rewrite UFonts in a stock font package; append a shared palette and atlases.

Pipeline:
  font_config (FontSpec dict) → bucket-group by (ttf, size_px, tier_cell, ...)
  → render per-bucket atlases → append a shared UPalette + per-bucket UTexture
  exports → rewrite each UFont export to point at the new texture refs.

The package layout is preserved: original UFont exports keep their indices
and absolute offsets; new exports are appended after the stock binary
region. UFont outers stay untouched, and new textures inherit their bucket
representative font as Outer so modern renderers' "UI texture" brightness
immunity (Outer ∈ Font) applies to the new atlases.

API
---
    build_package(stock_pkg, out_pkg, font_config, charset)

`font_config` is a `{ufont_name: FontSpec}` dict (load via
`font_config.load_font_config_from_toml`). `charset` is an iterable of int
codepoints (load via `charset.load_charset`).

CLI
---
    python build_font_package.py --stock <stock.u> --out <patched.u> \\
        --fonts-toml <fonts.toml> --package <pkg_name> \\
        --charset <charset.toml|charset.txt>
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from atlas import ATLAS_SIZE, BucketAtlases, build_bucket_atlases, select_tier
from charset import load_charset
from font_config import FontSpec, load_font_config_from_toml
from pages import assemble_pages
from ue1_reader import (
    DEFAULT_NEW_EXPORT_FLAGS,
    DEFAULT_NEW_PALETTE_FLAGS,
    Package,
)
from ue1_texture import FMipmap, UPalette, UTexture
from ue1_ufont import UFont


ATLAS_NAME_PREFIX = "LocAtlas_"
SHARED_PALETTE_NAME = "LocPalette"


def _resolve_import(pkg: Package, class_name: str, object_name: str) -> int:
    for i, imp in enumerate(pkg.imports):
        if imp["class_name"] == class_name and imp["object_name"] == object_name:
            return -(i + 1)
    raise KeyError(f"{class_name}:{object_name} not in imports")


def _build_palette_blob(pkg: Package) -> bytes:
    none_idx = pkg.names.index("None")
    return UPalette(
        none_name_idx=none_idx,
        colors=[(i, i, i, 0xFF) for i in range(256)],
    ).serialize()


def _build_texture_blob(pkg: Package, palette_ref: int, atlas: bytes, abs_start: int) -> bytes:
    ni = lambda n: pkg.names.index(n)
    tex = UTexture(
        none_idx=ni("None"),
        bmasked_idx=ni("bMasked"),
        palette_idx=ni("Palette"),
        ubits_idx=ni("UBits"),
        vbits_idx=ni("VBits"),
        usize_idx=ni("USize"),
        vsize_idx=ni("VSize"),
        uclamp_idx=ni("UClamp"),
        vclamp_idx=ni("VClamp"),
        internal_time_idx=ni("InternalTime"),
        palette_ref=palette_ref,
        usize=ATLAS_SIZE, vsize=ATLAS_SIZE,
        mips=[FMipmap(data=atlas, usize=ATLAS_SIZE, vsize=ATLAS_SIZE)],
    )
    return tex.serialize(abs_start=abs_start)


def _bucket_key(spec: FontSpec) -> tuple:
    """Buckets share an atlas iff every key field matches.

    `tier_cell` (atlas grid size) gates on max(size_px, vsize), so two
    top-align fonts with same (ttf, size_px, ascii_ttf) but different vsize
    falling into different cell tiers must NOT share an atlas. `vert_align`
    (with vsize when 'bottom') matters because bottom alignment shifts glyph
    y by an amount that depends on vsize. `weight` keeps Regular and Bold of
    the same VF-axis font in separate atlases (different ink).
    """
    align_vsize = spec.vsize if spec.vert_align != 'top' else None
    tier_cell = select_tier(spec.size_px, spec.vsize).cell
    return (spec.ttf, spec.size_px, tier_cell, spec.ascii_ttf, spec.vert_align,
            align_vsize, spec.weight)


def build_package(stock_pkg: str | Path,
                  out_pkg: str | Path,
                  font_config: dict[str, FontSpec],
                  charset: list[int]) -> bytes:
    """Build the rewritten package and write to `out_pkg`. Returns the bytes."""
    pkg = Package(str(stock_pkg))

    buckets: dict[tuple, list[str]] = defaultdict(list)
    for name, spec in font_config.items():
        buckets[_bucket_key(spec)].append(name)

    bucket_atlases: dict[tuple, BucketAtlases] = {}
    for key in buckets:
        ttf, size_px, tier_cell, ascii_ttf, vert_align, align_vsize, weight = key
        bucket_vsize = max(font_config[name].vsize for name in buckets[key])
        ba = build_bucket_atlases(
            ttf_path=ttf, size_px=size_px, charset=charset, ascii_ttf_path=ascii_ttf,
            vert_align=vert_align,
            vsize=align_vsize if vert_align == 'bottom' else bucket_vsize,
            weight=weight,
        )
        bucket_atlases[key] = ba
        assert ba.tier.cell == tier_cell, (
            f"bucket key tier_cell {tier_cell} != actual {ba.tier.cell}"
        )
        ascii_tag = f"+{Path(ascii_ttf).stem}" if ascii_ttf else ""
        align_tag = f" align={vert_align}@vsize{align_vsize}" if vert_align != 'top' else ""
        print(f"[bucket {Path(ttf).stem}@{size_px}px{ascii_tag}{align_tag} cell={tier_cell}] "
              f"{len(ba.atlases)} atlases, {len(ba.char_to_glyph)} glyphs, fonts={buckets[key]}")

    # Assign export indices. Palette = first new export; textures follow in
    # deterministic bucket order. Indices are 1-based ObjRef values.
    original_export_count = len(pkg.exports)
    palette_ref_future = original_export_count + 1

    atlas_export_refs: dict[tuple, list[int]] = {}
    texture_positions: list[tuple] = []
    next_ref = palette_ref_future + 1
    # Mixed-type sort key: coerce None → "" / 0 so the seven-tuple compares cleanly.
    for key in sorted(buckets,
                      key=lambda k: (k[0], k[1], k[2], k[3] or "", k[4], k[5] or 0, k[6] or 0)):
        ba = bucket_atlases[key]
        refs = []
        for local_idx, atlas_bytes in enumerate(ba.atlases):
            refs.append(next_ref)
            texture_positions.append((key, local_idx, atlas_bytes))
            next_ref += 1
        atlas_export_refs[key] = refs

    # Build UFont replacement blobs first; their sizes feed abs_start for the
    # appended texture blobs below.
    replacements: dict[str, bytes] = {}
    none_idx = pkg.names.index("None")
    for key, font_names in buckets.items():
        ba = bucket_atlases[key]
        tex_refs = atlas_export_refs[key]
        for name in font_names:
            spec = font_config[name]
            pages = assemble_pages(ba, vsize=spec.vsize, texture_refs=tex_refs)
            blob = UFont(
                none_name_idx=none_idx,
                pages=pages,
                characters_per_page=ba.tier.cpp,
            ).serialize()
            replacements[name] = blob

    # Compute the cursor where palette-blob lands. Package.rewrite() writes:
    #   a) size-changed REPLACEMENT blobs (in pkg.exports order)
    #   b) add_exports blobs (in declaration order)
    # so the cursor at palette landing = pkg.import_offset + Σ replacement deltas.
    replacement_size_delta = 0
    for e in pkg.exports:
        if e["size"] == 0:
            continue
        name = e["name"]
        if name in replacements and len(replacements[name]) != e["size"]:
            replacement_size_delta += len(replacements[name])
    append_cursor = pkg.import_offset + replacement_size_delta

    tex_class_ref = _resolve_import(pkg, "Class", "Texture")
    pal_class_ref = _resolve_import(pkg, "Class", "Palette")

    # Stock pattern: every Texture/Palette belonging to a UFont has Outer = that
    # Font's export. Modern community renderers (d3d10/d3d11) treat textures
    # whose outer is a UFont as UI textures, exempting them from in-game
    # brightness/gamma. Outer=NULL → texture is brightness-affected.
    font_name_to_ref = {
        e["name"]: e["idx"] + 1
        for e in pkg.exports
        if pkg.resolve_class(e["class_ref"]) == "Font"
    }
    bucket_outer_ref: dict[tuple, int] = {}
    for key, font_names in buckets.items():
        rep = sorted(font_names)[0]
        bucket_outer_ref[key] = font_name_to_ref[rep]

    palette_outer_ref = font_name_to_ref[
        sorted(name for names in buckets.values() for name in names)[0]
    ]

    palette_blob = _build_palette_blob(pkg)
    add_exports: list[dict] = [{
        "class_ref": pal_class_ref, "super_ref": 0,
        "group_ref": palette_outer_ref,
        "name": SHARED_PALETTE_NAME, "flags": DEFAULT_NEW_PALETTE_FLAGS,
        "blob": palette_blob,
    }]
    append_cursor += len(palette_blob)

    atlas_global_idx = 0
    for key, _local_idx, atlas_bytes in texture_positions:
        tex_blob = _build_texture_blob(pkg, palette_ref_future, atlas_bytes, abs_start=append_cursor)
        add_exports.append({
            "class_ref": tex_class_ref, "super_ref": 0,
            "group_ref": bucket_outer_ref[key],
            "name": f"{ATLAS_NAME_PREFIX}{atlas_global_idx}", "flags": DEFAULT_NEW_EXPORT_FLAGS,
            "blob": tex_blob,
        })
        append_cursor += len(tex_blob)
        atlas_global_idx += 1

    new_pkg_bytes = pkg.rewrite(replacements=replacements, add_exports=add_exports)
    out_path = Path(out_pkg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(new_pkg_bytes)
    print(f"Wrote {out_path} ({len(new_pkg_bytes)} bytes, +{len(add_exports)} new exports)")
    return new_pkg_bytes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stock", required=True, help="Stock font package path (e.g. DeusExUI.u).")
    ap.add_argument("--out", required=True, help="Output path for the rewritten package.")
    ap.add_argument("--fonts-toml", required=True, help="Path to fonts.toml.")
    ap.add_argument("--package", required=True,
                    help="Package name to look up in fonts.toml [packages.<name>].")
    ap.add_argument("--charset", required=True,
                    help="Charset definition file (charset.toml or charset.txt).")
    args = ap.parse_args(argv)

    font_config = load_font_config_from_toml(args.fonts_toml).package(args.package)
    charset = load_charset(args.charset)

    build_package(
        stock_pkg=args.stock,
        out_pkg=args.out,
        font_config=font_config,
        charset=charset,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
