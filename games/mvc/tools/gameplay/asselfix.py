"""Select screen: the partner (2nd character) figure and name stay intact while / after the special-partner roulette
(mktag.py `--asselfix`, needs `--assistsel`).  Assist-bugs helper B, 2026-11-21.  All patches in DAT/SEL01.ARC.

Bug (rc4.6 / rc4.7, user report): with --assistsel every player picks main + partner and then gets the stock roulette
(assistsel.py A: state 10 sets the side's assist bit 0x8007b744).  Stock MvC never has a partner AND a special partner:
two SEL01 objects follow the bit and assume "bit set = no partner":
  1. the assist figure, code 0x154 object (record 0x8007cf68, one per side: 0x800849b8 P1 / 0x800848d0 P2 in Beetle),
     handler 0x80195520.., state at 0x80195568: once the roulette starts it checks the side's bit (0x801955b0) and, set,
     shows the roulette's current assist as a full figure at the PARTNER figure's spot (x 0x90 / 0x170, y 0xe0) with
     the partner's draw slot (+0x44 = 4 / 7, same as the partner figure code 0x44 object 0x80084d58 / 0x80084b88).
     The partner figure is still there: the two share the figure slot, so the partner is hidden behind / mixed with
     the assist and after the stop a wrong-coloured assist figure stays (the "glitched 2nd character").
  2. the partner's name label, code 0x54 kind 0x1c sub 2 (follows the code 0x44 figure; handler 0x8019777c): bit set
     and +0x2d != 0 -> 0x801979c0 (gone), so the partner's name (e.g. RYU) vanished when the roulette appeared.
Measured (Beetle, rc4.7, ARCADE P1 Zangief + Ryu, work/asselfix): object moves / kills in a state during the roulette
(only the 0x154 object moves the assist figure), VRAM: the assist figure uploads its frame cells into 576..600 x
257..335 (tpage 576, 4 bpp), which the partner figure no longer shows.

Fix (only with the flag; the roulette window, icons, cursor, name and the id 0x8007b8d8 / da are untouched):
  F1 0x801955c4 `beqz v0,0x801958ec` -> `b 0x801958ec`: the assist figure always removes itself at its bit check
     (stock: removed when the bit is clear).  Same handler at the ARCADE stage screen: there selscreen 5 / assistsel C
     already clear the bits before it, so it was removed there anyway (stagecheck: partner figures, no assist figure).
  F2 0x801977b8 `bnez v0,0x801979c0` -> nop: the partner name label (kind 0x1c, +0x2d != 0) no longer removes itself
     when the side's bit is set; the main's label (+0x2d = 0) never did.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from selscreen import FILE, BASE

FIXED = {    # RAM address: (stock word, new word)
    0x801955c4: (0x104000C9, 0x100000C9),     # F1 assist figure: `beqz v0, 0x801958ec` -> `b 0x801958ec`
    0x801977b8: (0x14400081, 0x00000000),     # F2 partner name label: `bnez v0, 0x801979c0` -> nop
}


def overlay_patches():
    """[(file, offset, bytes)] for DAT/SEL01.ARC (applied after allpatches / assistsel)"""
    return [(FILE, a - BASE, struct.pack("<I", n)) for a, (o, n) in sorted(FIXED.items())]


def check_file(data):
    for a, (o, n) in FIXED.items():
        assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"{FILE} +{a - BASE:x}: not stock (asselfix)"


if __name__ == "__main__":
    ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
    d = open(os.path.join(ROOT, "games", "mvc", "work", "gpw", "files", FILE), "rb").read()
    check_file(d)
    print("stock words ok:", ", ".join("%08x" % a for a in sorted(FIXED)))
