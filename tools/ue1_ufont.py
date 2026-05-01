"""UE1 UFont read/write. Disk layout per docs/ue1-package-format.md."""
import struct
from dataclasses import dataclass, field
from typing import List

from ue1_reader import read_compact_index, write_compact_index


@dataclass
class FFontCharacter:
    start_u: int
    start_v: int
    u_size: int
    v_size: int

    @staticmethod
    def parse(data: bytes, off: int):
        su, sv, us, vs = struct.unpack_from("<iiii", data, off)
        return FFontCharacter(su, sv, us, vs), 16

    def serialize(self) -> bytes:
        return struct.pack("<iiii", self.start_u, self.start_v, self.u_size, self.v_size)


@dataclass
class FFontPage:
    texture_ref: int  # ObjRef: +N = export N-1, -N = import N-1, 0 = NULL
    characters: List[FFontCharacter] = field(default_factory=list)

    @staticmethod
    def parse(data: bytes, off: int):
        start = off
        tex, k = read_compact_index(data, off); off += k
        num, k = read_compact_index(data, off); off += k
        chars = []
        for _ in range(num):
            ch, k = FFontCharacter.parse(data, off); off += k
            chars.append(ch)
        return FFontPage(tex, chars), off - start

    def serialize(self) -> bytes:
        out = bytearray()
        out += write_compact_index(self.texture_ref)
        out += write_compact_index(len(self.characters))
        for ch in self.characters:
            out += ch.serialize()
        return bytes(out)


@dataclass
class UFont:
    none_name_idx: int                   # CompactIndex of "None" in parent package name table
    pages: List[FFontPage] = field(default_factory=list)
    characters_per_page: int = 256

    @staticmethod
    def parse(data: bytes, none_name_idx: int):
        off = 0
        term, k = read_compact_index(data, off); off += k
        assert term == none_name_idx, f"expected None idx={none_name_idx}, got {term}"
        num, k = read_compact_index(data, off); off += k
        pages = []
        for _ in range(num):
            p, k = FFontPage.parse(data, off); off += k
            pages.append(p)
        cpp = struct.unpack_from("<I", data, off)[0]; off += 4
        assert off == len(data), f"parse left {len(data) - off}B unread"
        return UFont(none_name_idx, pages, cpp)

    def serialize(self) -> bytes:
        out = bytearray()
        out += write_compact_index(self.none_name_idx)
        out += write_compact_index(len(self.pages))
        for p in self.pages:
            out += p.serialize()
        out += struct.pack("<I", self.characters_per_page)
        return bytes(out)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from ue1_reader import Package

    pkg = Package(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else "FontMenuSmall"
    none_idx = pkg.names.index("None")

    exp = next(e for e in pkg.exports if e["name"] == target)
    orig = pkg.read_export_bytes(exp)
    font = UFont.parse(orig, none_idx)
    out = font.serialize()

    print(f"{target}: orig={len(orig)}B, serialized={len(out)}B, match={orig == out}")
    print(f"  Pages={len(font.pages)}, CharsPerPage={font.characters_per_page}")
    print(f"  Page[0]: tex_ref={font.pages[0].texture_ref}, chars={len(font.pages[0].characters)}")
    if orig != out:
        for i in range(min(len(orig), len(out))):
            if orig[i] != out[i]:
                print(f"  first diff @ {i}: orig={orig[i]:02x} out={out[i]:02x}")
                break
