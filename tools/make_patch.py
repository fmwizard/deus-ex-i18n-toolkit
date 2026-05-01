"""Build a Deus Ex localization patch by running per-stage builders.

Five stages, each independent and skippable:

    int         transcode .int files (UTF-8 → UTF-16 LE + BOM)
    contex      rewrite DeusExConText.u from a {key: text} dict
    deusextext  rewrite DeusExText.u from a {key: text} dict; verify T1/T2/T3
    font        rebuild UFont packages with custom atlases
    dll         word-wrap helper patches for Extension.dll + DeusExText.dll
                (default off; enable for scriptio-continua scripts)

`all` runs the enabled stages in canonical order. Each stage shells out to
the corresponding sub-CLI; the command is echoed before execution so any
failure can be reproduced by hand from the printed line.

CLI
---
    python make_patch.py all                       # uses ./patch_config.toml
    python make_patch.py int contex                # build a subset
    python make_patch.py all --config alt.toml     # use a different config
    python make_patch.py all --deploy              # also copy to [deploy].target
    python make_patch.py all --deploy PATH         # override deploy target
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from patch_paths import PatchConfig, load as load_config


TOOLS = Path(__file__).resolve().parent
STAGE_ORDER = ("int", "contex", "deusextext", "font", "dll")

STOCK_FILENAME = {
    "contex": "DeusExConText.u",
    "deusextext": "DeusExText.u",
}

FONT_PACKAGE_FILENAMES = {
    "DeusExUI":  ("DeusExUI.u",  "system"),
    "DXFonts":   ("DXFonts.utx", "textures"),
    "Extension": ("Extension.u", "system"),
}


class StageError(RuntimeError):
    pass


def _shell_quote(s: str) -> str:
    if not s or any(c in s for c in ' "\t'):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _run(argv: list[str], *, stage: str) -> None:
    print(f"  $ {' '.join(_shell_quote(a) for a in argv)}")
    result = subprocess.run(argv)
    if result.returncode != 0:
        raise StageError(f"stage {stage}: command exited {result.returncode}")


def _py(script: Path, *args: str) -> list[str]:
    return [sys.executable, str(script), *args]


def stage_int(cfg: PatchConfig) -> None:
    _run(
        _py(TOOLS / "build_int.py",
            "--source", str(cfg.int_.source),
            "--out-dir", str(cfg.output_system_dir)),
        stage="int",
    )


def stage_contex(cfg: PatchConfig) -> None:
    _run(
        _py(TOOLS / "build_contex.py",
            "--stock", str(cfg.stock(STOCK_FILENAME["contex"])),
            "--translations", str(cfg.contex.translations),
            "--out", str(cfg.output_system(STOCK_FILENAME["contex"]))),
        stage="contex",
    )


def stage_deusextext(cfg: PatchConfig) -> None:
    stock = cfg.stock(STOCK_FILENAME["deusextext"])
    out = cfg.output_system(STOCK_FILENAME["deusextext"])
    _run(
        _py(TOOLS / "import_deusextext.py",
            "--stock", str(stock),
            "--translations", str(cfg.deusextext.translations),
            "--out", str(out)),
        stage="deusextext",
    )

    print("  verifying (T1/T2/T3)...")
    from verify_deusextext import (
        t1_identity_roundtrip,
        t2_same_content_rewrite,
        t3_patched_against_translations,
    )
    if not t1_identity_roundtrip(str(stock)):
        raise StageError("deusextext T1 identity round-trip failed")
    if not t2_same_content_rewrite(str(stock)):
        raise StageError("deusextext T2 same-content rewrite failed")
    translations = json.loads(cfg.deusextext.translations.read_text(encoding="utf-8"))
    if not isinstance(translations, dict):
        raise StageError("[stages.deusextext].translations must be a JSON object")
    if not t3_patched_against_translations(str(out), translations):
        raise StageError("deusextext T3 spot check failed")


def stage_font(cfg: PatchConfig) -> None:
    cfg.output_system_dir.mkdir(parents=True, exist_ok=True)
    cfg.output_textures_dir.mkdir(parents=True, exist_ok=True)
    for pkg_name in cfg.font.packages:
        stock_filename, dst_kind = FONT_PACKAGE_FILENAMES[pkg_name]
        stock = cfg.stock(stock_filename)
        out = (cfg.output_system(stock_filename) if dst_kind == "system"
               else cfg.output_textures(stock_filename))
        _run(
            _py(TOOLS / "build_font_package.py",
                "--stock", str(stock),
                "--out", str(out),
                "--fonts-toml", str(cfg.font.fonts_toml),
                "--package", pkg_name,
                "--charset", str(cfg.font.charset)),
            stage="font",
        )


def stage_dll(cfg: PatchConfig) -> None:
    cfg.output_system_dir.mkdir(parents=True, exist_ok=True)
    _run(
        _py(TOOLS / "wrap_helpers" / "patch_extension_dll.py",
            str(cfg.stock("Extension.dll")),
            str(cfg.output_system("Extension.dll"))),
        stage="dll",
    )
    _run(
        _py(TOOLS / "wrap_helpers" / "patch_deusextext_dll.py",
            str(cfg.stock("DeusExText.dll")),
            str(cfg.output_system("DeusExText.dll"))),
        stage="dll",
    )


STAGE_FN = {
    "int": stage_int,
    "contex": stage_contex,
    "deusextext": stage_deusextext,
    "font": stage_font,
    "dll": stage_dll,
}

STAGE_ENABLE = {
    "int": lambda cfg: cfg.int_.enable,
    "contex": lambda cfg: cfg.contex.enable,
    "deusextext": lambda cfg: cfg.deusextext.enable,
    "font": lambda cfg: cfg.font.enable,
    "dll": lambda cfg: cfg.dll.enable,
}


def deploy(cfg: PatchConfig, target_override: str | None) -> None:
    """Mirror `[output].root` into the deploy target, overwriting files in place."""
    if target_override:
        target = Path(target_override).resolve()
    elif cfg.deploy_target is not None:
        target = cfg.deploy_target
    else:
        raise StageError(
            "deploy: target not set — fill [deploy].target in patch_config.toml "
            "or pass --deploy PATH"
        )
    if not target.exists():
        raise StageError(f"deploy: target {target} does not exist")
    if not cfg.output_root.exists():
        raise StageError(
            f"deploy: output dir {cfg.output_root} not found — run stages first"
        )

    print(f"\ndeploy: {cfg.output_root} → {target}")
    copied = 0
    for src in cfg.output_root.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(cfg.output_root)
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(f"  overwriting {rel}")
        else:
            print(f"  new         {rel}")
        shutil.copy2(src, dst)
        copied += 1
    print(f"deploy: {copied} files copied")


def select_stages(requested: list[str], cfg: PatchConfig) -> list[str]:
    """Expand `all`, dedupe, then filter by enable toggle.

    Stages explicitly named on the command line that resolve to `enable=false`
    raise SystemExit so the user catches the contradiction. Stages disabled
    only via `all` expansion are silently skipped.
    """
    explicit = {s for s in requested if s in STAGE_ORDER}
    expanded: list[str] = []
    seen: set[str] = set()
    for s in requested:
        if s == "all":
            for stage in STAGE_ORDER:
                if stage not in seen:
                    seen.add(stage)
                    expanded.append(stage)
        elif s not in seen:
            seen.add(s)
            expanded.append(s)

    final: list[str] = []
    for stage in expanded:
        if STAGE_ENABLE[stage](cfg):
            final.append(stage)
        elif stage in explicit:
            raise SystemExit(
                f"stage {stage!r} requested on the command line but disabled in "
                f"config ([stages.{stage}].enable = false)"
            )
    return final


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "stages",
        nargs="+",
        choices=[*STAGE_ORDER, "all"],
        help=f"stage name(s) to build; `all` runs {list(STAGE_ORDER)} in canonical order",
    )
    ap.add_argument(
        "--config",
        default=None,
        help="path to patch_config.toml (default: ./patch_config.toml)",
    )
    ap.add_argument(
        "--deploy",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="after building, copy [output].root → deploy target "
             "(empty = use [deploy].target from config)",
    )
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    stages = select_stages(args.stages, cfg)

    print(f"stock_dir:   {cfg.stock_dir}")
    print(f"output_root: {cfg.output_root}")
    print(f"stages:      {stages}")
    print()

    total_start = time.time()
    for stage in stages:
        print(f"=== {stage} ===")
        stage_start = time.time()
        try:
            STAGE_FN[stage](cfg)
        except StageError as e:
            print(f"ABORT: {e}", file=sys.stderr)
            return 1
        print(f"=== {stage} done ({time.time() - stage_start:.1f}s) ===\n")

    if args.deploy is not None:
        try:
            deploy(cfg, args.deploy or None)
        except StageError as e:
            print(f"ABORT: {e}", file=sys.stderr)
            return 1

    print(f"Total: {time.time() - total_start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
