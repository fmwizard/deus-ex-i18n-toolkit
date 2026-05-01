"""Binary patch for Extension.dll — switch ComputerWindow word-wrap to
per-character.

`XComputerWindow::CalculateCharDisplayPosition` @ 0x10010710 runs a word-fit
lookahead that only treats ASCII space (0x20) as a word boundary. Without
spaces, a paragraph is one giant "word" longer than the column count, so the
caller breaks it at every character.

Fix: flip the space-boundary `jz` at 0x1001079D to an unconditional `jmp`.
The lookahead exits on iteration 1 every time → v8=0 → caller wraps via the
normal column-boundary path. Every char behaves like its own word.

Side effect: English word-wrap in ComputerTerminal is lost too; that's fine
when the target language fully replaces English in those views. Patching the
`bWordWrap` flag at its writers does not work — some unaudited path sets the
bit back on at runtime; the lookahead-side patch sidesteps the flag.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BinaryPatch:
    name: str
    # Unique stock pattern that brackets the edit. Must appear exactly once
    # in the whole DLL buffer.
    stock_pattern: bytes
    # Bytes to write in place of `stock_pattern` (same length required).
    new_pattern: bytes

    def apply(self, data: bytearray) -> None:
        if len(self.stock_pattern) != len(self.new_pattern):
            raise ValueError(f"{self.name}: pattern length mismatch")
        occ = _find_all(data, self.stock_pattern)
        if len(occ) != 1:
            raise RuntimeError(
                f"{self.name}: expected 1 match, got {len(occ)} "
                f"(pattern={self.stock_pattern.hex()})"
            )
        off = occ[0]
        data[off : off + len(self.new_pattern)] = self.new_pattern
        print(f"  OK {self.name}: @ file 0x{off:08x}")


def _find_all(data: bytes, pattern: bytes) -> list[int]:
    out = []
    start = 0
    while True:
        i = data.find(pattern, start)
        if i < 0:
            return out
        out.append(i)
        start = i + 1


# Stock lookahead @ 0x1001079D:
#   cmp word [eax+8], 20h     ; is this char ASCII space?
#   jz    loc_100107AF        ; yes -> exit loop with v8=0 (word fits)
#   inc   ecx                 ; no -> keep scanning
# The `jz` operand byte (0x74) flips to `jmp short` (0xEB); same displacement,
# no length change. The loop exits on iteration 1 every time -> v8=0 ->
# LABEL_14 places the char via the normal column-boundary wrap path.
LOOKAHEAD_PATCH = BinaryPatch(
    name="CalculateCharDisplayPosition lookahead jz->jmp",
    stock_pattern=bytes.fromhex("66 83 78 08 20 74 10 41".replace(" ", "")),
    new_pattern=bytes.fromhex("66 83 78 08 20 EB 10 41".replace(" ", "")),
)


PATCHES: list[BinaryPatch] = [
    LOOKAHEAD_PATCH,
]


def apply_all(stock: bytes) -> bytes:
    data = bytearray(stock)
    for p in PATCHES:
        p.apply(data)
    return bytes(data)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: python -m wrap_helpers.patch_extension_dll "
            "<stock_extension_dll> <out_extension_dll>"
        )
    stock_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    stock = stock_path.read_bytes()
    out = apply_all(stock)
    if len(out) != len(stock):
        raise SystemExit("patched DLL size must match stock")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    print(f"Wrote {out_path} ({len(out)} bytes, {len(PATCHES)} patches applied)")


if __name__ == "__main__":
    main()
