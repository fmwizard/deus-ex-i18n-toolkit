"""Conversation property-tag parser + eventList traversal.

UE1 property-tag protocol (minimal subset):
  - property name ref: compact-idx → name_table index (None = end-of-properties)
  - info byte bits:
      [3:0]  type:      1=Byte, 2=Int, 3=Bool, 4=Float, 5=Object, 6=Name,
                        10=Array, 13=Str (StrProperty), 15=Struct
      [6:4]  size_info: 0-4 → fixed 1/2/4/12/16 bytes;
                        5=1-byte prefix, 6=2-byte prefix, 7=4-byte prefix
      [7]    array_flag: 1 if this is an array element; a 1-byte array index
                        immediately follows the info byte (before size prefix / payload)
  - Struct (ptype=15): carries an extra name-ref compact-idx before payload.
  - Str (ptype=13): payload is a compact-idx FString: len (including null) + body + null.
  - FString negative length: UTF-16LE, (-len)*2-2 body bytes.

Note: ptype 10 (Array) and ptype 15 (Struct) are not present in the 1955-conversation
DX stock dataset (empirically confirmed); both branches are defensive dead code there.

Only the 5 properties needed for the Conversation header are decoded; everything
else is skipped.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

from ue1_reader import read_compact_index, Package


PROP_TYPE_BYTE = 1
PROP_TYPE_INT = 2
PROP_TYPE_BOOL = 3
PROP_TYPE_FLOAT = 4
PROP_TYPE_OBJECT = 5
PROP_TYPE_NAME = 6
PROP_TYPE_STR = 13  # StrProperty in UE1 — NOT 7 (7 is Delegate)


@dataclass
class ConversationHeader:
    con_name: str | None = None
    con_owner_name: str | None = None
    event_list_objref: int = 0          # export ref (positive = 1-based export idx)
    conversation_id: int = 0
    audio_package_name: str | None = None


def _read_payload_size(data: bytes, off: int, size_info: int) -> tuple[int, int]:
    """Return (payload_size_in_bytes, bytes_consumed_for_size_field).

    size_info encoding:
      0-4 → fixed sizes 1, 2, 4, 12, 16 (no extra bytes consumed)
      5   → 1-byte size prefix at data[off]
      6   → 2-byte LE prefix at data[off:off+2]
      7   → 4-byte LE prefix at data[off:off+4]
    """
    _fixed = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}
    if size_info in _fixed:
        return _fixed[size_info], 0
    if size_info == 5:
        return data[off], 1
    if size_info == 6:
        return struct.unpack_from("<H", data, off)[0], 2
    if size_info == 7:
        return struct.unpack_from("<I", data, off)[0], 4
    raise ValueError(f"invalid size_info: {size_info}")


def _decode_fstring(data: bytes, off: int) -> str | None:
    """Decode a compact-idx-prefixed FString at data[off]. Returns the string body (null stripped)."""
    slen, sk = read_compact_index(data, off)
    body_off = off + sk
    if slen > 0:
        return data[body_off: body_off + slen - 1].decode("latin-1", "replace")
    if slen < 0:
        # UTF-16LE: -slen UTF-16 chars including null terminator
        byte_count = (-slen) * 2 - 2
        return data[body_off: body_off + byte_count].decode("utf-16-le", "replace")
    return ""  # slen == 0 → empty string


def parse_conversation(export_data: bytes, name_table: list[str]) -> ConversationHeader:
    """Decode Conversation export property-tag stream. Unknown properties are skipped."""
    hdr = ConversationHeader()
    off = 0
    total = len(export_data)

    while off < total:
        try:
            name_idx, k = read_compact_index(export_data, off)
        except Exception:
            break
        off += k
        if name_idx < 0 or name_idx >= len(name_table):
            break
        prop_name = name_table[name_idx]
        if prop_name == "None":
            break

        if off >= total:
            break
        info = export_data[off]
        off += 1
        ptype = info & 0x0F
        size_info = (info >> 4) & 0x07
        array_flag = (info >> 7) & 0x01
        # array_flag=1: a 1-byte array index immediately follows the info byte;
        # skip it before reading the size prefix or payload.
        if array_flag:
            if off >= total:
                break
            off += 1

        # Bool (ptype=3): value is encoded in the info byte; payload is always 0 bytes.
        if ptype == PROP_TYPE_BOOL:
            continue

        if ptype == 15:  # Struct — extra struct-type name ref before payload
            try:
                _, sk = read_compact_index(export_data, off)
                off += sk
            except Exception:
                break

        try:
            payload_size, size_k = _read_payload_size(export_data, off, size_info)
        except Exception:
            break
        off += size_k

        if prop_name == "conName" and ptype == PROP_TYPE_NAME:
            try:
                nref, _ = read_compact_index(export_data, off)
                hdr.con_name = name_table[nref]
            except Exception:
                pass
        elif prop_name == "conOwnerName" and ptype == PROP_TYPE_STR:
            hdr.con_owner_name = _decode_fstring(export_data, off)
        elif prop_name == "audioPackageName" and ptype == PROP_TYPE_STR:
            hdr.audio_package_name = _decode_fstring(export_data, off)
        elif prop_name == "eventList" and ptype == PROP_TYPE_OBJECT:
            try:
                oref, _ = read_compact_index(export_data, off)
                hdr.event_list_objref = oref
            except Exception:
                pass
        elif prop_name == "conversationID" and ptype == PROP_TYPE_INT:
            try:
                hdr.conversation_id = struct.unpack_from("<i", export_data, off)[0]
            except Exception:
                pass

        off += payload_size

    return hdr


def walk_event_list(pkg: Package, head_objref: int) -> list[int]:
    """Walk nextEvent chain starting at head_objref. Returns list of export indices (0-based) in dialogue order.

    Uses a generic property-tag scanner that works for all ConEvent* classes
    without per-class parsers.
    """
    result: list[int] = []
    current = head_objref
    visited: set[int] = set()

    while current != 0 and current not in visited:
        visited.add(current)
        if current < 0:
            break  # import ref — stop
        export_idx = current - 1  # UE1 export refs are 1-based
        if export_idx < 0 or export_idx >= len(pkg.exports):
            break
        result.append(export_idx)
        e = pkg.exports[export_idx]
        eb = pkg.read_export_bytes(e)
        next_ref = _extract_next_event(eb, pkg.names)
        if next_ref is None:
            break
        current = next_ref

    return result


def _extract_next_event(export_data: bytes, name_table: list[str]) -> int | None:
    """Generic property-tag scan for 'nextEvent' object ref.

    Returns:
      int  — the object ref value (0 means end-of-chain, >0 means next export)
      None — parse error or field not found (caller should stop walking)
    """
    off = 0
    total = len(export_data)

    while off < total:
        try:
            name_idx, k = read_compact_index(export_data, off)
        except Exception:
            return None
        off += k
        if name_idx < 0 or name_idx >= len(name_table):
            return None
        prop_name = name_table[name_idx]
        if prop_name == "None":
            return 0  # clean end-of-properties, no nextEvent → chain ends

        if off >= total:
            return None
        info = export_data[off]
        off += 1
        ptype = info & 0x0F
        size_info = (info >> 4) & 0x07
        array_flag = (info >> 7) & 0x01
        if array_flag:
            if off >= total:
                return None
            off += 1

        if ptype == PROP_TYPE_BOOL:
            continue

        if ptype == 15:  # Struct — skip struct name
            try:
                _, sk = read_compact_index(export_data, off)
                off += sk
            except Exception:
                return None

        try:
            payload_size, size_k = _read_payload_size(export_data, off, size_info)
        except Exception:
            return None
        off += size_k

        if prop_name == "nextEvent" and ptype == PROP_TYPE_OBJECT:
            try:
                oref, _ = read_compact_index(export_data, off)
                return oref
            except Exception:
                return None

        off += payload_size

    return 0
