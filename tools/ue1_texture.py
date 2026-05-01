"""UE1 UTexture + UPalette + FMipmap write.

Build-only (full parser not required). Tagged-property block is rebuilt in a
fixed field order matching stock DeusExUI UTexture layout:

    bMasked, Palette, UBits, VBits, USize, VSize, UClamp, VClamp,
    InternalTime[0], InternalTime[1], None

Name indices and InfoByte values come from the target package's name table
and the stock texture's observed encoding.
"""
import struct
from dataclasses import dataclass, field
from typing import List

from ue1_reader import write_compact_index


@dataclass
class UPalette:
    none_name_idx: int
    colors: List[tuple]  # list of (B, G, R, A) tuples

    def serialize(self) -> bytes:
        out = bytearray()
        out += write_compact_index(self.none_name_idx)  # None terminator for tagged props
        out += write_compact_index(len(self.colors))
        for b, g, r, a in self.colors:
            out += struct.pack("<BBBB", b, g, r, a)
        return bytes(out)


@dataclass
class FMipmap:
    data: bytes            # P8 pixel bytes, len = usize * vsize
    usize: int
    vsize: int

    @property
    def ubits(self) -> int:
        v = (self.usize - 1).bit_length()
        assert 1 << v == self.usize, f"usize {self.usize} not 2^n"
        return v

    @property
    def vbits(self) -> int:
        v = (self.vsize - 1).bit_length()
        assert 1 << v == self.vsize, f"vsize {self.vsize} not 2^n"
        return v

    def serialize(self, abs_start: int) -> bytes:
        """abs_start = absolute file offset where this FMipmap begins.

        WidthOffset is a TLazyArray skip pointer, not a free field. The engine
        does `Seek(WidthOffset)` to jump past pixel data and read the trailing
        USize/VSize/UBits/VBits, so WidthOffset = abs file offset of the byte
        right after DataArray.
        """
        assert len(self.data) == self.usize * self.vsize, \
            f"data len {len(self.data)} != {self.usize}*{self.vsize}"
        data_num_bytes = write_compact_index(len(self.data))
        end_of_data_rel = 4 + len(data_num_bytes) + len(self.data)
        width_offset = abs_start + end_of_data_rel

        out = bytearray()
        out += struct.pack("<I", width_offset)
        out += data_num_bytes
        out += self.data
        out += struct.pack("<II", self.usize, self.vsize)
        out += struct.pack("<BB", self.ubits, self.vbits)
        return bytes(out)


@dataclass
class UTexture:
    """Rebuild a simple P8 UTexture in a DeusExUI-style package."""
    # Name-table indices (look these up in the parent Package once)
    none_idx: int
    bmasked_idx: int
    palette_idx: int
    ubits_idx: int
    vbits_idx: int
    usize_idx: int
    vsize_idx: int
    uclamp_idx: int
    vclamp_idx: int
    internal_time_idx: int

    palette_ref: int   # ObjRef to UPalette export (+N / -N / 0)
    usize: int
    vsize: int
    mips: List[FMipmap]
    bmasked: bool = False
    internal_time: tuple = (0, 0)  # two INT32s

    def _ubits(self) -> int:
        v = (self.usize - 1).bit_length()
        assert 1 << v == self.usize
        return v

    def _vbits(self) -> int:
        v = (self.vsize - 1).bit_length()
        assert 1 << v == self.vsize
        return v

    def _write_palette_prop(self, out: bytearray):
        ref_bytes = write_compact_index(self.palette_ref)
        # size_code slot in InfoByte encodes payload byte count; pick the smallest fit
        sc_map = {1: 0, 2: 1, 4: 2}
        if len(ref_bytes) not in sc_map:
            raise ValueError(f"palette_ref CompactIndex size {len(ref_bytes)} not encodable")
        size_code = sc_map[len(ref_bytes)]
        info = (size_code << 4) | 5  # type=5 (Object), bit7=0, bit6..4=size_code
        out += write_compact_index(self.palette_idx)
        out += struct.pack("<B", info)
        out += ref_bytes

    def serialize(self, abs_start: int = 0) -> bytes:
        """abs_start = absolute file offset where this UTexture binary begins.
        Needed because each FMipmap's WidthOffset must point into the final file."""
        out = bytearray()

        # bMasked: Bool — InfoByte 0xd3 (matches stock), payload 1B value
        out += write_compact_index(self.bmasked_idx)
        out += b"\xd3"
        out += b"\x01" if self.bmasked else b"\x00"

        # Palette: Object
        self._write_palette_prop(out)

        # UBits, VBits: Byte (size_code=0, 1B payload)
        out += write_compact_index(self.ubits_idx); out += b"\x01"; out += struct.pack("<B", self._ubits())
        out += write_compact_index(self.vbits_idx); out += b"\x01"; out += struct.pack("<B", self._vbits())

        # USize, VSize, UClamp, VClamp: Int (size_code=2, 4B payload)
        for name_idx, val in [
            (self.usize_idx, self.usize),
            (self.vsize_idx, self.vsize),
            (self.uclamp_idx, self.usize),   # UClamp = USize
            (self.vclamp_idx, self.vsize),   # VClamp = VSize
        ]:
            out += write_compact_index(name_idx); out += b"\x22"; out += struct.pack("<i", val)

        # InternalTime[0] and InternalTime[1]: Int, static array
        out += write_compact_index(self.internal_time_idx); out += b"\x22"; out += struct.pack("<i", self.internal_time[0])
        out += write_compact_index(self.internal_time_idx); out += b"\xa2"; out += b"\x01"; out += struct.pack("<i", self.internal_time[1])

        # None terminator
        out += write_compact_index(self.none_idx)

        # Binary tail: Mips TArray (no CompMips since bHasComp flag not set)
        out += write_compact_index(len(self.mips))
        for m in self.mips:
            mip_abs_start = abs_start + len(out)
            out += m.serialize(mip_abs_start)

        return bytes(out)
