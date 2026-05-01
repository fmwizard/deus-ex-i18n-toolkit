"""Tests for adapters.paratranz.to_paratranz."""
import json
from pathlib import Path

import pytest

from adapters.paratranz.to_paratranz import (
    convert, from_contex, from_deusextext, render_context_for_entry,
    split_by_audio_package, MISC_BUCKET, main,
)


def _speech(text, speaker="JC", addressee="NPC"):
    return {"type": "ConSpeech", "text": text}


def _choice(text):
    return {"type": "ConChoice", "text": text}


def test_deusextext_flat_dict_to_paratranz_list():
    en = {"00_Book01": "hello", "00_Datacube01": "world"}
    out = from_deusextext(en)
    assert out == [
        {"key": "00_Book01", "original": "hello"},
        {"key": "00_Datacube01", "original": "world"},
    ]


def test_convert_dispatches_on_entries_key():
    contex_input = {
        "entries": [{
            "key": "42", "type": "ConSpeech", "en_text": "hi",
            "audio_package": None, "conv_name": None, "conv_owner": None,
            "speaker": None, "addressee": None,
            "context_before": [], "context_after": [],
        }],
        "per_class_counts": {"ConSpeech": 1},
    }
    out = convert(contex_input)
    assert len(out) == 1
    assert out[0]["key"] == "42"
    assert out[0]["original"] == "hi"
    assert "context" in out[0]


def test_convert_dispatches_on_flat_dict():
    out = convert({"foo": "bar"})
    assert out == [{"key": "foo", "original": "bar"}]


def test_convert_rejects_unknown_shape():
    with pytest.raises(SystemExit):
        convert([1, 2, 3])  # bare list — not entries object, not flat dict
    with pytest.raises(SystemExit):
        convert({"k": 42})  # values aren't strings


def test_choice_renders_with_prompt_and_siblings():
    """A ConChoice's context shows the NPC prompt + sibling options + current marked with >."""
    entry = {
        "key": "100",
        "type": "ConChoice",
        "audio_package": "Mission03",
        "conv_name": "HelloMaggie",
        "conv_owner": "MaggieChow",
        "speaker": "JCDenton",
        "addressee": "MaggieChow",
        "en_text": "I need to talk to him.",
        "context_before": [
            _speech("Yep. Sad old bastard with a datajack."),
        ],
        "context_after": [
            _choice("I heard that he might be staying upstairs."),
            _choice("Where can I find him?"),
        ],
    }
    ctx = render_context_for_entry(entry)
    assert "Mission03 / HelloMaggie" in ctx
    assert "JCDenton -> MaggieChow" in ctx
    assert "Yep. Sad old bastard with a datajack." in ctx
    assert "Player Options:" in ctx
    assert "> I need to talk to him." in ctx
    assert "  I heard that he might be staying upstairs." in ctx
    assert "  Where can I find him?" in ctx


def test_choice_lists_pre_prompt_choices_too():
    """ConChoice options that appear in context_before *after* the prompt are siblings too."""
    entry = {
        "key": "101",
        "type": "ConChoice",
        "audio_package": None, "conv_name": None, "conv_owner": None,
        "speaker": "JC", "addressee": "NPC",
        "en_text": "Option B",
        "context_before": [
            _speech("Pick one."),
            _choice("Option A"),  # earlier sibling option
        ],
        "context_after": [
            _choice("Option C"),
        ],
    }
    ctx = render_context_for_entry(entry)
    assert "Pick one." in ctx
    assert "  Option A" in ctx
    assert "> Option B" in ctx
    assert "  Option C" in ctx


def test_choice_with_no_prompt_still_renders_options():
    """Choice without a preceding ConSpeech: still shows the option block."""
    entry = {
        "key": "102", "type": "ConChoice",
        "audio_package": None, "conv_name": None, "conv_owner": None,
        "speaker": None, "addressee": None,
        "en_text": "Lone option",
        "context_before": [],
        "context_after": [],
    }
    ctx = render_context_for_entry(entry)
    assert "Player Options:" in ctx
    assert "> Lone option" in ctx


def test_choice_uses_group_members_for_precise_siblings():
    """When choice_group_id + group_members map are provided, siblings are picked
    precisely regardless of how walk order interleaved reply branches."""
    entry = {
        "key": "201", "type": "ConChoice",
        "audio_package": None, "conv_name": None, "conv_owner": None,
        "speaker": None, "addressee": None,
        "choice_group_id": 99,
        "en_text": "Option B",
        # Window only sees the prompt + reply branches (no ConChoice in window).
        "context_before": [_speech("Prompt")],
        "context_after": [_speech("reply 1"), _speech("reply 2")],
    }
    group_members = {99: [
        {"key": "200", "en_text": "Option A", "choice_group_id": 99},
        {"key": "201", "en_text": "Option B", "choice_group_id": 99},
        {"key": "202", "en_text": "Option C", "choice_group_id": 99},
    ]}
    ctx = render_context_for_entry(entry, group_members)
    assert "Prompt" in ctx
    assert "  Option A" in ctx
    assert "> Option B" in ctx
    assert "  Option C" in ctx
    # Walk-order siblings preserved from group_members list order.
    assert ctx.index("Option A") < ctx.index("Option B") < ctx.index("Option C")


def test_speech_renders_short_window():
    """ConSpeech: 2 lines before + 2 lines after, no Player Options block."""
    entry = {
        "key": "200", "type": "ConSpeech",
        "audio_package": "Intro", "conv_name": "OpenScene",
        "conv_owner": None,
        "speaker": "BobPage", "addressee": "JCDenton",
        "en_text": "Sufficiently impressive.",
        "context_before": [
            _speech("Earlier line A"),
            _speech("Earlier line B"),
            _speech("Earlier line C (oldest, should be trimmed)"),
        ],
        "context_after": [
            _speech("Next line"),
        ],
    }
    ctx = render_context_for_entry(entry)
    assert "Intro / OpenScene" in ctx
    assert "BobPage -> JCDenton" in ctx
    assert "Sufficiently impressive." in ctx
    # Window keeps the *closest* 2 (B, C → drop A from the head).
    assert "Earlier line B" in ctx
    assert "Earlier line C" in ctx
    assert "Next line" in ctx
    assert "Player Options:" not in ctx


def test_split_by_audio_package_buckets_entries():
    items = [
        {"key": "1", "original": "a", "context": "", "_audio_package": "Mission01"},
        {"key": "2", "original": "b", "context": "", "_audio_package": "Mission01"},
        {"key": "3", "original": "c", "context": "", "_audio_package": "AIBarks"},
        {"key": "4", "original": "d", "context": "", "_audio_package": None},
    ]
    buckets = split_by_audio_package(items)
    assert set(buckets.keys()) == {"Mission01", "AIBarks", MISC_BUCKET}
    assert len(buckets["Mission01"]) == 2
    assert len(buckets["AIBarks"]) == 1
    assert len(buckets[MISC_BUCKET]) == 1
    # Internal `_audio_package` is stripped from each bucketed entry.
    for entries in buckets.values():
        for e in entries:
            assert "_audio_package" not in e


def test_from_contex_carries_audio_package_internally():
    """from_contex preserves audio_package as an internal hint for splitting."""
    entries = [{
        "key": "1", "type": "ConSpeech", "en_text": "hi",
        "audio_package": "Mission01", "conv_name": None, "conv_owner": None,
        "speaker": None, "addressee": None,
        "context_before": [], "context_after": [],
    }]
    out = from_contex(entries)
    assert out[0]["_audio_package"] == "Mission01"


def test_main_cli_writes_paratranz_list(tmp_path):
    en_path = tmp_path / "en.json"
    out_path = tmp_path / "upload.json"
    en_path.write_text(json.dumps({
        "entries": [{
            "key": "1", "type": "ConSpeech", "en_text": "hi",
            "audio_package": None, "conv_name": None, "conv_owner": None,
            "speaker": None, "addressee": None,
            "context_before": [], "context_after": [],
        }],
        "per_class_counts": {"ConSpeech": 1},
    }), encoding="utf-8")
    rc = main(["--en", str(en_path), "--out", str(out_path)])
    assert rc == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["key"] == "1"
    assert data[0]["original"] == "hi"
    # Internal `_audio_package` hint must not leak into uploaded JSON.
    assert "_audio_package" not in data[0]


def test_main_cli_out_dir_splits_by_audio_package(tmp_path):
    en_path = tmp_path / "en.json"
    en_path.write_text(json.dumps({
        "entries": [
            {"key": "1", "type": "ConSpeech", "en_text": "a",
             "audio_package": "Mission01", "conv_name": None, "conv_owner": None,
             "speaker": None, "addressee": None,
             "context_before": [], "context_after": []},
            {"key": "2", "type": "ConSpeech", "en_text": "b",
             "audio_package": "Mission01", "conv_name": None, "conv_owner": None,
             "speaker": None, "addressee": None,
             "context_before": [], "context_after": []},
            {"key": "3", "type": "ConChoice", "en_text": "c",
             "audio_package": None, "conv_name": None, "conv_owner": None,
             "speaker": None, "addressee": None,
             "context_before": [], "context_after": []},
        ],
    }), encoding="utf-8")
    out_dir = tmp_path / "out"
    rc = main(["--en", str(en_path), "--out-dir", str(out_dir)])
    assert rc == 0
    files = {p.name for p in out_dir.iterdir()}
    assert files == {f"{MISC_BUCKET}.json", "Mission01.json"}
    m1 = json.loads((out_dir / "Mission01.json").read_text(encoding="utf-8"))
    assert {e["key"] for e in m1} == {"1", "2"}
    misc = json.loads((out_dir / f"{MISC_BUCKET}.json").read_text(encoding="utf-8"))
    assert {e["key"] for e in misc} == {"3"}
    # `_audio_package` must not leak to uploaded JSON.
    for f in [m1, misc]:
        for entry in f:
            assert "_audio_package" not in entry


def test_main_cli_out_dir_rejects_deusextext_input(tmp_path):
    en_path = tmp_path / "en.json"
    en_path.write_text(json.dumps({"00_Book01": "hi"}), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        main(["--en", str(en_path), "--out-dir", str(out_dir)])


def test_main_cli_requires_out_or_out_dir(tmp_path):
    en_path = tmp_path / "en.json"
    en_path.write_text(json.dumps({"k": "v"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--en", str(en_path)])
