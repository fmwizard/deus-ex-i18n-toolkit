"""Tests for charset: TOML loader, TXT loader, dispatch, validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from charset import (
    BMP_MAX,
    load_charset,
    load_charset_from_toml,
    load_charset_from_txt,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_toml_codecs_gb2312_covers_common_cjk(tmp_path):
    toml = _write(tmp_path / "charset.toml", 'codecs = ["gb2312"]\n')
    cs = set(load_charset_from_toml(toml))
    for ch in "杀出重围":
        assert ord(ch) in cs, f"missing {ch}"
    assert ord("A") in cs
    assert ord("0") in cs


def test_toml_ranges(tmp_path):
    toml = _write(tmp_path / "charset.toml", "ranges = [[0x4E00, 0x4E02]]\n")
    cs = load_charset_from_toml(toml)
    assert cs == [0x4E00, 0x4E01, 0x4E02]


def test_toml_codepoints(tmp_path):
    toml = _write(tmp_path / "charset.toml", "codepoints = [0x00A0, 0x2014]\n")
    assert load_charset_from_toml(toml) == [0x00A0, 0x2014]


def test_toml_chars(tmp_path):
    toml = _write(tmp_path / "charset.toml", 'chars = "AB杀出"\n')
    cs = load_charset_from_toml(toml)
    assert cs == sorted({ord("A"), ord("B"), ord("杀"), ord("出")})


def test_toml_all_sources_merged(tmp_path):
    toml = _write(tmp_path / "charset.toml", """
codecs = []
ranges = [[0x30, 0x32]]
codepoints = [0x00A0, 0x2014]
chars = "AB"
""")
    cs = load_charset_from_toml(toml)
    expected = sorted({0x30, 0x31, 0x32, 0x00A0, 0x2014, ord("A"), ord("B")})
    assert cs == expected


def test_toml_output_sorted_and_deduped(tmp_path):
    toml = _write(tmp_path / "charset.toml", """
codepoints = [0x42, 0x42, 0x41, 0x43]
chars = "ABC"
""")
    assert load_charset_from_toml(toml) == [0x41, 0x42, 0x43]


def test_toml_unknown_codec_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", 'codecs = ["totally-not-a-codec"]\n')
    with pytest.raises(SystemExit, match="unknown codec"):
        load_charset_from_toml(toml)


def test_toml_inverted_range_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", "ranges = [[0x100, 0x80]]\n")
    with pytest.raises(SystemExit, match=r"low > high"):
        load_charset_from_toml(toml)


def test_toml_malformed_range_pair_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", "ranges = [[0x10]]\n")
    with pytest.raises(SystemExit, match=r"\[low, high\] pair"):
        load_charset_from_toml(toml)


def test_toml_non_bmp_codepoint_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", f"codepoints = [{BMP_MAX + 1}]\n")
    with pytest.raises(SystemExit, match="out of BMP range"):
        load_charset_from_toml(toml)


def test_toml_negative_codepoint_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", "codepoints = [-1]\n")
    with pytest.raises(SystemExit, match="out of BMP range"):
        load_charset_from_toml(toml)


def test_toml_unknown_top_level_key_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", """
codepoints = [0x41]
mystery = 1
""")
    with pytest.raises(SystemExit, match="unknown top-level key.*mystery"):
        load_charset_from_toml(toml)


def test_toml_empty_charset_rejected(tmp_path):
    toml = _write(tmp_path / "charset.toml", "codecs = []\n")
    with pytest.raises(SystemExit, match="charset is empty"):
        load_charset_from_toml(toml)


def test_toml_missing_file_rejected(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        load_charset_from_toml(tmp_path / "nope.toml")


def test_toml_codecs_must_be_list(tmp_path):
    toml = _write(tmp_path / "charset.toml", 'codecs = "gb2312"\n')
    with pytest.raises(SystemExit, match="codecs must be a list"):
        load_charset_from_toml(toml)


def test_toml_chars_must_be_string(tmp_path):
    toml = _write(tmp_path / "charset.toml", "chars = 42\n")
    with pytest.raises(SystemExit, match="chars must be a string"):
        load_charset_from_toml(toml)


def test_txt_collects_chars_excluding_newlines(tmp_path):
    txt = _write(tmp_path / "charset.txt", "AB\nCD\r\n杀出\n")
    cs = load_charset_from_txt(txt)
    expected = sorted({ord("A"), ord("B"), ord("C"), ord("D"), ord("杀"), ord("出")})
    assert cs == expected
    assert ord("\n") not in cs
    assert ord("\r") not in cs


def test_txt_keeps_ascii_space(tmp_path):
    """ASCII space is a real codepoint a charset may legitimately need."""
    txt = _write(tmp_path / "charset.txt", "A B\n")
    assert ord(" ") in set(load_charset_from_txt(txt))


def test_txt_dedup_and_sort(tmp_path):
    txt = _write(tmp_path / "charset.txt", "BCABA\nCBA")
    assert load_charset_from_txt(txt) == [ord("A"), ord("B"), ord("C")]


def test_txt_empty_file_rejected(tmp_path):
    txt = _write(tmp_path / "charset.txt", "\n\n")
    with pytest.raises(SystemExit, match="charset is empty"):
        load_charset_from_txt(txt)


def test_txt_missing_file_rejected(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        load_charset_from_txt(tmp_path / "nope.txt")


def test_dispatch_toml(tmp_path):
    toml = _write(tmp_path / "charset.toml", "codepoints = [0x41]\n")
    assert load_charset(toml) == [0x41]


def test_dispatch_txt(tmp_path):
    txt = _write(tmp_path / "charset.txt", "A")
    assert load_charset(txt) == [0x41]


def test_dispatch_unsupported_extension(tmp_path):
    p = _write(tmp_path / "charset.json", '["A"]')
    with pytest.raises(SystemExit, match="unsupported charset file extension"):
        load_charset(p)


def test_dispatch_extension_case_insensitive(tmp_path):
    toml = _write(tmp_path / "charset.TOML", "codepoints = [0x42]\n")
    assert load_charset(toml) == [0x42]
