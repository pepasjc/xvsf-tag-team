"""Second life bar per side (benched partner) for the tag hack - X-Men vs. Street Fighter (SLUS-00627).

The port still contains the arcade four-bar HUD; it is only switched off by the mode flag 0x8004278c
(1 in battle/versus/training):

  0x80033fbc..  every frame: display values 0x80042388 (P1 slot 0), 0x8004238a (P1 slot 1),
                0x8004238c (P2 slot 0), 0x8004238e (P2 slot 1) = main/partner object +0x224, exchanged
                when the main object's +0x230 ("swapped") is set -> a slot belongs to a CHARACTER.
  0x8008096c    yellow bars: 0x800804e0(state, obj, x, y, value, slot) for the two main objects and,
                only if 0x8004278c == 0 and the side's main character is not the boss (0x10), for the
                partner objects 0x80043178 / 0x800434b8 (slots 2/3, x 0x65 / -0xf5, y 0x14).
                0x800804e0 draws a slot thin (4 px instead of 7, 3 px lower) when its object has +0x230
                set, i.e. the benched character's bar is the small one - exactly the arcade look.
  0x80080d08    red (recoverable, +0x22c) bars, all four slots, always (0x80080b14).
  0x80080eec    bar frames: slots 2/3 only while their display value is non-zero.

Patch
  * stub (replaces `jal 0x80075414` at 0x8003402c, right after the display values are written):
    per SIDE  vis = this side's main character is not the boss (+0x54 != 0x10) and neither object
    of the side is "assist only" (+0x74, set by the round-init stub of tools/tagpatch.py for a
    reduced partner set; exchanged by a swap).  Stored in two flag bytes.  So in the boss fight the
    player's side keeps both bars when its partner is a full character, and the boss's side has
    one.  No life value is substituted or written: 0 = knocked out, drawn empty.
  * 0x8008096c: the 0x8004278c gate is removed, the two "main is the boss" tests become "flag == 0".
  * 0x80080eec: the two slot-1 frame tests read the flag instead of the display value.
  * 1.1 (not with --nospeed): the fight after Apocalypse is one character per side, as on the arcade -
    see FINAL in build().
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # tools/mipsasm.py
from mipsasm import Asm, REG

ORG, LIMIT = 0x800195d8, 0x80019674          # 156 bytes, break-tested dead code
EXE_BASE, EXE_HDR = 0x80010000, 0x800
HOOK_AT, HOOK_ORIG, ORIG_FN = 0x8003402c, 0x0C01D505, 0x80075414
BOSS = 0x10


class A(Asm):
    def srlv(self, rd, rt, rs):
        self._i(lambda pc, L: 0x06 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def nor(self, rd, rs, rt):
        self._i(lambda pc, L: 0x27 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def xor_(self, rd, rs, rt):
        self._i(lambda pc, L: 0x26 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)


MODE, IDS = 0x8004218c, 0x800423b2           # game mode (1 = arcade); P1 main, P1 partner, P2 main, P2 partner (char * 2)
PARTNER_LIFE = (0x80043178 + 0x224, 0x80043178 + 0x22c, 0x800434b8 + 0x224, 0x800434b8 + 0x22c)


def build(final=True):
    """final: 1.1 "fight after Apocalypse" rule (see FINAL below); False = the 1.0.1 stub."""
    a = A(ORG)
    a.label("stub")
    a.lui("$t7", 0x8004)
    a.addiu("$a0", "$t7", 0x2a10)                 # P1 main object
    a.label("fl_hi")
    a.lui("$a2", 0)                               # flag bytes (patched below)
    a.label("fl_lo")
    a.addiu("$a2", "$a2", 0)
    a.ori("$a3", "$zero", 2)
    if final:
        # FINAL: the arcade's last fight (after Apocalypse) is the player's point character against its
        # own partner, ONE character per side: the game sets both partner slots to the boss id with 0
        # life (FBNeo xmvsfu1d: ids 9/8 vs 0/8, one bar per side, one round).  The port mirrors the team
        # instead (P1 main = P1 partner, P2 main = P2 partner, both full) - in the hack a tag match.
        # Arcade mode with both sides mirrored happens only there.  Then: both partner objects get 0
        # life / 0 recoverable life every frame (= knocked out: the tag hook, team super, counter, the
        # CPU's arcade tag branch and the KO replacement all refuse a partner with 0 life) and their bars
        # are hidden.  t5 = 1 unless it is that fight.
        a.lb("$t4", MODE & 0xFFFF, "$t7")
        a.lh("$t5", (IDS + 0) & 0xFFFF, "$t7")
        a.lh("$t6", (IDS + 2) & 0xFFFF, "$t7")
        a.lh("$t8", (IDS + 4) & 0xFFFF, "$t7")
        a.lh("$t9", (IDS + 6) & 0xFFFF, "$t7")
        a.xori("$t4", "$t4", 1)
        a.xor_("$t5", "$t5", "$t6")
        a.xor_("$t8", "$t8", "$t9")
        a.or_("$t5", "$t5", "$t8")
        a.or_("$t5", "$t5", "$t4")
        a.bne("$t5", "$zero", "side")
        a.sltu("$t5", "$zero", "$t5")             # 1 = not the final fight
        for addr in PARTNER_LIFE:
            a.sh("$zero", addr & 0xFFFF, "$t7")
    a.label("side")
    a.lb("$t0", 0x54, "$a0")                      # this side's main character * 2
    a.lw("$t3", 0x234, "$a0")                     # partner object
    a.lb("$t1", 0x74, "$a0")                      # "assist only" = reduced set (exchanged by a swap,
    a.xori("$t0", "$t0", BOSS)                    #  so look at both objects of the side)
    a.lb("$t2", 0x74, "$t3")
    a.sltu("$t0", "$zero", "$t0")                 # 1 = main is not the boss
    a.addiu("$a3", "$a3", -1)
    a.or_("$t1", "$t1", "$t2")
    a.sltiu("$t1", "$t1", 1)                      # 1 = full partner
    a.and_("$t0", "$t0", "$t1")
    if final:
        a.and_("$t0", "$t0", "$t5")               # FINAL: no partner bar
    a.sb("$t0", 0, "$a2")                         # vis[side]
    a.addiu("$a0", "$a0", 0x348)                  # P2 main object
    a.bne("$a3", "$zero", "side")
    a.addiu("$a2", "$a2", 1)
    a.j(ORIG_FN)                                  # the call we replaced (tail)
    a.nop()
    a.label("flags")
    a.word(0)
    return a


def _w(*ws):
    return struct.pack(f"<{len(ws)}I", *ws)


def patches():
    a = build(final="--nospeed" not in sys.argv); code = bytearray(a.assemble())
    L = a.labels()
    fl = L["flags"]
    hi, lo = ((fl + 0x8000) >> 16) & 0xFFFF, fl & 0xFFFF
    code[L["fl_hi"] - ORG:L["fl_hi"] - ORG + 4] = _w(0x3C060000 | hi)
    code[L["fl_lo"] - ORG:L["fl_lo"] - ORG + 4] = _w(0x24C60000 | lo)
    assert ORG + len(code) <= LIMIT, f"stub too big: {len(code)}"
    lui_v0 = 0x3C020000 | hi
    lb_v0 = lambda n: 0x80420000 | ((lo + n) & 0xFFFF)
    assert (lo + 1) < 0x8000 or lo >= 0x8000
    return [
        (ORG, bytes(code)),
        (HOOK_AT, _w(0x0C000000 | ((L["stub"] >> 2) & 0x03FFFFFF))),   # was jal 0x80075414 (delay slot nop)
        (0x80080a68, _w(0)),                                          # was bnez v0 (0x8004278c) -> skip partner bars
        (0x80080a78, _w(lui_v0, lb_v0(0))),                           # was lb v0, P1 main +0x54
        (0x80080a84, _w(0x1040000C)),                                 # was beq v0,s0(0x10) -> beq v0,zero (same target)
        (0x80080abc, _w(lb_v0(1))),                                   # was lb v0,0x2dac(v0) with lui 0x8004 before
        (0x80080ab8, _w(lui_v0)),
        (0x80080ac8, _w(0x1040000C)),                                 # was beq v0,s0
        (0x80081048, _w(lui_v0, lb_v0(0))),                           # frame slot 1 of P1: was lh v0,0x8004238a
        (0x800810b8, _w(lui_v0, lb_v0(1))),                           # frame slot 1 of P2: was lh v0,0x8004238e
    ]


ORIG = {0x8003402c: 0x0C01D505, 0x80080a68: 0x14400024, 0x80080a78: 0x3C028004, 0x80080a7c: 0x80422A64,
        0x80080a84: 0x1050000C, 0x80080ab8: 0x3C028004, 0x80080abc: 0x80422DAC, 0x80080ac8: 0x1050000C,
        0x80081048: 0x3C028004, 0x8008104c: 0x8442238A, 0x800810b8: 0x3C028004, 0x800810bc: 0x8442238E}


def check_orig(read32):
    for a, w in ORIG.items():
        assert read32(a) == w, f"unexpected code at {a:08x}: {read32(a):08x}"


def apply_ram(emu):
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "disc", "files", "SLUS_006.27"), "rb").read()
    check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data[:16].hex()}")
