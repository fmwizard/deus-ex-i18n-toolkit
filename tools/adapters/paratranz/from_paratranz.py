"""Convert a paratranz translation export into `{key: text}` JSON.

Paratranz exports its project as a list of `{key, original, translation, stage, context}`
objects (per-file or merged).  Toolkit `build_*` modules consume a flat
`{key: text}` dict, so this adapter unwraps the paratranz envelope.

Behavior:
  * Entries with empty/missing `translation` are dropped.
  * `--min-stage N` (default 0) keeps only entries whose `stage >= N`.
    Paratranz convention: 0=untranslated, 1-3=in progress, 5=reviewed.
    Pick a threshold that matches your project's review policy.
  * Duplicate keys (paratranz cross-file) raise `SystemExit` so silent overwrites
    don't ship a wrong translation.

CLI
---
    python -m adapters.paratranz.from_paratranz \\
        --paratranz <export.json> --out <translations.json> [--min-stage 5]

Multi-file paratranz dumps: pass `--paratranz` once per file; the merged dict
is the union, with cross-file key collisions raising `SystemExit`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def from_paratranz(items: list[dict], min_stage: int = 0) -> dict[str, str]:
    """Filter + flatten one paratranz JSON list into `{key: translation}`."""
    out: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit(f"paratranz entry must be an object, got: {type(item).__name__}")
        key = item.get("key")
        translation = item.get("translation") or ""
        stage = item.get("stage", 0)
        if not key:
            continue
        if not translation:
            continue
        if stage < min_stage:
            continue
        if key in out:
            raise SystemExit(
                f"duplicate key in paratranz input: {key!r} "
                f"(remove the duplicate or split the file)"
            )
        out[key] = translation
    return out


def merge_files(paths: list[Path], min_stage: int = 0) -> dict[str, str]:
    """Union of multiple paratranz files; cross-file duplicates raise SystemExit."""
    merged: dict[str, str] = {}
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(
                f"{p}: paratranz export must be a JSON list, got {type(data).__name__}"
            )
        sub = from_paratranz(data, min_stage=min_stage)
        for k, v in sub.items():
            if k in merged:
                raise SystemExit(
                    f"duplicate key {k!r} across files (last seen in {p})"
                )
            merged[k] = v
    return merged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--paratranz", required=True, action="append",
                    help="Paratranz export JSON path (repeatable for multi-file dumps).")
    ap.add_argument("--out", required=True, help="Output `{key: text}` JSON path.")
    ap.add_argument("--min-stage", type=int, default=0,
                    help="Drop entries with stage below this (paratranz convention: 5=reviewed).")
    args = ap.parse_args(argv)

    merged = merge_files([Path(p) for p in args.paratranz], min_stage=args.min_stage)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"Wrote {out_path} ({len(merged)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
