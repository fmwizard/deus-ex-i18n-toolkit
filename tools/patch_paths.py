"""Schema loader for patch_config.toml.

All paths in the config resolve relative to the toml file's directory unless
absolute. Each stage owns its own subtable; an unset subtable means "stage
runs with default toggle, missing required keys raise SystemExit at load
time so the orchestrator never starts a misconfigured run".

Schema
------
    [input]
    stock_dir = "stock"          # required

    [output]
    root = "patch"               # required

    [deploy]
    target = ""                  # optional; empty = require --deploy PATH on CLI

    [stages.int]                 # default enable = true
    enable = true
    source = "translations/int"  # required when enabled

    [stages.contex]              # default enable = true
    enable = true
    translations = "translations/contex.json"   # {key: text} JSON object

    [stages.deusextext]          # default enable = true
    enable = true
    translations = "translations/deusextext.json"

    [stages.font]                # default enable = true
    enable = true
    fonts_toml = "fonts.toml"
    charset = "charset.toml"
    packages = ["DeusExUI", "DXFonts", "Extension"]   # optional, default = all three

    [stages.dll]                 # default enable = false
    enable = false
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


VALID_STAGES = ("int", "contex", "deusextext", "font", "dll")
VALID_FONT_PACKAGES = ("DeusExUI", "DXFonts", "Extension")
DEFAULT_FONT_PACKAGES = list(VALID_FONT_PACKAGES)
STAGE_ENABLE_DEFAULTS = {
    "int": True,
    "contex": True,
    "deusextext": True,
    "font": True,
    "dll": False,
}

_ALLOWED_TOP = {"input", "output", "deploy", "stages"}


@dataclass(frozen=True)
class IntStage:
    enable: bool
    source: Path | None


@dataclass(frozen=True)
class ContexStage:
    enable: bool
    translations: Path | None


@dataclass(frozen=True)
class DeusExTextStage:
    enable: bool
    translations: Path | None


@dataclass(frozen=True)
class FontStage:
    enable: bool
    fonts_toml: Path | None
    charset: Path | None
    packages: list[str]


@dataclass(frozen=True)
class DllStage:
    enable: bool


@dataclass(frozen=True)
class PatchConfig:
    stock_dir: Path
    output_root: Path
    deploy_target: Path | None
    int_: IntStage
    contex: ContexStage
    deusextext: DeusExTextStage
    font: FontStage
    dll: DllStage

    @property
    def output_system_dir(self) -> Path:
        return self.output_root / "System"

    @property
    def output_textures_dir(self) -> Path:
        return self.output_root / "Textures"

    def output_system(self, filename: str) -> Path:
        return self.output_system_dir / filename

    def output_textures(self, filename: str) -> Path:
        return self.output_textures_dir / filename

    def stock(self, filename: str) -> Path:
        return self.stock_dir / filename


def _resolve(p: str, base: Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (base / path).resolve()


def _validate_keys(section: str, raw: dict, allowed: set[str]) -> None:
    extras = set(raw.keys()) - allowed
    if extras:
        raise SystemExit(
            f"[{section}] unknown key(s) {sorted(extras)}; allowed: {sorted(allowed)}"
        )


def _stage_enable(raw: dict, name: str) -> bool:
    value = raw.get("enable", STAGE_ENABLE_DEFAULTS[name])
    if not isinstance(value, bool):
        raise SystemExit(
            f"[stages.{name}].enable must be bool, got {type(value).__name__}"
        )
    return value


def _build_int_stage(raw: dict, base: Path) -> IntStage:
    _validate_keys("stages.int", raw, {"enable", "source"})
    enable = _stage_enable(raw, "int")
    source: Path | None = None
    if enable:
        if "source" not in raw:
            raise SystemExit("[stages.int].source is required when enable = true")
        source = _resolve(raw["source"], base)
    return IntStage(enable=enable, source=source)


def _build_translations_stage(raw: dict, base: Path, name: str):
    _validate_keys(f"stages.{name}", raw, {"enable", "translations"})
    enable = _stage_enable(raw, name)
    translations: Path | None = None
    if enable:
        if "translations" not in raw:
            raise SystemExit(
                f"[stages.{name}].translations is required when enable = true"
            )
        translations = _resolve(raw["translations"], base)
    return enable, translations


def _build_font_stage(raw: dict, base: Path) -> FontStage:
    _validate_keys("stages.font", raw, {"enable", "fonts_toml", "charset", "packages"})
    enable = _stage_enable(raw, "font")
    fonts_toml: Path | None = None
    charset: Path | None = None
    packages = list(DEFAULT_FONT_PACKAGES)
    if enable:
        for key in ("fonts_toml", "charset"):
            if key not in raw:
                raise SystemExit(f"[stages.font].{key} is required when enable = true")
        fonts_toml = _resolve(raw["fonts_toml"], base)
        charset = _resolve(raw["charset"], base)
        if "packages" in raw:
            packages = raw["packages"]
            if not isinstance(packages, list) or not all(isinstance(s, str) for s in packages):
                raise SystemExit("[stages.font].packages must be a list of strings")
            unknown = set(packages) - set(VALID_FONT_PACKAGES)
            if unknown:
                raise SystemExit(
                    f"[stages.font].packages contains unknown name(s) {sorted(unknown)}; "
                    f"valid: {sorted(VALID_FONT_PACKAGES)}"
                )
            if not packages:
                raise SystemExit(
                    "[stages.font].packages cannot be empty when enable = true"
                )
    return FontStage(enable=enable, fonts_toml=fonts_toml, charset=charset, packages=packages)


def _build_dll_stage(raw: dict) -> DllStage:
    _validate_keys("stages.dll", raw, {"enable"})
    return DllStage(enable=_stage_enable(raw, "dll"))


DEFAULT_CONFIG_FILENAME = "patch_config.toml"


def load(config_path: str | Path | None = None) -> PatchConfig:
    """Load `patch_config.toml`. When `config_path` is None, looks for
    `patch_config.toml` in the current working directory."""
    if config_path is None:
        path = Path.cwd() / DEFAULT_CONFIG_FILENAME
    else:
        path = Path(config_path)
    if not path.is_file():
        raise SystemExit(f"patch_config.toml not found: {path}")
    base = path.parent.resolve()

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    _validate_keys(path.name, raw, _ALLOWED_TOP)

    if "input" not in raw or "stock_dir" not in raw.get("input", {}):
        raise SystemExit("[input].stock_dir is required")
    _validate_keys("input", raw["input"], {"stock_dir"})
    stock_dir = _resolve(raw["input"]["stock_dir"], base)

    if "output" not in raw or "root" not in raw.get("output", {}):
        raise SystemExit("[output].root is required")
    _validate_keys("output", raw["output"], {"root"})
    output_root = _resolve(raw["output"]["root"], base)

    deploy_target: Path | None = None
    deploy_raw = raw.get("deploy", {})
    if deploy_raw:
        _validate_keys("deploy", deploy_raw, {"target"})
        target = deploy_raw.get("target", "").strip()
        deploy_target = _resolve(target, base) if target else None

    stages_raw = raw.get("stages", {})
    if stages_raw:
        _validate_keys("stages", stages_raw, set(VALID_STAGES))

    int_stage = _build_int_stage(stages_raw.get("int", {}), base)
    contex_enable, contex_translations = _build_translations_stage(
        stages_raw.get("contex", {}), base, "contex")
    deusextext_enable, deusextext_translations = _build_translations_stage(
        stages_raw.get("deusextext", {}), base, "deusextext")
    font_stage = _build_font_stage(stages_raw.get("font", {}), base)
    dll_stage = _build_dll_stage(stages_raw.get("dll", {}))

    return PatchConfig(
        stock_dir=stock_dir,
        output_root=output_root,
        deploy_target=deploy_target,
        int_=int_stage,
        contex=ContexStage(enable=contex_enable, translations=contex_translations),
        deusextext=DeusExTextStage(enable=deusextext_enable, translations=deusextext_translations),
        font=font_stage,
        dll=dll_stage,
    )
