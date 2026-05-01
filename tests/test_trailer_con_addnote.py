import os
from pathlib import Path
import pytest
from ue1_reader import Package
from contex import trailer_con_addnote

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


def _mk_synthetic_addnote(body: bytes, fstr_len_ci: bytes, size_info: int = 5) -> bytes:
    """Minimal synthetic AddNote: single StrProperty named via name_ref=1."""
    fstring = fstr_len_ci + body
    info = 0x0D | (size_info << 4)
    return bytes([0x01, info, len(fstring)]) + fstring + b"\x00"


def test_parse_serialize_roundtrip_synthetic():
    data = _mk_synthetic_addnote(b"Hello\x00", b"\x06")
    p = trailer_con_addnote.parse(data)
    assert p.string_body == "Hello"
    assert p.string_encoding == "ansi"
    rebuilt = trailer_con_addnote.serialize(p, p.string_body, p.string_encoding)
    assert rebuilt == data


def test_mutation_addnote_preserves_trailing():
    data = _mk_synthetic_addnote(b"Hello\x00", b"\x06")
    p = trailer_con_addnote.parse(data)
    new_bytes = trailer_con_addnote.serialize(p, "different text", "ansi")
    p2 = trailer_con_addnote.parse(new_bytes)
    assert p2.string_body == "different text"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes


def test_encoding_flip_ansi_to_utf16le_addnote():
    data = _mk_synthetic_addnote(b"Hello\x00", b"\x06")
    p = trailer_con_addnote.parse(data)
    new_bytes = trailer_con_addnote.serialize(p, "你好，世界", "utf16le")
    p2 = trailer_con_addnote.parse(new_bytes)
    assert p2.string_body == "你好，世界"
    assert p2.string_encoding == "utf16le"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes


def test_parse_raises_on_bad_data():
    with pytest.raises(ValueError):
        trailer_con_addnote.parse(b"\x00" * 20)


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_roundtrip_all_conaddnote_exports():
    pkg = Package(STOCK_CONTEX)
    exports = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "ConEventAddNote"]
    assert len(exports) == 103
    failures = []
    for e in exports:
        eb = pkg.read_export_bytes(e)
        try:
            p = trailer_con_addnote.parse(eb, pkg.names)
        except Exception as ex:
            failures.append((e["idx"], str(ex)))
            continue
        rebuilt = trailer_con_addnote.serialize(p, p.string_body, p.string_encoding)
        if rebuilt != eb:
            failures.append((e["idx"], f"roundtrip mismatch ({len(rebuilt)}!={len(eb)})"))
    assert failures == [], f"{len(failures)}/{len(exports)} failed: {failures[:5]}"
