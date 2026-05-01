"""Verify the DeusExText.u import pipeline.

Three checks:
    T1 — every stock ExtString round-trips byte-identical through decode → encode
    T2 — feeding stock content through `build()` yields the same decoded text
    T3 — patched .u output matches the translation dict it was built from

T3 is end-to-end: read the post-build `.u`, decode each ExtString, compare
against the input translation dict on a stratified sample. Useful as a smoke
test after deploying a localization patch.

CLI
---
    python verify_deusextext.py t1 --stock <stock.u>
    python verify_deusextext.py t2 --stock <stock.u>
    python verify_deusextext.py t3 --patched <patched.u> --translations <t.json>
    python verify_deusextext.py all --stock <stock.u> [--patched ... --translations ...]

`all` runs t1 and t2 against `--stock`; t3 also runs when `--patched` and
`--translations` are provided.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

from ue1_reader import Package
from ue1_fstring import encode_fstring, decode_fstring


def _iter_extstring(p: Package):
    for e in p.exports:
        if p.resolve_class(e['class_ref']) == 'ExtString':
            yield e


def _read_extstring_translations(p: Package) -> dict[str, str]:
    """Decode every ExtString in the package into a `{name: text}` dict."""
    out = {}
    for e in _iter_extstring(p):
        raw = p.read_export_bytes(e)
        s, _ = decode_fstring(raw, 1)
        out[e['name']] = s
    return out


def t1_identity_roundtrip(stock_path: str) -> bool:
    """Every ExtString decode → re-encode must yield the exact original bytes."""
    p = Package(stock_path)
    fail = 0
    total = 0
    for e in _iter_extstring(p):
        total += 1
        raw = p.read_export_bytes(e)
        header = raw[0]
        if header != 0x00:
            print(f"  FAIL {e['name']} unexpected header {header:#x}")
            fail += 1
            continue
        s, _ = decode_fstring(raw, 1)
        rebuilt = bytes([header]) + encode_fstring(s)
        if rebuilt != raw:
            fail += 1
            print(f"  FAIL {e['name']} size={len(raw)}")
            print(f"    orig hex: {raw.hex()[:80]}")
            print(f"    rebl hex: {rebuilt.hex()[:80]}")
            if fail > 3:
                break
    print(f"T1 identity round-trip: {total - fail}/{total} pass")
    return fail == 0


def t2_same_content_rewrite(stock_path: str) -> bool:
    """Build a package using stock content as translations; decoded text must match."""
    from import_deusextext import build

    p_orig = Package(stock_path)
    orig_map = _read_extstring_translations(p_orig)

    new_buf, _ = build(stock_path, orig_map)

    with tempfile.NamedTemporaryFile(suffix='.u', delete=False) as f:
        f.write(new_buf)
        tmp = f.name
    try:
        p_new = Package(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)

    new_map = _read_extstring_translations(p_new)

    if orig_map.keys() != new_map.keys():
        print(f"T2 FAIL: export name set diverged. "
              f"missing={orig_map.keys() - new_map.keys()} "
              f"extra={new_map.keys() - orig_map.keys()}")
        return False

    fail = 0
    for name, s_orig in orig_map.items():
        if s_orig != new_map[name]:
            fail += 1
            print(f"  FAIL {name}: orig[{len(s_orig)}] != new[{len(new_map[name])}]")
            if fail > 3:
                break
    print(f"T2 same-content rewrite: {len(orig_map) - fail}/{len(orig_map)} pass")
    return fail == 0


def t3_patched_against_translations(patched_path: str,
                                    translations: dict[str, str],
                                    sample_size: int = 10) -> bool:
    """Decode patched ExtStrings; sample must equal translation dict entries.

    Sampling is stratified by export-name prefix (split at the first `_`) to
    spread coverage across logically grouped exports without requiring any
    knowledge of the underlying naming convention.
    """
    p = Package(patched_path)
    name_to_payload = _read_extstring_translations(p)

    by_prefix: dict[str, list[str]] = {}
    for name in translations:
        by_prefix.setdefault(name.split('_')[0], []).append(name)
    rng = random.Random(42)
    sample = [rng.choice(v) for v in by_prefix.values()]
    while len(sample) < sample_size:
        sample.append(rng.choice(list(translations.keys())))

    fail = 0
    for name in sample:
        expected = translations[name]
        actual = name_to_payload.get(name)
        if actual != expected:
            fail += 1
            print(f"  FAIL {name}")
            print(f"    expected[:60]: {expected[:60]!r}")
            print(f"    actual[:60]:   {(actual[:60] if actual else None)!r}")
        else:
            non_ascii = any(ord(c) >= 128 for c in actual)
            tag = 'non-ASCII' if non_ascii else 'ASCII'
            print(f"  OK   {name}  ({len(actual)} chars, {tag})")
    print(f"T3 patched against translations: {len(sample) - fail}/{len(sample)} pass")
    return fail == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('test', choices=['t1', 't2', 't3', 'all'])
    ap.add_argument('--stock', help='Stock .u for t1/t2 (and t2 within all).')
    ap.add_argument('--patched', help='Patched .u for t3.')
    ap.add_argument('--translations',
                    help='JSON {key: text} dict for t3 (post-adapter).')
    args = ap.parse_args(argv)

    ok = True
    if args.test in ('t1', 'all'):
        if not args.stock:
            ap.error('t1 requires --stock')
        ok &= t1_identity_roundtrip(args.stock)
    if args.test in ('t2', 'all'):
        if not args.stock:
            ap.error('t2 requires --stock')
        ok &= t2_same_content_rewrite(args.stock)
    if args.test in ('t3', 'all'):
        if args.patched and args.translations:
            translations = json.loads(Path(args.translations).read_text(encoding='utf-8'))
            if not isinstance(translations, dict):
                ap.error('--translations must be a JSON object')
            ok &= t3_patched_against_translations(args.patched, translations)
        elif args.test == 't3':
            ap.error('t3 requires --patched and --translations')
        else:
            print('T3 skipped (--patched and --translations not provided)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
