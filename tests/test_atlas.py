import pytest
from atlas import AtlasTier, select_tier


def test_tier_small():
    t = select_tier(size_px=10)
    assert t.cell == 16
    assert t.cpp == 256
    assert t.cells_per_atlas == 256  # 16x16


def test_tier_medium():
    t = select_tier(size_px=14)
    assert t.cell == 20
    assert t.cpp == 128
    assert t.cells_per_atlas == 144  # 12x12 (atlas 256 / cell 20 = 12 remainder)


def test_tier_large():
    t = select_tier(size_px=24)
    assert t.cell == 32
    assert t.cpp == 64
    assert t.cells_per_atlas == 64  # 8x8


def test_tier_too_big_raises():
    with pytest.raises(ValueError, match="gate"):
        select_tier(size_px=30)


def test_tier_gated_by_vsize_when_larger():
    """vsize > size_px → tier must fit vsize, not size_px. The engine reads
    `vsize` rows from the cell, so a cell smaller than vsize bleeds into the
    cell below. Concrete case: size_px=17 vsize=23 must land in cell=32."""
    t = select_tier(size_px=17, vsize=23)
    assert t.cell == 32, f"vsize=23 must fit (cell>=23), got cell={t.cell}"
    # When vsize ≤ size_px, tier follows size_px (no regression for normal cases)
    t = select_tier(size_px=14, vsize=10)
    assert t.cell == 20

def test_tier_vsize_too_big_raises():
    with pytest.raises(ValueError, match="gate"):
        select_tier(size_px=10, vsize=30)


def test_tier_cpp_fits_atlas():
    """CharactersPerPage must be ≤ cells_per_atlas (naive one-page-one-atlas)."""
    for size_px in [8, 10, 12, 14, 17, 20, 24, 28]:
        t = select_tier(size_px)
        assert t.cpp <= t.cells_per_atlas, f"size_px={size_px}: CPP={t.cpp} > cells={t.cells_per_atlas}"


def test_glyph_loc_fields():
    from atlas import GlyphLoc
    g = GlyphLoc(atlas_idx=2, start_u=32, start_v=48, usize=10)
    assert g.atlas_idx == 2
    assert g.start_u == 32
    assert g.start_v == 48
    assert g.usize == 10


def test_bucket_atlases_fields():
    from atlas import GlyphLoc, BucketAtlases
    tier = select_tier(10)
    ba = BucketAtlases(atlases=[b"\0" * (256 * 256)], char_to_glyph={}, tier=tier)
    assert len(ba.atlases) == 1
    assert ba.char_to_glyph == {}
    assert ba.tier.cpp == 256


import os

CJK_TTF = os.environ.get("DX1_TEST_CJK_TTF")
CJK_TTF_ALT = os.environ.get("DX1_TEST_CJK_TTF_ALT")
VF_TTF = os.environ.get("DX1_TEST_VF_TTF")

HAS_CJK = bool(CJK_TTF) and os.path.exists(CJK_TTF)
HAS_CJK_ALT = bool(CJK_TTF_ALT) and os.path.exists(CJK_TTF_ALT)
HAS_VF = bool(VF_TTF) and os.path.exists(VF_TTF)


@pytest.mark.skipif(not HAS_CJK, reason="DX1_TEST_CJK_TTF not set")
def test_build_bucket_atlases_ascii_only():
    from atlas import build_bucket_atlases
    ascii_charset = list(range(0x20, 0x7F))  # 95 chars, fits page 0
    ba = build_bucket_atlases(ttf_path=CJK_TTF, size_px=10, charset=ascii_charset)
    # Page 0 only used (all ASCII wchar < 256) → 1 atlas
    assert len(ba.atlases) == 1
    for wchar in ascii_charset:
        assert wchar in ba.char_to_glyph, f"missing glyph for {chr(wchar)}"
        g = ba.char_to_glyph[wchar]
        assert g.atlas_idx == 0
        assert 0 <= g.start_u < 256
        assert 0 <= g.start_v < 256
        assert g.usize > 0
    # Atlas 0 is ATLAS_SIZE x ATLAS_SIZE P8
    assert len(ba.atlases[0]) == 256 * 256


@pytest.mark.skipif(not HAS_CJK, reason="DX1_TEST_CJK_TTF not set")
def test_nbsp_as_space_overrides_glyph():
    """nbsp_as_space=True must render U+00A0 identical to ASCII space. Pixel
    fonts that ship NBSP as a full-ink block produce visible tofu at word
    boundaries unless the override kicks in."""
    from atlas import build_bucket_atlases, ATLAS_SIZE
    charset = [ord(' '), 0x00A0, ord('中')]
    ba = build_bucket_atlases(
        ttf_path=CJK_TTF, size_px=10, charset=charset, nbsp_as_space=True,
    )

    g_space = ba.char_to_glyph[ord(' ')]
    g_nbsp = ba.char_to_glyph[0x00A0]
    assert g_nbsp.usize == g_space.usize, (
        f"NBSP advance {g_nbsp.usize} != space advance {g_space.usize}"
    )

    def cell_bytes(loc):
        buf = ba.atlases[loc.atlas_idx]
        out = bytearray()
        for row in range(ba.tier.cell):
            start = (loc.start_v + row) * ATLAS_SIZE + loc.start_u
            out += buf[start:start + ba.tier.cell]
        return bytes(out)

    assert cell_bytes(g_nbsp) == cell_bytes(g_space), (
        "NBSP atlas cell differs from space cell"
    )


@pytest.mark.skipif(not (HAS_CJK and HAS_CJK_ALT), reason="hybrid fonts not configured")
def test_hybrid_ascii_override_widens_ascii_advance():
    """With ascii_ttf set, ASCII usize comes from the alt font (wider) while
    CJK stays on the main font. Core hybrid-atlas invariant."""
    from atlas import build_bucket_atlases

    charset = [ord("A"), ord("B"), ord("中"), ord("文")]

    main_only = build_bucket_atlases(ttf_path=CJK_TTF, size_px=10, charset=charset)
    hybrid = build_bucket_atlases(
        ttf_path=CJK_TTF, size_px=10, charset=charset, ascii_ttf_path=CJK_TTF_ALT,
    )

    for ch in ("A", "B"):
        w = ord(ch)
        assert hybrid.char_to_glyph[w].usize > main_only.char_to_glyph[w].usize, (
            f"hybrid ASCII {ch!r} usize {hybrid.char_to_glyph[w].usize} "
            f"not > main-only {main_only.char_to_glyph[w].usize}"
        )
    for ch in ("中", "文"):
        w = ord(ch)
        assert hybrid.char_to_glyph[w].usize == main_only.char_to_glyph[w].usize, (
            f"hybrid should not touch CJK usize for {ch!r}"
        )


@pytest.mark.skipif(not (HAS_CJK and HAS_CJK_ALT), reason="hybrid fonts not configured")
def test_hybrid_cjk_pixels_match_main_only():
    """Hybrid atlas must render CJK glyphs pixel-identical to the main-only
    atlas. Guards against ascii_shift math leaking into the CJK render path."""
    from atlas import build_bucket_atlases, ATLAS_SIZE

    charset = [ord("A"), ord("中"), ord("文"), ord("码"), ord("头")]
    main_only = build_bucket_atlases(ttf_path=CJK_TTF, size_px=10, charset=charset)
    hybrid = build_bucket_atlases(
        ttf_path=CJK_TTF, size_px=10, charset=charset, ascii_ttf_path=CJK_TTF_ALT,
    )

    def cell_bytes(ba, loc):
        buf = ba.atlases[loc.atlas_idx]
        out = bytearray()
        for row in range(ba.tier.cell):
            start = (loc.start_v + row) * ATLAS_SIZE + loc.start_u
            out += buf[start : start + ba.tier.cell]
        return bytes(out)

    for ch in ("中", "文", "码", "头"):
        w = ord(ch)
        m_cell = cell_bytes(main_only, main_only.char_to_glyph[w])
        h_cell = cell_bytes(hybrid, hybrid.char_to_glyph[w])
        assert m_cell == h_cell, f"CJK {ch!r} pixels differ between main-only and hybrid"


@pytest.mark.skipif(not HAS_VF, reason="DX1_TEST_VF_TTF not set")
def test_vf_weight_changes_ink():
    """Bold (wght=700) must produce noticeably more ink than Regular (wght=400)
    for the same VF font + size_px. If the wght axis is not actually applied,
    both atlases render at the design default and ink totals match."""
    from atlas import build_bucket_atlases
    cjk_charset = [ord(c) for c in "中文测试字汉化"]
    regular = build_bucket_atlases(
        ttf_path=VF_TTF, size_px=17, charset=cjk_charset, weight=400,
    )
    bold = build_bucket_atlases(
        ttf_path=VF_TTF, size_px=17, charset=cjk_charset, weight=700,
    )
    def total_ink(ba):
        return sum(sum(b for b in atlas if b > 0) for atlas in ba.atlases)
    r_ink = total_ink(regular)
    b_ink = total_ink(bold)
    assert b_ink > r_ink * 1.1, (
        f"Bold ink {b_ink} not >10% heavier than Regular {r_ink} — "
        f"VF wght axis likely not being applied"
    )


@pytest.mark.skipif(not HAS_VF, reason="DX1_TEST_VF_TTF not set")
def test_vf_weight_none_leaves_design_default():
    """weight=None leaves the VF at its design default. For NotoSansSC the
    default is Thin (100), so the atlas renders lighter than weight=400."""
    from atlas import build_bucket_atlases
    cjk_charset = [ord(c) for c in "中文测试字汉化"]
    default = build_bucket_atlases(
        ttf_path=VF_TTF, size_px=17, charset=cjk_charset, weight=None,
    )
    regular = build_bucket_atlases(
        ttf_path=VF_TTF, size_px=17, charset=cjk_charset, weight=400,
    )
    def total_ink(ba):
        return sum(sum(b for b in atlas if b > 0) for atlas in ba.atlases)
    assert total_ink(default) < total_ink(regular), (
        f"weight=None ink {total_ink(default)} not < Regular {total_ink(regular)} — "
        f"design default may not be lighter or VF axis may have leaked through"
    )


@pytest.mark.skipif(not HAS_CJK, reason="DX1_TEST_CJK_TTF not set")
def test_pad_advance_extends_usize():
    """pad_advance={cp: n} adds n px to that codepoint's advance. Used to
    avoid visual merging of adjacent full-em-box glyphs (e.g. CJK U+2026)."""
    from atlas import build_bucket_atlases
    from PIL import ImageFont
    charset = [ord(' '), ord('A'), 0x2026]
    ba = build_bucket_atlases(
        ttf_path=CJK_TTF, size_px=10, charset=charset,
        pad_advance={0x2026: 1},
    )
    raw_font = ImageFont.truetype(CJK_TTF, 10)
    raw_advance = max(1, int(round(raw_font.getlength('…'))))
    g_ellipsis = ba.char_to_glyph[0x2026]
    assert g_ellipsis.usize == raw_advance + 1, (
        f"U+2026 usize={g_ellipsis.usize} expected raw {raw_advance} + 1"
    )
    # Chars not in pad_advance keep raw advance.
    g_A = ba.char_to_glyph[ord('A')]
    raw_A = max(1, int(round(raw_font.getlength('A'))))
    assert g_A.usize == raw_A
