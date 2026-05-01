import pytest
from contex import encode_fstring, write_compact_index
from ue1_reader import read_compact_index


def test_encode_fstring_ansi():
    body, n = encode_fstring("hello", "ansi")
    assert body == b"hello\x00"
    assert n == 6


def test_encode_fstring_utf16le():
    body, n = encode_fstring("你好", "utf16le")
    assert body == "你好".encode("utf-16-le") + b"\x00\x00"
    assert n == -3


def test_compact_index_roundtrip():
    for v in [0, 1, -1, 63, -63, 64, -64, 8192, -8192, 10079, -3]:
        buf = write_compact_index(v)
        back, _ = read_compact_index(buf, 0)
        assert back == v, f"{v} -> {buf.hex()} -> {back}"


def test_encode_fstring_length_boundary_ansi():
    """ANSI length 63 → 1-byte compact idx; 64 → 2-byte compact idx."""
    _, n63 = encode_fstring("x" * 62, "ansi")
    assert n63 == 63
    _, n64 = encode_fstring("x" * 63, "ansi")
    assert n64 == 64
    ci63 = write_compact_index(n63)
    ci64 = write_compact_index(n64)
    assert len(ci63) == 1
    assert len(ci64) == 2


def test_encode_fstring_empty():
    body, n = encode_fstring("", "ansi")
    assert body == b"\x00"
    assert n == 1


def test_encode_fstring_utf16_length_boundary():
    """UTF-16 length boundary: -63 wchar (1-byte CI) vs -64 wchar (2-byte CI)."""
    _, n63 = encode_fstring("x" * 62, "utf16le")
    assert n63 == -63
    _, n64 = encode_fstring("x" * 63, "utf16le")
    assert n64 == -64
    ci63 = write_compact_index(n63)
    ci64 = write_compact_index(n64)
    assert len(ci63) == 1
    assert len(ci64) == 2


def test_encode_fstring_raises_on_non_latin1_ansi():
    """ansi path must raise UnicodeEncodeError for non-latin-1 chars."""
    with pytest.raises(UnicodeEncodeError):
        encode_fstring("你好", "ansi")
