"""Transcode mission .int localization files: UTF-8 → UTF-16 LE + BOM.

Deus Ex Unicode build's `appLoadFileToString` recognizes UTF-16 LE when the
leading bytes are `FF FE` (BOM). Translation .int sources commonly arrive
as UTF-8; this transcoder produces the engine-expected encoding and runs a
smoke check that catches source typos which would break the INI parser.

CLI
---
    python build_int.py --source DIR --out-dir DIR

Verification
------------
For each output file:
  1. The first two bytes must be `FF FE`.
  2. The body must decode as UTF-16 LE (strict).
  3. Every non-trivial line must match `[Section]` or `Key=...`
     (DX1 supports `Key[N]=...` array syntax).
A failure aborts the run and prints the offending file + line.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


BOM = b"\xff\xfe"

_SECTION_RE = re.compile(r"^\s*\[[^\]\r\n]+\]\s*$")
_KEY_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?\s*=")
_COMMENT_RE = re.compile(r"^\s*(;|//)")


def _is_valid_line(line: str) -> bool:
    """Pass empty / comment / section / `key=value` lines.

    Continuation lines inside quoted strings aren't recognized; DX .int files
    don't use them in practice. A false positive is acceptable — the caller
    sees the smoke-check warning and inspects.
    """
    if not line.strip():
        return True
    if _COMMENT_RE.match(line):
        return True
    if _SECTION_RE.match(line):
        return True
    if _KEY_RE.match(line):
        return True
    return False


def _transcode(src_bytes: bytes) -> bytes:
    """UTF-8 (optionally with BOM) → UTF-16 LE + BOM.

    Decoding via utf-8-sig absorbs a stray UTF-8 BOM at the source head
    instead of letting it become a literal `\\ufeff` char in the output.
    """
    text = src_bytes.decode("utf-8-sig")
    return BOM + text.encode("utf-16-le")


def _smoke_check(path: Path, data: bytes) -> list[str]:
    errors: list[str] = []
    if data[:2] != BOM:
        errors.append(f"{path}: BOM missing (first 2 bytes: {data[:2].hex()})")
        return errors

    try:
        text = data[2:].decode("utf-16-le")
    except UnicodeDecodeError as e:
        errors.append(f"{path}: UTF-16 LE decode failure at byte {e.start}: {e.reason}")
        return errors

    for i, line in enumerate(text.splitlines(), start=1):
        if not _is_valid_line(line):
            snippet = line[:80] + ("…" if len(line) > 80 else "")
            errors.append(f"{path}:{i}: INI smoke fail: {snippet!r}")

    return errors


def transcode_dir(source: Path, out_dir: Path) -> tuple[int, list[str]]:
    """Transcode every `*.int` under `source` into `out_dir`.

    Returns (count_written, errors). Caller decides abort semantics.
    """
    source = source.resolve()
    out_dir = out_dir.resolve()

    if not source.is_dir():
        raise NotADirectoryError(f"{source} is not a directory")

    out_dir.mkdir(parents=True, exist_ok=True)

    int_files = sorted(source.glob("*.int"))
    if not int_files:
        raise FileNotFoundError(f"no *.int files found under {source}")

    all_errors: list[str] = []
    count = 0
    for src_path in int_files:
        src_bytes = src_path.read_bytes()
        try:
            out_bytes = _transcode(src_bytes)
        except UnicodeDecodeError as e:
            all_errors.append(f"{src_path}: UTF-8 decode failure at byte {e.start}: {e.reason}")
            continue
        out_path = out_dir / src_path.name
        out_path.write_bytes(out_bytes)
        count += 1
        all_errors.extend(_smoke_check(out_path, out_bytes))
    return count, all_errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="Directory of UTF-8 .int source files.")
    ap.add_argument("--out-dir", required=True, help="Output directory for UTF-16 LE .int files.")
    args = ap.parse_args(argv)

    source = Path(args.source)
    out_dir = Path(args.out_dir)

    count, errors = transcode_dir(source, out_dir)
    print(f"Transcoded {count} .int files: {source} → {out_dir}")

    if errors:
        print(f"\n{len(errors)} smoke check error(s):", file=sys.stderr)
        for err in errors[:20]:
            print(f"  {err}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
