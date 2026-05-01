"""End-to-end build_contex tests against stock DeusExConText.u."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from build_contex import build
from scan_contex import scan

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_empty_translations_produces_valid_package():
    new_bytes, stats = build(STOCK_CONTEX, {})
    assert len(new_bytes) > 0
    assert stats["translated"] == 0
    assert stats["skipped_no_translation"] > 0
    assert stats["opaque_passthrough"] >= 0


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_stats_partition_supported_class_exports():
    """translated + skipped_no_translation + opaque_passthrough equals the count
    of all exports in CLASS_PARSERS — every supported export lands in exactly
    one bucket.
    """
    new_bytes, stats = build(STOCK_CONTEX, {})
    src = scan(STOCK_CONTEX)
    total_supported = sum(src["per_class_counts"].values())
    bucket_sum = stats["translated"] + stats["skipped_no_translation"] + stats["opaque_passthrough"]
    assert bucket_sum == total_supported


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_translation_appears_in_rewritten_package(tmp_path):
    src = scan(STOCK_CONTEX)
    sample = next(e for e in src["entries"] if e["type"] == "ConSpeech" and e["en_text"])
    key = sample["key"]
    new_text = "你好，世界——这是一段测试译文。"

    new_bytes, stats = build(STOCK_CONTEX, {key: new_text})
    assert stats["translated"] == 1

    out_path = tmp_path / "DeusExConText_rewritten.u"
    out_path.write_bytes(new_bytes)
    rescanned = scan(out_path)
    rebuilt = next(e for e in rescanned["entries"] if e["key"] == key)
    assert rebuilt["en_text"] == new_text


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_unrelated_exports_unchanged(tmp_path):
    """Translating one key must not perturb sibling exports' bodies."""
    src = scan(STOCK_CONTEX)
    speeches = [e for e in src["entries"] if e["type"] == "ConSpeech" and e["en_text"]]
    target_key = speeches[0]["key"]
    other_key = speeches[1]["key"]
    other_en = speeches[1]["en_text"]

    new_bytes, _ = build(STOCK_CONTEX, {target_key: "替换文本"})
    out_path = tmp_path / "out.u"
    out_path.write_bytes(new_bytes)
    rescanned = scan(out_path)
    other = next(e for e in rescanned["entries"] if e["key"] == other_key)
    assert other["en_text"] == other_en


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_each_class_can_be_translated(tmp_path):
    """One translation in each supported class survives the rewrite."""
    src = scan(STOCK_CONTEX)
    picks: dict[str, dict] = {}
    for entry in src["entries"]:
        if entry["type"] not in picks and entry["en_text"]:
            picks[entry["type"]] = entry
        if len(picks) == len(("ConSpeech", "ConChoice", "ConEventAddGoal", "ConEventAddNote")):
            break

    translations = {p["key"]: f"译文-{cls}" for cls, p in picks.items()}
    new_bytes, stats = build(STOCK_CONTEX, translations)
    assert stats["translated"] == len(translations)

    out_path = tmp_path / "out.u"
    out_path.write_bytes(new_bytes)
    rescanned = scan(out_path)
    by_key = {e["key"]: e for e in rescanned["entries"]}
    for key, expected in translations.items():
        assert by_key[key]["en_text"] == expected


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_cli_writes_output_file(tmp_path):
    src = scan(STOCK_CONTEX)
    sample = next(e for e in src["entries"] if e["type"] == "ConSpeech" and e["en_text"])
    translations_path = tmp_path / "translations.json"
    translations_path.write_text(
        json.dumps({sample["key"]: "命令行测试译文"}, ensure_ascii=False),
        encoding="utf-8",
    )
    out_path = tmp_path / "out.u"

    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    result = subprocess.run(
        [
            sys.executable, str(tools_dir / "build_contex.py"),
            "--stock", STOCK_CONTEX,
            "--translations", str(translations_path),
            "--out", str(out_path),
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_cli_rejects_non_dict_translations(tmp_path):
    """A JSON list (instead of dict) must produce a clear error, not a traceback."""
    translations_path = tmp_path / "translations.json"
    translations_path.write_text("[]", encoding="utf-8")
    out_path = tmp_path / "out.u"
    stock = STOCK_CONTEX or "missing.u"

    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    result = subprocess.run(
        [
            sys.executable, str(tools_dir / "build_contex.py"),
            "--stock", stock,
            "--translations", str(translations_path),
            "--out", str(out_path),
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "must be a JSON object" in result.stderr
