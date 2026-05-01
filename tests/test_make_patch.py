"""Tests for make_patch: stage selection, expansion, and toggle handling."""
from __future__ import annotations

from pathlib import Path

import pytest

from make_patch import STAGE_ORDER, select_stages
from patch_paths import load


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


def test_all_expands_to_enabled_stages(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    # dll defaults to off, so `all` must skip it.
    assert select_stages(["all"], cfg) == ["int", "contex", "deusextext", "font"]


def test_all_includes_dll_when_enabled(tmp_path):
    body = MINIMAL_TOML + '\n[stages.dll]\nenable = true\n'
    cfg = load(_write(tmp_path, body))
    assert select_stages(["all"], cfg) == list(STAGE_ORDER)


def test_explicit_stage_order_preserved(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert select_stages(["contex", "int"], cfg) == ["contex", "int"]


def test_explicit_dedupes(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert select_stages(["int", "int", "contex"], cfg) == ["int", "contex"]


def test_all_plus_explicit_dedupes(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL_TOML))
    assert select_stages(["all", "int"], cfg) == ["int", "contex", "deusextext", "font"]


def test_explicit_disabled_stage_raises(tmp_path):
    """Naming a disabled stage on the CLI surfaces the contradiction."""
    body = MINIMAL_TOML  # dll off by default
    cfg = load(_write(tmp_path, body))
    with pytest.raises(SystemExit, match="disabled in config"):
        select_stages(["dll"], cfg)


def test_all_silently_skips_disabled(tmp_path):
    """When `all` resolves to a disabled stage, it's dropped without warning."""
    body = MINIMAL_TOML + '\n[stages.font]\nenable = false\n'
    # Re-parse: font stage now disabled. (TOML: later inline table merges.)
    cfg_path = tmp_path / "patch_config.toml"
    cfg_path.write_text(
        """
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
enable = false
""",
        encoding="utf-8",
    )
    cfg = load(cfg_path)
    assert select_stages(["all"], cfg) == ["int", "contex", "deusextext"]
