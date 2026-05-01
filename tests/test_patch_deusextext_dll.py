"""Tests for wrap_helpers.patch_deusextext_dll — GetText egress NBSP hook.

Covers:
  - Stock anchor uniqueness + offset
  - Cave area is all-zero padding before patch
  - Output size unchanged
  - JMP rel32 deltas point at the right addresses
  - Cave bytes match the hand-encoded assembly
  - Non-target regions are byte-identical to stock
"""
import os
import struct
from pathlib import Path

import pytest

from wrap_helpers.patch_deusextext_dll import (
    CAVE_RVA,
    CAVE_SIZE,
    HOOK_ANCHOR_OFFSET,
    HOOK_ANCHOR_STOCK,
    HOOK_OVERWRITE_OFFSET_IN_ANCHOR,
    HOOK_RETURN_RVA,
    HOOK_SITE_RVA,
    IMAGEBASE,
    _build_cave,
    _build_jmp_to_cave,
    apply_all,
)

STOCK_DLL = os.environ.get("DX1_TEST_STOCK_DEUSEXTEXT_DLL")
HAS_STOCK = bool(STOCK_DLL) and Path(STOCK_DLL).exists()

pytestmark = pytest.mark.skipif(
    not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXTEXT_DLL not set"
)


@pytest.fixture(scope="module")
def stock_bytes() -> bytes:
    return Path(STOCK_DLL).read_bytes()


@pytest.fixture(scope="module")
def patched_bytes(stock_bytes) -> bytes:
    return apply_all(stock_bytes)


def test_stock_anchor_at_expected_offset(stock_bytes):
    occ = []
    start = 0
    while True:
        i = stock_bytes.find(HOOK_ANCHOR_STOCK, start)
        if i < 0:
            break
        occ.append(i)
        start = i + 1
    assert len(occ) == 1, f"anchor must be unique, found at {occ}"
    assert occ[0] == HOOK_ANCHOR_OFFSET, (
        f"anchor at file offset 0x{occ[0]:x}, expected 0x{HOOK_ANCHOR_OFFSET:x}"
    )


def test_cave_region_is_zero_padding_in_stock(stock_bytes):
    region = stock_bytes[CAVE_RVA : CAVE_RVA + CAVE_SIZE]
    assert region == b"\x00" * CAVE_SIZE, f"cave region not all zero: {region.hex()}"


def test_output_size_unchanged(stock_bytes, patched_bytes):
    assert len(patched_bytes) == len(stock_bytes)


def test_output_differs_from_stock(stock_bytes, patched_bytes):
    assert patched_bytes != stock_bytes


def test_jmp_at_hook_site(patched_bytes):
    """The 5 bytes at HOOK_SITE_RVA must be JMP rel32 pointing to the cave."""
    jmp = patched_bytes[HOOK_SITE_RVA : HOOK_SITE_RVA + 5]
    assert jmp[0:1] == b"\xE9"
    rel = struct.unpack("<i", jmp[1:5])[0]
    target = HOOK_SITE_RVA + 5 + rel
    assert target == CAVE_RVA, (
        f"hook JMP lands at RVA 0x{target:x}, expected cave 0x{CAVE_RVA:x}"
    )


def test_anchor_prefix_preserved(patched_bytes):
    """The 23-byte anchor prefix (local-var reloads + rep movsd/movsb) is left
    intact — only the trailing 5 bytes were overwritten."""
    prefix_len = HOOK_OVERWRITE_OFFSET_IN_ANCHOR
    prefix = patched_bytes[HOOK_ANCHOR_OFFSET : HOOK_ANCHOR_OFFSET + prefix_len]
    assert prefix == HOOK_ANCHOR_STOCK[:prefix_len]


def test_cave_bytes_match_design(patched_bytes):
    """Bit-for-bit comparison against the hand-encoded cave."""
    cave = patched_bytes[CAVE_RVA : CAVE_RVA + CAVE_SIZE]
    assert cave == _build_cave()


def test_cave_jmp_back_points_at_pop_esi(patched_bytes):
    """The trailing JMP in the cave must land on HOOK_RETURN_RVA (=pop esi at
    0x10001941)."""
    jmp_back = patched_bytes[CAVE_RVA + 31 : CAVE_RVA + 36]
    assert jmp_back[0:1] == b"\xE9"
    rel = struct.unpack("<i", jmp_back[1:5])[0]
    target = (CAVE_RVA + 31) + 5 + rel
    assert target == HOOK_RETURN_RVA, (
        f"cave back-JMP lands at RVA 0x{target:x}, expected 0x{HOOK_RETURN_RVA:x}"
    )


def test_only_two_regions_modified(stock_bytes, patched_bytes):
    """Only the 5-byte hook site and the 36-byte cave should differ; nothing
    else."""
    expected_modified = set()
    expected_modified.update(range(HOOK_SITE_RVA, HOOK_SITE_RVA + 5))
    expected_modified.update(range(CAVE_RVA, CAVE_RVA + CAVE_SIZE))
    actual_modified = {
        i for i, (a, b) in enumerate(zip(stock_bytes, patched_bytes)) if a != b
    }
    extra = actual_modified - expected_modified
    assert not extra, f"unexpected diff at offsets: {sorted(extra)[:20]}"


def test_apply_is_deterministic(stock_bytes):
    out1 = apply_all(stock_bytes)
    out2 = apply_all(stock_bytes)
    assert out1 == out2


def test_apply_to_already_patched_raises(patched_bytes):
    with pytest.raises(RuntimeError, match="anchor"):
        apply_all(patched_bytes)


def test_jmp_to_cave_rel32_correct():
    jmp = _build_jmp_to_cave()
    assert jmp[0:1] == b"\xE9"
    rel = struct.unpack("<i", jmp[1:5])[0]
    assert (IMAGEBASE + HOOK_SITE_RVA) + 5 + rel == IMAGEBASE + CAVE_RVA


def test_cave_size_constant():
    assert len(_build_cave()) == CAVE_SIZE
