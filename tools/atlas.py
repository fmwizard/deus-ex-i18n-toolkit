"""Per-bucket atlas generation. See docs/font-pipeline-internals.md."""
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont


ATLAS_SIZE = 256  # stock UE1 D3DDrv hardcoded 256 max tex dim (single mip required)


@dataclass(frozen=True)
class AtlasTier:
    cell: int             # square cell edge in atlas pixels
    cpp: int              # CharactersPerPage, 2^n, ≤ cells_per_atlas
    cells_per_atlas: int  # (ATLAS_SIZE // cell) ** 2


def select_tier(size_px: int, vsize: int | None = None) -> AtlasTier:
    """Choose CELL + CPP for a rendering bucket.

    Tier is gated by `max(size_px, vsize)` rather than `size_px` alone — the
    engine reads `vsize` rows from the cell, so when `vsize > cell` it spills
    into the cell directly below in atlas (whose top rows then appear as stray
    pixels at the bottom of the displayed glyph). Forcing tier to fit `vsize`
    keeps `cell >= vsize` and eliminates that overflow. Stock fonts where
    VSize > size_px (e.g. FontConversationLarge: size_px=17 vsize=23) used to
    silently land in the wrong tier and bleed; this gate fixes them.
    """
    gate = max(size_px, vsize) if vsize is not None else size_px
    if gate <= 12:
        cell, cpp = 16, 256
    elif gate <= 20:
        cell, cpp = 20, 128
    elif gate <= 28:
        cell, cpp = 32, 64
    else:
        raise ValueError(f"size_px/vsize gate={gate} exceeds supported tier (≤28)")
    cells_per_atlas = (ATLAS_SIZE // cell) ** 2
    return AtlasTier(cell=cell, cpp=cpp, cells_per_atlas=cells_per_atlas)


@dataclass(frozen=True)
class GlyphLoc:
    atlas_idx: int  # index into BucketAtlases.atlases
    start_u: int    # atlas-relative pixel X
    start_v: int    # atlas-relative pixel Y
    usize: int      # x-advance (font.getlength)


@dataclass
class BucketAtlases:
    atlases: list[bytes]               # list of ATLAS_SIZE×ATLAS_SIZE P8 bytes
    char_to_glyph: dict[int, GlyphLoc] # wchar -> location
    tier: AtlasTier


def _ink_bottom(font: "ImageFont.FreeTypeFont", char: str) -> int:
    """Return the bottom row of `char`'s actual rendered ink, not its metric
    bbox.  PIL's font.getbbox() can extend past the inked pixels (e.g. Small
    SimSun 'A' metric bottom=10 but ink bottom=9), which throws off baseline
    alignment between fonts whose metric-vs-ink gap differs.  This probe
    renders the char into a generous canvas and uses Image.getbbox() to find
    the true ink extent, then maps back to the font's coordinate system."""
    canvas_h = font.size * 3
    img = Image.new("L", (font.size * 4, canvas_h), 0)
    ImageDraw.Draw(img).text((0, 0), char, fill=255, font=font)
    bbox = img.getbbox()
    if bbox is None:
        return font.getbbox(char)[3]  # blank glyph fallback
    return bbox[3]


def _apply_weight(font: "ImageFont.FreeTypeFont", weight: int | None) -> None:
    """Pin a Variable Font's wght axis to `weight` (e.g. 400=Regular, 700=Bold).

    PIL loads VF files with the font designer's design-default — for
    NotoSansSC-VF that is Thin (100), so without an explicit set the atlas
    renders as if no weight was selected.  Static TTFs have no axes and the
    OSError early-return is harmless.

    PIL's axis dict has fields {minimum, default, maximum, name} — no `tag`
    field, so the weight axis must be matched by `name == b"Weight"`.
    """
    if weight is None:
        return
    try:
        axes = font.get_variation_axes()
    except OSError:
        return  # not a VF
    if not axes:
        return
    values = [a.get("default", weight) for a in axes]
    for i, a in enumerate(axes):
        if a.get("name") == b"Weight":
            values[i] = weight
    font.set_variation_by_axes(values)


def build_bucket_atlases(
    ttf_path: str,
    size_px: int,
    charset: list[int],
    ascii_ttf_path: str | None = None,
    vert_align: str = 'top',
    vsize: int | None = None,
    weight: int | None = None,
    baseline_priority_range: tuple[int, int] | None = None,
    align_bottom_range: tuple[int, int] | None = None,
    nbsp_as_space: bool = False,
    pad_advance: dict[int, int] | None = None,
) -> BucketAtlases:
    """Render every char in charset into per-page atlases.

    Layout: one atlas per used logical page (wchar // CPP).
    Chars within a page take cells in order of increasing wchar,
    at cell index (wchar % CPP).

    `ascii_ttf_path` (optional): render wchars < 0x80 from a different TTF
    while the rest of the charset stays on `ttf_path`. Use for fixed-grid
    HUD paths where the main font's half-width ASCII leaves visible gaps in
    a 10-px cell. Alt ASCII glyphs are baseline-aligned to the main font's
    ASCII 'A' so mixed lines still share a visual baseline.

    `vert_align`: 'top' (default) renders glyphs aligned to cell top — bbox
    top → y=0 within each cell. 'bottom' renders aligned to cell bottom —
    deepest priority-range bottom → y=vsize-1, leaving any vsize-vs-ink
    padding at the top. 'bottom' requires `vsize` so the offset can be
    computed; engines that read atlas[start_v : start_v+vsize] will then see
    whitespace + glyph rather than glyph + whitespace, which is what HUD
    slots with top-clip text areas need.

    `baseline_priority_range`: (lo, hi) codepoint range whose bbox tops drive
    the baseline. Outliers in the rest of the charset (e.g. accented Latin)
    are ignored. For CJK localizations: (0x4E00, 0x9FFF).

    `align_bottom_range`: (lo, hi) codepoint range whose bbox bottoms drive
    `vert_align='bottom'`. Same value as `baseline_priority_range` is typical.

    `nbsp_as_space`: render U+00A0 as ASCII space. Use when an upstream
    pipeline swaps space → NBSP to suppress word-wrap (typical for CJK).

    `pad_advance`: {codepoint: extra_px} added to that char's advance. Use to
    fix tight inter-glyph spacing — e.g. `{0x2026: 1}` for CJK ellipsis where
    adjacent `……` visually merge into one blob.
    """
    if vert_align not in ('top', 'bottom'):
        raise ValueError(f"vert_align must be 'top' or 'bottom', got {vert_align!r}")
    if vert_align == 'bottom' and vsize is None:
        raise ValueError("vert_align='bottom' requires vsize")
    tier = select_tier(size_px, vsize)
    cols = ATLAS_SIZE // tier.cell
    font = ImageFont.truetype(ttf_path, size_px)
    _apply_weight(font, weight)

    # Baseline shift: when baseline_priority_range is set, use min bbox top
    # from that range only, ignoring outliers in the rest of the charset. A
    # few accented Latin / Greek chars often have bbox[1] < CJK top, which
    # would shove CJK glyphs downward and clip their bottoms against the
    # per-glyph VSize clip the engine applies (esp. in tight vsize=9..13
    # cells). Useful when one charset dominates the visual surface.
    bpr = baseline_priority_range
    abr = align_bottom_range
    priority_tops: list[int] = []
    priority_bottoms: list[int] = []
    all_tops: list[int] = []
    for wchar in charset:
        bbox = font.getbbox(chr(wchar))
        if bbox[2] > bbox[0]:
            all_tops.append(bbox[1])
            if bpr and bpr[0] <= wchar <= bpr[1]:
                priority_tops.append(bbox[1])
            if abr and abr[0] <= wchar <= abr[1]:
                priority_bottoms.append(bbox[3])
    if priority_tops:
        min_top = min(priority_tops)
    elif all_tops:
        min_top = min(all_tops)
    else:
        min_top = 0

    # For vert_align='bottom', compute the y shift that puts the deepest
    # priority-range glyph bottom at cell row (vsize-1). Aligning to the
    # deepest descender in the configured range keeps every glyph in the
    # cell. Render position: draw_y = cell_top + (vsize - max_bottom),
    # equivalent to substituting min_top below with that expression.
    if vert_align == 'bottom':
        max_bottom = max(priority_bottoms) if priority_bottoms else size_px
        # Reuse the existing draw.text(y - min_top) path: solving
        #   cell_top - effective_min_top == cell_top + (vsize - max_bottom)
        # gives effective_min_top = max_bottom - vsize.
        min_top = max_bottom - vsize

    # Optional ASCII override font + baseline shift. The alt font's 'A' bottom
    # is aligned to the main font's 'A' bottom so both glyph sets share a
    # visual baseline. Use ink bottom from a probe render rather than
    # font.getbbox() — PIL's metric bbox can extend past the actual ink (e.g.
    # Small SimSun 'A' getbbox bottom=10 but ink bottom=9, while BOUTIQUE 'A'
    # getbbox=ink=9). Aligning by metric leaves the alt 'A' 1 px below the
    # main 'A' on screen.
    ascii_font = None
    ascii_shift = min_top
    if ascii_ttf_path is not None:
        ascii_font = ImageFont.truetype(ascii_ttf_path, size_px)
        _apply_weight(ascii_font, weight)
        main_a_bottom = _ink_bottom(font, "A")
        alt_a_bottom = _ink_bottom(ascii_font, "A")
        ascii_shift = alt_a_bottom - main_a_bottom + min_top

    # Group charset by logical page
    pages_chars: dict[int, list[int]] = {}
    for wchar in charset:
        p = wchar // tier.cpp
        pages_chars.setdefault(p, []).append(wchar)

    # Stable page order for reproducible output
    used_pages = sorted(pages_chars.keys())
    atlases: list[bytes] = []
    char_to_glyph: dict[int, GlyphLoc] = {}

    for atlas_idx, page in enumerate(used_pages):
        img = Image.new("L", (ATLAS_SIZE, ATLAS_SIZE), 0)
        draw = ImageDraw.Draw(img)
        for wchar in pages_chars[page]:
            cell_idx = wchar % tier.cpp
            if cell_idx >= tier.cells_per_atlas:
                raise RuntimeError(
                    f"cell_idx {cell_idx} overflow cells_per_atlas {tier.cells_per_atlas}"
                )
            col = cell_idx % cols
            row = cell_idx // cols
            x = col * tier.cell
            y = row * tier.cell
            # When nbsp_as_space is set, render U+00A0 as ASCII space. Used
            # by pipelines that swap space → NBSP globally to suppress
            # word-wrap (typical for CJK lines without natural break points).
            # Some TTFs ship U+00A0 as a full-ink placeholder block instead
            # of inheriting the space glyph; this override avoids tofu boxes
            # at every word boundary in those cases.
            glyph_char = " " if (nbsp_as_space and wchar == 0x00A0) else chr(wchar)
            use_ascii_override = ascii_font is not None and wchar < 0x80
            render_font = ascii_font if use_ascii_override else font
            render_shift = ascii_shift if use_ascii_override else min_top
            draw.text((x, y - render_shift), glyph_char, fill=255, font=render_font)
            usize = max(1, int(round(render_font.getlength(glyph_char))))
            # Per-char advance padding. CJK fonts paint U+2026 spanning the
            # full em-box, so two adjacent `……` end up with inter-glyph dot
            # gap ≈ 0–1 px while intra-glyph gap is 2–3 px, visually merging
            # the middle two dots; pad_advance={0x2026: 1} balances that.
            if pad_advance and wchar in pad_advance:
                usize += pad_advance[wchar]
            char_to_glyph[wchar] = GlyphLoc(
                atlas_idx=atlas_idx, start_u=x, start_v=y, usize=usize
            )
        atlases.append(img.tobytes())

    return BucketAtlases(atlases=atlases, char_to_glyph=char_to_glyph, tier=tier)


# Missing-glyph behavior: when the TTF lacks a glyph for some wchar,
# `font.getbbox` returns a zero-area bbox and `draw.text` renders nothing.
# The char still gets a char_to_glyph entry with usize≥1 and an empty atlas
# cell — in game this shows as a 1-pixel gap. Using '?' as a replacement
# glyph would require per-char detection and re-rendering.
