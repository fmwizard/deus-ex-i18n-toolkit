"""Tests for scan_deusextext."""
import json
import os
from pathlib import Path

import pytest

from scan_deusextext import scan, main

STOCK_DEUSEXTEXT = os.environ.get("DX1_TEST_STOCK_DEUSEXTEXT")
HAS_STOCK = bool(STOCK_DEUSEXTEXT) and Path(STOCK_DEUSEXTEXT).exists()


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXTEXT not set")
def test_scan_returns_dict_keyed_by_export_name():
    out = scan(STOCK_DEUSEXTEXT)
    assert isinstance(out, dict)
    assert out, "expected at least one ExtString in stock"
    for k, v in out.items():
        assert isinstance(k, str)
        assert isinstance(v, str)


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXTEXT not set")
def test_known_book_and_datacube_keys_present():
    """Stock DX has named ExtStrings for books / datacubes / infolinks."""
    out = scan(STOCK_DEUSEXTEXT)
    assert "00_Book01" in out
    assert "00_Datacube01" in out
    assert len(out) >= 400


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXTEXT not set")
def test_keys_match_import_deusextext_consumer():
    """scan output keys must align with import_deusextext.build() expectations
    (it requires every ExtString export name to appear in the translations dict)."""
    from import_deusextext import build
    en = scan(STOCK_DEUSEXTEXT)
    new_buf, stats = build(STOCK_DEUSEXTEXT, en)
    assert stats["replaced"] == len(en)
    assert stats["ignored_extra"] == []


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXTEXT not set")
def test_cli_writes_json(tmp_path):
    out_path = tmp_path / "en.json"
    rc = main(["--stock", STOCK_DEUSEXTEXT, "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data
