"""Tests for verify_deusextext: T1/T2/T3 round-trip checks."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from import_deusextext import build
from ue1_fstring import decode_fstring
from ue1_reader import Package
from verify_deusextext import (
    _read_extstring_translations,
    t1_identity_roundtrip,
    t2_same_content_rewrite,
    t3_patched_against_translations,
)


STOCK_DEUSEXTEXT = os.environ.get("DX1_TEST_STOCK_DEUSEXTEXT")
HAS_STOCK = bool(STOCK_DEUSEXTEXT) and Path(STOCK_DEUSEXTEXT).exists()


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_t1_passes_on_stock():
    assert t1_identity_roundtrip(STOCK_DEUSEXTEXT) is True


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_t2_passes_on_stock():
    assert t2_same_content_rewrite(STOCK_DEUSEXTEXT) is True


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_t3_passes_when_patched_matches_translations(tmp_path):
    p = Package(STOCK_DEUSEXTEXT)
    translations = _read_extstring_translations(p)

    new_buf, _ = build(STOCK_DEUSEXTEXT, translations)
    out = tmp_path / "patched.u"
    out.write_bytes(new_buf)

    assert t3_patched_against_translations(str(out), translations) is True


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_t3_fails_when_translations_dont_match(tmp_path):
    """A divergent translation dict must surface as a T3 failure."""
    p = Package(STOCK_DEUSEXTEXT)
    translations = _read_extstring_translations(p)

    new_buf, _ = build(STOCK_DEUSEXTEXT, translations)
    out = tmp_path / "patched.u"
    out.write_bytes(new_buf)

    diverged = dict(translations)
    for k in list(diverged)[:3]:
        diverged[k] = diverged[k] + " <DIVERGED>"

    assert t3_patched_against_translations(str(out), diverged) is False
