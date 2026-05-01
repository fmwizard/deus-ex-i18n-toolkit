"""ConEventAddGoal trailer parser — UE1 property-tag stream.

Two observed branches (DX stock):

1. no-string branch (170/337 exports):
    [goalName (NameProperty)]
    [bGoalCompleted (BoolProperty)]
    [eventType (ByteProperty) = 12]
    [nextEvent (ObjectProperty)]
    [Conversation (ObjectProperty)]
    [None]

2. has-string branch (164/337 exports):
    [goalName (NameProperty)]
    [goalText (StrProperty) — translatable]
    [bPrimaryGoal (BoolProperty)]
    [eventType (ByteProperty) = 12]
    [nextEvent (ObjectProperty)]
    [Conversation (ObjectProperty)]
    [None]

+ 14 exports have a `Label` StrProperty — code-identifier (Hop/Done/Primary/...),
not translatable; ignored even when present.

Parser identifies the branch by searching for a "goalText" StrProperty.  If absent,
the export is opaque passthrough.  If present, rewrite goalText's payload.
"""
from __future__ import annotations

from contex import (
    ParsedExport,
    find_str_property_tag,
    parse_str_property_export,
    serialize_str_property_export,
)

TARGET_PROP = "goalText"
_HAS_STRING_FLAG = 0x33
_NO_STRING_FLAG = 0x31


def parse(export_data: bytes, pkg_names: list[str] | None = None) -> ParsedExport:
    """Extract goalText FString from a ConEventAddGoal export.

    If goalText is absent (no-string branch), returns opaque passthrough.
    """
    if pkg_names is None:
        # Synthetic mode (no name table). byte[4] flag selects the branch:
        # 0x31 = no-string (opaque), 0x33 = has-string (StrProperty tag at offset 5).
        if len(export_data) >= 5 and export_data[4] == _NO_STRING_FLAG:
            return ParsedExport(
                string_body="",
                string_encoding="ansi",
                raw_string_offset=0,
                raw_string_length=0,
                str_prop_name_ref=0,
                str_prop_info_byte=0,
                prefix_tag_bytes=b"",
                trailing_tag_bytes=bytes(export_data),
            )
        from contex import read_compact_index, decode_info_byte, size_info_to_size, decode_fstring
        prefix = bytes(export_data[:5])
        off = 5
        name_ref, k = read_compact_index(export_data, off)
        off += k
        info = export_data[off]
        off += 1
        ptype, size_info, array_flag = decode_info_byte(info)
        payload_size, consumed = size_info_to_size(size_info, export_data, off)
        off += consumed
        payload_start = off
        payload = export_data[payload_start:payload_start + payload_size]
        text, encoding = decode_fstring(payload)
        tag_end = payload_start + payload_size
        return ParsedExport(
            string_body=text,
            string_encoding=encoding,
            raw_string_offset=payload_start,
            raw_string_length=payload_size,
            str_prop_name_ref=name_ref,
            str_prop_info_byte=info,
            prefix_tag_bytes=prefix,
            trailing_tag_bytes=bytes(export_data[tag_end:]),
        )

    tag = find_str_property_tag(export_data, pkg_names, TARGET_PROP)
    if tag is None:
        return ParsedExport(
            string_body="",
            string_encoding="ansi",
            raw_string_offset=0,
            raw_string_length=0,
            str_prop_name_ref=0,
            str_prop_info_byte=0,
            prefix_tag_bytes=b"",
            trailing_tag_bytes=bytes(export_data),
        )
    return parse_str_property_export(export_data, pkg_names, TARGET_PROP)


def serialize(parsed: ParsedExport, new_body: str, new_encoding: str) -> bytes:
    """Rebuild export bytes. Opaque passthrough if no goalText was present."""
    if parsed.str_prop_name_ref == 0 and parsed.str_prop_info_byte == 0 and parsed.prefix_tag_bytes == b"":
        return bytes(parsed.trailing_tag_bytes)
    return serialize_str_property_export(parsed, new_body, new_encoding)
