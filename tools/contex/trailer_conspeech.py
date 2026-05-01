"""ConSpeech trailer parser — UE1 property-tag stream.

Empirical layout (all 10079 stock DX exports):
    [Speech (StrProperty)  — size_info ∈ {3, 4, 5, 6}]
    [soundID (IntProperty) — size_info=2, 4B value]
    [None]

size_info distribution for Speech:
    3 (12B fixed) → 166 exports (body byte count == 12 coincidentally)
    4 (16B fixed) → 110 exports (body byte count == 16)
    5 (1B u8)     → 9720 exports
    6 (2B u16)    → 83 exports  (body byte count > 255, e.g. long monologues)

Parser locates the Speech StrProperty by name (name-table lookup) rather than
positional scan — robust to future changes in prefix/trailing tags.
"""
from __future__ import annotations

from contex import (
    ParsedExport,
    parse_str_property_export,
    serialize_str_property_export,
    parse_synthetic_one_strprop,
)

TARGET_PROP = "Speech"


def parse(export_data: bytes, pkg_names: list[str] | None = None) -> ParsedExport:
    """Extract Speech FString from a ConSpeech export.

    When pkg_names is None (synthetic test data), falls back to
    parse_synthetic_one_strprop which assumes the export starts with a single
    StrProperty tag.
    """
    if pkg_names is None:
        return parse_synthetic_one_strprop(export_data)
    return parse_str_property_export(export_data, pkg_names, TARGET_PROP)


def serialize(parsed: ParsedExport, new_body: str, new_encoding: str) -> bytes:
    """Rebuild export bytes with new Speech text.

    size_info is re-chosen based on the new FString payload size (UTF-16 CJK
    typically lands in size_info=5 or 6; the info byte is updated accordingly).
    """
    return serialize_str_property_export(parsed, new_body, new_encoding)
