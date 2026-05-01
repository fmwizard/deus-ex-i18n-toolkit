"""Tests for patch_paths: schema validation + path resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from patch_paths import (
    DEFAULT_FONT_PACKAGES,
    PatchConfig,
    VALID_FONT_PACKAGES,
    load,
)


MINIMAL_TOML = """
[input]
stock_dir = "stock"

[output]
root = "patch"

[stages.int]
source = "tx/int"

[stages.contex]
translations = "tx/contex.json"

[stages.deusextext]
translations = "tx/deusextext.json"

[stages.font]
fonts_toml = "fonts.toml"
charset = "charset.toml"
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "patch_config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_minimal_toml_loads(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert isinstance(cfg, PatchConfig)
    assert cfg.stock_dir == (tmp_path / "stock").resolve()
    assert cfg.output_root == (tmp_path / "patch").resolve()
    assert cfg.deploy_target is None


def test_path_resolution_relative_vs_absolute(tmp_path):
    abs_dir = tmp_path / "elsewhere"
    abs_dir.mkdir()
    body = MINIMAL_TOML.replace(
        'stock_dir = "stock"',
        f'stock_dir = "{abs_dir.as_posix()}"',
    )
    cfg = load(_write(tmp_path, body))
    assert cfg.stock_dir == abs_dir.resolve()
    assert cfg.output_root == (tmp_path / "patch").resolve()  # still relative


def test_default_enable_flags(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert cfg.int_.enable is True
    assert cfg.contex.enable is True
    assert cfg.deusextext.enable is True
    assert cfg.font.enable is True
    assert cfg.dll.enable is False  # dll defaults to off


def test_int_stage_source_resolved(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert cfg.int_.source == (tmp_path / "tx" / "int").resolve()


def test_font_stage_default_packages(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert cfg.font.packages == DEFAULT_FONT_PACKAGES


def test_font_stage_explicit_packages(tmp_path):
    body = MINIMAL_TOML + '\npackages = ["DeusExUI"]\n'
    cfg = load(_write(tmp_path, body))
    assert cfg.font.packages == ["DeusExUI"]


def test_font_stage_unknown_package_rejected(tmp_path):
    body = MINIMAL_TOML + '\npackages = ["NotAPackage"]\n'
    with pytest.raises(SystemExit, match="unknown name"):
        load(_write(tmp_path, body))


def test_font_stage_empty_packages_rejected(tmp_path):
    body = MINIMAL_TOML + '\npackages = []\n'
    with pytest.raises(SystemExit, match="cannot be empty"):
        load(_write(tmp_path, body))


def test_dll_enable_true(tmp_path):
    body = MINIMAL_TOML + '\n[stages.dll]\nenable = true\n'
    cfg = load(_write(tmp_path, body))
    assert cfg.dll.enable is True


def test_disabled_stage_does_not_require_paths(tmp_path):
    """Disabling a stage means its required keys can stay unset."""
    body = """
[input]
stock_dir = "stock"

[output]
root = "patch"

[stages.int]
enable = false

[stages.contex]
enable = false

[stages.deusextext]
enable = false

[stages.font]
enable = false
"""
    cfg = load(_write(tmp_path, body))
    assert cfg.int_.source is None
    assert cfg.contex.translations is None
    assert cfg.deusextext.translations is None
    assert cfg.font.fonts_toml is None
    assert cfg.font.charset is None


def test_enabled_stage_missing_required_raises(tmp_path):
    body = """
[input]
stock_dir = "stock"
[output]
root = "patch"
[stages.int]
enable = true
"""
    with pytest.raises(SystemExit, match=r"\[stages\.int\]\.source is required"):
        load(_write(tmp_path, body))


def test_deploy_target_resolves(tmp_path):
    deploy_dir = tmp_path / "game"
    deploy_dir.mkdir()
    body = MINIMAL_TOML + f'\n[deploy]\ntarget = "{deploy_dir.as_posix()}"\n'
    cfg = load(_write(tmp_path, body))
    assert cfg.deploy_target == deploy_dir.resolve()


def test_deploy_target_empty_string_means_none(tmp_path):
    body = MINIMAL_TOML + '\n[deploy]\ntarget = ""\n'
    cfg = load(_write(tmp_path, body))
    assert cfg.deploy_target is None


def test_unknown_top_level_key_rejected(tmp_path):
    body = MINIMAL_TOML + '\n[bogus]\nx = 1\n'
    with pytest.raises(SystemExit, match="unknown key"):
        load(_write(tmp_path, body))


def test_unknown_stage_rejected(tmp_path):
    body = MINIMAL_TOML + '\n[stages.bogus]\nenable = true\n'
    with pytest.raises(SystemExit, match=r"\[stages\] unknown key"):
        load(_write(tmp_path, body))


def test_unknown_stage_key_rejected(tmp_path):
    body = MINIMAL_TOML + '\n[stages.int.extra]\nx = 1\n'
    # tomllib turns this into stages.int.extra subtable; loader rejects.
    with pytest.raises(SystemExit, match=r"\[stages\.int\] unknown key"):
        load(_write(tmp_path, body))


def test_missing_input_section_raises(tmp_path):
    body = """
[output]
root = "patch"
"""
    with pytest.raises(SystemExit, match=r"\[input\]\.stock_dir is required"):
        load(_write(tmp_path, body))


def test_missing_output_section_raises(tmp_path):
    body = """
[input]
stock_dir = "stock"
"""
    with pytest.raises(SystemExit, match=r"\[output\]\.root is required"):
        load(_write(tmp_path, body))


def test_enable_must_be_bool(tmp_path):
    body = """
[input]
stock_dir = "stock"
[output]
root = "patch"
[stages.int]
enable = "yes"
"""
    with pytest.raises(SystemExit, match=r"\.enable must be bool"):
        load(_write(tmp_path, body))


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        load(tmp_path / "nope.toml")


def test_default_config_loads_from_cwd(tmp_path, monkeypatch):
    _write(tmp_path, MINIMAL_TOML)
    monkeypatch.chdir(tmp_path)
    cfg = load()
    assert cfg.stock_dir == (tmp_path / "stock").resolve()


def test_default_config_missing_in_cwd_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="not found"):
        load()


def test_example_template_parses():
    """The shipped example template must itself be a valid config."""
    repo = Path(__file__).resolve().parent.parent
    example = repo / "patch_config.toml.example"
    assert example.is_file()
    cfg = load(example)
    assert cfg.dll.enable is False  # dll off by default in template
