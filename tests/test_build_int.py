"""Tests for build_int: UTF-8 → UTF-16 LE + BOM transcoder."""
from __future__ import annotations

import pytest

from build_int import BOM, _is_valid_line, _smoke_check, _transcode, transcode_dir


def test_transcode_plain_ascii():
    src = b'[Section]\r\nKey="value"\r\n'
    out = _transcode(src)
    assert out[:2] == BOM
    assert out[2:].decode("utf-16-le") == '[Section]\r\nKey="value"\r\n'


def test_transcode_non_ascii():
    src = 'Name="斯科特"\r\n'.encode("utf-8")
    out = _transcode(src)
    assert out[:2] == BOM
    assert out[2:].decode("utf-16-le") == 'Name="斯科特"\r\n'


def test_transcode_absorbs_utf8_bom():
    """A stray UTF-8 BOM at the source head is dropped, not re-emitted."""
    src = b"\xef\xbb\xbf" + 'Name="斯科特"\r\n'.encode("utf-8")
    out = _transcode(src)
    assert out[:2] == BOM
    text = out[2:].decode("utf-16-le")
    assert not text.startswith("﻿")
    assert text == 'Name="斯科特"\r\n'


def test_transcode_empty_file():
    src = b""
    out = _transcode(src)
    assert out == BOM


def test_transcode_invalid_utf8_raises():
    with pytest.raises(UnicodeDecodeError):
        _transcode(b"\xff\xfe\x80\x81")


@pytest.mark.parametrize("line", [
    "",
    "   ",
    "[Section]",
    "[UNATCOTroop0]",
    "Key=value",
    'Name="Scott"',
    'Name="斯科特"',
    'NanoKeyData[0]="(...)"',
    "; comment",
    "// comment",
    "  [Section]  ",
    "  Key = value",
])
def test_valid_line_accepts(line):
    assert _is_valid_line(line)


@pytest.mark.parametrize("line", [
    "garbage no equals",
    "123=no leading digit",
    "= no key",
    "random text with spaces and punctuation!",
])
def test_valid_line_rejects(line):
    assert not _is_valid_line(line)


def test_smoke_check_happy(tmp_path):
    path = tmp_path / "ok.int"
    data = BOM + '[S]\r\nKey="v"\r\n; comment\r\n'.encode("utf-16-le")
    assert _smoke_check(path, data) == []


def test_smoke_check_missing_bom(tmp_path):
    path = tmp_path / "nobom.int"
    data = '[S]\r\nKey="v"\r\n'.encode("utf-16-le")
    errs = _smoke_check(path, data)
    assert len(errs) == 1
    assert "BOM missing" in errs[0]


def test_smoke_check_catches_junk_line(tmp_path):
    path = tmp_path / "junk.int"
    data = BOM + "[S]\r\ngarbage line with no equals\r\n".encode("utf-16-le")
    errs = _smoke_check(path, data)
    assert len(errs) == 1
    assert "INI smoke fail" in errs[0]
    assert "junk.int:2" in errs[0]


def test_transcode_dir_happy(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()

    (src / "a.int").write_bytes('[A]\r\nKey="中文"\r\n'.encode("utf-8"))
    (src / "b.int").write_bytes('[B]\r\nK[0]="x"\r\n'.encode("utf-8"))

    count, errors = transcode_dir(src, out)

    assert count == 2
    assert errors == []
    assert (out / "a.int").exists()
    assert (out / "b.int").exists()
    assert (out / "a.int").read_bytes()[:2] == BOM
    assert (out / "a.int").read_bytes()[2:].decode("utf-16-le") == '[A]\r\nKey="中文"\r\n'


def test_transcode_dir_missing_source_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        transcode_dir(tmp_path / "nope", tmp_path / "out")


def test_transcode_dir_empty_source_raises(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    with pytest.raises(FileNotFoundError):
        transcode_dir(src, tmp_path / "out")


def test_transcode_dir_propagates_smoke_errors(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()

    (src / "bad.int").write_bytes('[S]\r\njunk line\r\n'.encode("utf-8"))

    count, errors = transcode_dir(src, out)

    assert count == 1
    assert len(errors) == 1
    assert "bad.int:2" in errors[0]


def test_transcode_dir_ignores_non_int(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()

    (src / "a.int").write_bytes(b'[A]\r\nKey="v"\r\n')
    (src / "readme.txt").write_bytes(b"skip me")

    count, errors = transcode_dir(src, out)
    assert count == 1
    assert errors == []
    assert not (out / "readme.txt").exists()
