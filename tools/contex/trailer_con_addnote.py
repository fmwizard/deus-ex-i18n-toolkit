"""ConEventAddNote trailer parser — UE1 property-tag stream.

Empirical layout (all 103 stock DX exports):
    [noteText (StrProperty) — size_info=5 usually, 6 for one long note]
    [eventType (ByteProperty) = 13]
    [nextEvent (ObjectProperty)]
    [Conversation (ObjectProperty)]
    [None]

+ 1 export has a `Label` StrProperty ('ModifiedContinue2') — code-id, not translatable.

102/103 exports have noteText; 1 export (edge case, ConEventAddNote39 — Label-only)
has no translatable noteText.  Parser falls back to opaque passthrough for that one.
"""
from __future__ import annotations

from contex import (
    ParsedExport,
    find_str_property_tag,
    parse_str_property_export,
    serialize_str_property_export,
    parse_synthetic_one_strprop,
)

TARGET_PROP = "noteText"


def parse(export_data: bytes, pkg_names: list[str] | None = None) -> ParsedExport:
    """Extract noteText FString from a ConEventAddNote export."""
    if pkg_names is None:
        return parse_synthetic_one_strprop(export_data)
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
    """Rebuild export bytes. Opaque passthrough if no noteText was present."""
    if parsed.str_prop_name_ref == 0 and parsed.str_prop_info_byte == 0 and parsed.prefix_tag_bytes == b"":
        return bytes(parsed.trailing_tag_bytes)
    return serialize_str_property_export(parsed, new_body, new_encoding)
