# Paratranz adapter

Reference adapter for [paratranz.cn](https://paratranz.cn). Converts toolkit
scan output to paratranz upload JSON, and translated paratranz exports back to
the `{key: text}` dicts the toolkit's build pipelines consume.

Other platforms (Crowdin, Transifex, Weblate, gettext PO, ...) follow the same
pattern: a small `to_*` script that adds platform metadata, and a small
`from_*` script that strips it back to a flat dict. This adapter is the
reference; PRs for other platforms welcome.

## Upload (toolkit → paratranz)

Two source pipelines, one CLI:

```bash
# ConText (dialogue): scan stock → paratranz upload
python tools/scan_contex.py --pkg DeusExConText.u --out en_contex.json
python tools/adapters/paratranz/to_paratranz.py --en en_contex.json --out upload_contex.json

# DeusExText (datacubes / books): scan stock → paratranz upload
python tools/scan_deusextext.py --stock DeusExText.u --out en_deusextext.json
python tools/adapters/paratranz/to_paratranz.py --en en_deusextext.json --out upload_deusextext.json
```

The adapter detects input shape:

* scan_contex output (`{"entries": [...], ...}`) — produces entries with a
  rendered `context` field for paratranz reviewers (see below).
* scan_deusextext output (`{export_name: en_text}`) — produces flat entries
  without context (datacubes are self-contained).

Each upload entry is `{"key", "original", "context"?}`. Upload directly to a
paratranz project of matching scope.

### Split by mission

Stock DeusExConText.u has ~10,000 entries — too large for a single paratranz
file. Use `--out-dir` instead of `--out` to split contex output by
`audio_package` (the mission/scene the conversation belongs to):

```bash
python tools/adapters/paratranz/to_paratranz.py \
    --en en_contex.json --out-dir upload_dir/
# Wrote upload_dir/Mission01.json (633 entries)
# Wrote upload_dir/Mission02.json (1084 entries)
# ...
# Wrote upload_dir/AIBarks.json (1498 entries)
# Wrote upload_dir/_misc.json (300 entries)   ← entries with no audio_package
```

The misc bucket collects entries whose owning Conversation has no
`audioPackageName` set (typically dead/unreferenced ConChoice exports).
`--out-dir` is contex-only; scan_deusextext input has no audio_package
concept and rejects this flag.

### ConChoice rendering

Player reply options carry their full sibling block in the `context` field, so
the reviewer can see every option a player picks between. Walk-order
interleaving of reply branches doesn't matter; siblings are matched precisely
by `choice_group_id` (the parent ConEventChoice's export index):

```
Mission02 / JockSecondStory
JCDenton -> Jock

What do you have for me?

Player Options:
  You can have this beer.
> Never mind.
```

`>` marks the entry currently being translated.

### Non-choice rendering

ConSpeech / ConEventAddGoal / ConEventAddNote get a short prose window — two
adjacent texts before, two after — to disambiguate similar-sounding lines.

## Download (paratranz → toolkit)

```bash
# Single export file
python -m adapters.paratranz.from_paratranz \
    --paratranz exported.json \
    --out cn_translations.json \
    --min-stage 5

# Multi-file dump (paratranz dumps one JSON per source file)
python -m adapters.paratranz.from_paratranz \
    --paratranz dump/Mission01.json \
    --paratranz dump/Mission02.json \
    --paratranz dump/AIBarks.json \
    --out cn_contex.json
```

`--min-stage N` keeps entries whose `stage >= N`. Paratranz convention:

| stage | meaning |
|------:|---------|
|     0 | untranslated |
|   1-3 | drafted / under review |
|     5 | reviewed (default project ship gate) |

Pick a threshold that matches your project's review policy. The default of 0
accepts everything that has any non-empty translation.

The output `{key: text}` JSON is what `tools/build_contex.py` and
`tools/import_deusextext.py` expect:

```bash
python tools/build_contex.py --stock DeusExConText.u --translations cn_contex.json --out DeusExConText.u
python tools/import_deusextext.py --stock DeusExText.u --translations cn_deusextext.json --out DeusExText.u
```

## Sanity checks

* Cross-file key collisions are detected and raise `SystemExit` — paratranz
  occasionally lets the same `key` appear in two source files; the adapter
  refuses to silently pick one. Either remove the duplicate in paratranz or
  rename one upstream.
* Paratranz entries with empty `translation` are dropped, not propagated as
  empty strings.
* Non-list paratranz files raise — the adapter expects the standard paratranz
  per-file dump shape.
