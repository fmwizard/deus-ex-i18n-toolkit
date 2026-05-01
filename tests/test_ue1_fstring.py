"""Unit tests for ue1_fstring encode/decode."""
import pytest
from ue1_fstring import encode_fstring, decode_fstring


@pytest.mark.parametrize("s", [
    "",
    "hello",
    "<DC=255,255,255>\r\n<P><B>UNATCO</B>\r\n",
    "x" * 63,     # compact_index 1-byte boundary
    "x" * 64,     # compact_index 2-byte boundary
    "x" * 8192,   # compact_index 3-byte boundary
])
def test_roundtrip_ascii(s):
    buf = encode_fstring(s)
    decoded, consumed = decode_fstring(buf, 0)
    assert decoded == s
    assert consumed == len(buf)


@pytest.mark.parametrize("s", [
    "你好",
    "《UNATCO 手册》",
    "<DC=255,255,255>\r\n<P><B>《UNATCO 手册》</B>\r\n",
    "中" * 1000,
])
def test_roundtrip_cjk(s):
    buf = encode_fstring(s)
    decoded, consumed = decode_fstring(buf, 0)
    assert decoded == s
    assert consumed == len(buf)


def test_ascii_encoding_choice():
    """ASCII-only must use latin-1 path (positive cidx)."""
    buf = encode_fstring("hello")
    # first byte is compact_index; positive means high bit 0x80 unset
    assert buf[0] & 0x80 == 0


def test_cjk_encoding_choice():
    """CJK must use UTF-16 path (negative cidx)."""
    buf = encode_fstring("你好")
    # negative compact_index: high bit 0x80 set
    assert buf[0] & 0x80 == 0x80


def test_decode_offset_nonzero():
    """decode_fstring must honour non-zero offsets."""
    prefix = b"\x00\x00\x00"
    buf = prefix + encode_fstring("test")
    decoded, consumed = decode_fstring(buf, len(prefix))
    assert decoded == "test"
    assert consumed == len(buf) - len(prefix)
