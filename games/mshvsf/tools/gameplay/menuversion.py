"""Version line on the main menu - MSHvSF (SLUS-00793).  Counterpart of tools/titlepatch.py (own name: that module is on sys.path too) (XvSF).

    EXE        0x8003b780..  (dead, break-tested range 0x8003b780-0x8003b808, games/mshvsf/docs/CODESPACE.md)
               menuhook: one call of the game's text routine 0x80022e20(text, x << 16 | y, colour << 16 | 0x08000001)
               (the same call the main-menu routine makes for BATTLE ... GALLERY) + the string.
    OPDEMO.BIN (overlay at 0x80094800) 0x800994e0: `jr ra` at the end of the main-menu text routine
               0x80099404 (ra and s-registers restored, `addiu sp,sp,0x30` in the delay slot) -> `j menuhook`;
               menuhook returns to that routine's caller.  Runs only while the main menu is drawn.

patches()          EXE part [(addr, bytes)]
overlay_patches()  [(file, offset, bytes)] for OPDEMO.BIN on the disc
apply_ram(emu)     both; call while the main menu (OPDEMO.BIN) is in RAM.
"""
import os, struct, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mipsasm import Asm

ORG, LIMIT = 0x8003b780, 0x8003b808
MENU_AT, MENU_FILE, OVL_BASE = 0x800994e0, "OPDEMO.BIN", 0x80094800
MENU_ORIG = 0x03E00008                     # jr ra
PRINT = 0x80022e20
DEFAULT = "TAG HACK 1.0"
X_RIGHT, Y, COLOUR = 0x18c, 0xe8, 0x20     # right edge (x in the routine's units), bottom line, menu colour
CHAR_W = 8


def build(text=DEFAULT):
    assert text and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-" for c in text) and len(text) <= 24
    x = X_RIGHT - CHAR_W * len(text)
    a = Asm(ORG)
    a.label("menuhook")
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x10, "$sp")
    a.label("str_hi"); a.lui("$a0", 0)
    a.label("str_lo"); a.addiu("$a0", "$a0", 0)
    a.lui("$a1", x)
    a.ori("$a1", "$a1", Y)
    a.lui("$a2", 0x0800 | COLOUR)
    a.jal(PRINT)
    a.ori("$a2", "$a2", 1)
    a.lw("$ra", 0x10, "$sp")
    a.nop()
    a.jr("$ra")
    a.addiu("$sp", "$sp", 0x18)
    a.label("text")
    a.blob(text.encode() + b"\0" * (4 - len(text) % 4))
    code = bytearray(a.assemble()); L = a.labels()
    t = L["text"]; hi, lo = ((t + 0x8000) >> 16) & 0xFFFF, t & 0xFFFF
    code[L["str_hi"] - ORG:L["str_hi"] - ORG + 4] = struct.pack("<I", 0x3C040000 | hi)
    code[L["str_lo"] - ORG:L["str_lo"] - ORG + 4] = struct.pack("<I", 0x24840000 | lo)
    assert ORG + len(code) <= LIMIT, f"too big: {len(code)}"
    return bytes(code), L["menuhook"]


def patches(text=DEFAULT):
    return [(ORG, build(text)[0])]


def overlay_patches(text=DEFAULT):
    hook = build(text)[1]
    return [(MENU_FILE, MENU_AT - OVL_BASE, struct.pack("<I", 0x08000000 | (hook >> 2 & 0x3FFFFFF)))]


def apply_ram(emu, text=DEFAULT):
    assert emu.u32(MENU_AT) in (MENU_ORIG, struct.unpack("<I", overlay_patches(text)[0][2])[0]), "main menu overlay not in RAM"
    for addr, data in patches(text):
        emu.poke(addr, data)
    for f, off, data in overlay_patches(text):
        emu.poke(OVL_BASE + off, data)


if __name__ == "__main__":
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data.hex()}")
    for f, off, data in overlay_patches():
        print(f"{f} +{off:x} {data.hex()}")
