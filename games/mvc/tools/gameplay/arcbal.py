"""ARCADE BALANCE for MvC (mktag.py --arcbal, needs --exopt; arcade-balance lead, 2026-11-22).

Study: games/mvc/docs/ARCADE_BALANCE.md + games/mvc/work/arcbal/MVC_REPORT.md (FBNeo mvscu vs Beetle).  Tag battles
already run the arcade rule side of the versus flag 0x8007b75d; what is left are two port bugs and the Onslaught
battle (stock loader -> flag 1).  All values below are our own numbers derived from that analysis (no ROM data).

EX OPTIONS row "ARCADE BALANCE"  OFF / ON   byte 0x80011761 (EX block +5; 0 = OFF = cold-boot default, 1 = ON)
                                            (user 2026-11-22: default OFF = stock PS1 values at power-on; was ON)
EX OPTIONS row "ARCADE SPEED"    OFF / ON   byte 0x80011762 (EX block +6; 0 = OFF = default)  only with --arcspeed
                                            (prepared, not in the default line: needs a MiSTer speed check)

Group BAL (ON = arcade, OFF = the build's stock words):
  V1  0x8003a8c0..0x8003a8f8 (15 words): meter on BLOCK for the attacker.  Stock reads the hit flags byte instead of
      the value byte (+0x10) and has the bit 6 / bit 4 cases swapped (misplaced delay slot); arcade 0x1ccb4 order:
      value != 0 -> value, flags bit 6 -> 8, bit 4 -> 10, else the attacker's move value (+0x299).  t0 is dead after.
  V2  0x8003ac28..0x8003ac58 (13 words): red life -= max(1, dmg*24 >> 5) (arcade 0x1ce60); stock has no minimum, so
      1-point hits / chip stay fully recoverable.  (3*dmg) >> 2 == (24*dmg) >> 5; the return value is unused.
  V3  versus-flag readers G1-G6 (+ the meter tick twin) -> `li rt, 0`: their flag-0 (arcade / Cross Over) rule in every
      battle.  Tag battles already read 0 (tagmode.py), so this only changes battles the stock loader runs
      (Onslaught): meter not doubled, no hyper chaining, bench-only regen, assist stock counted, team move 0x1414 cost.
Group SPD (ARCADE SPEED ON): TURBO SPEED period 10 -> 6 (0x8004b228 `li a0,10` -> `li a0,6`): the default 11/10
  logic frames per video frame becomes the arcade factory 7/6 (TURBO SPEED option 1 = the same).

Mechanism (0 per-frame cost): the EXE on the disc keeps the stock words of group BAL (cold boot = OFF).  A hook right
after SEL01.ARC's end in RAM (0x801ed98c.., 492 B) runs at every character pick on the SELECT screen (SEL01
0x80190268 `jal 0x80085ab0`), writes each group's word set from the option byte, FlushCache (BIOS A0 0x44), then
tail-jumps to 0x80085ab0.  The option can only change in the menu, and every way from the menu to a battle passes the
select (ARCADE / VERSUS / TRAINING, continue, challenger); the words stay in the EXE through the whole ARCADE run.
NOT a VS-screen site: between ARCADE fights SEL01 is not reloaded (its body survives the tag battle) but the RAM after
its end holds battle data (P2 partner / assist) -> a VS-read hook there jumped into garbage (mvc_ab01 / mvc_ab02
regress: freeze at fight 2).  The select always runs right after a SEL01 load that reads whole sectors, so the hook
lives in place in SEL01's last-sector slack (mvc_ab04; ab02 / ab03 carried a SEL01 copy at the end of the image with
the file table repointed - dropped: a far seek per select load on real drives).  Excludes --sa06 (same tail).
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "speed", "frame"), os.path.join(ROOT, "tools")]

BAL, SPD = 0x80011761, 0x80011762                 # optrows.BYTES["ARCADE BALANCE"], ["ARCADE SPEED"]
SITE, SITE_STOCK = 0x80190268, 0x0C0216AC          # SEL01 select: jal 0x80085ab0 after a character pick (delay slot nop)
READ = 0x80085ab0                                   # (the hook tail-jumps to the stock callee, a0 / a1 kept)
HOOK_AT, HOOK_END = 0x801ed98c, 0x801edcec         # SEL01 last-sector slack (= sa06.HOOK_AT / HOOK_END)

V1_AT = 0x8003a8c0
V1_STOCK = [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~,
            0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~]
V1_ARC = [0x90680010,   # lbu   t0, 0x10(v1)      value byte
          0x8c8400d8,   # lw    a0, 0xd8(a0)      attacker
          0x1500000a,   # bnez  t0, e             value != 0 -> value
          0x00051182,   # srl   v0, a1, 6
          0x30420001,   # andi  v0, v0, 1
          0x14400007,   # bnez  v0, e             bit 6 -> 8
          0x24080008,   # li    t0, 8
          0x00051102,   # srl   v0, a1, 4
          0x30420001,   # andi  v0, v0, 1
          0x14400003,   # bnez  v0, e             bit 4 -> 10
          0x2408000a,   # li    t0, 10
          0x80880299,   # lb    t0, 0x299(a0)     else the attacker's move value
          0x00000000,   # nop                     load delay
          0x01002825,   # e: move a1, t0
          0x2402ff7f]   # li    v0, -0x81         (0x8003a8fc `and a1,a1,v0` and the rest stay stock)
V2_AT = 0x8003ac28
V2_STOCK = [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~,
            0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~]
V2_ARC = [0x00051040,   # sll   v0, a1, 1
          0x00451021,   # addu  v0, v0, a1        3 * dmg
          0x9483029e,   # lhu   v1, 0x29e(a0)     red life
          0x00021083,   # sra   v0, v0, 2         (3 * dmg) >> 2 == (24 * dmg) >> 5
          0x14400002,   # bnez  v0, a
          0x00621823,   # subu  v1, v1, v0
          0x2463ffff,   # addiu v1, v1, -1        loss 0 -> the arcade's minimum 1
          0x00031400,   # a: sll v0, v1, 16
          0x04410002,   # bgez  v0, b
          0xa483029e,   # sh    v1, 0x29e(a0)
          0xa480029e,   # sh    zero, 0x29e(a0)   negative -> 0
          0x03e00008,   # b: jr ra
          0x00000000]
# versus-flag readers `lb rt, -0x48a3(base)` (MVC_REPORT.md / work/arcbal/flag/FLAG_READERS.md) -> `li rt, 0`
GATES = {0x8003a970: 0x8042b75d,   # G1 meter x2 (meter add 0x8003a96c)
         0x8004fa80: 0x8042b75d,   # G1 twin: per-frame meter tick passes 2 with flag 0 (undoubled) = +2 as before
         0x80056c64: 0x8063b75d,   # G2 hyper chaining (0x80056bf8)
         0x80056ea8: 0x8063b75d,   # G2 hyper chaining (0x80056e04)
         0x8003ad3c: 0x8042b75d,   # G3 red-life regen: benched only
         0x800366e4: 0x8042b75d,   # G4 regen delay reset per hit (hit reaction)
         0x8005302c: 0x8042b75d,   # G4 twin
         0x80052c00: 0x8042b75d,   # G5 assist stock counted
         0x800302ac: 0x8043b75d}   # G6 team move 0x1414 costs 1 level
SPD_SITE, SPD_STOCK, SPD_ARC = 0x8004b228, 0x2404000a, 0x24040006   # TURBO period 10 -> 6


def gate_word(w):
    return 0x24000000 | (w & 0x001F0000)            # addiu rt, zero, 0


def groups(speed=False):
    """[(byte, value_for_word_A, [(addr, word_A, word_B)])]: byte == value_for_word_A -> word_A else word_B"""
    bal = [(V1_AT + 4 * i, a, s) for i, (a, s) in enumerate(zip(V1_ARC, V1_STOCK)) if a != s]
    bal += [(V2_AT + 4 * i, a, s) for i, (a, s) in enumerate(zip(V2_ARC, V2_STOCK)) if a != s]
    bal += [(a, gate_word(s), s) for a, s in sorted(GATES.items())]
    g = [(BAL, 1, bal)]                                  # BAL byte 1 = ON -> arcade words (0 = OFF = default)
    if speed: g.append((SPD, 1, [(SPD_SITE, SPD_ARC, SPD_STOCK)]))   # SPD byte 1 = ON -> arcade period
    return g


def stock_words(speed=False):
    """[(addr, word)] the build must have before --arcbal (asserted by mktag)"""
    return [(a, s) for byte, v, ents in groups(speed) for a, _, s in ents]


def exe_patches():
    """none: the EXE keeps the stock words, cold boot = OFF (user 2026-11-22); the select hook writes the set the row
    asks for before every VS-path battle"""
    return []


SRC = r"""
        .set noreorder
        .set noat
abhook: addiu $sp, $sp, -32
        sw    $ra, 24($sp)
        sw    $a0, 16($sp)
        sw    $a1, 20($sp)
        lui   $t5, %hi(GTAB)
        addiu $t5, $t5, %lo(GTAB)
1:      lw    $t6, 0($t5)                 /* group: option byte address (0 = end) */
        lw    $t7, 4($t5)                 /* byte value that selects word A */
        lw    $t2, 8($t5)                 /* entries */
        beqz  $t6, 4f
        addiu $t1, $t5, 12
        lbu   $t0, 0($t6)
        nop
        xor   $t0, $t0, $t7
        sltu  $t0, $zero, $t0             /* 0 -> word A, 1 -> word B */
        sll   $t0, $t0, 2
2:      lw    $t3, 0($t1)                 /* address */
        addu  $t4, $t1, $t0
        lw    $t4, 4($t4)                 /* word A / word B */
        addiu $t2, $t2, -1
        sw    $t4, 0($t3)
        bnez  $t2, 2b
        addiu $t1, $t1, 12
        j     1b
        move  $t5, $t1
4:      li    $t2, 0xa0                   /* FlushCache: the words are code */
        jalr  $t2
        li    $t1, 0x44
        lw    $a0, 16($sp)
        lw    $a1, 20($sp)
        lw    $ra, 24($sp)
        j     READ
        addiu $sp, $sp, 32
        .align 2
GTAB:
GROUPS
        .word 0, 0, 0
"""


def hook(speed=False):
    """-> (code bytes at HOOK_AT, (SITE, word))"""
    from gas import gas
    tab = ""
    for byte, v, ents in groups(speed):
        tab += "        .word 0x%08x, %d, %d\n" % (byte, v, len(ents))
        tab += "".join("        .word 0x%08x, 0x%08x, 0x%08x\n" % e for e in ents)
    code, sym = gas(SRC.replace("GROUPS", tab), HOOK_AT, {"READ": READ})
    assert HOOK_AT + len(code) <= HOOK_END, "arcbal hook too big: %d B" % len(code)
    import hazard
    bad = hazard.hazards(code, HOOK_AT)
    assert not bad, bad
    return code, (SITE, struct.pack("<I", 0x0C000000 | (HOOK_AT >> 2 & 0x3ffffff)))


if __name__ == "__main__":
    sp = "--arcspeed" in sys.argv
    code, (s, w) = hook(sp)
    print("hook %d B at %08x (room %d); site %08x -> %s" % (len(code), HOOK_AT, HOOK_END - HOOK_AT, s, w.hex()))
    for byte, v, ents in groups(sp):
        print("group %08x (A when %d): %d words" % (byte, v, len(ents)))
