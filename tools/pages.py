"""Assemble a UFont's dense Pages[] array from BucketAtlases + VSize.

Engine `WrappedPrint` uses `page = wchar / CPP` as a direct index into Pages[],
so Pages[] must be dense. Unused pages are placeholder FFontPage with
NULL texture_ref and Characters=[].
"""
from ue1_ufont import FFontCharacter, FFontPage
from atlas import BucketAtlases

NULL_TEXTURE_OBJREF = 0

BMP_SIZE = 0x10000


def assemble_pages(
    ba: BucketAtlases,
    vsize: int,
    texture_refs: list[int],
) -> list[FFontPage]:
    """Build the Pages[] list for one UFont.

    texture_refs[atlas_idx] is the UTexture ObjRef (+1-based export index)
    for atlas #atlas_idx. len(texture_refs) must equal len(ba.atlases).
    """
    if len(texture_refs) != len(ba.atlases):
        raise ValueError(
            f"texture_refs len {len(texture_refs)} != atlas count {len(ba.atlases)}"
        )
    cpp = ba.tier.cpp
    pages_num = BMP_SIZE // cpp  # ceil not needed; BMP_SIZE is 2^16, cpp is 2^n

    # Group glyphs by logical page
    page_glyphs: dict[int, dict[int, tuple]] = {}  # page -> {cell_idx: GlyphLoc}
    for wchar, gl in ba.char_to_glyph.items():
        p = wchar // cpp
        cell_idx = wchar % cpp
        page_glyphs.setdefault(p, {})[cell_idx] = gl

    pages: list[FFontPage] = []
    empty_char = FFontCharacter(0, 0, 0, 0)
    for p in range(pages_num):
        if p not in page_glyphs:
            pages.append(FFontPage(texture_ref=NULL_TEXTURE_OBJREF, characters=[]))
            continue
        glyphs = page_glyphs[p]
        max_cell = max(glyphs.keys())
        chars: list[FFontCharacter] = []
        for i in range(max_cell + 1):
            gl = glyphs.get(i)
            if gl is None:
                chars.append(empty_char)
            else:
                chars.append(FFontCharacter(
                    start_u=gl.start_u, start_v=gl.start_v, u_size=gl.usize, v_size=vsize,
                ))
        # All glyphs in a page must come from the same atlas (naive strategy)
        atlas_ids = {gl.atlas_idx for gl in glyphs.values()}
        assert len(atlas_ids) == 1, f"page {p} spans {len(atlas_ids)} atlases"
        atlas_idx = atlas_ids.pop()
        pages.append(FFontPage(texture_ref=texture_refs[atlas_idx], characters=chars))
    return pages
