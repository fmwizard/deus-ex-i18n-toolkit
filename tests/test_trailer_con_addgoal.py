import os
from pathlib import Path
import pytest
from ue1_reader import Package
from contex import trailer_con_addgoal

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


def _mk_synthetic_addgoal_has_string(body: bytes, fstr_len_ci: bytes, size_info: int = 5) -> bytes:
    """has-string synthetic: 5-byte prefix (byte[4]=0x33) + StrProperty tag + trailer.

    Parser sees byte[4]==0x33, treats bytes [0:5] as opaque prefix, then parses
    a StrProperty tag starting at offset 5.
    """
    prefix = b"\x2a\x16\x01\x01\x33"
    fstring = fstr_len_ci + body
    info = 0x0D | (size_info << 4)
    tag = bytes([0x01, info, len(fstring)]) + fstring
    trailer = b"\x03\x01\x0c\x02\x15\x01\x00"
    return prefix + tag + trailer


def _mk_synthetic_addgoal_no_string() -> bytes:
    """no-string synthetic: byte[4]==0x31 ⇒ fully opaque passthrough."""
    return b"\x2a\x16\x52\x05\x31\xd3\x00\x03\x01\x0c\x02\x15\x71\x23\x01\x05\x26\x00"


def test_parse_no_string_synthetic():
    data = _mk_synthetic_addgoal_no_string()
    p = trailer_con_addgoal.parse(data)
    assert p.string_body == ""
    rebuilt = trailer_con_addgoal.serialize(p, p.string_body, p.string_encoding)
    assert rebuilt == data


def test_parse_has_string_synthetic():
    data = _mk_synthetic_addgoal_has_string(b"Hello\x00", b"\x06")
    p = trailer_con_addgoal.parse(data)
    assert p.string_body == "Hello"
    assert p.string_encoding == "ansi"
    rebuilt = trailer_con_addgoal.serialize(p, p.string_body, p.string_encoding)
    assert rebuilt == data


def test_mutation_addgoal_has_string_preserves_trailing():
    data = _mk_synthetic_addgoal_has_string(b"Hello\x00", b"\x06")
    p = trailer_con_addgoal.parse(data)
    new_bytes = trailer_con_addgoal.serialize(p, "different text", "ansi")
    p2 = trailer_con_addgoal.parse(new_bytes)
    assert p2.string_body == "different text"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes
    assert p2.prefix_tag_bytes == p.prefix_tag_bytes


def test_encoding_flip_ansi_to_utf16le_addgoal():
    data = _mk_synthetic_addgoal_has_string(b"Hello\x00", b"\x06")
    p = trailer_con_addgoal.parse(data)
    new_bytes = trailer_con_addgoal.serialize(p, "你好，世界", "utf16le")
    p2 = trailer_con_addgoal.parse(new_bytes)
    assert p2.string_body == "你好，世界"
    assert p2.string_encoding == "utf16le"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes
    assert p2.prefix_tag_bytes == p.prefix_tag_bytes


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_roundtrip_all_conaddgoal_exports():
    pkg = Package(STOCK_CONTEX)
    exports = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "ConEventAddGoal"]
    assert len(exports) == 337
    failures = []
    for e in exports:
        eb = pkg.read_export_bytes(e)
        try:
            p = trailer_con_addgoal.parse(eb, pkg.names)
        except Exception as ex:
            failures.append((e["idx"], str(ex)))
            continue
        rebuilt = trailer_con_addgoal.serialize(p, p.string_body, p.string_encoding)
        if rebuilt != eb:
            failures.append((e["idx"], f"roundtrip mismatch ({len(rebuilt)}!={len(eb)})"))
    assert failures == [], f"{len(failures)}/{len(exports)} failed: {failures[:5]}"
