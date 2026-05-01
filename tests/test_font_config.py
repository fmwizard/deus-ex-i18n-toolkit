"""Tests for font_config: FontSpec schema, STOCK_VSIZE_TABLE, TOML loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from font_config import (
    FontConfig,
    FontSpec,
    STOCK_VSIZE_TABLE,
    load_font_config_from_toml,
)


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


def _write_toml(tmp_path: Path, body: str, fonts: dict[str, Path] | None = None) -> Path:
    if fonts:
        for rel, _src in fonts.items():
            _touch(tmp_path / rel)
    toml_path = tmp_path / "fonts.toml"
    toml_path.write_text(body, encoding="utf-8")
    return toml_path


def test_font_spec_defaults():
    spec = FontSpec(ttf="x.ttf", size_px=10, vsize=10)
    assert spec.ascii_ttf is None
    assert spec.vert_align == "top"
    assert spec.weight is None


def test_font_spec_is_hashable():
    a = FontSpec(ttf="x.ttf", size_px=10, vsize=10)
    b = FontSpec(ttf="x.ttf", size_px=10, vsize=10)
    assert {a, b} == {a}


def test_stock_vsize_table_covers_all_dx_ufonts():
    expected_deusexui = {
        "FontMenuSmall", "FontMenuSmall_DS", "FontMenuHeaders", "FontMenuHeaders_DS",
        "FontFixedWidthSmall", "FontFixedWidthSmall_DS", "FontTiny",
        "FontMenuTitle", "FontTitleLarge", "FontHUDWingDings",
        "FontSansSerif_8", "FontSansSerif_8_Bold",
        "FontConversation", "FontConversationBold", "FontFixedWidthLocation",
        "FontLocation", "FontComputer8x20_A", "FontComputer8x20_B", "FontComputer8x20_C",
        "FontConversationLarge", "FontConversationLargeBold",
        "FontMenuExtraLarge", "FontSpinningDX",
    }
    assert expected_deusexui.issubset(STOCK_VSIZE_TABLE.keys())
    assert {"HUDMessageTrueType", "MainMenuTrueType"}.issubset(STOCK_VSIZE_TABLE.keys())
    assert {"TechMedium", "TechSmall", "TechTiny"}.issubset(STOCK_VSIZE_TABLE.keys())


def test_loader_happy_path(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation     = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17, weight = 400 }
FontConversationBold = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17, weight = 700 }
FontFixedWidthSmall  = { ttf = "fonts/cjk.ttf", size_px = 10, vsize = 11, ascii_ttf = "fonts/ascii.ttf" }
FontTiny             = { ttf = "fonts/tiny.ttf", size_px = 8, vsize = 9, vert_align = "bottom" }

[packages.DXFonts]
HUDMessageTrueType = { ttf = "fonts/cjk.ttf", size_px = 17, vsize = 21, weight = 400 }
""", fonts={
        "fonts/cjk.ttf": tmp_path,
        "fonts/ascii.ttf": tmp_path,
        "fonts/tiny.ttf": tmp_path,
    })

    cfg = load_font_config_from_toml(toml)
    assert isinstance(cfg, FontConfig)
    assert set(cfg.packages) == {"DeusExUI", "DXFonts"}

    convo = cfg.package("DeusExUI")["FontConversation"]
    assert convo.size_px == 13
    assert convo.vsize == 17
    assert convo.weight == 400
    assert convo.vert_align == "top"
    assert convo.ascii_ttf is None
    assert Path(convo.ttf).is_file()
    assert Path(convo.ttf).name == "cjk.ttf"

    hybrid = cfg.package("DeusExUI")["FontFixedWidthSmall"]
    assert hybrid.ascii_ttf is not None
    assert Path(hybrid.ascii_ttf).name == "ascii.ttf"

    tiny = cfg.package("DeusExUI")["FontTiny"]
    assert tiny.vert_align == "bottom"


def test_relative_paths_resolve_against_toml_dir(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17 }
""", fonts={"fonts/cjk.ttf": tmp_path})
    cfg = load_font_config_from_toml(toml)
    spec = cfg.package("DeusExUI")["FontConversation"]
    assert Path(spec.ttf).is_absolute()
    assert Path(spec.ttf).parent.name == "fonts"


def test_absolute_path_preserved(tmp_path):
    abs_ttf = _touch(tmp_path / "elsewhere" / "abs.ttf").resolve()
    toml_body = f"""
[packages.DeusExUI]
FontConversation = {{ ttf = "{abs_ttf.as_posix()}", size_px = 13, vsize = 17 }}
"""
    toml = _write_toml(tmp_path, toml_body)
    cfg = load_font_config_from_toml(toml)
    spec = cfg.package("DeusExUI")["FontConversation"]
    assert Path(spec.ttf) == abs_ttf


def test_vsize_overrides_apply(tmp_path):
    toml = _write_toml(tmp_path, """
[vsize_overrides]
FontMenuHeaders = 10  # stock=9 -> 10

[packages.DeusExUI]
FontMenuHeaders = { ttf = "fonts/cjk.ttf", size_px = 10, vsize = 10 }
""", fonts={"fonts/cjk.ttf": tmp_path})
    cfg = load_font_config_from_toml(toml)
    assert cfg.vsize_overrides == {"FontMenuHeaders": 10}
    assert cfg.expected_vsize("FontMenuHeaders") == 10
    assert cfg.expected_vsize("FontMenuSmall") == STOCK_VSIZE_TABLE["FontMenuSmall"]


def test_unknown_ufont_in_packages_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontTotallyMadeUp = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17 }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="FontTotallyMadeUp.*unknown UFont"):
        load_font_config_from_toml(toml)


def test_unknown_ufont_in_overrides_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[vsize_overrides]
FontMadeUp = 99
""")
    with pytest.raises(SystemExit, match=r"unknown UFont 'FontMadeUp'"):
        load_font_config_from_toml(toml)


def test_vsize_mismatch_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 18 }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="vsize=18 != expected 17"):
        load_font_config_from_toml(toml)


def test_shrinking_vsize_override_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[vsize_overrides]
FontConversation = 16  # stock=17 -> illegal shrink
""")
    with pytest.raises(SystemExit, match="must be > stock vsize=17"):
        load_font_config_from_toml(toml)


def test_equal_vsize_override_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[vsize_overrides]
FontConversation = 17  # stock==override is pointless and likely a mistake
""")
    with pytest.raises(SystemExit, match="must be > stock vsize=17"):
        load_font_config_from_toml(toml)


def test_missing_required_key_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", vsize = 17 }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="missing required key.*size_px"):
        load_font_config_from_toml(toml)


def test_unknown_entry_key_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17, color = "red" }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="unknown key.*color"):
        load_font_config_from_toml(toml)


def test_bad_vert_align_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17, vert_align = "middle" }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="vert_align must be one of"):
        load_font_config_from_toml(toml)


def test_missing_ttf_file_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/does_not_exist.ttf", size_px = 13, vsize = 17 }
""")
    with pytest.raises(SystemExit, match="TTF path not found"):
        load_font_config_from_toml(toml)


def test_missing_ascii_ttf_file_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontFixedWidthSmall = { ttf = "fonts/cjk.ttf", size_px = 10, vsize = 11, ascii_ttf = "fonts/missing.ttf" }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="TTF path not found"):
        load_font_config_from_toml(toml)


def test_unknown_top_level_key_rejected(tmp_path):
    toml = _write_toml(tmp_path, """
[mystery]
foo = 1

[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17 }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="unknown top-level key.*mystery"):
        load_font_config_from_toml(toml)


def test_empty_packages_rejected(tmp_path):
    toml = _write_toml(tmp_path, "[packages]\n")
    with pytest.raises(SystemExit, match="at least one"):
        load_font_config_from_toml(toml)


def test_missing_toml_file_rejected(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        load_font_config_from_toml(tmp_path / "nope.toml")


def test_package_lookup_unknown_raises():
    cfg = FontConfig(packages={"DeusExUI": {}})
    with pytest.raises(KeyError, match="DXFonts"):
        cfg.package("DXFonts")


def test_weight_must_be_int(tmp_path):
    toml = _write_toml(tmp_path, """
[packages.DeusExUI]
FontConversation = { ttf = "fonts/cjk.ttf", size_px = 13, vsize = 17, weight = "bold" }
""", fonts={"fonts/cjk.ttf": tmp_path})
    with pytest.raises(SystemExit, match="weight must be int"):
        load_font_config_from_toml(toml)
