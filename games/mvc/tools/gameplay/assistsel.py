"""Special partner (assist) roulette back in the tag-mode select (allpatches.overlay_patches(assist=True), mktag.py
`--assistsel`).  Every player (VERSUS, ARCADE, TRAINING incl. the dummy) picks main + partner and then gets the
stock special-partner roulette; the ARCADE CPU team gets a random assist.  Result at the battle load: assist bit per
side 0x8007b744 (bit0 P1, bit1 P2) set and id 0x8007b8d8 s16[2] = assist * 4 (0x00..0x15).  Without the option
nothing changes (selscreen.py output stays byte-identical).  All patches are in DAT/SEL01.ARC (selscreen.BASE).

Stock flow (per-player select machine 0x8018f958, states = +4, table 0x801b01c4[state / 2]):
  2  main picked (0x8018fe10): versus flag set -> assist bit cleared, TYPE SELECT question (selscreen 1: skipped)
  6  (0x80190098): bit set ("special partner") -> partner = main, on to 10; bit clear -> 8 (partner pick)
  8  partner pick (0x80190170) -> 10
  10 (0x80190280): versus flag set and the side's bit clear -> no roulette; else the kind-6 roulette object
     (0x801980f4(0x8007cf68, side, 0x600); object code 0x8019881c.., ids 0x801b8d48[0..21]) is spawned: the player
     stops it (or it stops by itself), it writes 0x8007b8d8 / da.  Stock versus started it from the TYPE SELECT
     "special" answer (bit set in state 4).

Patches (only with the option):
  A. 0x801902c4 `lb v0,0x5c(v1)` (state 10's bit read; delay slot `lb v1,1(s2)` = side) -> `jal asbit`: the side's
     bit is set and returned, so state 10 always spawns the stock roulette after the partner pick (stock code and
     graphics; the training dummy runs the same machine, selscreen 4).
  B. 0x801900e0 `bnez v0,0x801900f4` (state 6) -> nop: always the partner pick, even when a bit is still set (cancel
     after the roulette).  The stock "special" path 0x801900f4-0x8019016c (124 B) is then unreachable (no other branch
     / jump / data word into it: SEL01 scan) and holds our code.
  C. ARCADE CPU (mode 0, one human): the stage-screen stub (selscreen 5, CPUTEAM) keeps clearing both bits before
     the stage figures (stagecheck: partner figures, no assist figure), after 0x80047418 has put a random assist
     (stock table 0x80071824, ids 0x00-0x13) into the CPU side's id.  The VS screen's first portrait init
     (0x801970a4, selscreen's `jal vsinit`) -> `jal vsas`: bits = 3 (human's roulette + CPU's random id), then the
     same vsinit.  Challenger / demo / other modes: untouched.
  D. select end 0x8018f2d0 (versus flag set): a side with the bit set got partner = main (TEAM +0x84 / +0x88, partner
     object id, stock solo + assist) and a side without it the default id 0x10.  Both skipped (0x8018f4b4,
     0x8018f528 `beqz` -> `b` past the side's block): the picked partner and the roulette id stay.
  E. same function: the "hold 3 buttons = partner starts" swap (pad & 0x70) only ran with the bit clear
     (0x8018f3ac, 0x8018f43c `bnez` -> nop): it works again with the assist.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import selscreen
from selscreen import Asm, FILE, BASE, JAL, lo

ORG, LIMIT = 0x801900f4, 0x80190170                     # state 6 "special partner" path, dead after B
BITS = 0x8007b744
SITE_A, SITE_B, SITE_C = 0x801902c4, 0x801900e0, 0x801970a4


def build():
    L0 = selscreen.build()[1]
    a = Asm(ORG)
    # asbit: v1 = side (0 / 1, loaded in the jal's delay slot); returns v0 = bits with the side's bit set
    a.label("asbit")
    a.lui("$t0", 0x8008)
    a.lbu("$v0", lo(BITS), "$t0")
    a.addiu("$t1", "$v1", 1)                             # side 0 -> bit 1, side 1 -> bit 2
    a.or_("$v0", "$v0", "$t1")
    a.jr("$ra")
    a.sb("$v0", lo(BITS), "$t0")
    # vsas: ARCADE with one human -> both bits, then vsinit (its registers: none expected from here)
    a.label("vsas")
    a.lui("$t1", 0x8008)
    a.lb("$t2", lo(0x8007b740), "$t1")                   # mode: 0 ARCADE
    a.lbu("$t3", lo(0x8007bdc9), "$t1")                  # human sides: 1 P1, 2 P2, 3 both
    a.bne("$t2", "$zero", "vsas_go")
    a.addiu("$t3", "$t3", -1)
    a.sltiu("$t3", "$t3", 2)
    a.beq("$t3", "$zero", "vsas_go")
    a.ori("$t2", "$zero", 3)
    a.sb("$t2", lo(BITS), "$t1")
    a.label("vsas_go")
    a.j(L0["vsinit"])
    a.nop()
    code = a.assemble(); L = a.labels()
    assert ORG + len(code) <= LIMIT, f"assistsel code too big: {len(code)} B, room {LIMIT - ORG}"
    return bytes(code), L


SITES = {    # RAM address: stock word (SITE_C: stock under selscreen's `jal vsinit`)
    SITE_A: 0x8062005C,
    SITE_B: 0x14400004,
    SITE_C: 0x8042B75D,
}
FIXED = {    # D / E: select end 0x8018f2d0, words (stock, new)
    0x8018f4b4: (0x1040000C, 0x10000011),               # D. P1 bit set -> partner = main: `beqz` -> `b 0x8018f4fc`
    0x8018f528: (0x1040000C, 0x10000011),               #    P2: `beqz` -> `b 0x8018f570` (also skips the id 0x10 default)
    0x8018f3ac: (0x1440000E, 0x00000000),               # E. P1 3-button order swap blocked by the bit: `bnez` -> nop
    0x8018f43c: (0x14400010, 0x00000000),               #    P2
}
SITES.update((a, o) for a, (o, n) in FIXED.items())


def ram_patches():
    code, L = build()
    return [(ORG, code), (SITE_A, struct.pack("<I", JAL(L["asbit"]))), (SITE_B, bytes(4)),
            (SITE_C, struct.pack("<I", JAL(L["vsas"])))] + [(a, struct.pack("<I", n)) for a, (o, n) in sorted(FIXED.items())]


def overlay_patches():
    """[(file, offset, bytes)] for DAT/SEL01.ARC, applied after selscreen's (SITE_C replaces its word)"""
    return [(FILE, a - BASE, d) for a, d in ram_patches()]


def check_file(data):
    for a, o in SITES.items():
        assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"{FILE} +{a - BASE:x}: not stock"
    assert struct.unpack_from("<I", data, ORG - BASE)[0] == 0x1460000C              # `bnez v1,0x80190128`


if __name__ == "__main__":
    code, L = build()
    print(len(code), "of", LIMIT - ORG, "bytes;", {k: hex(v) for k, v in L.items()})
    ROOT = selscreen.ROOT
    d = open(os.path.join(ROOT, "games", "mvc", "work", "gpw", "files", FILE), "rb").read()
    check_file(d)
    print("stock words ok")
