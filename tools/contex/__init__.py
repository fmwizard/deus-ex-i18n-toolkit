"""ConText event parsers. Each text-bearing export class has its own trailer parser.

All parsers expose a uniform interface:
    parse(export_data: bytes, pkg_names: list[str] | None = None) -> ParsedExport
    serialize(parsed: ParsedExport, new_body: str, new_encoding: str) -> bytes

UE1 property-tag serialization (what the engine actually reads):

    [name_ref (compact-idx)]       name-table index of the property name
    [info byte]                    bits 0..3 = ptype, bits 4..6 = size_info, bit 7 = array_flag
    [array index byte (optional)]  present if array_flag==1 AND ptype!=3 (Bool value lives in the flag bit for Bool)
    [size prefix (0/1/2/4 bytes)]  determined by size_info (see size_info_to_size)
    [payload (size bytes)]         depends on ptype
        - StrProperty (13): FString = compact-idx length + body bytes + null
        - IntProperty  (2): 4 bytes int
        - ByteProperty (1): 1 byte
        - ObjectProperty (5): compact-idx object-table ref
        - BoolProperty (3): NO payload; value is the array_flag bit

A "None" name terminates the property stream.  Bytes before the text-bearing
StrProperty (e.g. NameProperty, BoolProperty) are preserved verbatim in
`prefix_tag_bytes`; bytes after (including the terminating None + any extra
property tags or trailing data) are preserved verbatim in `trailing_tag_bytes`.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from ue1_reader import read_compact_index, write_compact_index  # noqa: F401 (re-exported)


# Canonical UE1 ptype values for DX (engine v68).
PTYPE_BYTE = 1
PTYPE_INT = 2
PTYPE_BOOL = 3
PTYPE_FLOAT = 4
PTYPE_OBJECT = 5
PTYPE_NAME = 6
PTYPE_STRING = 7  # obsolete
PTYPE_CLASS = 8
PTYPE_ARRAY = 9
PTYPE_STRUCT = 10
PTYPE_VECTOR = 11
PTYPE_ROTATOR = 12
PTYPE_STR = 13
PTYPE_MAP = 14
PTYPE_FIXED_ARRAY = 15


@dataclass
class ParsedExport:
    """Parsed view of a text-bearing ConText export.

    Fields:
        string_body: decoded Python str (trailing null STRIPPED, no UE1 length
            prefix byte).  Empty for no-string variants (e.g. AddGoal bGoalCompleted branch).
        string_encoding: "ansi" or "utf16le"
        raw_string_offset: byte offset within export_data where the FString
            payload (compact-idx length) starts
        raw_string_length: byte count of the FString payload (compact-idx +
            body + null), i.e. the value the size_prefix encodes

        # Property-tag metadata for the text-bearing StrProperty:
        str_prop_name_ref: name-table index of the StrProperty (e.g. "Speech")
        str_prop_info_byte: original info byte (keeps ptype + array_flag; only
            size_info bits are rewritten during serialize if payload_size grew)
        prefix_tag_bytes: raw bytes of all property tags BEFORE the text-bearing
            StrProperty (preserved verbatim).  Empty for classes where the text
            tag is first (ConSpeech, ConChoice, ConEventAddNote).
        trailing_tag_bytes: raw bytes AFTER the FString payload (preserved
            verbatim).  Includes the remaining property tags + the None
            terminator + any post-None trailer bytes.
    """
    string_body: str
    string_encoding: str  # "ansi" | "utf16le"
    raw_string_offset: int
    raw_string_length: int
    str_prop_name_ref: int = 0
    str_prop_info_byte: int = 0
    prefix_tag_bytes: bytes = b""
    trailing_tag_bytes: bytes = b""


_FIXED_SIZE = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}


def size_info_to_size(size_info: int, data: bytes, off: int) -> tuple[int, int]:
    """Read property-tag payload size given size_info (0-7).

    Returns (payload_size, prefix_consumed).
        size_info 0..4 → fixed 1/2/4/12/16 bytes (no prefix consumed)
        size_info 5    → 1-byte prefix (u8)
        size_info 6    → 2-byte prefix (u16)
        size_info 7    → 4-byte prefix (u32)
    """
    if size_info <= 4:
        return (_FIXED_SIZE[size_info], 0)
    if size_info == 5:
        return (data[off], 1)
    if size_info == 6:
        return (struct.unpack_from("<H", data, off)[0], 2)
    if size_info == 7:
        return (struct.unpack_from("<I", data, off)[0], 4)
    raise ValueError(f"bad size_info {size_info}")


def write_size_prefix(payload_size: int, size_info: int) -> bytes:
    """Serialize the size prefix bytes for a chosen size_info.

    For size_info 0..4 no bytes are written (payload size is implicit).
    Raises ValueError if payload_size doesn't match the fixed slot or overflows
    the prefix capacity.
    """
    if size_info <= 4:
        expected = _FIXED_SIZE[size_info]
        if payload_size != expected:
            raise ValueError(
                f"size_info={size_info} requires payload_size={expected} (got {payload_size})"
            )
        return b""
    if size_info == 5:
        if payload_size > 0xFF:
            raise ValueError(f"payload_size {payload_size} overflows size_info=5 (max 255)")
        return bytes([payload_size])
    if size_info == 6:
        if payload_size > 0xFFFF:
            raise ValueError(f"payload_size {payload_size} overflows size_info=6 (max 65535)")
        return struct.pack("<H", payload_size)
    if size_info == 7:
        if payload_size > 0xFFFFFFFF:
            raise ValueError(f"payload_size {payload_size} overflows size_info=7")
        return struct.pack("<I", payload_size)
    raise ValueError(f"bad size_info {size_info}")


def choose_size_info(payload_size: int) -> int:
    """Pick canonical size_info for a payload size, matching UE1's encoder.

    Observed in stock DX DeusExConText.u: UE1 prefers the fixed slots (3=12B,
    4=16B) over size_info=5 (1-byte prefix) when the payload happens to match
    exactly.  For other sizes it picks the smallest size_info that fits.
    """
    if payload_size == 1: return 0
    if payload_size == 2: return 1
    if payload_size == 4: return 2
    if payload_size == 12: return 3
    if payload_size == 16: return 4
    if payload_size <= 0xFF: return 5
    if payload_size <= 0xFFFF: return 6
    return 7


def decode_info_byte(info: int) -> tuple[int, int, int]:
    """Returns (ptype, size_info, array_flag)."""
    return (info & 0x0F, (info >> 4) & 0x07, (info >> 7) & 0x01)


def encode_info_byte(ptype: int, size_info: int, array_flag: int) -> int:
    """Inverse of decode_info_byte."""
    assert 0 <= ptype <= 15
    assert 0 <= size_info <= 7
    assert 0 <= array_flag <= 1
    return ptype | (size_info << 4) | (array_flag << 7)


@dataclass
class PropertyTag:
    """Raw (unparsed-payload) view of one property tag in an export stream."""
    name_ref: int
    name_str: str
    ptype: int
    size_info: int
    array_flag: int
    tag_start: int       # first byte of compact-idx name_ref
    payload_start: int   # first byte of payload (after info byte, array idx byte, size prefix)
    payload_size: int    # payload byte count (0 for Bool)
    tag_end: int         # one past last payload byte
    struct_name_ref: int | None = None


def iter_property_tags(
    data: bytes,
    pkg_names: list[str],
    start: int = 0,
    max_tags: int = 256,
):
    """Yield PropertyTag for every tag in the stream until a 'None' terminator.

    Does NOT raise on truncated data; simply stops yielding.  The 'None'
    terminator itself is NOT yielded (but its position is computable as
    `last_tag.tag_end` → then the 1-byte CI(0) for 'None').

    Stops early if name_ref is out of range (malformed export).
    """
    off = start
    total = len(data)
    count = 0
    while off < total and count < max_tags:
        tag_start = off
        try:
            name_ref, k = read_compact_index(data, off)
        except Exception:
            return
        if name_ref < 0 or name_ref >= len(pkg_names):
            return
        name = pkg_names[name_ref]
        if name == "None":
            return
        off += k
        if off >= total:
            return
        info = data[off]
        off += 1
        ptype, size_info, array_flag = decode_info_byte(info)
        # Array index byte (1-4 bytes per UE1 spec) follows for array_flag==1
        # when the property holds array data.  For Bool (ptype=3), the "array_flag"
        # bit carries the bool VALUE rather than signalling an array index — no
        # extra byte is consumed.  For other ptypes array_flag==1 means 1-byte idx.
        # (Observed in stock DX: AddGoal/AddNote/ConChoice's BoolProperty entries
        # all have array_flag=1 but payload_size=0 and no array idx byte.)
        struct_name_ref = None
        if ptype == PTYPE_STRUCT:
            try:
                struct_name_ref, sk = read_compact_index(data, off)
                off += sk
            except Exception:
                return
        payload_size, consumed = size_info_to_size(size_info, data, off)
        off += consumed
        payload_start = off
        off += payload_size
        tag_end = off
        yield PropertyTag(
            name_ref=name_ref,
            name_str=name,
            ptype=ptype,
            size_info=size_info,
            array_flag=array_flag,
            tag_start=tag_start,
            payload_start=payload_start,
            payload_size=payload_size,
            tag_end=tag_end,
            struct_name_ref=struct_name_ref,
        )
        count += 1


def find_str_property_tag(
    data: bytes,
    pkg_names: list[str],
    target_name: str,
) -> PropertyTag | None:
    """Find the property tag with the given name (must be StrProperty).

    Returns None if not found.  Raises ValueError if found but not StrProperty.
    """
    for tag in iter_property_tags(data, pkg_names):
        if tag.name_str == target_name:
            if tag.ptype != PTYPE_STR:
                raise ValueError(
                    f"expected StrProperty for {target_name!r}, "
                    f"got ptype={tag.ptype} (info byte size_info={tag.size_info})"
                )
            return tag
    return None


def encode_fstring(body: str, encoding: str) -> tuple[bytes, int]:
    """Encode Python str to UE1 FString body bytes + signed compact-idx length.

    Returns (body_bytes_with_null, signed_length).
    - ansi: body + b"\\x00", length = +N (total bytes incl null)
    - utf16le: body.encode("utf-16-le") + b"\\x00\\x00", length = -N (N = wchar count incl null)

    The ansi path raises UnicodeEncodeError on non-latin-1 chars — callers
    must pre-route non-latin-1 strings to utf16le.
    """
    if encoding == "ansi":
        encoded = body.encode("latin-1") + b"\x00"
        return encoded, len(encoded)
    if encoding == "utf16le":
        encoded = body.encode("utf-16-le") + b"\x00\x00"
        wchar_count = len(encoded) // 2
        return encoded, -wchar_count
    raise ValueError(f"unknown encoding: {encoding}")


def decode_fstring(payload: bytes) -> tuple[str, str]:
    """Decode an FString payload blob (compact-idx length + body + null).

    Returns (text_without_null, encoding) where encoding is "ansi" or "utf16le".
    Raises ValueError if malformed.
    """
    n, k = read_compact_index(payload, 0)
    if n > 0:
        if k + n > len(payload):
            raise ValueError(f"FString truncated: need {k+n} bytes, have {len(payload)}")
        if payload[k + n - 1] != 0:
            raise ValueError("FString missing ansi null terminator")
        return (payload[k:k + n - 1].decode("latin-1"), "ansi")
    if n < 0:
        nc = -n
        wide_bytes = nc * 2
        if k + wide_bytes > len(payload):
            raise ValueError(f"UTF-16 FString truncated: need {k+wide_bytes} bytes, have {len(payload)}")
        if payload[k + wide_bytes - 2:k + wide_bytes] != b"\x00\x00":
            raise ValueError("UTF-16 FString missing null terminator")
        return (payload[k:k + wide_bytes - 2].decode("utf-16-le"), "utf16le")
    raise ValueError("FString has zero length")


def parse_str_property_export(
    data: bytes,
    pkg_names: list[str],
    target_name: str,
) -> ParsedExport:
    """Parse an export whose text payload is a StrProperty named `target_name`.

    Layout:
        [ optional prefix property tags (preserved verbatim) ]
        [ name_ref(target_name) compact-idx ]
        [ info byte (ptype=13, size_info=?, array_flag=0) ]
        [ size prefix (0/1/2/4 bytes per size_info) ]
        [ FString payload: compact-idx length + body + null ]
        [ optional trailing property tags + None terminator + any trailing bytes ]

    Returns a ParsedExport populated with text + metadata.
    Raises ValueError if the target property isn't present or isn't a StrProperty.
    """
    tag = find_str_property_tag(data, pkg_names, target_name)
    if tag is None:
        raise ValueError(f"property tag {target_name!r} not found in export (total={len(data)})")

    payload = data[tag.payload_start:tag.payload_start + tag.payload_size]
    text, encoding = decode_fstring(payload)

    prefix = bytes(data[:tag.tag_start])
    trailing = bytes(data[tag.tag_end:])

    return ParsedExport(
        string_body=text,
        string_encoding=encoding,
        raw_string_offset=tag.payload_start,
        raw_string_length=tag.payload_size,
        str_prop_name_ref=tag.name_ref,
        str_prop_info_byte=data[tag.tag_start + _ci_len(data, tag.tag_start)],
        prefix_tag_bytes=prefix,
        trailing_tag_bytes=trailing,
    )


def _ci_len(data: bytes, off: int) -> int:
    """Length in bytes of the compact-idx at data[off]."""
    _, k = read_compact_index(data, off)
    return k


def serialize_str_property_export(parsed: ParsedExport, new_body: str, new_encoding: str) -> bytes:
    """Rebuild export bytes for a parse_str_property_export()-parsed export.

    Steps:
        1. Encode FString (compact-idx length + body + null) from new_body+new_encoding.
        2. Choose size_info based on new FString byte count.
        3. Rewrite info byte: keep original ptype + array_flag, swap in new size_info.
        4. Emit: prefix_tag_bytes + CI(name_ref) + info + size_prefix + FString + trailing_tag_bytes.
    """
    body_bytes, length = encode_fstring(new_body, new_encoding)
    length_bytes = write_compact_index(length)
    fstring_bytes = length_bytes + body_bytes
    payload_size = len(fstring_bytes)

    new_size_info = choose_size_info(payload_size)
    orig_ptype, _orig_si, orig_array = decode_info_byte(parsed.str_prop_info_byte)
    new_info = encode_info_byte(orig_ptype, new_size_info, orig_array)
    size_prefix_bytes = write_size_prefix(payload_size, new_size_info)

    out = bytearray()
    out += parsed.prefix_tag_bytes
    out += write_compact_index(parsed.str_prop_name_ref)
    out.append(new_info)
    out += size_prefix_bytes
    out += fstring_bytes
    out += parsed.trailing_tag_bytes
    return bytes(out)


def parse_synthetic_one_strprop(data: bytes) -> ParsedExport:
    """Parser for hand-crafted test data that's laid out as:
        [1-byte name_ref CI] [info byte] [size_prefix] [FString] [trailing bytes]

    Used by tests that construct property-tag streams without a full name table.
    The info byte's size_info drives how many size-prefix bytes to consume.
    """
    name_ref, k = read_compact_index(data, 0)
    info = data[k]
    ptype, size_info, array_flag = decode_info_byte(info)
    off = k + 1
    struct_name_ref = None
    if ptype == PTYPE_STRUCT:
        struct_name_ref, sk = read_compact_index(data, off)
        off += sk
    payload_size, consumed = size_info_to_size(size_info, data, off)
    off += consumed
    payload_start = off
    payload = data[payload_start:payload_start + payload_size]
    text, encoding = decode_fstring(payload)
    tag_end = payload_start + payload_size
    return ParsedExport(
        string_body=text,
        string_encoding=encoding,
        raw_string_offset=payload_start,
        raw_string_length=payload_size,
        str_prop_name_ref=name_ref,
        str_prop_info_byte=info,
        prefix_tag_bytes=b"",
        trailing_tag_bytes=bytes(data[tag_end:]),
    )
