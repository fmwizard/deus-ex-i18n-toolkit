"""Tests for adapters.paratranz.from_paratranz."""
import json
from pathlib import Path

import pytest

from adapters.paratranz.from_paratranz import from_paratranz, merge_files, main


def test_basic_flatten():
    items = [
        {"key": "a", "original": "hi", "translation": "你好", "stage": 5},
        {"key": "b", "original": "bye", "translation": "再见", "stage": 5},
    ]
    assert from_paratranz(items) == {"a": "你好", "b": "再见"}


def test_drops_empty_translation():
    items = [
        {"key": "a", "original": "hi", "translation": "", "stage": 1},
        {"key": "b", "original": "bye", "translation": "再见", "stage": 5},
        {"key": "c", "original": "ok"},  # missing translation entirely
    ]
    assert from_paratranz(items) == {"b": "再见"}


def test_min_stage_filter():
    items = [
        {"key": "a", "translation": "draft", "stage": 1},
        {"key": "b", "translation": "reviewed", "stage": 5},
    ]
    assert from_paratranz(items, min_stage=5) == {"b": "reviewed"}
    assert from_paratranz(items, min_stage=0) == {"a": "draft", "b": "reviewed"}


def test_missing_stage_treated_as_zero():
    items = [{"key": "a", "translation": "x"}]  # no stage key
    assert from_paratranz(items, min_stage=0) == {"a": "x"}
    assert from_paratranz(items, min_stage=1) == {}


def test_duplicate_key_within_file_raises():
    items = [
        {"key": "a", "translation": "first", "stage": 5},
        {"key": "a", "translation": "second", "stage": 5},
    ]
    with pytest.raises(SystemExit):
        from_paratranz(items)


def test_non_dict_entry_raises():
    with pytest.raises(SystemExit):
        from_paratranz(["not a dict"])


def test_skips_entry_without_key():
    items = [{"translation": "orphan", "stage": 5}]
    assert from_paratranz(items) == {}


def test_merge_files_union(tmp_path):
    f1 = tmp_path / "p1.json"
    f1.write_text(json.dumps([
        {"key": "a", "translation": "AA", "stage": 5},
    ]), encoding="utf-8")
    f2 = tmp_path / "p2.json"
    f2.write_text(json.dumps([
        {"key": "b", "translation": "BB", "stage": 5},
    ]), encoding="utf-8")
    assert merge_files([f1, f2]) == {"a": "AA", "b": "BB"}


def test_merge_files_cross_file_collision_raises(tmp_path):
    f1 = tmp_path / "p1.json"
    f1.write_text(json.dumps([{"key": "a", "translation": "AA", "stage": 5}]),
                  encoding="utf-8")
    f2 = tmp_path / "p2.json"
    f2.write_text(json.dumps([{"key": "a", "translation": "AA-prime", "stage": 5}]),
                  encoding="utf-8")
    with pytest.raises(SystemExit):
        merge_files([f1, f2])


def test_merge_rejects_non_list_file(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"key": "a"}), encoding="utf-8")  # object, not list
    with pytest.raises(SystemExit):
        merge_files([f])


def test_main_cli_single_file(tmp_path):
    in_path = tmp_path / "p.json"
    in_path.write_text(json.dumps([
        {"key": "x", "translation": "X", "stage": 5},
        {"key": "y", "translation": "draft", "stage": 1},
    ]), encoding="utf-8")
    out_path = tmp_path / "out.json"
    rc = main(["--paratranz", str(in_path), "--out", str(out_path), "--min-stage", "5"])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == {"x": "X"}


def test_main_cli_multiple_files(tmp_path):
    f1 = tmp_path / "p1.json"
    f1.write_text(json.dumps([{"key": "a", "translation": "AA", "stage": 5}]),
                  encoding="utf-8")
    f2 = tmp_path / "p2.json"
    f2.write_text(json.dumps([{"key": "b", "translation": "BB", "stage": 5}]),
                  encoding="utf-8")
    out_path = tmp_path / "out.json"
    rc = main(["--paratranz", str(f1), "--paratranz", str(f2),
               "--out", str(out_path)])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == {"a": "AA", "b": "BB"}
