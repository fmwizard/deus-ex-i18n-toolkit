import os
from pathlib import Path
import pytest
from ue1_reader import Package
from contex import trailer_conchoice

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


def _mk_synthetic_conchoice(body: bytes, fstr_len_ci: bytes, size_info: int = 5) -> bytes:
    """Minimal synthetic ConChoice: single StrProperty named via name_ref=1."""
    fstring = fstr_len_ci + body
    info = 0x0D | (size_info << 4)
    return bytes([0x01, info, len(fstring)]) + fstring + b"\x00"


def test_parse_serialize_roundtrip_synthetic():
    data = _mk_synthetic_conchoice(b"Hello\x00", b"\x06")
    p = trailer_conchoice.parse(data)
    assert p.string_body == "Hello"
    assert p.string_encoding == "ansi"
    rebuilt = trailer_conchoice.serialize(p, p.string_body, p.string_encoding)
    assert rebuilt == data


def test_mutation_conchoice_preserves_trailing():
    data = _mk_synthetic_conchoice(b"Hello\x00", b"\x06")
    p = trailer_conchoice.parse(data)
    new_bytes = trailer_conchoice.serialize(p, "different text", "ansi")
    p2 = trailer_conchoice.parse(new_bytes)
    assert p2.string_body == "different text"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes


def test_encoding_flip_ansi_to_utf16le_conchoice():
    data = _mk_synthetic_conchoice(b"Hello\x00", b"\x06")
    p = trailer_conchoice.parse(data)
    new_bytes = trailer_conchoice.serialize(p, "你好，世界", "utf16le")
    p2 = trailer_conchoice.parse(new_bytes)
    assert p2.string_body == "你好，世界"
    assert p2.string_encoding == "utf16le"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes


def test_parse_raises_on_bad_data():
    with pytest.raises(ValueError):
        trailer_conchoice.parse(b"\x00" * 20)


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_roundtrip_all_conchoice_exports():
    pkg = Package(STOCK_CONTEX)
    exports = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "ConChoice"]
    assert len(exports) == 408
    failures = []
    for e in exports:
        eb = pkg.read_export_bytes(e)
        try:
            p = trailer_conchoice.parse(eb, pkg.names)
        except Exception as ex:
            failures.append((e["idx"], str(ex)))
            continue
        rebuilt = trailer_conchoice.serialize(p, p.string_body, p.string_encoding)
        if rebuilt != eb:
            failures.append((e["idx"], f"roundtrip mismatch ({len(rebuilt)}!={len(eb)})"))
    assert failures == [], f"{len(failures)}/{len(exports)} failed: {failures[:5]}"
