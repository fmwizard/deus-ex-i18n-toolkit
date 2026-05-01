"""UE1 FString encode/decode with automatic latin-1 / UTF-16 LE selection.

FString protocol:
- compact_index > 0 → latin-1, 1 byte per char, 1-byte null terminator
- compact_index < 0 → UTF-16 LE, 2 bytes per char, 2-byte null terminator
- |compact_index| = char count INCLUDING the null terminator
"""
from ue1_reader import read_compact_index, write_compact_index


def encode_fstring(s: str) -> bytes:
    """Encode a Python str as UE1 FString bytes.

    Chooses latin-1 if all chars fit, otherwise UTF-16 LE.
    """
    if all(ord(c) < 256 for c in s):
        char_count = len(s) + 1  # include null
        return write_compact_index(char_count) + s.encode('latin-1') + b'\x00'
    else:
        char_count = len(s) + 1  # include null (BMP-only; no surrogate handling)
        return write_compact_index(-char_count) + s.encode('utf-16-le') + b'\x00\x00'


def decode_fstring(buf: bytes, off: int) -> tuple[str, int]:
    """Decode a UE1 FString at buf[off:]. Returns (str, total_consumed_bytes)."""
    cidx, k = read_compact_index(buf, off)
    if cidx >= 0:
        # latin-1
        char_count = cidx
        byte_len = char_count  # 1 byte/char
        body = buf[off + k : off + k + byte_len]
        assert body[-1] == 0, f"latin-1 fstring missing null terminator at off={off}"
        return body[:-1].decode('latin-1'), k + byte_len
    else:
        # UTF-16 LE
        char_count = -cidx
        byte_len = char_count * 2
        body = buf[off + k : off + k + byte_len]
        assert body[-2:] == b'\x00\x00', f"UTF-16 fstring missing null terminator at off={off}"
        return body[:-2].decode('utf-16-le'), k + byte_len
