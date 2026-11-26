"""Playable Onslaught (form 1) - mktag.py `--onsl` (prototype, 2026-11-21).  Patches in DAT/SEL01.ARC (selscreen.BASE)
+ tagload.c ONSL.  Without the flag nothing changes.

Stock facts (Beetle, work/onsl probes p1-p3; SEL01 code):
* The PS1 port already has a playable Onslaught: hidden cell Wolverine DOWN (cursor table 0x801b011c: cell 8 down ->
  0x22), open when ANY unlock bit of the memory-card word 0x8007b72c is set (0x80190ce0 `lw v0,-0x48d4(v0)`), blocked
  in CROSS OVER and when both sides are human and the other one already picked Onslaught (0x80190d18..).  Picking him
  (state 2, 0x8018fda0: cursor 0x22) skips the partner (+4 += 8; TEAM partner word = 0x22 = main) and the select sets
  stage 9 (his arena).  Stock VERSUS on the stock disc: he walks / attacks / specials under P1 input, 1v1 rules.
* rc4.10 (cell locked unless the card has a bit): picking him there -> tag loader declined 0xfc (slot 0) -> stock
  loading under the tag build -> NOW LOADING hang (Beetle, p2.py).  Latent for players whose card unlocked anything.

Patch (only with the flag):
  O1 0x80190ce0 `lw v0,-0x48d4(v0)` -> `li v0,-1`: the Onslaught cell is always open (like selscreen's six secrets).
  tagload.c ONSL: Onslaught accepted as P1 or P2 main (solo: his partner word shares his slot, like the arcade boss);
  the stage-9 RAM top (TOP_ONSL) is chosen by the stage byte (9 only with Onslaught) instead of "P2 main == 0x11".
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from selscreen import FILE, BASE

FIXED = {    # RAM address: (stock word, new word)
    0x80190ce0: (0x8C42B72C, 0x2402FFFF),     # O1 Onslaught cell: `lw v0,-0x48d4(v0)` (unlock word) -> `li v0,-1`
}


def overlay_patches(argv=()):
    """[(file, offset, bytes)] for DAT/SEL01.ARC (after selscreen / assistsel / asopt)"""
    out = [(FILE, a - BASE, struct.pack("<I", n)) for a, (o, n) in sorted(FIXED.items())]
    if "--onslfix" in sys.argv:                      # F3 select hover: his figure + name plate on the hidden cell (below)
        out += [(FILE, a - BASE, struct.pack("<I", n)) for a, (o, n) in sorted(FIX_SEL.items())]
    if "--assistsel" in argv:                        # R: no special-partner roulette / picker for an Onslaught side
        code, site = oclr(argv)
        out += [(FILE, OCLR_AT - BASE, code), (FILE, ROU_SITE - BASE, struct.pack("<I", site))]
    return out


# F3 (--onslfix) select hover: the big figure object (SEL01 0x80193740 state machine) stores the id and stops when the
# cursor is the hidden cell 0x22 (0x8019394c), and the name plate that follows it waits while the figure's id is 0x22
# (0x801978a4) -> nothing on hover, his figure / name only after the pick.  Both branches made unconditional: the stock
# figure + name animations for id 0x22 (the ones the pick shows) run on hover like every other character.
FIX_SEL = {0x8019394c: (0x14430004, 0x10000004),     # bne v0,v1,+4 (cursor != 0x22 -> setup) -> b (always set up)
           0x801978a4: (0x14620006, 0x10000006)}     # bne v1,v0,+6 (id != 0x22 -> show)    -> b (always show)


def check_file(data):
    if "--onslfix" in sys.argv:
        for a, (o, n) in FIX_SEL.items():
            assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"{FILE} +{a - BASE:x}: not stock (onslfix)"
    for a, (o, n) in FIXED.items():
        assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"{FILE} +{a - BASE:x}: not stock (onsl)"


# ---- form 1 only for a HUMAN Onslaught (static RE helper 2026-11-21; obj+3 = 1 human / 0 CPU, so the arcade boss is stock)
# PL11 code (tag-loaded item only: mktag a0_item patches the code part after the relocation check; offsets = A0 file
# offsets, same in PL11_10 / PL11_20; RAM = file + 0x80161cdc in the P2 slot)
PL11 = {
    0x41F0: (0x00000000, 0x82080003),   # A1 0x80165ecc hit handler: nop -> lb t0,3(s0) (human flag)
    0x4204: (0x00000000, 0x15000016),   # A2 0x80165ee0 nop -> bnez t0,0x80165f3c: human life 0 = normal KO (no clamp to 1,
                                        #    no fight state 4 = no transformation into form 2)
    # D life bonus (balance): human Onslaught takes half damage = the defender multiplier obj+0x12c (x N/32, 0 = off, read
    #   by the common damage calc 0x8003a28c at 0x8003a494) set to 16 in his hit handler 0x80165e18 before the damage call
    #   0x80165e8c; CPU boss: 0 (stock).  His own defence row is already ~0.75x an average character, so human = ~0.37x:
    #   one bar ~ the arcade boss's two forms.  Throws (0x8003a608 branch) are not halved.
    0x4160: (0x00000000, 0x82080003),   # D1 0x80165e3c nop -> lb t0,3(s0)
    0x416C: (0x00000000, 0x00084100),   # D2 0x80165e48 nop -> sll t0,t0,4
    0x4190: (0x00000000, 0xA208012C),   # D3 0x80165e6c nop -> sb t0,0x12c(s0)
    0x103C: (0x00000000, 0x82280003),   # B1 0x80162d18 nop -> lb t0,3(s1)
    0x1050: (0x24020002, 0x25020002),   # B2 0x80162d2c li v0,2 -> addiu v0,t0,2: human never sees "state 2" (timer < 31 ->
                                        #    transform request) as 2 (compares with 3)
}
# EXE: match end 0x8004ba38 sets b828+0x39 = -1 for an Onslaught loser -> phase 10 waits for the stage-9 death sequence,
# which never starts on a time over (life > 0): endless phase 10.  Human losers skip the flag.
EXE = {
    0x8004bf54: (0x14400016, 0x1440001B),   # C bnez v0,0x8004bfb0 -> bnez v0,0x8004bfc4
}


# F2 (--onslfix) damage dealt: measured (work/onslfix onsko.py --dmgout / dmgctl.py, same 60 s scripted attack loop vs
# team 9,a, ARCADE BALANCE OFF or ON = the same) a human Onslaught dealt 228 per minute, normal characters 390-690 (median
# ~580).  The common damage calc 0x8003a28c multiplies by the ATTACKER's +0x12b (x N/32, 0 = off; never written by the game)
# -> for a human Onslaught +0x12b = 4 x his +0x12c (= 16, D above) = 64: his hits x2.  Three free slots of his hit handler,
# after D (no call in between): set the first time he is hit, kept for the match.  CPU boss: +0x12c = 0 -> 0 (stock).
FIX_PL11 = {
    0x41E0: (0x00000000, 0x9208012C),   # E1 0x80165ebc nop -> lbu t0,0x12c(s0)  (16 human / 0 CPU)
    0x4270: (0x00000000, 0x00084880),   # E2 0x80165f4c nop -> sll t1,t0,2       (load-delay slot of lhu v1: no v1 use)
    0x4284: (0x00000000, 0xA209012B),   # E3 0x80165f60 nop -> sb t1,0x12b(s0)   (load-delay slot of lb v0: no v0 use)
}


def pl11_patch(part):
    """part = mktag a0_item partA of char 0x11 (file offsets) -> patched bytes"""
    b = bytearray(part)
    for o, (old, new) in (list(PL11.items()) + (list(FIX_PL11.items()) if "--onslfix" in sys.argv else [])):
        assert struct.unpack_from("<I", b, o)[0] == old, f"PL11 +{o:x}: not stock (onsl)"
        struct.pack_into("<I", b, o, new)
    return bytes(b)


def exe_patches():
    exe = open(os.path.join(HERE, "..", "..", "disc", "SLUS_010.59"), "rb").read()
    for a, (o, n) in EXE.items():
        assert struct.unpack_from("<I", exe, a - 0x80010000 + 0x800)[0] == o, f"onsl: EXE {a:08x} not stock"
    return [(a, struct.pack("<I", n)) for a, (o, n) in EXE.items()]


# ---- round 2 (2026-11-22, rc4.11 base) -------------------------------------------------------------------------------
# T time over vs a solo Onslaught: the tag-rules branch of 0x8004b544 sums main + partner life per side
# (0x8004b674..0x8004b698; his partner object is the eliminated dummy, life 0) -> 144 vs up to 288.  Stub (verified words,
# static RE): adds a HUMAN Onslaught main's life once more (P1 and P2), then `j 0x8004b6d8`.  It is appended to his tag
# code item so that it ENDS at the giant-form block (mktag a0_item); tagload.c ONSL writes `j stub` into 0x8004b694 when
# he loads (h->xoff) and puts the stock `j 0x8004b6d8` back at the start of every tl_main.  Resident exactly while his
# code is: no EXE / kernel span needed.  CPU boss (+3 = 0): stub adds nothing.
TO_SITE, TO_STOCK = 0x8004b694, 0x08012DB6
TO_WORDS = [0x3c098008, 0x852abede, 0x240b0022, 0x154b0006, 0x812abe93, 0x00000000, 0x11400003, 0x852ac124,
            0x00000000, 0x00ca3021, 0x852ac2ee, 0x00000000, 0x154b0006, 0x812ac2a3, 0x00000000, 0x11400003,
            0x852ac534, 0x00000000, 0x008a2021, 0x08012db6, 0x00000000, 0x00000000]      # 22 words = 88 B (8-aligned)


def to_stub():
    return b"".join(struct.pack("<I", w) for w in TO_WORDS)


# R roulette skip (needs --assistsel; with --asopt it chains to asopt's `clr`): state 10 of the select machine calls
# asbit (bit set -> roulette / picker) then, at 0x801902cc, asopt's `clr` (delay slot `srav v0,v0,v1`, v1 = side).
# oclr: the side's TEAM main word 0x8007b8aa + 4 * side == 0x22 (Onslaught) -> clear the side's bit, v0 = 0 -> stock
# "no special partner" path; else tail-jump to clr (or return).  Code at the END of SEL01's last-sector slack
# (0x801ed98c-0x801edcec, zero on the disc, read with the file; arcbal / sa06 hooks start at its FRONT).
ROU_SITE = 0x801902cc
SLACK_END = 0x801edcec
OCLR_LEN = 64
OCLR_AT = SLACK_END - OCLR_LEN                       # 0x801edcac


def oclr(argv=()):
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "tools"))
    from mipsasm import Asm
    clr = None
    if "--asopt" in argv:
        import asopt
        clr = asopt.build(asopt.rou(argv))[1]["clr"]
    a = Asm(OCLR_AT)
    a.label("oclr")
    a.sll("$t0", "$v1", 2)
    a.lui("$t1", 0x8008)
    a.addu("$t0", "$t0", "$t1")
    a.lh("$t0", -0x4756, "$t0")                     # 0x8007b8aa + 4 * side: the side's main (id * 2)
    a.ori("$t2", "$zero", 0x22)
    a.bne("$t0", "$t2", "other")
    a.addiu("$t2", "$v1", 1)                         # side 0 -> bit 1, side 1 -> bit 2
    a.lbu("$t0", -0x48bc, "$t1")                    # 0x8007b744 assist bits
    a.nop()                                          # load delay
    a.and_("$t3", "$t0", "$t2")
    a.subu("$t0", "$t0", "$t3")                      # bits & ~side bit
    a.sb("$t0", -0x48bc, "$t1")
    a.jr("$ra")
    a.ori("$v0", "$zero", 0)                         # no special partner for him
    a.label("other")
    if clr is not None:
        a.j(clr)
        a.nop()
    else:
        a.jr("$ra")
        a.nop()
    code = a.assemble()
    assert len(code) <= OCLR_LEN, len(code)
    code = code + bytes(OCLR_LEN - len(code))
    return code, 0x0C000000 | (OCLR_AT >> 2 & 0x3ffffff)


def check_slack(data, argv=()):
    """SEL01 bytes before our patch: the slack end must be zero, the site asopt's `jal clr` (or the stock nop)"""
    o = OCLR_AT - BASE
    assert data[o:o + OCLR_LEN] == bytes(OCLR_LEN), "onsl: SEL01 slack end not free"
    w = struct.unpack_from("<I", data, ROU_SITE - BASE)[0]
    if "--asopt" in argv:
        import asopt
        assert w == 0x0C000000 | (asopt.build(asopt.rou(argv))[1]["clr"] >> 2 & 0x3ffffff), "onsl: %08x not asopt's jal clr" % ROU_SITE
    else:
        assert w == 0, "onsl: %08x not the stock nop" % ROU_SITE
    if "--arcbal" in argv:                           # arcbal / sa06 hooks grow from the slack FRONT
        import arcbal
        assert arcbal.HOOK_AT + len(arcbal.hook("--arcspeed" in argv)[0]) <= OCLR_AT, "onsl: arcbal hook reaches the oclr stub"


# ---- --onslfix (2026-11-24, user HW reports on playable Onslaught) ----------------------------------------------------
# F1 stage: 0x80047074 (stage choice, called by every select / stage screen) sets stage 9 when EITHER main word is 0x22
# (Onslaught) before its ARCADE rotation -> an ARCADE run as Onslaught was all stage 9.  The test block 0x80047078..0x800470a0
# is rewritten so that ARCADE (mode 0x8007b740 == 0) skips it (rotation as for every character); the final boss fight still
# gets stage 9 from the fight counter (SEL01 0x8018ed8c); VERSUS / other modes keep his arena.  11 words, same frame.
FIX_STAGE_AT = 0x80047078
FIX_STAGE_SHA = None                                  # (stock words checked by value below)
FIX_STAGE_OLD = [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~,
                 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~]
FIX_STAGE_NEW = [0x3c028008,                          # lui  v0,0x8008
                 0x8043b740,                          # lb   v1,-0x48c0(v0)      mode
                 0xafbf0014,                          # sw   ra,0x14(sp)
                 0x1060000b,                          # beqz v1,0x800470b4        ARCADE: rotation
                 0xafb00010,                          # sw   s0,0x10(sp)
                 0x8444bede,                          # lh   a0,-0x4122(v0)      P1 main
                 0x8445c2ee,                          # lh   a1,-0x3d12(v0)      P2 main
                 0x24030022,                          # li   v1,0x22
                 0x10830002,                          # beq  a0,v1,0x800470a4     -> stage 9
                 0x00000000,                          # nop
                 0x14a30004]                          # bne  a1,v1,0x800470b4  (delay: 0x800470a4 lui v1)


# F4 music: a KO fades the BGM (sound 0x16c, EXE 0x80036d2c) and schedules 0x80086754 = switch to the incoming
# character's theme; that routine returns at once on stage 9 (the boss stage keeps its music) -> any stage-9 match that is
# not the stock boss fight (whose music the fight-counter path 0x80031e20 restarts) stayed silent until it ended, e.g.
# VERSUS with a playable Onslaught.  The stage-9 return is dropped: stage 9 switches themes like every stage.
FIX_MUSIC = {0x80086780: (0x10620015, 0x00000000)}   # beq v1,v0,0x800867d8 (stage 9 -> return) -> nop

# F1 follow-up (arcade freeze at a KO on a normal stage, mvc_1_0e arc 0 fight 7): three EXE sites (round start / KO /
# round end) call stage-9 module code (0x800a11ec(2), 0x800a2338(1)) whenever 0x8003d410(0x22) finds Onslaught in a slot.
# Stock: Onslaught always fights on stage 9.  With F1 he plays normal stages, whose module occupies 0x800a.... -> the call
# jumps into that stage's data.  The sites now call a 6-word helper "v0 = (stage == 9)" (stage 9 battles always have
# Onslaught) in the free tail of CODESPACE span H (0x80049d84-0x80049dbc: --excard uses 32 B, fnscan dead code).
FIX_STG9_AT = 0x80049da4
FIX_STG9 = [0x3c028008,                               # lui   v0,0x8008
            0x9042bdd9,                               # lbu   v0,-0x4227(v0)    stage
            0x00000000,                               # nop
            0x38420009,                               # xori  v0,v0,9
            0x03e00008,                               # jr    ra
            0x2c420001]                               # sltiu v0,v0,1
FIX_STG9_SITES = (0x80023a00, 0x80023c2c, 0x80023e0c)  # jal 0x8003d410 (a0 = 0x22 in the delay slot stays, unused)


def fix_exe_patches(exe_read=None):
    """--onslfix EXE words; exe_read(addr, n) of the image being built (else the extracted stock EXE)"""
    if exe_read is None:
        exe = open(os.path.join(HERE, "..", "..", "disc", "SLUS_010.59"), "rb").read()
        exe_read = lambda a, n: exe[a - 0x80010000 + 0x800:a - 0x80010000 + 0x800 + n]
    old = list(struct.unpack("<11I", exe_read(FIX_STAGE_AT, 44)))
    assert old == FIX_STAGE_OLD, "onslfix: stage choice 0x80047078 not stock"
    new_ = list(FIX_STAGE_NEW)
    if "--onslstg" in sys.argv:          # (2026-11-25 TEST discs only, user: stress Onslaught hypers on normal stages) every mode
        new_[3] = 0x1000000b             # skips the stage-9 force (b 0x800470b4 = the rotation path), not just ARCADE
    out = [(FIX_STAGE_AT, b"".join(struct.pack("<I", w) for w in new_))]
    for a, (o, n) in sorted(FIX_MUSIC.items()):
        assert struct.unpack("<I", exe_read(a, 4))[0] == o, "onslfix: music gate %08x not stock" % a
        out.append((a, struct.pack("<I", n)))
    jal_ = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)
    for a in FIX_STG9_SITES:
        assert struct.unpack("<I", exe_read(a, 4))[0] == jal_(0x8003d410), "onslfix: stage-9 call site %08x not stock" % a
        out.append((a, struct.pack("<I", jal_(FIX_STG9_AT))))
    stock = open(os.path.join(HERE, "..", "..", "disc", "SLUS_010.59"), "rb").read()
    o_ = FIX_STG9_AT - 0x80010000 + 0x800
    assert exe_read(FIX_STG9_AT, 24) == stock[o_:o_ + 24], "onslfix: span H tail %08x not stock (used by another flag)" % FIX_STG9_AT
    out.append((FIX_STG9_AT, b"".join(struct.pack("<I", w) for w in FIX_STG9)))
    return out
