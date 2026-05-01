"""End-to-end scan_contex test against stock DeusExConText.u."""
import os
from pathlib import Path

import pytest

from scan_contex import scan

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_scan_contex_produces_expected_shape():
    out = scan(STOCK_CONTEX)
    assert "entries" in out
    assert "per_class_counts" in out

    counts = out["per_class_counts"]
    assert counts.get("ConSpeech") == 10079
    assert counts.get("ConChoice") == 408
    assert counts.get("ConEventAddGoal") == 337
    assert counts.get("ConEventAddNote") == 103
    assert len(out["entries"]) == 10079 + 408 + 337 + 103


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_entries_have_canonical_fields():
    out = scan(STOCK_CONTEX)
    sample = out["entries"][0]
    expected = {
        "key", "type", "audio_package", "conv_name", "conv_owner",
        "speaker", "addressee", "choice_group_id",
        "en_text", "context_before", "context_after",
    }
    assert expected.issubset(sample.keys())
    # `key` is the export_idx as a string (stable JSON dict key for translations)
    assert sample["key"].isdigit()
    assert sample["type"] in {"ConSpeech", "ConChoice", "ConEventAddGoal", "ConEventAddNote"}


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_audio_package_no_xml_suffix():
    out = scan(STOCK_CONTEX)
    seen = {e["audio_package"] for e in out["entries"] if e["audio_package"]}
    assert seen, "expected at least some entries with non-null audio_package"
    for ap in seen:
        assert not ap.lower().endswith(".xml"), f"audio_package should not carry .xml suffix: {ap!r}"
    # 18 unique audio package names appear in stock DX (matches Conversation.audioPackageName).
    assert "Intro" in seen
    assert "Mission01" in seen


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_speaker_addressee_populated_for_speech():
    """At least 80% of ConSpeech entries should carry speaker + addressee strings."""
    out = scan(STOCK_CONTEX)
    speeches = [e for e in out["entries"] if e["type"] == "ConSpeech"]
    with_speaker = sum(1 for e in speeches if e["speaker"])
    with_addressee = sum(1 for e in speeches if e["addressee"])
    assert with_speaker / len(speeches) >= 0.80, (
        f"only {with_speaker}/{len(speeches)} speeches have speaker"
    )
    assert with_addressee / len(speeches) >= 0.80


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_context_window_within_conversation():
    """For a ConSpeech mid-conversation, context_before/after should hold up to 3 sibling texts."""
    out = scan(STOCK_CONTEX)
    speeches_with_context = [
        e for e in out["entries"]
        if e["type"] == "ConSpeech" and (e["context_before"] or e["context_after"])
    ]
    assert speeches_with_context, "expected some entries to carry surrounding context"
    valid_types = {"ConSpeech", "ConChoice", "ConEventAddGoal", "ConEventAddNote"}
    for e in speeches_with_context[:50]:
        assert len(e["context_before"]) <= 3
        assert len(e["context_after"]) <= 3
        for sib in e["context_before"] + e["context_after"]:
            assert {"type", "text", "choice_group_id"}.issubset(sib.keys())
            assert sib["type"] in valid_types
            assert isinstance(sib["text"], str)
            assert sib["choice_group_id"] is None or isinstance(sib["choice_group_id"], int)


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_choice_entries_see_choice_siblings_in_context():
    """A ConChoice's context window should include other ConChoice siblings (the
    co-occurring options under the same ConEventChoice) alongside ConSpeech entries.
    Without type info on siblings, downstream renderers can't tell options from prose."""
    out = scan(STOCK_CONTEX)
    choices = [e for e in out["entries"] if e["type"] == "ConChoice"]
    saw_choice_sibling = False
    for e in choices:
        for sib in e["context_before"] + e["context_after"]:
            if sib["type"] == "ConChoice":
                saw_choice_sibling = True
                break
        if saw_choice_sibling:
            break
    assert saw_choice_sibling, (
        "expected at least one ConChoice to have another ConChoice in its context window"
    )


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_keys_are_unique():
    out = scan(STOCK_CONTEX)
    keys = [e["key"] for e in out["entries"]]
    assert len(keys) == len(set(keys)), "entry keys must be unique"
