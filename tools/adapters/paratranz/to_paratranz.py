"""Convert scan output JSON into paratranz upload-ready JSON.

Accepts two input shapes and dispatches by detection:

  * scan_contex output — a JSON object with an `"entries"` list of dicts
    (rich schema: type / speaker / addressee / context_before / context_after /
    choice_group_id / ...)
  * scan_deusextext output — a flat JSON object `{export_name: en_text}`

Output is always a paratranz-style list:

    [
      {"key": "<canonical key>", "original": "<source text>", "context": "<rendered>"},
      ...
    ]

The `context` field is rendered for ConText entries (so paratranz reviewers see
the surrounding conversation) and omitted for DeusExText entries (datacubes /
books are self-contained paragraphs).

ConText rendering keys off the entry's own `type`:

  * **ConChoice** — the current line is one of the player's reply options.
    All ConChoice entries sharing the same `choice_group_id` (i.e. the same
    parent ConEventChoice) are listed as the option block, regardless of how
    walk order interleaved reply branches between them.  The renderer also
    pulls the most recent `ConSpeech` in `context_before` to show as the prompt.
    The current entry is marked with `>`.

  * Anything else (`ConSpeech`, `ConEventAddGoal`, `ConEventAddNote`) — a
    short before/after window of immediately adjacent texts.

CLI
---
    python -m adapters.paratranz.to_paratranz --en <scan-output.json> --out <upload.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def render_context_for_entry(entry: dict, group_members: dict | None = None) -> str:
    """Build the multi-line `context` string for one scan_contex entry.

    `group_members` maps `choice_group_id -> [entries...]`; when present, a
    ConChoice can list every sibling under the same parent ConEventChoice. If
    omitted, the renderer falls back to scanning the entry's own context window
    for sibling ConChoice texts.
    """
    header_lines: list[str] = []
    audio = entry.get("audio_package")
    conv_name = entry.get("conv_name")
    if audio or conv_name:
        slug = " / ".join(x for x in (audio, conv_name) if x)
        header_lines.append(slug)
    speaker = entry.get("speaker")
    addressee = entry.get("addressee")
    if speaker or addressee:
        header_lines.append(f"{speaker or '?'} -> {addressee or '?'}")

    body_lines: list[str] = []
    cur_type = entry.get("type")
    before = entry.get("context_before") or []
    after = entry.get("context_after") or []
    cur_text = entry.get("en_text", "")

    if cur_type == "ConChoice":
        # Prompt: most recent ConSpeech in context_before.
        prompt_text = None
        for s in reversed(before):
            if s.get("type") == "ConSpeech":
                prompt_text = s.get("text", "")
                break

        # Sibling options: prefer exact lookup by choice_group_id; if no group
        # info available, scan the local context window for ConChoice entries.
        gid = entry.get("choice_group_id")
        if group_members is not None and gid is not None and gid in group_members:
            options = group_members[gid]
        else:
            window_choices = [s for s in before + after if s.get("type") == "ConChoice"]
            options = window_choices + [{"text": cur_text, "key": entry.get("key")}]

        if prompt_text:
            body_lines.append(prompt_text)
            body_lines.append("")
        body_lines.append("Player Options:")
        cur_key = entry.get("key")
        for opt in options:
            text = opt.get("en_text") or opt.get("text", "")
            if opt.get("key") == cur_key:
                body_lines.append(f"> {text}")
            else:
                body_lines.append(f"  {text}")
    else:
        # Non-choice: 2 lines before + 2 lines after, prose context.
        for s in before[-2:]:
            body_lines.append(s.get("text", ""))
        if body_lines:
            body_lines.append("")
        body_lines.append(cur_text)
        if after[:2]:
            body_lines.append("")
            for s in after[:2]:
                body_lines.append(s.get("text", ""))

    parts = []
    if header_lines:
        parts.append("\n".join(header_lines))
    if body_lines:
        parts.append("\n".join(body_lines))
    return "\n\n".join(parts)


def from_contex(entries: Iterable[dict]) -> list[dict]:
    """scan_contex entries -> paratranz upload list (carries audio_package)."""
    entries_list = list(entries)
    group_members: dict[int, list[dict]] = defaultdict(list)
    for e in entries_list:
        gid = e.get("choice_group_id")
        if gid is not None:
            group_members[gid].append(e)
    out = []
    for e in entries_list:
        out.append({
            "key": e["key"],
            "original": e.get("en_text", ""),
            "context": render_context_for_entry(e, group_members),
            "_audio_package": e.get("audio_package"),
        })
    return out


def from_deusextext(en_dict: dict[str, str]) -> list[dict]:
    """scan_deusextext flat dict -> paratranz upload list (no context)."""
    return [{"key": k, "original": v} for k, v in en_dict.items()]


def convert(scan_output) -> list[dict]:
    """Dispatch by input shape."""
    if isinstance(scan_output, dict) and "entries" in scan_output and isinstance(scan_output["entries"], list):
        return from_contex(scan_output["entries"])
    if isinstance(scan_output, dict) and all(isinstance(v, str) for v in scan_output.values()):
        return from_deusextext(scan_output)
    raise SystemExit(
        "Input does not match scan_contex (object with 'entries' list) "
        "or scan_deusextext (flat {key: str} object) shape."
    )


MISC_BUCKET = "_misc"


def _strip_internal_keys(item: dict) -> dict:
    """Drop adapter-internal keys (prefixed with `_`) from the upload entry."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def split_by_audio_package(items: list[dict]) -> dict[str, list[dict]]:
    """Bucket contex upload entries by `_audio_package`.

    Entries without `_audio_package` (or with null) land in `MISC_BUCKET`.
    Internal `_audio_package` field is stripped from the returned entries.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        pkg = item.get("_audio_package") or MISC_BUCKET
        buckets[pkg].append(_strip_internal_keys(item))
    return dict(buckets)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--en", required=True, help="scan_contex or scan_deusextext output JSON.")
    out_grp = ap.add_mutually_exclusive_group(required=True)
    out_grp.add_argument("--out", help="Single paratranz upload JSON output path.")
    out_grp.add_argument("--out-dir",
                         help="Directory; contex entries are split into one JSON per audio_package "
                              f"(no-package entries land in `{MISC_BUCKET}.json`). "
                              "Not supported for scan_deusextext input.")
    args = ap.parse_args(argv)

    data = json.loads(Path(args.en).read_text(encoding="utf-8"))
    items = convert(data)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned = [_strip_internal_keys(it) for it in items]
        out_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"Wrote {out_path} ({len(cleaned)} entries)")
        return 0

    is_contex = isinstance(data, dict) and "entries" in data
    if not is_contex:
        raise SystemExit("--out-dir is only supported for scan_contex input.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    buckets = split_by_audio_package(items)
    for pkg in sorted(buckets):
        bucket_path = out_dir / f"{pkg}.json"
        bucket_path.write_text(json.dumps(buckets[pkg], ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"Wrote {bucket_path} ({len(buckets[pkg])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
