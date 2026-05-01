import os
from pathlib import Path
import pytest
from ue1_reader import Package
from contex import trailer_conspeech

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


def _mk_synthetic_conspeech(body: bytes, fstr_len_ci: bytes, size_info: int = 5) -> bytes:
    """Build a minimal ConSpeech export in the property-tag layout:
        [CI(name_ref=1)][info byte: ptype=13 (StrProperty), size_info=5, array=0]
        [size_prefix (1B u8)]
        [FString: compact-idx len + body + null]
        [trailing: CI(0 None) terminator]
    """
    fstring = fstr_len_ci + body
    info = 0x0D | (size_info << 4)
    return bytes([0x01, info, len(fstring)]) + fstring + b"\x00"


def test_parse_serialize_roundtrip_synthetic():
    data = _mk_synthetic_conspeech(b"Hello\x00", b"\x06")
    p = trailer_conspeech.parse(data)
    assert p.string_body == "Hello"
    assert p.string_encoding == "ansi"
    rebuilt = trailer_conspeech.serialize(p, p.string_body, p.string_encoding)
    assert rebuilt == data


def test_mutation_conspeech_preserves_trailing():
    data = _mk_synthetic_conspeech(b"Hello\x00", b"\x06")
    p = trailer_conspeech.parse(data)
    new_bytes = trailer_conspeech.serialize(p, "different text", "ansi")
    p2 = trailer_conspeech.parse(new_bytes)
    assert p2.string_body == "different text"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes


def test_encoding_flip_ansi_to_utf16le_conspeech():
    data = _mk_synthetic_conspeech(b"Hello\x00", b"\x06")
    p = trailer_conspeech.parse(data)
    new_bytes = trailer_conspeech.serialize(p, "你好，世界", "utf16le")
    p2 = trailer_conspeech.parse(new_bytes)
    assert p2.string_body == "你好，世界"
    assert p2.string_encoding == "utf16le"
    assert p2.trailing_tag_bytes == p.trailing_tag_bytes


def test_parse_raises_on_bad_data():
    with pytest.raises(ValueError):
        trailer_conspeech.parse(b"\x00" * 20)


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_utf16_re_encode_updates_size_prefix():
    """ConSpeech10076 ANSI→UTF-16 re-encode must emit a correct size_prefix
    for the new (larger) payload.
    """
    pkg = Package(STOCK_CONTEX)
    target = next(e for e in pkg.exports if e["name"] == "ConSpeech10076")
    stock_bytes = pkg.read_export_bytes(target)
    p = trailer_conspeech.parse(stock_bytes, pkg.names)
    assert p.string_body == "Settle down, Agent."

    out = trailer_conspeech.serialize(p, "冷静，探员。", "utf16le")

    from contex import iter_property_tags
    tags = list(iter_property_tags(out, pkg.names))
    speech_tag = next(t for t in tags if t.name_str == "Speech")
    assert speech_tag.ptype == 13
    payload = out[speech_tag.payload_start:speech_tag.payload_start + speech_tag.payload_size]
    from ue1_reader import read_compact_index
    n, k = read_compact_index(payload, 0)
    assert n < 0
    assert abs(n) == 7
    body_bytes = payload[k:k + abs(n) * 2]
    assert body_bytes.endswith(b"\x00\x00")
    assert body_bytes[:-2].decode("utf-16-le") == "冷静，探员。"

    assert out[speech_tag.tag_end:] == p.trailing_tag_bytes


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_parse_all_stock_conspeech_no_spurious_length_prefix():
    """A correctly working parser should produce string_body where the first
    char rarely equals chr(len(body)). High rates of that pattern indicate the
    parser is leaking the size_prefix byte into the body.
    """
    pkg = Package(STOCK_CONTEX)
    exports = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "ConSpeech"]
    false_prefix_count = 0
    for e in exports:
        eb = pkg.read_export_bytes(e)
        p = trailer_conspeech.parse(eb, pkg.names)
        body = p.string_body
        if not body:
            continue
        if len(body) <= 127 and ord(body[0]) == len(body):
            false_prefix_count += 1
    rate = false_prefix_count / len(exports)
    assert rate < 0.01, f"{false_prefix_count}/{len(exports)} = {rate*100:.2f}% spurious"


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_roundtrip_all_conspeech_exports():
    pkg = Package(STOCK_CONTEX)
    exports = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "ConSpeech"]
    assert len(exports) == 10079
    failures = []
    for e in exports:
        eb = pkg.read_export_bytes(e)
        try:
            p = trailer_conspeech.parse(eb, pkg.names)
        except Exception as ex:
            failures.append((e["idx"], str(ex)))
            continue
        rebuilt = trailer_conspeech.serialize(p, p.string_body, p.string_encoding)
        if rebuilt != eb:
            failures.append((e["idx"], f"roundtrip mismatch ({len(rebuilt)}!={len(eb)})"))
    assert failures == [], f"{len(failures)}/{len(exports)} failed: {failures[:5]}"
