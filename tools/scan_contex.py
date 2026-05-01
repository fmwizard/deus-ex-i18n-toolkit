"""Scan DeusExConText.u and emit en_contex.json.

Walks every Conversation export, follows its event chain, and collects the
text-bearing entries (ConSpeech / ConChoice / ConEventAddGoal / ConEventAddNote)
along with conversational context: who is speaking to whom, the conversation
audio package, and a small window of surrounding speeches.

Output schema:
    {
      "entries": [
        {
          "key": "<export_idx as decimal string>",
          "type": "ConSpeech" | "ConChoice" | "ConEventAddGoal" | "ConEventAddNote",
          "audio_package": "Mission01" | null,
          "conv_name": "<Conversation.conName>" | null,
          "conv_owner": "<Conversation.conOwnerName>" | null,
          "speaker": "<Pawn class name>" | null,
          "addressee": "<Pawn class name>" | null,
          "choice_group_id": <ConEventChoice export_idx> | null,
          "en_text": "<source string>",
          "context_before": [{"type": "ConSpeech"|..., "text": "<text>", "choice_group_id": int|null}, ...],
          "context_after":  [{"type": "ConSpeech"|..., "text": "<text>", "choice_group_id": int|null}, ...]
        },
        ...
      ],
      "per_class_counts": {"ConSpeech": N, ...},
      "parse_failures": [{"export_idx": int, "class": str, "error": str}, ...]
    }

`key` is the canonical translation-dictionary key; build_contex consumes a
`{key: cn_text}` dict.  `audio_package` is the raw Conversation.audioPackageName
(no `.xml` suffix); platform adapters (e.g. paratranz) decide how to map it.
"""
from __future__ import annotations
import argparse
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ue1_reader import Package, read_compact_index
from contex import trailer_conspeech, trailer_conchoice, trailer_con_addgoal, trailer_con_addnote
from contex.conversation_parser import parse_conversation, walk_event_list


CLASS_PARSERS = {
    "ConSpeech": trailer_conspeech,
    "ConChoice": trailer_conchoice,
    "ConEventAddGoal": trailer_con_addgoal,
    "ConEventAddNote": trailer_con_addnote,
}

CONTEXT_WINDOW = 3  # number of surrounding speeches to emit per entry

_FIXED_SIZE = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}


def _scan_props(eb: bytes, names: list[str]) -> dict[str, list[tuple[int, bytes]]]:
    """Scan a UE1 property-tag stream; return {prop_name: [(ptype, payload_bytes), ...]}.

    Tolerant of truncation: returns whatever was successfully parsed before any
    structural error.  Bool properties carry no payload (their value is the
    array_flag bit); they're recorded with empty payload bytes.
    """
    result: dict[str, list[tuple[int, bytes]]] = defaultdict(list)
    off = 0
    total = len(eb)
    try:
        while off < total:
            name_idx, k = read_compact_index(eb, off)
            off += k
            if name_idx < 0 or name_idx >= len(names):
                break
            prop_name = names[name_idx]
            if prop_name == "None":
                break
            if off >= total:
                break
            info = eb[off]
            off += 1
            ptype = info & 0x0F
            size_info = (info >> 4) & 0x07
            array_flag = (info >> 7) & 0x01
            if array_flag and ptype != 3:
                if off >= total:
                    break
                off += 1
            if ptype == 3:  # Bool — no payload
                result[prop_name].append((ptype, b""))
                continue
            if ptype == 15:  # Struct — extra struct-type name ref
                _, sk = read_compact_index(eb, off)
                off += sk
            if size_info in _FIXED_SIZE:
                sz, sc = _FIXED_SIZE[size_info], 0
            elif size_info == 5:
                if off >= total:
                    break
                sz, sc = eb[off], 1
            elif size_info == 6:
                sz, sc = struct.unpack_from("<H", eb, off)[0], 2
            else:
                sz, sc = struct.unpack_from("<I", eb, off)[0], 4
            off += sc
            payload = bytes(eb[off:off + sz])
            result[prop_name].append((ptype, payload))
            off += sz
    except Exception:
        pass
    return dict(result)


def _decode_object_ref(payload: bytes) -> int:
    """Decode an Object property payload (compact-idx) → object ref. 0 if invalid."""
    try:
        oref, _ = read_compact_index(payload, 0)
        return oref
    except Exception:
        return 0


def _decode_fstring(payload: bytes) -> str | None:
    """Decode a StrProperty payload (compact-idx length + body + null) → str.

    Returns None on any decode error.
    """
    if not payload:
        return None
    try:
        slen, sk = read_compact_index(payload, 0)
        if slen > 0:
            return payload[sk:sk + slen - 1].decode("latin-1", "replace")
        if slen < 0:
            byte_count = (-slen) * 2 - 2
            return payload[sk:sk + byte_count].decode("utf-16-le", "replace")
        return ""
    except Exception:
        return None


def _build_event_speech_map(pkg: Package) -> dict[int, dict]:
    """ConEventSpeech export_idx (0-based) → {speech_idx, speaker, addressee}.

    speech_idx is the 0-based ConSpeech export idx that holds the actual text.
    speaker / addressee are decoded from speakerName / speakingToName StrProperties
    (None when missing or undecodable).
    """
    mapping: dict[int, dict] = {}
    for e in pkg.exports:
        if pkg.resolve_class(e["class_ref"]) != "ConEventSpeech":
            continue
        try:
            eb = pkg.read_export_bytes(e)
            props = _scan_props(eb, pkg.names)
            speech_payloads = props.get("ConSpeech", [])
            speech_idx = None
            for ptype, payload in speech_payloads:
                if ptype == 5:
                    oref = _decode_object_ref(payload)
                    if oref > 0:
                        speech_idx = oref - 1  # 1-based → 0-based
                        break
            if speech_idx is None:
                continue
            speaker = None
            for ptype, payload in props.get("speakerName", []):
                if ptype == 13:
                    speaker = _decode_fstring(payload)
                    break
            addressee = None
            for ptype, payload in props.get("speakingToName", []):
                if ptype == 13:
                    addressee = _decode_fstring(payload)
                    break
            mapping[e["idx"]] = {
                "speech_idx": speech_idx,
                "speaker": speaker,
                "addressee": addressee,
            }
        except Exception:
            pass
    return mapping


def _walk_choice_list(pkg: Package, head_objref: int) -> list[int]:
    """Walk ConChoice options starting at the ChoiceList head.

    Stock DX ConChoice exports do not carry a `nextChoice` ObjectProperty
    (0/408 in DeusExConText.u), so the choice group is identified by export-
    index contiguity instead: start at the head and consume consecutive
    ConChoice exports until the next class boundary.
    """
    result: list[int] = []
    idx = head_objref - 1
    while 0 <= idx < len(pkg.exports):
        if pkg.resolve_class(pkg.exports[idx]["class_ref"]) != "ConChoice":
            break
        result.append(idx)
        idx += 1
    return result


def _build_event_choice_map(pkg: Package) -> dict[int, list[int]]:
    """ConEventChoice export_idx → list of ConChoice export_idxs (0-based)."""
    mapping: dict[int, list[int]] = {}
    for e in pkg.exports:
        if pkg.resolve_class(e["class_ref"]) != "ConEventChoice":
            continue
        try:
            eb = pkg.read_export_bytes(e)
            props = _scan_props(eb, pkg.names)
            head_oref = 0
            for ptype, payload in props.get("ChoiceList", []):
                if ptype == 5:
                    head_oref = _decode_object_ref(payload)
                    break
            if head_oref <= 0:
                continue
            choices = _walk_choice_list(pkg, head_oref)
            if choices:
                mapping[e["idx"]] = choices
        except Exception:
            pass
    return mapping


def scan(stock_path: str | Path) -> dict:
    """Scan a DeusExConText.u and return the en_contex output dict."""
    pkg = Package(str(stock_path))

    evt_speech_map = _build_event_speech_map(pkg)
    evt_choice_map = _build_event_choice_map(pkg)

    # Per text-bearing export, capture conversational metadata + in-conv order.
    # Tuple shape:
    #   (audio_package, conv_name, conv_owner, speaker, addressee,
    #    conv_id, order, choice_group_id)
    # `choice_group_id` is the ConEventChoice export_idx for ConChoice entries
    # (so siblings under the same prompt share an id), and None otherwise.
    event_to_meta: dict[int, tuple] = {}
    conv_order: dict[int, list[int]] = defaultdict(list)
    conv_failures: list[dict] = []

    convs = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "Conversation"]
    for conv_e in convs:
        try:
            h = parse_conversation(pkg.read_export_bytes(conv_e), pkg.names)
        except Exception as ex:
            conv_failures.append({"export_idx": conv_e["idx"], "error": str(ex)})
            continue
        if h.event_list_objref <= 0:
            continue
        try:
            walked = walk_event_list(pkg, h.event_list_objref)
        except Exception as ex:
            conv_failures.append({"export_idx": conv_e["idx"], "error": f"walk: {ex}"})
            continue
        order = 0
        # Track speaker context per conversation: ConChoice inherits the most
        # recent ConEventSpeech's speaker/addressee in walk order.
        last_speaker = None
        last_addressee = None
        for ei in walked:
            if ei < 0 or ei >= len(pkg.exports):
                continue
            cls = pkg.resolve_class(pkg.exports[ei]["class_ref"])
            if cls == "ConEventSpeech":
                info = evt_speech_map.get(ei)
                if info is None:
                    continue
                last_speaker = info["speaker"]
                last_addressee = info["addressee"]
                text_idx = info["speech_idx"]
                if text_idx not in event_to_meta:
                    event_to_meta[text_idx] = (
                        h.audio_package_name, h.con_name, h.con_owner_name,
                        last_speaker, last_addressee, h.conversation_id, order, None,
                    )
                    conv_order[h.conversation_id].append(text_idx)
                    order += 1
            elif cls == "ConEventChoice":
                # Choice options carry the speaker that just finished talking.
                # The player (addressee) is replying, so swap the pair.
                # All ConChoice under this ConEventChoice share its export_idx
                # as `choice_group_id` so downstream renderers can identify
                # sibling options even when walk order interleaves reply branches.
                group_id = ei
                for cidx in evt_choice_map.get(ei, []):
                    if cidx not in event_to_meta:
                        event_to_meta[cidx] = (
                            h.audio_package_name, h.con_name, h.con_owner_name,
                            last_addressee, last_speaker, h.conversation_id, order,
                            group_id,
                        )
                        conv_order[h.conversation_id].append(cidx)
                        order += 1
            elif cls in ("ConEventAddGoal", "ConEventAddNote"):
                if ei not in event_to_meta:
                    event_to_meta[ei] = (
                        h.audio_package_name, h.con_name, h.con_owner_name,
                        None, None, h.conversation_id, order, None,
                    )
                    conv_order[h.conversation_id].append(ei)
                    order += 1

    # Cache decoded text bodies + class for context window lookup; keyed by export_idx.
    text_cache: dict[int, str] = {}
    cls_cache: dict[int, str] = {}
    entries_raw: list[tuple[int, str, str]] = []  # (export_idx, class, en_text)
    parse_failures: list[dict] = []
    per_class_counts: dict[str, int] = defaultdict(int)

    for e in pkg.exports:
        cls = pkg.resolve_class(e["class_ref"])
        if cls not in CLASS_PARSERS:
            continue
        eb = pkg.read_export_bytes(e)
        try:
            p = CLASS_PARSERS[cls].parse(eb, pkg.names)
        except Exception as ex:
            parse_failures.append({"export_idx": e["idx"], "class": cls, "error": str(ex)})
            continue
        text_cache[e["idx"]] = p.string_body
        cls_cache[e["idx"]] = cls
        entries_raw.append((e["idx"], cls, p.string_body))
        per_class_counts[cls] += 1

    def _sibling_dict(idx: int) -> dict:
        sib_meta = event_to_meta.get(idx)
        sib_group = sib_meta[7] if sib_meta is not None else None
        return {
            "type": cls_cache.get(idx, ""),
            "text": text_cache.get(idx, ""),
            "choice_group_id": sib_group,
        }

    entries = []
    for export_idx, cls, en_text in entries_raw:
        meta = event_to_meta.get(export_idx)
        if meta is not None:
            (audio_package, conv_name, conv_owner, speaker, addressee,
             conv_id, _order, choice_group_id) = meta
            siblings = conv_order.get(conv_id, [])
            try:
                pos = siblings.index(export_idx)
            except ValueError:
                pos = -1
            if pos >= 0:
                before_idxs = siblings[max(0, pos - CONTEXT_WINDOW):pos]
                after_idxs = siblings[pos + 1:pos + 1 + CONTEXT_WINDOW]
                context_before = [_sibling_dict(i) for i in before_idxs]
                context_after = [_sibling_dict(i) for i in after_idxs]
            else:
                context_before, context_after = [], []
        else:
            audio_package = conv_name = conv_owner = speaker = addressee = None
            choice_group_id = None
            context_before, context_after = [], []
        entries.append({
            "key": str(export_idx),
            "type": cls,
            "audio_package": audio_package,
            "conv_name": conv_name,
            "conv_owner": conv_owner,
            "speaker": speaker,
            "addressee": addressee,
            "choice_group_id": choice_group_id,
            "en_text": en_text,
            "context_before": context_before,
            "context_after": context_after,
        })

    return {
        "entries": entries,
        "per_class_counts": dict(per_class_counts),
        "parse_failures": parse_failures,
        "conv_failures": conv_failures,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pkg", required=True, help="path to stock DeusExConText.u")
    ap.add_argument("--out", required=True, help="output en_contex.json path")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    output = scan(args.pkg)

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = output["per_class_counts"]
    n = len(output["entries"])
    print(f"Wrote {out_path}")
    print(f"  entries: {n}")
    print(f"  per class: {counts}")
    if output["parse_failures"]:
        print(f"  parse failures: {len(output['parse_failures'])}")
    if output["conv_failures"]:
        print(f"  conversation failures: {len(output['conv_failures'])}")


if __name__ == "__main__":
    main()
