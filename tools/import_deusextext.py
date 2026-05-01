"""Replace ExtString payloads in DeusExText.u from a translation dict.

DeusExText.u stores localizable text as a flat list of `ExtString` class
exports. Each export's body is `0x00 header byte + FString`. This builder
rewrites every ExtString's body using a `{export_name: text}` dict and
returns the new package bytes.

API
---
    build(stock_path, translations) -> (new_bytes, stats)

`stats` keys:
  - `replaced`: int          — number of ExtStrings rewritten
  - `ignored_extra`: list    — translation keys with no matching export

`build` raises `ValueError` if any ExtString export has no entry in
`translations`. Library callers can wrap differently (for example,
`verify_deusextext.t2` reads stock content first, so its translation dict
is by construction complete).

CLI
---
    python import_deusextext.py --stock <stock.u> \\
                                --translations <translations.json> \\
                                --out <patched.u>

The translations JSON must be a `{key: text}` object whose keys match
ExtString export names verbatim. Translation formats with key conventions
(suffixes like `.txt`, list-shaped entries, etc.) need an adapter to
produce this dict shape first.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ue1_reader import Package
from ue1_fstring import encode_fstring


def _build_payload(text: str) -> bytes:
    """ExtString export body = `0x00` header byte + FString."""
    return b'\x00' + encode_fstring(text)


def build(stock_path: str | Path, translations: dict[str, str]) -> tuple[bytes, dict]:
    """Rewrite every ExtString payload using `translations[export_name]`.

    Raises `ValueError` if any ExtString export has no entry in `translations`.
    Translation entries that don't correspond to any export are reported in
    `stats['ignored_extra']` for the caller to surface.
    """
    p = Package(str(stock_path))
    ext_names = [e['name'] for e in p.exports
                 if p.resolve_class(e['class_ref']) == 'ExtString']

    missing = [n for n in ext_names if n not in translations]
    if missing:
        raise ValueError(
            f"{len(missing)} ExtString export(s) have no translation: "
            f"{sorted(missing)[:5]}"
        )

    ignored_extra = sorted(set(translations) - set(ext_names))

    replacements = {n: _build_payload(translations[n]) for n in ext_names}
    new_buf = p.rewrite(replacements)

    stats = {
        'replaced': len(replacements),
        'ignored_extra': ignored_extra,
    }
    return new_buf, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--stock', required=True, help='Stock DeusExText.u path.')
    ap.add_argument('--translations', required=True,
                    help='JSON file containing a {export_name: text} object.')
    ap.add_argument('--out', required=True, help='Output path for patched .u.')
    args = ap.parse_args(argv)

    raw = json.loads(Path(args.translations).read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise SystemExit(
            f"--translations must be a JSON object (got {type(raw).__name__}); "
            "list-shaped formats need adapter conversion first"
        )
    translations = {k: str(v) for k, v in raw.items()}

    try:
        new_buf, stats = build(args.stock, translations)
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(new_buf)

    print(f"Wrote {out_path} ({len(new_buf)} bytes, {stats['replaced']} ExtStrings)")
    if stats['ignored_extra']:
        print(f"[warn] {len(stats['ignored_extra'])} translation entries had "
              f"no matching ExtString export (ignored): "
              f"{stats['ignored_extra'][:5]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
