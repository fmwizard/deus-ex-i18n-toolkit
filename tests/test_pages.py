from atlas import AtlasTier, GlyphLoc, BucketAtlases
from pages import assemble_pages, NULL_TEXTURE_OBJREF


def _fake_bucket(tier, chars_map):
    """Build a BucketAtlases stub for testing without real rendering."""
    max_atlas = max((g.atlas_idx for g in chars_map.values()), default=-1)
    return BucketAtlases(
        atlases=[b"\0" * (256 * 256)] * (max_atlas + 1),
        char_to_glyph=chars_map,
        tier=tier,
    )


def test_assemble_pages_length_covers_bmp():
    tier = AtlasTier(cell=16, cpp=256, cells_per_atlas=256)
    ba = _fake_bucket(tier, {ord('A'): GlyphLoc(0, 0, 0, 8)})
    tex_refs = [10]  # ObjRef for atlas 0
    pages = assemble_pages(ba, vsize=10, texture_refs=tex_refs)
    # CPP=256 → Pages.Num must cover wchar 0..0xFFFF
    assert len(pages) == 0x10000 // 256


def test_assemble_pages_used_page_has_texture_and_chars():
    tier = AtlasTier(cell=16, cpp=256, cells_per_atlas=256)
    ba = _fake_bucket(tier, {ord('A'): GlyphLoc(0, 16, 0, 8)})
    pages = assemble_pages(ba, vsize=10, texture_refs=[42])
    # Page 0 has 'A' (wchar 0x41 < 256)
    page0 = pages[0]
    assert page0.texture_ref == 42
    # Characters array covers up through 'A' index at least
    assert len(page0.characters) >= ord('A') + 1
    # 'A' cell has our glyph data
    ch = page0.characters[ord('A')]
    assert ch.start_u == 16
    assert ch.u_size == 8
    assert ch.v_size == 10  # from vsize parameter


def test_assemble_pages_empty_page_has_null_texture():
    tier = AtlasTier(cell=16, cpp=256, cells_per_atlas=256)
    ba = _fake_bucket(tier, {0x4E00: GlyphLoc(0, 0, 0, 14)})  # '一' in page 0x4E
    pages = assemble_pages(ba, vsize=14, texture_refs=[99])
    # Page 0x50 has no chars → empty
    assert pages[0x50].texture_ref == NULL_TEXTURE_OBJREF
    assert pages[0x50].characters == []


def test_assemble_pages_vsize_applies_to_every_char():
    tier = AtlasTier(cell=16, cpp=256, cells_per_atlas=256)
    ba = _fake_bucket(tier, {
        ord('A'): GlyphLoc(0, 0, 0, 8),
        ord('B'): GlyphLoc(0, 16, 0, 8),
    })
    pages = assemble_pages(ba, vsize=17, texture_refs=[7])
    assert pages[0].characters[ord('A')].v_size == 17
    assert pages[0].characters[ord('B')].v_size == 17


def test_assemble_pages_multi_page_each_has_own_texture():
    tier = AtlasTier(cell=16, cpp=256, cells_per_atlas=256)
    ba = _fake_bucket(tier, {
        ord('A'):    GlyphLoc(0, 0, 0, 8),   # page 0 -> atlas 0
        0x4E00:      GlyphLoc(1, 0, 0, 14),  # page 0x4E -> atlas 1
    })
    pages = assemble_pages(ba, vsize=10, texture_refs=[100, 200])
    assert pages[0].texture_ref == 100
    assert pages[0x4E].texture_ref == 200
