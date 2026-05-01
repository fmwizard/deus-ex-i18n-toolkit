"""ConChoice trailer parser — UE1 property-tag stream.

Empirical layout (all 408 stock DX exports):
    [choiceText (StrProperty)        — size_info ∈ {3, 4, 5}]  (absent in 21 exports)
    [choiceLabel (StrProperty)       — size_info=5, "ChoiceSpeechLabel_N" code-id, NOT translatable]
    [bDisplayAsSpeech (BoolProperty) — array_flag carries the bool value]
    [soundID (IntProperty)           — size_info=2, 4B value]
    [optional flagRef (ObjectProperty)  — size_info=5 or 1]
    [optional nextChoice (ObjectProperty) — size_info=5 or 1]
    [None]

Only `choiceText` carries translatable text. 21 exports (minority) have no
choiceText at all (action-only choice entries); for those parse() returns an
empty-body ParsedExport and serialize() round-trips unchanged.
"""
from __future__ import annotations

from contex import (
    ParsedExport,
    find_str_property_tag,
    parse_str_property_export,
    serialize_str_property_export,
    parse_synthetic_one_strprop,
)

TARGET_PROP = "choiceText"


def parse(export_data: bytes, pkg_names: list[str] | None = None) -> ParsedExport:
    """Extract choiceText FString from a ConChoice export.

    If choiceText is absent (21/408 stock DX exports), returns an empty-body
    ParsedExport with trailing_tag_bytes == whole export (fully opaque passthrough).
    """
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
    """Rebuild export bytes. If no choiceText was present, returns trailing_tag_bytes verbatim."""
    if parsed.str_prop_name_ref == 0 and parsed.str_prop_info_byte == 0 and parsed.prefix_tag_bytes == b"":
        return bytes(parsed.trailing_tag_bytes)
    return serialize_str_property_export(parsed, new_body, new_encoding)
