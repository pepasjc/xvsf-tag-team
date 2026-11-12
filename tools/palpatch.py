"""Palette fix for the tag switch (X-Men vs. Street Fighter, SLUS-00627).

Where character colours come from
  * 0x80042258[char]  -> that character's palette block inside its loaded data: 3 CLUT rows
    (0x60 bytes); the alternate colour set follows at +0x60 and is chosen by object +0x22a.
  * Each of the four player objects owns three fixed CLUT rows, index in object +0x238:
    P1 12, P2 15, P1 partner 18, P2 partner 21   (row n = VRAM (0, 480+n), 16 colours).
  * 0x8002e018(obj) uploads the rows of BOTH objects of obj's side from the characters they
    currently play (0x8002e1dc for P1's side, 0x8002e330 for P2's side; plus 0x8002e59c extras),
    through 0x8002de80(data, row, count) -> 0x8002c554 -> LoadImage.
  The tag swap 0x8006b248 exchanges the characters of the two objects (and their +0x22a flags)
  but nobody re-uploads the rows, so the incoming character is drawn with the rows of the
  character that object played before, until some later event calls 0x8002e018.

Patch: in the tag request handler 0x8006e9a0, the `jal 0x8006fbd4` at 0x8006e9b8 (right after the
swap) is redirected to a stub that does the original call and then 0x8002e018(obj).

  0x80015ad0  40 bytes   stub (verified-dead libgpu code, reserved range 0x80015ad0-0x80015b34)
  0x8006e9b8   4 bytes   jal stub      (was jal 0x8006fbd4; delay slot `move a0,s0` kept)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # tools/mipsasm.py
from mipsasm import Asm

ORG, LIMIT = 0x80015ad0, 0x80015b34
HOOK_AT, HOOK_ORIG = 0x8006e9b8, 0x0C01BEF5        # jal 0x8006fbd4
FACE = 0x8006fbd4            # original callee (leaf): facing update
SIDE_PALETTES = 0x8002e018   # (obj) upload main + partner palettes of obj's side
EXE_BASE, EXE_HDR = 0x80010000, 0x800


def build():
    a = Asm(ORG)
    a.label("stub")                       # a0 = s0 = the object that tagged (delay slot of the jal)
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x10, "$sp")
    a.jal(FACE)                           # the call we replaced
    a.nop()
    a.jal(SIDE_PALETTES)                  # both objects of this side now play other characters
    a.addu("$a0", "$s0", "$zero")
    a.lw("$ra", 0x10, "$sp")
    a.nop()
    a.jr("$ra")
    a.addiu("$sp", "$sp", 0x18)
    return a


def patches():
    a = build(); code = a.assemble()
    assert ORG + len(code) <= LIMIT
    stub = a.labels()["stub"]
    return [(ORG, code), (HOOK_AT, struct.pack("<I", 0x0C000000 | ((stub >> 2) & 0x03FFFFFF)))]


def apply_ram(emu):
    assert emu.u32(HOOK_AT) in (HOOK_ORIG, struct.unpack("<I", patches()[1][1])[0]), "unexpected code at the hook"
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    for addr, data in patches():
        print(f"{addr:08x} {len(data):3d} {data.hex()}")
