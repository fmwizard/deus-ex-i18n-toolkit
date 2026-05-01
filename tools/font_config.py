"""Static font configuration schema for Deus Ex UI UFonts.

The toolkit ships the schema (FontSpec dataclass + STOCK_VSIZE_TABLE) and a
TOML loader that materializes a user-provided fonts.toml into FontSpec dicts.
Glyph rendering primitives (atlas.py._apply_weight() etc.) live in atlas.py.

STOCK_VSIZE_TABLE is the engine ground truth: each UFont's vsize from stock
DeusExUI.u / DXFonts.utx / Extension.u. UI layout (line height, slot
geometry) is coupled to vsize, so a replacement font's vsize MUST match the
stock value unless deliberately bumped via [vsize_overrides] in fonts.toml.
Overrides may only grow (engine reads more atlas rows; shrinking would clip
stock English glyphs that fit at the original vsize).

fonts.toml schema:

    # Optional. Map of UFont name -> bumped vsize (must be > stock).
    [vsize_overrides]
    FontMenuHeaders = 10

    # Required. One subtable per package.
    # TTF paths are resolved relative to the toml file's directory; absolute
    # paths are used as-is.
    [packages.DeusExUI]
    FontMenuSmall       = { ttf = "fonts/cjk-pixel.ttf", size_px = 10, vsize = 10 }
    FontConversation    = { ttf = "fonts/cjk.ttf",       size_px = 13, vsize = 17, weight = 400 }
    FontFixedWidthSmall = { ttf = "fonts/cjk.ttf",       size_px = 10, vsize = 11, ascii_ttf = "fonts/ascii.ttf" }
    FontTiny            = { ttf = "fonts/tiny.ttf",      size_px =  8, vsize =  9, vert_align = "bottom" }

    [packages.DXFonts]
    HUDMessageTrueType  = { ttf = "fonts/cjk.ttf", size_px = 17, vsize = 21, weight = 400 }
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FontSpec:
    ttf: str
    size_px: int
    vsize: int
    # Optional ASCII override. When set, atlas builder renders wchars < 0x80
    # from `ascii_ttf` while the rest comes from `ttf`. Used for fixed-grid
    # cells where the main font's narrower ASCII advances leave visible gaps.
    ascii_ttf: str | None = None
    # Vertical alignment within the atlas cell:
    #   'top'    glyph bbox top -> cell y=0 (default; matches stock English).
    #   'bottom' glyph bbox bottom -> cell y=vsize-1 (anchors descenders to
    #            the slot baseline; useful when slot text-area clipping cuts
    #            the cell top).
    vert_align: str = "top"
    # Variable Font wght axis pin (e.g. 400=Regular, 700=Bold). Required for
    # VFs whose design default is not the desired weight (e.g. NotoSansSC-VF
    # defaults to Thin=100). None leaves the font at its design default.
    weight: int | None = None


VALID_VERT_ALIGN = {"top", "bottom"}
_REQUIRED_KEYS = {"ttf", "size_px", "vsize"}
_OPTIONAL_KEYS = {"ascii_ttf", "vert_align", "weight"}
_ALLOWED_KEYS = _REQUIRED_KEYS | _OPTIONAL_KEYS
_ALLOWED_TOP_LEVEL = {"vsize_overrides", "packages"}


# Stock VSize per UFont, harvested from the three stock DX packages with
# ue1_ufont.py. UI layout math is coupled to these values. See the spec
# section on stock VSize reference if adding more entries.
STOCK_VSIZE_TABLE: dict[str, int] = {
    # DeusExUI.u (23 UFonts)
    "FontMenuSmall":              10,
    "FontMenuSmall_DS":           10,
    "FontMenuHeaders":             9,
    "FontMenuHeaders_DS":         11,
    "FontFixedWidthSmall":        11,
    "FontFixedWidthSmall_DS":     11,
    "FontTiny":                    9,
    "FontMenuTitle":              12,
    "FontTitleLarge":             12,
    "FontHUDWingDings":           12,
    "FontSansSerif_8":            13,
    "FontSansSerif_8_Bold":       13,
    "FontConversation":           17,
    "FontConversationBold":       17,
    "FontFixedWidthLocation":     17,
    "FontLocation":               20,
    "FontComputer8x20_A":         20,
    "FontComputer8x20_B":         20,
    "FontComputer8x20_C":         20,
    "FontConversationLarge":      23,
    "FontConversationLargeBold":  23,
    "FontMenuExtraLarge":         29,
    "FontSpinningDX":             32,
    # DXFonts.utx (2 UFonts)
    "HUDMessageTrueType":         21,
    "MainMenuTrueType":           26,
    # Extension.u Tech series (6 UFonts)
    "TechMedium":                 10,
    "TechMedium_B":               10,
    "TechMedium_DS":              10,
    "TechSmall":                   8,
    "TechSmall_DS":                8,
    "TechTiny":                    6,
}


@dataclass
class FontConfig:
    """Parsed fonts.toml. `packages[<pkg>][<font>]` returns a FontSpec."""
    packages: dict[str, dict[str, FontSpec]] = field(default_factory=dict)
    vsize_overrides: dict[str, int] = field(default_factory=dict)

    def package(self, name: str) -> dict[str, FontSpec]:
        if name not in self.packages:
            raise KeyError(
                f"package {name!r} not in fonts.toml; available: {sorted(self.packages)}"
            )
        return self.packages[name]

    def expected_vsize(self, font_name: str) -> int:
        return self.vsize_overrides.get(font_name, STOCK_VSIZE_TABLE[font_name])


def _resolve_ttf(raw: str, base_dir: Path) -> str:
    p = Path(raw)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    if not p.is_file():
        raise SystemExit(f"TTF path not found: {p}")
    return str(p)


def _validate_vsize_overrides(raw: dict) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise SystemExit(f"[vsize_overrides] must be a table, got {type(raw).__name__}")
    out: dict[str, int] = {}
    for name, value in raw.items():
        if name not in STOCK_VSIZE_TABLE:
            raise SystemExit(
                f"[vsize_overrides] unknown UFont {name!r}; "
                f"must be one of STOCK_VSIZE_TABLE entries"
            )
        if not isinstance(value, int) or isinstance(value, bool):
            raise SystemExit(
                f"[vsize_overrides] {name}: vsize must be int, got {type(value).__name__}"
            )
        stock = STOCK_VSIZE_TABLE[name]
        if value <= stock:
            raise SystemExit(
                f"[vsize_overrides] {name}: override vsize={value} must be > "
                f"stock vsize={stock} (overrides may only grow)"
            )
        out[name] = value
    return out


def _build_font_spec(
    pkg_name: str,
    font_name: str,
    entry: dict,
    expected_vsize: int,
    base_dir: Path,
) -> FontSpec:
    if not isinstance(entry, dict):
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: entry must be a table, "
            f"got {type(entry).__name__}"
        )
    keys = set(entry.keys())
    missing = _REQUIRED_KEYS - keys
    if missing:
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: missing required key(s) {sorted(missing)}"
        )
    extras = keys - _ALLOWED_KEYS
    if extras:
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: unknown key(s) {sorted(extras)}; "
            f"allowed: {sorted(_ALLOWED_KEYS)}"
        )

    ttf = entry["ttf"]
    size_px = entry["size_px"]
    vsize = entry["vsize"]
    if not isinstance(ttf, str):
        raise SystemExit(f"packages.{pkg_name}.{font_name}: ttf must be a string")
    if not isinstance(size_px, int) or isinstance(size_px, bool) or size_px <= 0:
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: size_px must be a positive int"
        )
    if not isinstance(vsize, int) or isinstance(vsize, bool) or vsize <= 0:
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: vsize must be a positive int"
        )
    if vsize != expected_vsize:
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: vsize={vsize} != expected "
            f"{expected_vsize} (stock={STOCK_VSIZE_TABLE[font_name]})"
        )

    ascii_ttf = entry.get("ascii_ttf")
    if ascii_ttf is not None:
        if not isinstance(ascii_ttf, str):
            raise SystemExit(
                f"packages.{pkg_name}.{font_name}: ascii_ttf must be a string"
            )
        ascii_ttf = _resolve_ttf(ascii_ttf, base_dir)

    vert_align = entry.get("vert_align", "top")
    if vert_align not in VALID_VERT_ALIGN:
        raise SystemExit(
            f"packages.{pkg_name}.{font_name}: vert_align must be one of "
            f"{sorted(VALID_VERT_ALIGN)}, got {vert_align!r}"
        )

    weight = entry.get("weight")
    if weight is not None:
        if not isinstance(weight, int) or isinstance(weight, bool):
            raise SystemExit(
                f"packages.{pkg_name}.{font_name}: weight must be int or omitted"
            )

    return FontSpec(
        ttf=_resolve_ttf(ttf, base_dir),
        size_px=size_px,
        vsize=vsize,
        ascii_ttf=ascii_ttf,
        vert_align=vert_align,
        weight=weight,
    )


def load_font_config_from_toml(toml_path: str | Path) -> FontConfig:
    """Parse a fonts.toml into a FontConfig.

    Raises SystemExit on any schema violation (unknown UFont, vsize mismatch,
    shrinking override, missing TTF, malformed entry).
    """
    path = Path(toml_path)
    if not path.is_file():
        raise SystemExit(f"fonts.toml not found: {path}")
    base_dir = path.parent.resolve()

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    extras = set(raw.keys()) - _ALLOWED_TOP_LEVEL
    if extras:
        raise SystemExit(
            f"{path.name}: unknown top-level key(s) {sorted(extras)}; "
            f"allowed: {sorted(_ALLOWED_TOP_LEVEL)}"
        )

    vsize_overrides = _validate_vsize_overrides(raw.get("vsize_overrides", {}))

    raw_packages = raw.get("packages", {})
    if not isinstance(raw_packages, dict):
        raise SystemExit(f"[packages] must be a table, got {type(raw_packages).__name__}")
    if not raw_packages:
        raise SystemExit(f"{path.name}: at least one [packages.<name>] subtable is required")

    config = FontConfig(vsize_overrides=vsize_overrides)
    for pkg_name, raw_entries in raw_packages.items():
        if not isinstance(raw_entries, dict):
            raise SystemExit(
                f"packages.{pkg_name}: must be a table, got {type(raw_entries).__name__}"
            )
        specs: dict[str, FontSpec] = {}
        for font_name, entry in raw_entries.items():
            if font_name not in STOCK_VSIZE_TABLE:
                raise SystemExit(
                    f"packages.{pkg_name}.{font_name}: unknown UFont; "
                    f"must be one of STOCK_VSIZE_TABLE entries"
                )
            expected_vsize = vsize_overrides.get(font_name, STOCK_VSIZE_TABLE[font_name])
            specs[font_name] = _build_font_spec(
                pkg_name, font_name, entry, expected_vsize, base_dir
            )
        config.packages[pkg_name] = specs

    return config
