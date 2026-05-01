"""Binary patch for DeusExText.dll — runtime NBSP transform on
DDeusExTextParser::GetText output.

Datacube/news/email text in DeusExText.u is typically pre-processed (ASCII
space swapped to NBSP) so the engine word-wrapper doesn't break mid-word.
The runtime <PLAYERNAME> substitution however injects the player's name
with ASCII space, bypassing that pre-processing — the wrapper then breaks
the name across two lines.

Fix: hook GetText @ 0x100018e0 (the single egress for case 0/9/10 text
fetches). After it copies the wstring into the caller's FString buffer,
scan all wchars and replace 0x0020 → 0x00A0. Pre-processed text passes
through unchanged; runtime-injected names get their spaces hardened.

Before applying this "blanket transform on shared egress" pattern to a
different DLL, audit the egress callers to confirm none depend on
ASCII-space identity (e.g. `InStr(text, " ")` lookups would break).

Hook layout: 5-byte JMP rel32 at 0x1000193c → code cave at RVA 0x6660 (in
the .text padding tail [vsize=0x5653, rsize=0x6000) — file-aligned, mapped
at runtime). Cave does the scan, replays the 3 overwritten instructions,
JMPs back to 0x10001941.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path


IMAGEBASE = 0x10000000

# RVAs (== file offsets for this PE; .text vaddr == raddr == 0x1000).
HOOK_SITE_RVA   = 0x0000193C  # original: mov eax,[ebp+8] / pop ebx / pop edi
HOOK_RETURN_RVA = 0x00001941  # JMP-back target inside GetText (pop esi)
CAVE_RVA        = 0x00006660  # 16-byte aligned, well inside padding tail

CAVE_SIZE       = 36

# Unique 28-byte anchor bracketing the hook site. The 5-byte trailing slice
# (`8B 45 08 5B 5F`) at anchor[23:28] is what we overwrite; the 23-byte prefix
# captures GetText's local-variable reloads (specific [ebp-0x0C/-0x08/-0x04])
# plus the rep movsd / mov ecx,ebx / rep movsb tail. The shorter 11-byte
# epilogue-only pattern collides with another function at 0x100055AB whose
# local-var slots are different (see GetText vs sub_100055A0 disasm).
HOOK_ANCHOR_STOCK = bytes.fromhex(
    "8B4DF4"        # mov ecx, [ebp-0x0C]
    "8B75F8"        # mov esi, [ebp-0x08]
    "8B7DFC"        # mov edi, [ebp-0x04]
    "8BD9"          # mov ebx, ecx
    "C1E902"        # shr ecx, 2
    "83E303"        # and ebx, 3
    "F3A5"          # rep movsd
    "8BCB"          # mov ecx, ebx
    "F3A4"          # rep movsb
    "8B4508"        # mov eax, [ebp+8]   <- overwrite start (anchor[23])
    "5B"            # pop ebx
    "5F"            # pop edi
)
HOOK_ANCHOR_OFFSET = 0x1925              # file offset where anchor starts
HOOK_OVERWRITE_OFFSET_IN_ANCHOR = 23     # anchor[23:28] = the 5 bytes we replace


def _rel32(src_addr: int, dst_addr: int, instr_len: int = 5) -> bytes:
    """Encode signed 32-bit displacement: dst - (src + instr_len)."""
    rel = dst_addr - (src_addr + instr_len)
    return struct.pack("<i", rel)


def _build_jmp_to_cave() -> bytes:
    return b"\xE9" + _rel32(IMAGEBASE + HOOK_SITE_RVA, IMAGEBASE + CAVE_RVA)


def _build_cave() -> bytes:
    """36-byte cave: scan a2->data and replace wchar 0x0020 with 0x00A0,
    then replicate the 3 instructions overwritten by the JMP.

    Layout (offset within cave):
      +0   8B 45 08         mov eax, dword ptr [ebp+8]   ; eax = a2 (FString*)
      +3   8B 48 04         mov ecx, dword ptr [eax+4]   ; ecx = a2->count
      +6   85 C9            test ecx, ecx
      +8   74 13            jz cave_done (+29)
      +10  8B 10            mov edx, dword ptr [eax]     ; edx = a2->data
      +12  66 83 3A 20      cmp word ptr [edx], 0x20     ; cave_loop
      +16  75 05            jne cave_skip (+23)
      +18  66 C7 02 A0 00   mov word ptr [edx], 0xA0
      +23  83 C2 02         add edx, 2                   ; cave_skip
      +26  49               dec ecx
      +27  75 EF            jnz cave_loop (+12)
      +29  5B               pop ebx                       ; replicate 0x1000193f
      +30  5F               pop edi                       ; replicate 0x10001940
      +31  E9 ?? ?? ?? ??   jmp 0x10001941

    Registers used: eax/ecx/edx - all volatile in MSVC thiscall, no save needed.
    EBP is intact throughout (frame pointer untouched).
    """
    body = bytes.fromhex(
        "8B4508"        # mov eax, [ebp+8]
        "8B4804"        # mov ecx, [eax+4]
        "85C9"          # test ecx, ecx
        "7413"          # jz +0x13 (cave_done)
        "8B10"          # mov edx, [eax]
        "66833A20"      # cmp word [edx], 0x20
        "7505"          # jne +5 (cave_skip)
        "66C702A000"    # mov word [edx], 0xA0
        "83C202"        # add edx, 2
        "49"            # dec ecx
        "75EF"          # jnz -17 (cave_loop)
        "5B"            # pop ebx
        "5F"            # pop edi
    )
    if len(body) != 31:
        raise RuntimeError(f"cave body {len(body)} != 31")
    jmp_back = b"\xE9" + _rel32(IMAGEBASE + CAVE_RVA + 31, IMAGEBASE + HOOK_RETURN_RVA)
    cave = body + jmp_back
    if len(cave) != CAVE_SIZE:
        raise RuntimeError(f"cave {len(cave)} != {CAVE_SIZE}")
    return cave


def _verify_pe_layout(data: bytes) -> None:
    """Sanity-check assumptions: .text raddr == vaddr == 0x1000, cave fits in
    raw section."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    size_opt = struct.unpack_from("<H", data, e_lfanew + 0x14)[0]
    sec_table = e_lfanew + 0x18 + size_opt
    name = data[sec_table : sec_table + 8].rstrip(b"\x00").decode("ascii", "replace")
    if name != ".text":
        raise RuntimeError(f"first PE section is '{name}', expected '.text'")
    vsize = struct.unpack_from("<I", data, sec_table + 0x08)[0]
    vaddr = struct.unpack_from("<I", data, sec_table + 0x0C)[0]
    rsize = struct.unpack_from("<I", data, sec_table + 0x10)[0]
    raddr = struct.unpack_from("<I", data, sec_table + 0x14)[0]
    if vaddr != raddr:
        raise RuntimeError(
            f"PE assumption broken: .text vaddr=0x{vaddr:x}, raddr=0x{raddr:x} "
            "(this patcher needs RVA == file offset for .text)"
        )
    if not (vaddr <= CAVE_RVA < vaddr + rsize):
        raise RuntimeError(
            f"cave RVA 0x{CAVE_RVA:x} not within .text raw range "
            f"[0x{vaddr:x}, 0x{vaddr + rsize:x})"
        )
    if CAVE_RVA + CAVE_SIZE > vaddr + rsize:
        raise RuntimeError("cave overruns .text raw section")
    # Cave must lie *past* vsize so it doesn't overlap any function code.
    if CAVE_RVA < vaddr + vsize:
        raise RuntimeError(
            f"cave RVA 0x{CAVE_RVA:x} overlaps .text vsize "
            f"(0x{vaddr:x}..0x{vaddr + vsize:x})"
        )


def apply_all(stock: bytes) -> bytes:
    data = bytearray(stock)
    _verify_pe_layout(data)

    anchor_at = data.find(HOOK_ANCHOR_STOCK)
    if anchor_at < 0:
        raise RuntimeError(f"hook anchor not found (pattern={HOOK_ANCHOR_STOCK.hex()})")
    if data.find(HOOK_ANCHOR_STOCK, anchor_at + 1) >= 0:
        raise RuntimeError(f"hook anchor not unique (pattern={HOOK_ANCHOR_STOCK.hex()})")
    if anchor_at != HOOK_ANCHOR_OFFSET:
        raise RuntimeError(
            f"hook anchor at unexpected offset 0x{anchor_at:x} "
            f"(expected 0x{HOOK_ANCHOR_OFFSET:x})"
        )

    jmp_bytes = _build_jmp_to_cave()
    new_anchor = (
        HOOK_ANCHOR_STOCK[:HOOK_OVERWRITE_OFFSET_IN_ANCHOR]
        + jmp_bytes
    )
    if len(new_anchor) != len(HOOK_ANCHOR_STOCK):
        raise RuntimeError("new_anchor length mismatch")
    data[anchor_at : anchor_at + len(HOOK_ANCHOR_STOCK)] = new_anchor
    print(f"  OK hook site: file 0x{HOOK_SITE_RVA:08x}: 5-byte JMP rel32 -> cave")

    cave_bytes = _build_cave()
    pre = bytes(data[CAVE_RVA : CAVE_RVA + CAVE_SIZE])
    if any(b != 0 for b in pre):
        raise RuntimeError(
            f"cave region 0x{CAVE_RVA:x}..0x{CAVE_RVA + CAVE_SIZE:x} "
            f"not zero-filled (found {pre.hex()})"
        )
    data[CAVE_RVA : CAVE_RVA + CAVE_SIZE] = cave_bytes
    print(f"  OK code cave: file 0x{CAVE_RVA:08x}: {CAVE_SIZE} bytes")

    return bytes(data)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: python -m wrap_helpers.patch_deusextext_dll <stock> <out>"
        )
    stock_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    stock = stock_path.read_bytes()
    out = apply_all(stock)
    if len(out) != len(stock):
        raise SystemExit("patched DLL size must match stock")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    print(f"Wrote {out_path} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
