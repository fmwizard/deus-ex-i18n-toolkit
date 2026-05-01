"""Tests for import_deusextext: ExtString payload rewrite from {key: text}."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from import_deusextext import _build_payload, build, main
from ue1_fstring import decode_fstring, encode_fstring
from ue1_reader import Package


STOCK_DEUSEXTEXT = os.environ.get("DX1_TEST_STOCK_DEUSEXTEXT")
HAS_STOCK = bool(STOCK_DEUSEXTEXT) and Path(STOCK_DEUSEXTEXT).exists()


def test_build_payload_starts_with_zero_header():
    assert _build_payload("hello")[:1] == b'\x00'


def test_build_payload_round_trips_through_decode():
    payload = _build_payload("hello world")
    text, _ = decode_fstring(payload, 1)
    assert text == "hello world"


def test_build_payload_handles_non_ascii():
    payload = _build_payload("斯科特")
    text, _ = decode_fstring(payload, 1)
    assert text == "斯科特"


def test_build_payload_handles_empty_string():
    payload = _build_payload("")
    text, _ = decode_fstring(payload, 1)
    assert text == ""


# ---- env-gated against real stock ----


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_build_replaces_all_extstrings(tmp_path):
    """Round-trip stock content through build() and verify decoded text matches."""
    p = Package(STOCK_DEUSEXTEXT)
    translations = {}
    for e in p.exports:
        if p.resolve_class(e['class_ref']) == 'ExtString':
            raw = p.read_export_bytes(e)
            s, _ = decode_fstring(raw, 1)
            translations[e['name']] = s
    assert translations, "stock package has no ExtString exports?"

    new_buf, stats = build(STOCK_DEUSEXTEXT, translations)
    assert stats['replaced'] == len(translations)
    assert stats['ignored_extra'] == []

    out = tmp_path / "patched.u"
    out.write_bytes(new_buf)
    p_new = Package(str(out))

    for e in p_new.exports:
        if p_new.resolve_class(e['class_ref']) == 'ExtString':
            raw = p_new.read_export_bytes(e)
            s, _ = decode_fstring(raw, 1)
            assert s == translations[e['name']]


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_build_missing_translation_raises():
    p = Package(STOCK_DEUSEXTEXT)
    translations = {}
    skipped_one = False
    for e in p.exports:
        if p.resolve_class(e['class_ref']) == 'ExtString':
            if not skipped_one:
                skipped_one = True
                continue
            raw = p.read_export_bytes(e)
            s, _ = decode_fstring(raw, 1)
            translations[e['name']] = s

    with pytest.raises(ValueError, match="have no translation"):
        build(STOCK_DEUSEXTEXT, translations)


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_build_extra_translation_keys_reported():
    p = Package(STOCK_DEUSEXTEXT)
    translations = {}
    for e in p.exports:
        if p.resolve_class(e['class_ref']) == 'ExtString':
            raw = p.read_export_bytes(e)
            s, _ = decode_fstring(raw, 1)
            translations[e['name']] = s
    translations['__not_a_real_extstring_export__'] = 'ignored'

    _, stats = build(STOCK_DEUSEXTEXT, translations)
    assert '__not_a_real_extstring_export__' in stats['ignored_extra']
    assert stats['replaced'] == len(translations) - 1


# ---- CLI ----


def test_cli_rejects_non_dict_json(tmp_path):
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([{"key": "x", "translation": "y"}]), encoding='utf-8')
    with pytest.raises(SystemExit, match="must be a JSON object"):
        main(["--stock", "ignored",
              "--translations", str(bad),
              "--out", str(tmp_path / "out.u")])


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExText.u not available")
def test_cli_writes_patched_file(tmp_path):
    p = Package(STOCK_DEUSEXTEXT)
    translations = {}
    for e in p.exports:
        if p.resolve_class(e['class_ref']) == 'ExtString':
            raw = p.read_export_bytes(e)
            s, _ = decode_fstring(raw, 1)
            translations[e['name']] = s

    j = tmp_path / "t.json"
    j.write_text(json.dumps(translations), encoding='utf-8')
    out = tmp_path / "patched.u"

    rc = main(["--stock", STOCK_DEUSEXTEXT,
               "--translations", str(j),
               "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert out.stat().st_size > 0
