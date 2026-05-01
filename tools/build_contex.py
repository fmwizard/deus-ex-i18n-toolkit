"""Rewrite DeusExConText.u with translations from a {key: text} dict.

Input contract:
  - stock_path: path to stock DeusExConText.u
  - translations: dict mapping export_idx (decimal string, as emitted by
    scan_contex) to localized text

Translations are written verbatim into the property-tag stream as UTF-16 LE.
No glyph normalization is performed; pre-process the input dict if your target
language needs (e.g. CJK NBSP-for-space substitution).

Exports of supported classes (ConSpeech / ConChoice / ConEventAddGoal /
ConEventAddNote) without a translation entry keep their stock body. Exports
whose stock parse yields no translatable string (e.g. ConEventAddGoal in its
no-text branch) are passed through unchanged.
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
from contex import (
    trailer_conspeech,
    trailer_conchoice,
    trailer_con_addgoal,
    trailer_con_addnote,
)


CLASS_PARSERS = {
    "ConSpeech": trailer_conspeech,
    "ConChoice": trailer_conchoice,
    "ConEventAddGoal": trailer_con_addgoal,
    "ConEventAddNote": trailer_con_addnote,
}


def build(stock_path: str | Path, translations: dict[str, str]) -> tuple[bytes, dict[str, int]]:
    """Rewrite the package and return (new_package_bytes, stats).

    stats keys:
        translated:              exports whose body was replaced
        skipped_no_translation:  parseable exports with no entry in translations
        opaque_passthrough:      exports of supported class but with no string
                                 body to translate (preserved verbatim)
    """
    pkg = Package(str(stock_path))
    replacements: dict[str, bytes] = {}
    stats = {"translated": 0, "skipped_no_translation": 0, "opaque_passthrough": 0}

    for e in pkg.exports:
        cls = pkg.resolve_class(e["class_ref"])
        parser = CLASS_PARSERS.get(cls)
        if parser is None:
            continue
        eb = pkg.read_export_bytes(e)
        parsed = parser.parse(eb, pkg.names)

        if parsed.str_prop_name_ref == 0 and parsed.prefix_tag_bytes == b"":
            replacements[e["name"]] = parser.serialize(parsed, "", "ansi")
            stats["opaque_passthrough"] += 1
            continue

        new_text = translations.get(str(e["idx"]))
        if new_text is None:
            stats["skipped_no_translation"] += 1
            continue

        replacements[e["name"]] = parser.serialize(parsed, new_text, "utf16le")
        stats["translated"] += 1

    new_pkg_bytes = pkg.rewrite(replacements=replacements)
    return new_pkg_bytes, stats


def main():
    ap = argparse.ArgumentParser(
        description="Rewrite DeusExConText.u with translations from a {key: text} JSON dict.",
    )
    ap.add_argument("--stock", required=True, help="Stock DeusExConText.u path")
    ap.add_argument("--translations", required=True,
                    help="JSON file: object mapping export_idx (decimal string) to localized text")
    ap.add_argument("--out", required=True, help="Output path for rewritten package")
    args = ap.parse_args()

    translations = json.loads(Path(args.translations).read_text(encoding="utf-8"))
    if not isinstance(translations, dict):
        raise SystemExit(
            f"--translations must be a JSON object {{key: text}}, "
            f"got {type(translations).__name__}"
        )

    new_bytes, stats = build(args.stock, translations)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(new_bytes)

    print(f"Wrote {out}")
    print(f"  size: {len(new_bytes)} bytes ({len(new_bytes)/1024/1024:.2f} MB)")
    print(f"  stats: {stats}")


if __name__ == "__main__":
    main()
