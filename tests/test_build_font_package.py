"""Tests for build_font_package: UFont rewrite + atlas append round-trip."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from build_font_package import (
    ATLAS_NAME_PREFIX,
    SHARED_PALETTE_NAME,
    _bucket_key,
    _resolve_import,
    build_package,
)
from font_config import FontSpec
from ue1_reader import Package


STOCK_DEUSEX_UI = os.environ.get("DX1_TEST_STOCK_DEUSEXUI")
HAS_STOCK = bool(STOCK_DEUSEX_UI) and Path(STOCK_DEUSEX_UI).exists()

CJK_TTF = os.environ.get("DX1_TEST_CJK_TTF")
HAS_TTF = bool(CJK_TTF) and Path(CJK_TTF).exists()

HAS_FIXTURE = HAS_STOCK and HAS_TTF


# ---- pure-Python: bucket key shape ----


def test_bucket_key_groups_identical_specs():
    a = FontSpec(ttf="x.ttf", size_px=10, vsize=10)
    b = FontSpec(ttf="x.ttf", size_px=10, vsize=10)
    assert _bucket_key(a) == _bucket_key(b)


def test_bucket_key_separates_weight():
    a = FontSpec(ttf="x.ttf", size_px=13, vsize=17, weight=400)
    b = FontSpec(ttf="x.ttf", size_px=13, vsize=17, weight=700)
    assert _bucket_key(a) != _bucket_key(b)


def test_bucket_key_separates_ascii_override():
    a = FontSpec(ttf="x.ttf", size_px=10, vsize=10, ascii_ttf=None)
    b = FontSpec(ttf="x.ttf", size_px=10, vsize=10, ascii_ttf="ascii.ttf")
    assert _bucket_key(a) != _bucket_key(b)


def test_bucket_key_separates_vert_align_with_vsize():
    """'top' alignment ignores vsize in key; 'bottom' alignment includes it."""
    a = FontSpec(ttf="x.ttf", size_px=8, vsize=9, vert_align="top")
    b = FontSpec(ttf="x.ttf", size_px=8, vsize=9, vert_align="bottom")
    assert _bucket_key(a) != _bucket_key(b)

    c = FontSpec(ttf="x.ttf", size_px=8, vsize=9, vert_align="bottom")
    d = FontSpec(ttf="x.ttf", size_px=8, vsize=10, vert_align="bottom")
    assert _bucket_key(c) != _bucket_key(d)


# ---- env-gated against stock + a real TTF ----


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExUI.u not available")
def test_resolve_import_finds_texture_class():
    pkg = Package(STOCK_DEUSEX_UI)
    ref = _resolve_import(pkg, "Class", "Texture")
    assert ref < 0
    assert pkg.imports[-(ref + 1)]["object_name"] == "Texture"


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExUI.u not available")
def test_resolve_import_missing_raises():
    pkg = Package(STOCK_DEUSEX_UI)
    with pytest.raises(KeyError):
        _resolve_import(pkg, "Class", "NotARealClassName")


@pytest.mark.skipif(not HAS_FIXTURE,
                    reason="needs stock DeusExUI.u and DX1_TEST_CJK_TTF")
def test_build_package_round_trips(tmp_path):
    """Smoke test: build a single-font config, verify the output parses and
    contains the expected new exports plus a rewritten UFont."""
    # FontMenuSmall has stock vsize=10; pick size_px=10 so render fits.
    font_config = {
        "FontMenuSmall": FontSpec(ttf=CJK_TTF, size_px=10, vsize=10),
    }
    # Minimal charset: ASCII + a few higher codepoints exercises both the
    # basic ASCII page and at least one higher-page bucket without requiring
    # broad glyph coverage from the test font.
    charset = sorted(set(list(range(0x20, 0x7F)) + [0x00A0, 0x2014, 0x2026]))

    out = tmp_path / "out.u"
    new_bytes = build_package(STOCK_DEUSEX_UI, out, font_config, charset)

    assert out.read_bytes() == new_bytes

    pkg_orig = Package(STOCK_DEUSEX_UI)
    pkg_new = Package(str(out))

    # Same UFont count, same names — replacement is in-place.
    orig_fonts = [e["name"] for e in pkg_orig.exports
                  if pkg_orig.resolve_class(e["class_ref"]) == "Font"]
    new_fonts = [e["name"] for e in pkg_new.exports
                 if pkg_new.resolve_class(e["class_ref"]) == "Font"]
    assert orig_fonts == new_fonts

    # New exports: 1 palette + N atlases, all appended past stock count.
    assert len(pkg_new.exports) > len(pkg_orig.exports)
    new_names = [e["name"] for e in pkg_new.exports[len(pkg_orig.exports):]]
    assert new_names[0] == SHARED_PALETTE_NAME
    assert all(n.startswith(ATLAS_NAME_PREFIX) for n in new_names[1:])
    assert len(new_names) >= 2  # at least palette + 1 atlas

    # New texture exports must have Outer = a Font export (brightness immunity).
    font_idx_set = {e["idx"] for e in pkg_new.exports
                    if pkg_new.resolve_class(e["class_ref"]) == "Font"}
    for e in pkg_new.exports[len(pkg_orig.exports):]:
        # group_ref is 1-based ObjRef into export table.
        outer_idx = e["group_ref"] - 1
        assert outer_idx in font_idx_set, (
            f"new export {e['name']} has Outer outside Font set"
        )


@pytest.mark.skipif(not HAS_FIXTURE,
                    reason="needs stock DeusExUI.u and DX1_TEST_CJK_TTF")
def test_build_package_two_fonts_share_atlas(tmp_path):
    """Two FontSpecs with identical bucket key share atlas exports."""
    # FontMenuSmall (vsize=10) + FontMenuSmall_DS (vsize=10) — same stock vsize.
    spec = FontSpec(ttf=CJK_TTF, size_px=10, vsize=10)
    font_config = {
        "FontMenuSmall": spec,
        "FontMenuSmall_DS": spec,
    }
    charset = sorted(set(range(0x20, 0x7F)))

    out = tmp_path / "out.u"
    build_package(STOCK_DEUSEX_UI, out, font_config, charset)

    pkg_orig = Package(STOCK_DEUSEX_UI)
    pkg_new = Package(str(out))

    new_appends = pkg_new.exports[len(pkg_orig.exports):]
    atlas_count = sum(1 for e in new_appends if e["name"].startswith(ATLAS_NAME_PREFIX))
    palette_count = sum(1 for e in new_appends if e["name"] == SHARED_PALETTE_NAME)
    assert palette_count == 1
    # Single bucket → atlas count is decided by charset size, not font count.
    # The same atlas count should appear when only one of the fonts is used.
    out_single = tmp_path / "single.u"
    build_package(STOCK_DEUSEX_UI, out_single,
                  {"FontMenuSmall": spec}, charset)
    pkg_single = Package(str(out_single))
    single_appends = pkg_single.exports[len(pkg_orig.exports):]
    single_atlas_count = sum(1 for e in single_appends
                             if e["name"].startswith(ATLAS_NAME_PREFIX))
    assert atlas_count == single_atlas_count
