"""Assist HUD fixes (assist bugs lead, 2026-11-21; mktag.py `--ashud`, needs --assist --fs05).

Bug: in tag battles with assists the HUD assist portrait next to the "xN" stock counter was garbage (P1: thin strip,
P2: nothing).  Cause: the portrait 0x80043174 draws HUD elements 0x19 / 0x1a from the HUD page tiles 0xc9 (P1) / 0xdb
(P2), CLUT 0x15 (row 501); the stock versus loader fills them with 0x8002adfc(assist, 4 + side, 1) (LoadImage
(0x3c4 + 8 * slot, 0xc0, 8, 32) from the pointer the assist's init put into 0x80079da0[assist]); the tag loader never
did.  Fix part 1 = tagload.c AS_HUD (loader calls 0x8002adfc after each assist's init).  This file = part 2, EXE words:

  0x80043184 / 0x80043220  portrait P1 / P2: stock flag read -> ASSIST_GATE 0x800858c8 (as assist.py before rc4.4):
                           gate 1 in a tag battle -> drawn only for a side whose assist bit is set (AS_SAVE)
  0x80043288               P2 portrait x 0x1a0 -> 0x189 (the Cross Over position: the tag HUD also draws the
                           counter, which covered the portrait at 0x1a0)
  0x800433cc               P2 counter: flag read -> ASSIST_GATE (gate 1 -> the P2 bit decides, stock code)
  0x800432e4               counter function entry `lb v0,flag` -> `j CNT` (delay slot = the stock `addiu sp`):
                           v0 = flag | (gate & no assist bit at all) -> no counter in a tag battle without assists
                           (ASSIST OFF, fallback plan); Cross Over (gate = flag = 0) unchanged
CNT lives in stageanim chunk D 0x8002f780-0x8002f7b0 (48 B), unused in --fs05 builds (stageanim.py uses only chunk S
there; asserted by mktag).
"""
import os, struct, sys
# --ashudpal (rc4.9): HUD palette data of the secret assists, see palpatches()
PAL = {0x8006d306: (0x8c2d, 0x8c66, 0xfb00, 0xc2bb, 0xa9b4, 0x94c9),      # 0x14 Shadow   colours 3..8 (and 9..14)
       0x8006d326: (0xa4c8, 0xb90a, 0xc106, 0xc3de, 0xda12, 0xf6f7)}      # 0x15 Sentinel
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mipsasm import Asm

GATE, FLAG, BITS = 0x800858c8, 0x8007b75d, 0x8007b744
CNT, CNT_END = 0x8002f780, 0x8002f7b0
SITES = {    # addr: (stock word, new word)
    0x80043184: (0x80820075, 0x804258C8),     # lb v0,0x75(a0) -> lb v0,0x58c8(v0)  (v0 = 0x80080000)
    0x80043220: (0x80830075, 0x804358C8),     # lb v1,0x75(a0) -> lb v1,0x58c8(v0)
    0x80043288: (0x~~~~~~~~, 0x~~~~~~~~),     # addiu a2,zero,0x1a0 -> 0x189
    0x800433cc: (0x80830075, 0x804358C8),     # lb v1,0x75(a0) -> lb v1,0x58c8(v0)  (v0 = 0x80080000 from 0x800433c0)
    0x800432e4: (0x8042B75D, None),           # lb v0,-0x48a3(v0) -> j CNT
}


def lo(a):
    return a & 0xFFFF


def build():
    a = Asm(CNT)                                  # v0 = 0x80080000 (lui at 0x800432e0); sp already adjusted (delay slot)
    a.lb("$t1", lo(GATE), "$v0")
    a.lbu("$t0", lo(BITS), "$v0")
    a.lb("$v0", lo(FLAG), "$v0")
    a.andi("$t0", "$t0", 3)
    a.sltiu("$t0", "$t0", 1)                      # 1 = no assist on either side
    a.and_("$t0", "$t0", "$t1")                   # ... in a tag battle (gate 1)
    a.j(0x800432ec)
    a.or_("$v0", "$v0", "$t0")
    c = a.assemble()
    assert CNT + len(c) <= CNT_END
    return bytes(c)


def patches():
    exe = open(os.path.join(ROOT, "games", "mvc", "disc", "SLUS_010.59"), "rb").read()
    check(lambda ad: struct.unpack_from("<I", exe, ad - 0x80010000 + 0x800)[0])
    out = [(CNT, build())]
    for ad, (o, n) in SITES.items():
        if n is None: n = 0x08000000 | ((CNT & 0x0FFFFFFF) >> 2)
        out.append((ad, struct.pack("<I", n)))
    return out


def palpatches():
    """--ashudpal: secret assists 0x14 / 0x15 HUD portrait colours (stock entries = 0x8800 only -> black portrait).
    Entries 0x8006d300 / 0x8006d320 (map 0x8006ed9c[0x14 / 0x15] = 55 / 56, base 0x8006cc20); colours 3..14 = bytes
    6..29; alt half (9..14, obj+0xad) = the normal half.  Colours: work/asrou/palprev.py (Shadow: maroon suit, dark
    visor band, skin ramp, dark hair, backdrop 5 = HUD blue; Sentinel: lavender metal, blue-grey plate, yellow eyes)."""
    exe = open(os.path.join(ROOT, "games", "mvc", "disc", "SLUS_010.59"), "rb").read()
    out = []
    for ad, cols in PAL.items():
        o = ad - 0x80010000 + 0x800
        assert exe[o:o + 24] == struct.pack("<12H", *[0x8800] * 12), f"ashudpal: {ad:08x} not the stock black entry"
        out.append((ad, struct.pack("<12H", *(cols + cols))))
    return out


def check(read32):
    for ad, (o, n) in SITES.items():
        assert read32(ad) == o, f"ashud: {ad:08x} not stock ({read32(ad):08x})"
    for ad in range(CNT, CNT_END, 4):
        assert read32(ad) != 0x08000000 | ((CNT & 0x0FFFFFFF) >> 2)


if __name__ == "__main__":
    for ad, d in patches(): print(f"{ad:08x} {d.hex()}")
