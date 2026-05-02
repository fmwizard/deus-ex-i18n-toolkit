# Deus Ex i18n Toolkit

An open-source toolset for localizing **Deus Ex 1** (GOTY / Steam 1.112fm) into other languages. The toolkit takes care of binary-level work — rewriting the engine's text packages, generating font atlases for your script, and patching a couple of DLLs — so a localization team can focus on the parts that actually require human judgment: translating the script and choosing fonts.

It does not ship any translations. Bring your own translated strings as JSON dictionaries; the build pipeline encodes them into the engine's binary formats and produces drop-in replacements for the game's `System/` and `Textures/` folders.

## Contents

1. [Quickstart](#1-quickstart)
2. [Translation workflow](#2-translation-workflow)
3. [Font workflow](#3-font-workflow)
4. [Binary patches](#4-binary-patches)
5. [Build and deploy](#5-build-and-deploy)
6. [Pre-processing for Chinese, Japanese, Korean, and similar languages](#6-pre-processing-for-chinese-japanese-korean-and-similar-languages)

Deeper reverse-engineering notes for anyone forking the toolkit live under `docs/`.

---

## 1. Quickstart

Six steps from a fresh clone to a built patch. Each step is a small file you fill in, except for step 6, which runs the build.

### Layout

`cd` into the cloned repo and run every command from there. The clone doubles as your workspace — stock files, configs, translations, and build output all live alongside `tools/` and `prebuilt/`. After Step 5:

```
dx1-i18n-toolkit/
├── tools/                  toolkit (don't edit)
├── prebuilt/               toolkit drop-in DLLs and DeusEx.u (don't edit)
├── *.toml.example          toolkit templates (don't edit)
├── stock/                  Step 1 — copied from game install
├── fonts.toml              Step 2 — from fonts.toml.example, edited
├── charset.toml            Step 3 — same
├── patch_config.toml       Step 4 — same
├── translations/           Step 5
└── patch/                  Step 6 build output
```

### Step 1 — copy the stock game files

The build needs the original (untouched) game binaries to read from. Create a `stock/` subdirectory in the cloned repo and copy these files into it from your game's `System/`:

```
stock/
├── DeusExUI.u
├── DeusExConText.u
├── DeusExText.u
├── DXFonts.utx
├── Extension.u
├── Extension.dll
└── DeusExText.dll
```

Other `System/` files aren't read by the toolkit — copying them in too does no harm if that's easier than picking. Keep the originals pristine in your game install; the toolkit never writes back into `stock/`.

### Step 2 — write `fonts.toml`

Save `fonts.toml.example` as `fonts.toml` (drop the `.example` suffix) and edit. One line per UFont you want to replace, grouped by package:

```toml
[packages.DeusExUI]
FontMenuSmall   = { ttf = "fonts/MyFont.ttf",  size_px = 10, vsize = 10 }
FontMenuTitle   = { ttf = "fonts/MyFont.ttf",  size_px = 12, vsize = 12 }
# ... 19 more in DeusExUI

[packages.DXFonts]
HUDMessageTrueType = { ttf = "fonts/MyFont.ttf", size_px = 21, vsize = 21 }
MainMenuTrueType   = { ttf = "fonts/MyFont.ttf", size_px = 26, vsize = 26 }

[packages.Extension]
TechMedium = { ttf = "fonts/MyFont.ttf", size_px = 10, vsize = 10 }
# ... 5 more in Extension
```

UFonts you don't list keep their stock English glyphs. Schema details and the full list of 31 UFonts live in §3 and `docs/font-pipeline-internals.md`.

### Step 3 — write `charset.toml`

Save `charset.toml.example` as `charset.toml` and list which Unicode codepoints your atlas should contain. Multiple sources combine:

```toml
codecs = ["gb2312"]                    # any region codec (gb2312, shift_jis, euc-kr, ...)
ranges = [[0x0020, 0x007E]]            # printable ASCII
codepoints = [0x2026, 0x2014, 0x00B7]  # individual codepoints
chars = "—…·「」"                      # literal characters
```

Codepoints must be in the BMP (`U+0000`–`U+FFFF`) — the engine's atlas can't address higher.

### Step 4 — write `patch_config.toml`

Save `patch_config.toml.example` as `patch_config.toml` and adjust paths if needed. The defaults match the Layout above (everything alongside `tools/`):

```toml
[input]
stock_dir = "stock"

[output]
root = "patch"

[stages.int]
enable = true
source = "translations/int"

[stages.contex]
enable = true
translations = "translations/contex.json"

[stages.deusextext]
enable = true
translations = "translations/deusextext.json"

[stages.font]
enable = true
fonts_toml = "fonts.toml"
charset = "charset.toml"

[stages.dll]
enable = false        # see "Binary patches" below
```

### Step 5 — prepare your translations

Three input shapes, one per stage. See §2 for what each contains and how to extract the source strings.

```
translations/
├── int/                    # stage `int` — UTF-8 *.int files
│   ├── 00_Intro.int
│   ├── 01_NYC_UNATCOHQ.int
│   └── ... (one per mission, same names as stock System/*.int)
├── contex.json             # stage `contex` — {"<export_idx>": "translated text", ...}
└── deusextext.json         # stage `deusextext` — {"<export_name>": "translated text", ...}
```

You don't have to provide all three at once. Disable any stage you're not ready for in `patch_config.toml` (`enable = false`) and the build will skip it.

### Step 6 — build

```bash
python tools/make_patch.py all
```

Output lands in `patch/System/` and `patch/Textures/`, mirroring the layout you copy back into the game install. After editing translations or fonts, re-run; for faster iteration name only the stages you changed (e.g. `python tools/make_patch.py contex` if you only updated `contex.json`).

To deploy in one command, set `[deploy] target = "/path/to/Deus Ex"` in the config and add `--deploy`, or pass `--deploy /path/to/Deus Ex` directly.

---

## 2. Translation workflow

Deus Ex stores text in three different containers. Each has its own extraction tool, but they all feed the same `{key: translated_text}` JSON shape back to the build pipeline.

| Where | What's in it | Stage |
|---|---|---|
| `*.int` files in `System/` | UI strings — menus, button labels, weapon names, augmentation descriptions | `int` |
| `DeusExConText.u` | NPC dialogue, player reply choices, quest objectives, in-world notes | `contex` |
| `DeusExText.u` | Long-form text — datacubes, books, emails, newspapers | `deusextext` |

### Extracting source strings

`*.int` files are plain text already. To translate, copy each one out of `stock/` into your `translations/int/` directory, save it as UTF-8 with the same filename, and edit the values; the `int` stage transcodes those UTF-8 files into the UTF-16 LE + BOM the engine expects.

`DeusExConText.u` and `DeusExText.u` are binary UE1 packages. Extract their text with the toolkit's scanners:

```bash
# Conversation text (ConText)
python tools/scan_contex.py --pkg stock/DeusExConText.u --out en_contex.json

# Page text (datacubes, books, ...)
python tools/scan_deusextext.py --stock stock/DeusExText.u --out en_deusextext.json
```

`scan_contex` produces a richer schema with conversation context (speaker, addressee, surrounding lines, sibling reply choices) to help the translator disambiguate. `scan_deusextext` produces a flat `{export_name: text}` map — datacubes are self-contained.

### Building translations back in

Both build tools accept a `{key: translated_text}` JSON dict. Keys vary by stage:

* `contex` keys are export indices as decimal strings (`"408"`, `"3915"`).
* `deusextext` keys are export names as written (`"00_Book01"`, `"03_NYC_Newspaper"`) — no `.txt` suffix.

```bash
python tools/build_contex.py \
    --stock stock/DeusExConText.u \
    --translations translations/contex.json \
    --out patch/System/DeusExConText.u

python tools/import_deusextext.py \
    --stock stock/DeusExText.u \
    --translations translations/deusextext.json \
    --out patch/System/DeusExText.u
```

You normally don't run these by hand — `make_patch.py` invokes them per stage with paths from `patch_config.toml`. Standalone use is for one-off iteration on a single file.

### Translation platforms

The toolkit ships a reference adapter for [paratranz.cn](https://paratranz.cn) under `tools/adapters/paratranz/`. It converts toolkit scan output into paratranz's upload JSON and translated paratranz exports back into the `{key: text}` dicts the build pipeline expects. See `tools/adapters/paratranz/README.md` for upload/download walkthrough.

Other platforms (Crowdin, Transifex, Weblate, gettext PO, ...) follow the same pattern: a small `to_*` script that adds platform metadata, and a small `from_*` script that strips it back to a flat dict. PRs welcome.

---

## 3. Font workflow

Deus Ex uses two kinds of font asset:

* **UFont packages** (`DeusExUI.u`, `DXFonts.utx`, `Extension.u`) — bitmap atlas + glyph rectangle table. Each "font" (e.g. `FontMenuSmall`) is a UFont object inside a package. The engine looks glyphs up by codepoint in the atlas at runtime.
* **TrueType handoff** — a few UFonts wrap an external TTF; the engine reads the TTF directly. These are mostly the menu/HUD ones.

Either way, the toolkit produces a new UFont (with a fresh atlas covering your charset) by rasterizing glyphs from a TTF you supply.

### `fonts.toml` schema

Per-package, per-UFont. Inline tables, one entry per UFont you want to replace:

```toml
[packages.DeusExUI]
FontMenuSmall = {
    ttf       = "fonts/MyFont.ttf",
    size_px   = 10,                 # rasterization size
    vsize     = 10,                 # must match the stock UFont's vertical size
    ascii_ttf = "fonts/Latin.ttf",  # optional: render wchars < 0x80 from this TTF
                                    #           instead, leaving the main TTF for
                                    #           the rest. Useful when the main
                                    #           font's ASCII advances look too
                                    #           narrow in a fixed-grid cell
    vert_align = "bottom",          # optional: anchor glyphs to cell bottom
                                    #           instead of cell top (default)
    weight    = 700,                # optional: pin a Variable Font's wght axis
                                    #           (e.g. 400=Regular, 700=Bold);
                                    #           leave unset to use the design default
}
```

Required: `ttf`, `size_px`, `vsize`. Optional: `ascii_ttf`, `vert_align` (`"top"` / `"bottom"`), `weight`.

`vsize` is non-negotiable — the engine hardcodes line height per UFont elsewhere, so the rebuilt UFont must report the same vertical size as the stock one. The toolkit checks every entry against a built-in stock-vsize table and refuses to build if they disagree. The full table is in `docs/font-pipeline-internals.md`; for a quick reference, copy `fonts.toml.example` and edit the `ttf` paths.

UFonts not listed are passed through verbatim from the stock package — the original English glyphs remain. There is no "exclude" flag; *not listing a UFont is how you skip it*.

### Three UFonts to skip

These three are best left as stock English. The toolkit will refuse to build them anyway (the first because it's not text, the other two because they exceed the atlas size cap):

| UFont | Package | Reason |
|---|---|---|
| `FontHUDWingDings` | `DeusExUI` | Icon font — `'A'`, `'B'`, etc. render as datavault icons, not letters. CJK-izing it breaks the HUD icons. |
| `FontMenuExtraLarge` | `DeusExUI` | `vsize = 29`, above the 28-pixel atlas tier cap. |
| `FontSpinningDX` | `DeusExUI` | `vsize = 32`, animated rotating font, also above the cap. |

If you need to render large headings in your script, consider rebuilding `FontMenuTitle` with a larger `size_px` and accepting that the largest menu text stays in English. (Or fork and bump the atlas tier — see `docs/font-pipeline-internals.md`.)

### Charset

The font stage rasterizes every codepoint in your charset into the atlas. Bigger charset → bigger atlas → more VRAM, so list only what you need. Two formats:

`charset.toml` — combine multiple sources:

```toml
codecs = ["gb2312"]                    # bulk-include a region codec's coverage
ranges = [[0x0020, 0x007E]]            # closed intervals [low, high]
codepoints = [0x2026, 0x2014]          # individual integers
chars = "—…·"                          # literal string
```

`charset.txt` — alternative for projects that already have a corpus dump:

```
你好世界
The quick brown fox …
```

Every distinct codepoint in the file goes in (CR/LF excluded; ASCII space included).

Both formats are BMP-only (`U+0000`–`U+FFFF`). The loader rejects non-BMP codepoints with a clear error.

### Build CLI

`make_patch.py font` runs `build_font_package.py` for each of the three font-bearing packages. To iterate on a single package:

```bash
python tools/build_font_package.py \
    --stock stock/DeusExUI.u \
    --out patch/System/DeusExUI.u \
    --fonts-toml fonts.toml \
    --package DeusExUI \
    --charset charset.toml
```

Or restrict `make_patch.py font` with `[stages.font] packages = ["DeusExUI"]` in your config.

See `docs/font-pipeline-internals.md` for the full 31-UFont reference table, atlas tier ladder, vertical-alignment rationale, and the `weight` axis caveats.

---

## 4. Binary patches

Two language-neutral DLL patches plus one prebuilt `DeusEx.u` live under `prebuilt/`. Whether you need them depends on your script.

### Wordwrap DLLs

Some scripts use ASCII space between words (English, Russian, Vietnamese, ...). The engine wraps long lines on space, which works fine.

Other scripts write words back-to-back with no inter-word space (Chinese, Japanese, Korean, Thai, Lao, Khmer, Myanmar, ...). The engine doesn't know where it's allowed to break, so it pushes the entire paragraph onto one line and chops off whatever runs past the panel.

Two patches fix this:

| File | What it fixes |
|---|---|
| `Extension.dll` | Word-wrap on terminal screens / datavault panels — the `XComputerWindow` UI |
| `DeusExText.dll` | Datacube and book pages — handles cases where a placeholder like a player name gets split across lines |

If your script doesn't use spaces as word separators, enable both. The simplest path is to copy `prebuilt/Extension.dll` and `prebuilt/DeusExText.dll` straight into the game's `System/`. To rebuild from source instead, set `[stages.dll] enable = true` in `patch_config.toml` and run `make_patch.py dll`; the result is byte-for-byte identical to the prebuilt copy.

If your script uses spaces, leave both disabled. The patches are a no-op for English-style wrapping.

See §6 below for the small one-time text transform that makes these patches work for CJK-style languages.

### `prebuilt/DeusEx.u` (InfoLink and HUD label sizing)

Independent of the wordwrap DLLs. Stock `InfoLink` (the comm popup at the top of the screen) renders at a font size sized for English's 7-pixel ink height. Larger glyphs — including most CJK fonts — turn into a smudge at that size. The prebuilt `DeusEx.u` bumps a handful of widget sizings:

* `InfoLink` text panel — bigger font, taller box.
* HUD bottom-row labels (health, energy, ammo) — accommodate slightly taller glyphs.

If your TTF renders cleanly at stock sizes, skip this file and your `DeusEx.u` stays as the original. Otherwise, copy `prebuilt/DeusEx.u` into the game's `System/`. The toolkit doesn't build this file from source — it's a one-off UC patch, shipped prebuilt.

See `docs/dll-patches-explained.md` for the reverse-engineering writeup.

---

## 5. Build and deploy

`make_patch.py` is a thin orchestrator that calls each per-stage build tool with paths from `patch_config.toml` — picked up from the current working directory by default, or pass `--config PATH` to point at a different file.

```bash
python tools/make_patch.py all                  # all enabled stages
python tools/make_patch.py int contex           # only the named stages
python tools/make_patch.py all --deploy         # build + deploy to [deploy] target
python tools/make_patch.py all --deploy /game   # build + deploy to override path
```

Five stages:

| Stage | Output | Default |
|---|---|---|
| `int` | UTF-16 LE+BOM `*.int` files in `patch/System/` | enabled |
| `contex` | `patch/System/DeusExConText.u` | enabled |
| `deusextext` | `patch/System/DeusExText.u` | enabled |
| `font` | `patch/System/DeusExUI.u`, `patch/System/Extension.u`, `patch/Textures/DXFonts.utx` | enabled |
| `dll` | `patch/System/Extension.dll`, `patch/System/DeusExText.dll` | disabled |

### `patch_config.toml` shape

* `[input] stock_dir` — where the toolkit reads stock binaries.
* `[output] root` — where build products land. Mirrors the game's `System/` + `Textures/` layout.
* `[deploy] target` — optional install path for the bare `--deploy` flag.
* `[stages.<name>]` — per-stage settings. Each table has an `enable` boolean plus that stage's required input paths. Disabled stages can omit their inputs.

A stage failure aborts the build with a clear error before any deploy step runs.

### Deploy

The output tree mirrors the game install:

```
patch/
├── System/
│   ├── *.int
│   ├── DeusExConText.u
│   ├── DeusExText.u
│   ├── DeusExUI.u
│   ├── Extension.u
│   ├── Extension.dll        # only if dll stage enabled
│   └── DeusExText.dll       # only if dll stage enabled
└── Textures/
    └── DXFonts.utx
```

Copy the contents of `patch/System/` and `patch/Textures/` into your install's `System/` and `Textures/` (or use `--deploy`). Back up your originals first — the engine has no rollback.

---

## 6. Pre-processing for Chinese, Japanese, Korean, and similar languages

Triggered by: your target script doesn't use ASCII space to separate words. This section is the one place in the toolkit's docs that addresses CJK-style wrapping directly; the rest of the toolkit stays language-neutral.

The engine treats ASCII space (`U+0020`) as a soft wrap point. For English that's exactly right. For CJK, it produces a single-line paragraph that overflows the text panel because there are no spaces to break on.

The fix is a one-line substitution applied to every translated string before you feed it to the build pipeline: replace `U+0020` with `U+00A0` (non-breaking space).

```python
text = text.replace(" ", "\u00A0")
```

The engine then refuses to break on those spaces, and the wrap-on-character path in the DLL patches above takes over. Apply this in your translation pipeline before writing the `{key: text}` JSON — the toolkit deliberately performs *no* text transforms, so what you put in is what gets encoded into the binary.

### Companion: enable the DLL patches

Once you've replaced ASCII space with NBSP, the engine has no soft wrap points left. Without the §4 DLL patches, lines just run off the panel. Pair the NBSP replacement with `[stages.dll] enable = true` (or copy the prebuilt DLLs); together they implement character-level wrapping.

---

## License

MIT. See [LICENSE](LICENSE).

## Where to read further

* `docs/ue1-package-format.md` — the on-disk layout of `.u` / `.utx` packages, name table, export table, property tag protocol.
* `docs/font-pipeline-internals.md` — UFont format, atlas tiers, glyph rectangle table, the per-UFont stock vsize reference, ascii_ttf / vert_align / weight axis details.
* `docs/dll-patches-explained.md` — what each DLL patch changes, why, and how to rebuild from source.
