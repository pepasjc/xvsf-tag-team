"""Select screen + VS (loading) screen - Marvel vs. Capcom (SLUS-01059).  All patches are in DAT/SEL01.ARC
(file 371, read to 0x8018dcec by 0x8002c850; entry 0 = the select AND VS screen code at 0x8018dd00).  Nothing in
the EXE.  Patch addresses are RAM addresses; file offset = addr - 0x8018dcec.

1. No special partner (assist) in VERSUS / ARCADE / TRAINING: the per-player select state machine 0x8018f958
   (jump table 0x801b01c4 by +4/2) asks after the main pick "TYPE SELECT" (state 4: partner or special partner).
   State 2 (0x8018fe10) already clears the side's assist bit (0x8007b744, +0x19) before going there; the Cross
   Over path skips state 4 (+4 += 4 at 0x8018ffc0).  Patch: the VERSUS path takes the Cross Over exit too
   (0x8018ffb0 `jal 0x80199c34` (question window) -> nop, 0x8018ffb8 `j 0x801909e0` -> `j 0x8018ffc0`):
   every player picks a partner, the assist bit stays 0, so the special-partner roulette (state 10, needs the bit)
   and the assist files never come.  State 4 (0x8018ffd4-0x80190098, 196 B) is now dead: our code lives there.

2. Secret characters unlocked: the cursor-move function 0x80190ba0 blocks the step into a hidden cell unless the
   save-data word 0x8007b72c (memory card) has the bit:
       Chun-Li up -> Red Venom (0x12)        bit 6    0x80190c00
       Ryu up -> Orange Hulk (0x13)           bit 3    0x80190c18
       Zangief up -> Gold War Machine (0x14)  bit 1    0x80190c34
       Mega Man left -> Roll (0x08)           bit 16   0x80190c60 (lh 0x8007b72e)
       War Machine down -> Lilith (0x16)      bit 15   0x80190c88
       Gambit down -> Shadow Lady (0x15)      bit 11   0x80190cb4
   these six loads -> `li v0,-1`.  Wolverine down -> Onslaught (0x80190ce0, "any bit set") is NOT unlocked
   (the tag loader takes Onslaught only as the arcade boss), nor the "same character twice" rule at 0x80190e84.
   HOLD SELECT + confirm on the base character (main and partner pick): the confirm calls 0x80190fd4(obj,
   a1 = 1 SELECT held / 2 START held / 0, a2) (stock: Ryu / Zangief style variants, Mega Man variant); hook
   `secret` maps the cursor first:  War Machine -> Gold War Machine, Venom -> Red Venom, Hulk -> Orange Hulk,
   Chun-Li -> Shadow Lady, Morrigan -> Lilith.  Roll has no base character: its cell (left of Mega Man) is open.

3. VS screen with four portraits: the portrait object init (0x80197034 state) has the Cross Over layout (4
   portraits, tables 0x801b872c / 0x801b8838 / 0x801b8894) and the versus one (2 portraits; index 1 / 3 hidden),
   chosen by four reads of the versus flag 0x8007b75d (0x801970a4, 0x801972f8, 0x80197344, 0x801973bc).  They
   now read 0 (Cross Over layout); Onslaught (id 0x22) keeps its own single-portrait path (0x80197184, 0x801972ec,
   0x801973d4: stock checks).  The VS sprite file is SP_SEL4.DSP (the Cross Over one, 0x8018e174 / 0x8018e354; it
   also holds the Onslaught portrait) instead of SP_SEL3.DSP.  The first read is `jal vsinit` instead: in ARCADE
   (mode 0) with one human, the CPU team's partner is replaced when it equals one of the other three TEAM words
   (stock: the CPU partner word is the CPU main in the first fight, and the arcade's own pick may equal a player
   character): a base character 1..16 not in TEAM, start = main-loop counter.  It runs before the portraits read
   TEAM; the tag loader keeps a partner that differs from the main (tagload.c: random pick only when equal), so
   the VS screen, the loaded team and the fight agree.

4. TRAINING: after the main pick the training dummy (mode 3, both sides "human", 0x8018fcf4) got partner = main
   (a cut-down clone, stock assist rules) and its selection ended.  `bne` -> `b`: the dummy takes the normal path
   (partner pick like the player).  tagload.c accepts mode 3 and tagmode.py gives TRAINING the tag rules, so both
   teams load in full through the tag loader; the training life refill and dummy settings are untouched.
"""
import os, struct, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mipsasm import Asm

FILE, BASE = "SEL01.ARC", 0x8018dcec
ORG, LIMIT = 0x~~~~~~~~, 0x~~~~~~~~                     # dead state 4 of the select state machine
FD4 = 0x80190fd4                                        # confirm: variant byte
TEAM = 0x8007b8aa
J = lambda t: 0x08000000 | (t >> 2 & 0x3ffffff)
JAL = lambda t: 0x0C000000 | (t >> 2 & 0x3ffffff)
LI_M1 = 0x2402FFFF                                       # addiu v0,zero,-1
LI_0 = 0x24020000                                        # addiu v0,zero,0
SECRETS = [(0x01, 0x14), (0x06, 0x12), (0x03, 0x13), (0x0B, 0x15), (0x0F, 0x16)]   # base -> secret (char ids)


def lo(a):
    return a & 0xFFFF                                    # 0x8007xxxx with lo >= 0x8000 -> lui 0x8008


def build():
    a = Asm(ORG)
    # ---- secret(obj a0, a1 = 1 SELECT held, a2): base -> secret, then the stock 0x80190fd4
    a.label("secret")
    a.ori("$t0", "$zero", 1)
    a.bne("$a1", "$t0", "sec_go")
    a.lh("$t1", 0xa, "$a0")
    a.lui("$t2", 0); a.label("tab_hi")
    a.addiu("$t2", "$t2", 0); a.label("tab_lo")
    a.label("sec_l")
    a.lbu("$t3", 0, "$t2")
    a.lbu("$t4", 1, "$t2")
    a.beq("$t3", "$zero", "sec_go")
    a.addiu("$t2", "$t2", 2)
    a.bne("$t3", "$t1", "sec_l")
    a.nop()
    a.sh("$t4", 0xa, "$a0")
    a.label("sec_go")
    a.j(FD4)
    a.nop()
    # ---- vsinit: replaces `lb v0,-0x48a3(v0)` at 0x801970a4 (each portrait object's init).  v0 / v1 need not be
    # kept: the caller's `bnez v0` is patched out and 0x801970b0 sets v1 itself.  ARCADE (mode 0) with one human:
    # the CPU partner is kept if it differs from the other three TEAM words, else replaced (first portrait wins;
    # later calls find it unique).
    a.label("vsinit")
    a.lui("$t1", 0x8008)
    a.lb("$t2", lo(0x8007b740), "$t1")                   # mode: 0 ARCADE
    a.lbu("$t3", lo(0x8007bdc9), "$t1")                  # human sides: 1 P1, 2 P2
    a.addiu("$t5", "$t1", lo(TEAM))                      # CPU = P1 side (TEAM[0..1]) when only P2 plays
    a.bne("$t2", "$zero", "vs_ret")
    a.addiu("$t4", "$t3", -2)
    a.beq("$t4", "$zero", "vs_go")
    a.addiu("$t4", "$t3", -1)
    a.bne("$t4", "$zero", "vs_ret")                      # both humans (challenger) or demo: untouched
    a.addiu("$t5", "$t5", 4)                             # CPU = P2 side
    a.label("vs_go")
    a.lh("$t6", 0, "$t5")                                # CPU main (id*2)
    a.lh("$t2", 2, "$t5")                                # first candidate: the current CPU partner
    a.ori("$t8", "$zero", 0x22)
    a.addiu("$t7", "$t1", lo(TEAM + 8))
    a.beq("$t6", "$t8", "vs_ret")                        # Onslaught: boss rules, no partner
    a.lw("$t0", lo(0x8007b74c), "$t1")                   # main-loop counter as the random start
    a.b("vs_chk")
    a.sh("$zero", 2, "$t5")                              # own slot out of the comparison
    a.label("vs_next")
    a.addiu("$t0", "$t0", 1)
    a.andi("$t2", "$t0", 15)
    a.addiu("$t2", "$t2", 1)
    a.sll("$t2", "$t2", 1)                               # candidate id*2, base characters 1..16
    a.label("vs_chk")
    a.addiu("$t4", "$t1", lo(TEAM))
    a.label("vs_cmp")
    a.lh("$t3", 0, "$t4")
    a.addiu("$t4", "$t4", 2)
    a.beq("$t3", "$t2", "vs_next")
    a.nop()
    a.bne("$t4", "$t7", "vs_cmp")
    a.nop()
    a.sh("$t2", 2, "$t5")                                # CPU partner
    a.label("vs_ret")
    a.jr("$ra")
    a.nop()
    a.label("tab")
    a.blob(bytes(x for b, s in SECRETS for x in (b * 2, s * 2)) + bytes(2))
    code = bytearray(a.assemble()); L = a.labels()
    t = L["tab"]
    i = L["tab_hi"] - 4 - ORG
    code[i:i + 4] = struct.pack("<I", 0x3C0A0000 | ((t + 0x8000) >> 16 & 0xFFFF))       # lui t2
    i = L["tab_lo"] - 4 - ORG
    code[i:i + 4] = struct.pack("<I", 0x254A0000 | (t & 0xFFFF))                         # addiu t2,t2
    assert ORG + len(code) <= LIMIT, f"select code too big: {len(code)} B, room {LIMIT - ORG}"
    return bytes(code), L


# 5. ARCADE stage screen = the real teams (stagecheck.py; 2026-11-18): the SEL01 stage-screen setup calls 0x80047418
#    (special-partner / assist bits 0x8007b744) then 0x800472b4 (CPU team from the arcade table 0x800715a4: main, and
#    as partner the table's partner when the side's assist bit is clear, else the main again = mirror).  With the bit
#    set the stage screen showed the CPU's random ASSIST figure (record 0x8007cf68, kind-6 objects), never its partner.
#    0x8018ed9c `jal 0x800472b4` -> `jal CPUTEAM` (EXE dead span 0x80010af8, fnscan.py): assist bits cleared, then
#    0x800472b4 (table partner -> TEAM, so the side's partner FIGURE (kind 0, pointer table 0x801b8480 -> TEAM) shows
#    it and the assist figure kills itself), then a tail jump into vsinit, which replaces that partner when it equals
#    another TEAM word (now, before the figures read TEAM; the VS-screen call and the loader keep it).  Onslaught: the
#    table's partner for 0x22 is 0x22 (mirror) as before.  Assists are off in tag battles anyway (assist.py).
CPUTEAM, CPUTEAM_END = 0x80010af8, 0x80010b2c


def exe_patches():
    """[(EXE RAM address, bytes)]: the CPUTEAM stub (needs vsinit's address in the SEL01 code block)"""
    code, L = build()
    a = Asm(CPUTEAM)
    a.addiu("$sp", "$sp", -24)
    a.sw("$ra", 16, "$sp")
    a.lui("$t0", 0x8008)
    a.jal(0x800472b4)
    a.sb("$zero", lo(0x8007b744), "$t0")                 # delay slot: ASSIST_BITS = 0
    a.lw("$ra", 16, "$sp")
    a.j(L["vsinit"])
    a.addiu("$sp", "$sp", 24)
    c = a.assemble(); assert CPUTEAM + len(c) <= CPUTEAM_END
    return [(CPUTEAM, c)]


# RAM address: (stock word, new word); None = filled from the labels
SITES = {
    # 1. no TYPE SELECT question
    0x8018ffb0: (0x0C06670D, 0x00000000),
    0x8018ffb8: (0x08064278, J(0x8018ffc0)),
    # 2. hidden cells open
    0x80190c00: (0x8C42B72C, LI_M1),
    0x80190c18: (0x8C42B72C, LI_M1),
    0x80190c34: (0x8C42B72C, LI_M1),
    0x80190c60: (0x8442B72E, LI_M1),
    0x80190c88: (0x8C42B72C, LI_M1),
    0x80190cb4: (0x8C42B72C, LI_M1),
    #    SELECT + confirm (main pick 0x8018fb60, partner pick 0x80190214): jal 0x80190fd4 -> jal secret
    0x8018fb60: (0x0C0643F5, None),
    0x80190214: (0x0C0643F5, None),
    # 3. VS screen: four portraits
    0x801970a4: (0x8042B75D, None),                     # -> jal vsinit (delay slot: nop at 0x801970a8)
    0x801970ac: (0x14400037, 0x00000000),               # bnez v0 (versus layout) -> nop
    0x8018e174: (0x14400005, 0x10000005),               # SP_SEL4.DSP (Cross Over VS sprites) instead of SP_SEL3
    0x8018e354: (0x10400004, 0x10000004),
    0x8018fcf4: (0x1462002A, 0x1000002A),               # 4. TRAINING: no dummy clone (bne -> b)
    0x801972f8: (0x8042B75D, LI_0),
    0x80197344: (0x8042B75D, LI_0),
    0x801973bc: (0x8042B75D, LI_0),
    0x8018ed9c: (0x0C011CAD, JAL(0x80010af8)),          # 5. stage screen: CPU team -> CPUTEAM (EXE stub)
}


def ram_patches():
    """[(ram addr, bytes)] incl. the code block"""
    code, L = build()
    new = dict((a, n) for a, (o, n) in SITES.items())
    new[0x8018fb60] = new[0x80190214] = JAL(L["secret"])
    new[0x801970a4] = JAL(L["vsinit"])

    return [(ORG, code)] + [(a, struct.pack("<I", w)) for a, w in sorted(new.items())]


def overlay_patches():
    """[(file, offset, bytes)] for DAT/SEL01.ARC"""
    return [(FILE, a - BASE, d) for a, d in ram_patches()]


def check_file(data):
    for a, (o, n) in SITES.items():
        assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"{FILE} +{a - BASE:x}: not stock"
    assert struct.unpack_from("<I", data, ORG - BASE)[0] == 0x82420001         # state 4 entry `lb v0,1(s2)`


def apply_ram(emu):
    """while SEL01.ARC is in RAM (select screen)"""
    for a, (o, n) in SITES.items():
        w = emu.u32(a)
        assert w == o or w != o and emu.u32(0x8018ffb0) == 0, f"SEL01 not in RAM / unexpected {a:08x}: {w:08x}"
    for a, d in ram_patches():
        emu.poke(a, d)


if __name__ == "__main__":
    code, L = build()
    print(len(code), "of", LIMIT - ORG, "bytes;", {k: hex(v) for k, v in L.items() if not k.startswith(("tab_", "sec_l", "vs_"))})
    d = open(os.path.join(ROOT, "games", "mvc", "work", "gpw", "files", FILE), "rb").read()
    check_file(d)
    print("stock words ok")
