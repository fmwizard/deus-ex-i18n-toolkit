"""Scan DeusExText.u and emit `{key: en_text}` JSON.

DeusExText.u stores localizable text as a flat list of `ExtString` exports;
each export's name is the source filename (e.g. `00_Book01.txt`) and is the
canonical translation-dict key consumed by `import_deusextext.build()`.

Output is a flat JSON object:

    {
      "00_Book01.txt": "<en text>",
      "00_Datacube01.txt": "<en text>",
      ...
    }

CLI
---
    python scan_deusextext.py --stock <stock.u> --out <out.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ue1_reader import Package
from ue1_fstring import decode_fstring


def scan(stock_path: str | Path) -> dict[str, str]:
    """Decode every ExtString export into a `{export_name: text}` dict."""
    p = Package(str(stock_path))
    out: dict[str, str] = {}
    for e in p.exports:
        if p.resolve_class(e["class_ref"]) != "ExtString":
            continue
        raw = p.read_export_bytes(e)
        s, _ = decode_fstring(raw, 1)
        out[e["name"]] = s
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stock", required=True, help="Stock DeusExText.u path.")
    ap.add_argument("--out", required=True, help="Output JSON path.")
    args = ap.parse_args(argv)

    entries = scan(args.stock)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"Wrote {out_path} ({len(entries)} ExtStrings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
