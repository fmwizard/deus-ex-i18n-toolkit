"""Tests for wrap_helpers.patch_extension_dll — single-byte jz->jmp patch."""
import os
from pathlib import Path

import pytest

from wrap_helpers.patch_extension_dll import (
    LOOKAHEAD_PATCH,
    PATCHES,
    apply_all,
)

STOCK_DLL = os.environ.get("DX1_TEST_STOCK_EXTENSION_DLL")
HAS_STOCK = bool(STOCK_DLL) and Path(STOCK_DLL).exists()

pytestmark = pytest.mark.skipif(
    not HAS_STOCK, reason="DX1_TEST_STOCK_EXTENSION_DLL not set"
)


@pytest.fixture(scope="module")
def stock_bytes() -> bytes:
    return Path(STOCK_DLL).read_bytes()


@pytest.fixture(scope="module")
def patched_bytes(stock_bytes) -> bytes:
    return apply_all(stock_bytes)


def test_stock_pattern_unique(stock_bytes):
    """Lookahead pattern must occur exactly once in stock — uniqueness is what
    lets `apply()` write without ambiguity."""
    occurrences = []
    start = 0
    while True:
        i = stock_bytes.find(LOOKAHEAD_PATCH.stock_pattern, start)
        if i < 0:
            break
        occurrences.append(i)
        start = i + 1
    assert len(occurrences) == 1, f"pattern found at {occurrences}, expected 1"


def test_output_size_unchanged(stock_bytes, patched_bytes):
    assert len(patched_bytes) == len(stock_bytes)


def test_only_one_byte_changes(stock_bytes, patched_bytes):
    """The whole patch is a single jz->jmp byte flip (0x74 -> 0xEB)."""
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(stock_bytes, patched_bytes)) if a != b]
    assert len(diffs) == 1, f"expected 1 changed byte, got {len(diffs)}: {diffs[:10]}"
    _, before, after = diffs[0]
    assert before == 0x74, f"stock byte should be jz (0x74), got 0x{before:02X}"
    assert after == 0xEB, f"patched byte should be jmp short (0xEB), got 0x{after:02X}"


def test_patched_pattern_present(stock_bytes, patched_bytes):
    """The full new_pattern must appear in the patched buffer at the same offset."""
    new_off = patched_bytes.find(LOOKAHEAD_PATCH.new_pattern)
    stock_off = stock_bytes.find(LOOKAHEAD_PATCH.stock_pattern)
    assert new_off == stock_off and new_off >= 0


def test_apply_is_deterministic(stock_bytes):
    out1 = apply_all(stock_bytes)
    out2 = apply_all(stock_bytes)
    assert out1 == out2


def test_apply_to_already_patched_raises(patched_bytes):
    """Re-applying must fail loudly (stock pattern is gone)."""
    with pytest.raises(RuntimeError, match="expected 1 match, got 0"):
        apply_all(patched_bytes)


def test_patches_list_contains_lookahead():
    assert LOOKAHEAD_PATCH in PATCHES


def test_patch_pattern_lengths_match():
    assert len(LOOKAHEAD_PATCH.stock_pattern) == len(LOOKAHEAD_PATCH.new_pattern)
