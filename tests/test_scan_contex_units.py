"""Unit tests for scan_contex.py helpers that don't require stock data."""
from scan_contex import _scan_props, _decode_object_ref, _decode_fstring, _walk_choice_list


def test_scan_props_object_property():
    """One-property stream: ConSpeech=42 (Object ref).

    Bytes:
      0x01 → CI(1) = name "ConSpeech"
      0x05 → info: ptype=5 Object, size_info=0 (1B), array=0
      0x2A → CI(42) = object ref 42
      0x00 → CI(0) = "None" terminator
    """
    names = ["None", "ConSpeech"]
    stream = bytes([0x01, 0x05, 0x2A, 0x00])
    out = _scan_props(stream, names)
    assert "ConSpeech" in out
    ptype, payload = out["ConSpeech"][0]
    assert ptype == 5
    assert _decode_object_ref(payload) == 42


def test_scan_props_strproperty_decodes():
    """StrProperty payload should decode via _decode_fstring."""
    # name "speakerName" idx=1; FString CI(11) + b"PaulDenton\x00"
    body = b"PaulDenton\x00"
    fstring = bytes([len(body)]) + body  # CI(11) one byte
    info = 0x0D | (5 << 4)  # ptype=13 StrProperty, size_info=5 (1B)
    stream = bytes([0x01, info, len(fstring)]) + fstring + b"\x00"
    names = ["None", "speakerName"]
    out = _scan_props(stream, names)
    ptype, payload = out["speakerName"][0]
    assert ptype == 13
    assert _decode_fstring(payload) == "PaulDenton"


def test_scan_props_malformed_tail_tolerated():
    """Truncated stream returns whatever was parsed; never raises."""
    names = ["None", "ConSpeech"]
    out = _scan_props(bytes([0x01]), names)
    assert isinstance(out, dict)


def test_decode_fstring_utf16():
    """UTF-16 FString (negative length compact-idx)."""
    body_utf16 = "你好".encode("utf-16-le") + b"\x00\x00"
    # length = -3 wchars (incl null) → CI sign bit set + value 3
    from ue1_reader import write_compact_index
    payload = write_compact_index(-3) + body_utf16
    assert _decode_fstring(payload) == "你好"


def test_decode_object_ref_zero():
    assert _decode_object_ref(b"\x00") == 0


def test_walk_choice_list_cycle_protection():
    """Self-loop cycle should terminate via visited set."""
    loop_stream = bytes([0x01, 0x05, 0x02, 0x00])

    class FakePkg:
        def __init__(self):
            self.names = ["None", "nextChoice"]
            self.exports = [
                {"idx": 1, "class_ref": 0},
                {"idx": 2, "class_ref": 0},
            ]

        def resolve_class(self, r):
            return "ConChoice"

        def read_export_bytes(self, e):
            return loop_stream

    pkg = FakePkg()
    out = _walk_choice_list(pkg, 1)
    assert len(out) < 10
    assert isinstance(out, list)
