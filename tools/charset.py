"""Load the set of BMP wchars the font atlases must carry.

Two file formats, dispatched by extension:

charset.toml — structured; mix any of four sources (all unioned):

    # Predefined codecs. Toolkit enumerates every BMP codepoint encodable by
    # each codec — useful for region standards (gb2312, shift_jis, euc_kr,
    # cp1251, ...).
    codecs = ["gb2312"]

    # Inclusive Unicode ranges as [low, high] pairs.
    ranges = [
      [0x4E00, 0x9FFF],   # CJK Unified Ideographs
    ]

    # Individual codepoints — handy for one-off symbols outside the above.
    codepoints = [0x00A0]   # NBSP

    # Literal characters (each codepoint in the string is included).
    chars = "·—…"

charset.txt — plain literal: every codepoint in the file is included EXCEPT
ASCII line-end characters (CR, LF). Use this format to dump a flat character
list extracted from translations. Use TOML if you need codecs/ranges/comments.

Loaders return a sorted list of unique BMP codepoints (0..0xFFFF). Atlas.py
only renders BMP wchars; non-BMP codepoints raise SystemExit.
"""
from __future__ import annotations

import codecs as _codecs
import tomllib
from pathlib import Path

BMP_MAX = 0xFFFF
_ALLOWED_TOML_KEYS = {"codecs", "ranges", "codepoints", "chars"}


def _check_bmp(cp: int, source: str) -> None:
    if not isinstance(cp, int) or isinstance(cp, bool):
        raise SystemExit(f"{source}: codepoint must be int, got {type(cp).__name__}")
    if cp < 0 or cp > BMP_MAX:
        raise SystemExit(
            f"{source}: codepoint U+{cp:X} out of BMP range 0..U+{BMP_MAX:X}"
        )


def _enumerate_codec(codec_name: str) -> set[int]:
    try:
        _codecs.lookup(codec_name)
    except LookupError as exc:
        raise SystemExit(f"unknown codec {codec_name!r}: {exc}") from None
    out: set[int] = set()
    for cp in range(BMP_MAX + 1):
        try:
            chr(cp).encode(codec_name)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        out.add(cp)
    return out


def load_charset_from_toml(toml_path: str | Path) -> list[int]:
    path = Path(toml_path)
    if not path.is_file():
        raise SystemExit(f"charset.toml not found: {path}")

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    extras = set(raw.keys()) - _ALLOWED_TOML_KEYS
    if extras:
        raise SystemExit(
            f"{path.name}: unknown top-level key(s) {sorted(extras)}; "
            f"allowed: {sorted(_ALLOWED_TOML_KEYS)}"
        )

    out: set[int] = set()

    raw_codecs = raw.get("codecs", [])
    if not isinstance(raw_codecs, list):
        raise SystemExit(f"{path.name}: codecs must be a list, got {type(raw_codecs).__name__}")
    for entry in raw_codecs:
        if not isinstance(entry, str):
            raise SystemExit(f"{path.name}: codecs entries must be strings, got {entry!r}")
        out |= _enumerate_codec(entry)

    raw_ranges = raw.get("ranges", [])
    if not isinstance(raw_ranges, list):
        raise SystemExit(f"{path.name}: ranges must be a list, got {type(raw_ranges).__name__}")
    for entry in raw_ranges:
        if not isinstance(entry, list) or len(entry) != 2:
            raise SystemExit(
                f"{path.name}: each ranges entry must be a [low, high] pair, got {entry!r}"
            )
        low, high = entry
        _check_bmp(low, f"{path.name} ranges low")
        _check_bmp(high, f"{path.name} ranges high")
        if low > high:
            raise SystemExit(
                f"{path.name}: range [{low}, {high}] is empty (low > high)"
            )
        out.update(range(low, high + 1))

    raw_codepoints = raw.get("codepoints", [])
    if not isinstance(raw_codepoints, list):
        raise SystemExit(
            f"{path.name}: codepoints must be a list, got {type(raw_codepoints).__name__}"
        )
    for cp in raw_codepoints:
        _check_bmp(cp, f"{path.name} codepoints")
        out.add(cp)

    raw_chars = raw.get("chars", "")
    if not isinstance(raw_chars, str):
        raise SystemExit(f"{path.name}: chars must be a string, got {type(raw_chars).__name__}")
    for ch in raw_chars:
        cp = ord(ch)
        _check_bmp(cp, f"{path.name} chars")
        out.add(cp)

    if not out:
        raise SystemExit(f"{path.name}: charset is empty (provide codecs/ranges/codepoints/chars)")

    return sorted(out)


def load_charset_from_txt(txt_path: str | Path) -> list[int]:
    path = Path(txt_path)
    if not path.is_file():
        raise SystemExit(f"charset.txt not found: {path}")

    text = path.read_text(encoding="utf-8")
    out: set[int] = set()
    for ch in text:
        if ch in ("\r", "\n"):
            continue
        cp = ord(ch)
        _check_bmp(cp, f"{path.name}")
        out.add(cp)

    if not out:
        raise SystemExit(f"{path.name}: charset is empty")

    return sorted(out)


def load_charset(path: str | Path) -> list[int]:
    """Load a charset by file extension. .toml and .txt are supported."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".toml":
        return load_charset_from_toml(p)
    if suffix == ".txt":
        return load_charset_from_txt(p)
    raise SystemExit(
        f"unsupported charset file extension {suffix!r}; use .toml or .txt"
    )
