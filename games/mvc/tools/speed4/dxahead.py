"""Decode-ahead for the MvC tag hack ("dxahead", idea 1 of the dx task, 2026-11-18).

MvC has no next-frame pre-decode (MSHvSF has one: games/mshvsf/tools/speed/ahead.py).  The player path decodes every
tile of a frame group when the object's animation frame changes (0x8008c45c: per part 0x8008c318 -> jal 0x8001bd48 at
0x8008c434 into the staging arena, LoadImage).  Here the next group is predicted from the object's animation script
(obj+0x34 = next record, obj+0x3c = current group (sec1 offset); record = u16 frame | dur << 9, u16 info | end << 15,
after an end record a u32 loop target; frame table = blob + h[2]: u16 sec1 offset per frame; blob = *(0x80079bc0 +
4 * char), tools/cuts/animtab.py), and its tiles are decoded in the idle time of the frame (before DrawSync, while the
next tile still fits before the vblank: hblank counter 1, reset by the main loop at every iteration start) into a
stash in hardware-safe kernel RAM.  When the engine then asks for a tile (src, n) the stash holds, the n bytes are
copied instead of decoded.  A misprediction costs nothing but idle time: the engine's own request always decides.

Exactness: the stash bytes are the output of the same decoder entry 0x8001bd48 for the same (src, n); the pixel data
of a tag battle never moves.  Only the first n bytes are copied (the stock decoder's 0..15 overrun bytes past n are
not: DSM1 / DSA1 tiers never write them either, nothing reads them).  Active only while tl_dbg[0] == 1 (heapcap clears
it at every battle load: rematch / continue / challenger battles without a loader run have the module off),
LOADER_FULL == 3 and the tag rules flag 0x8007b75d == 0; a hit also needs the drawn object (*0x80092bec) to be the
object the stash was built for.  tl_main clears the state at every load; Onslaught battles (stage 9 owns upper RAM and
reloads character data mid-battle) get the stock words back.

Memory: code = one disc sector read by tl_main to 0x8000F000; state 0x8000F600-0x8000FA40; stash pools: side 0 (P1
objects) 0x8000A000-0x8000AFFF + 0x80007600-0x800083FF, side 1 (P2) 0x8000FA40-0x8000FFFF + 0x8000B100-0x8000B7FF +
0x8000C100-0x8000C7FF + 0x80009A00-0x80009CFF (mktag.py's hardware-safe kernel spans).
Hooks (written into the RAM EXE by tl_main): 0x80022a18 jal DrawSync -> jal DXI; 0x8008c434 jal 0x8001bd48 -> jal DXD.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "speed", "frame")]
from gas import gas

# kernel / cold RAM map (dx10, 2026-11-18; kocache keeps 0x8000F040-0x8000F83F and 0x8000A040-0x8000A0BF):
CODE_AT, ST = 0x801FE000, 0x8000F840   # code sector: the bgfast spot (battle-cold, off in Onslaught battles)
AUX_AT = 0x8000A100                    # aux sector: the row-resumable DSA1 decoder (dsa/dss.S)
SSZ, NE = 0x200, 40                    # side struct: +0 obj +4 group +8 nent +0xc ndone +0x10 rate +0x14 section;
DBG = ST + 2 * SSZ                     # entries at +0x20.  16 debug words
SL = DBG + 0x40                        # per side DSA1 slice state (dss.S layout), 0x130 each
MBX = DBG + 0x30                       # --koahead: kocache writes {start, end} of the freed file's unused part here
PF = SL + 2 * 0x130                    # --koprefill job state (0x38)
KOCONV = int("--koconv" in sys.argv)               # in-RAM conversion after a release (koconv.S in the prefill sector)
if KOCONV: sys.argv.append("--koprefill2")
PREFILL2 = int("--koprefill2" in sys.argv or os.environ.get("DX_KOPREFILL2", "0") == "1")
if PREFILL2: sys.argv.append("--koprefill")   # v2 extends the v1 job
ST_END = PF + ((0x4c if KOCONV else 0x48 if PREFILL2 else 0x38) if "--koprefill" in sys.argv or os.environ.get("DX_KOPREFILL", "0") == "1" else 0)
AUX2_AT = 0x80007600                   # --koprefill: third sector (pf.S); side 0's static pool then starts at 0x80007E00
KOAHEAD = int("--koahead" in sys.argv or os.environ.get("DX_KOAHEAD", "0") == "1")
PREFILL = int("--koprefill" in sys.argv or os.environ.get("DX_KOPREFILL", "0") == "1")
PF_SCR = 0x1100                        # prefill scratch at the start of the mailbox span (4 KB tile + overrun)
PF_BUDGET = int(os.environ.get("DX_PFBUDGET", str(48 * 1024)))   # --koprefill2: decoded bytes per job
MBX_STASH = PF_SCR + (0x130 if PREFILL2 else 0)   # the mailbox stash starts after the scratch (+ v2 DSA1 slice state)
H1, H1W0 = 0x80022a18, 0x0c004619      # jal DrawSync (0x80011864) in the frame end 0x80022a0c
H2, H2W0 = 0x8008c434, 0x0c006f52      # jal 0x8001bd48 (tile decoder) in 0x8008c318
H3, H3W0 = 0x80022a20, 0x0c004216      # jal VSync (0x80010858) in the frame end
VSYNC = 0x80010858
DEC, DRAWSYNC = 0x8001bd48, 0x80011864
MARGIN = int(os.environ.get("DX_MARGIN", "24"))
SLICE = int(os.environ.get("DX_SLICE", "1"))       # 0: whole DSA1 tiles only (the dx09 behaviour, A/B baselines)
AFTER = int(os.environ.get("DX_AFTER", "1"))      # pre-decode after DrawSync (MiSTer: before it, supers lost ~9 fps)
RATES = dict(R_DSM=48, R_DSX=110, R_DSH=140, R_DSA=900, R_RLE=16)   # cycles per byte, ~1.4x the cost model
if "--dsr" in sys.argv: RATES["R_DSR"] = 460      # CPU worker: DSR1 sections ('DSR1' in the DSA1 slot), whole tiles
PINP = int("--pinpartners" in sys.argv)          # TEST only (postko.py discs): partners' life pinned >= 100 while alive
DSRS = int("--dxdsrs" in sys.argv)                 # dx worker: DSR1 row slices (dsa/dssr.S in the aux sector instead of dss.S)
assert not DSRS or "--dsr" in sys.argv, "--dxdsrs needs --dsr"
POOLS = [[((0x80007E00 if os.environ.get("DX_KOPREFILL", "0") == "1" or "--koprefill" in sys.argv else 0x80007600), 0x80008400), (0x8000A900, 0x8000B000)],
         [(0x8000B100, 0x8000B800), (0x8000C100, 0x8000C800), (0x801FE800, 0x801FED00), (0x80009A00, 0x80009D00)]]
if "--dxp2fix" in sys.argv:             # dx worker hotfix (hook audit 2026-11-20): 0x801FE800-0x801FEC00 = the sound entry-swap
    POOLS[1] = [p for p in POOLS[1] if p != (0x801FE800, 0x801FED00)]   # code (CODESPACE.md; magic 'SNDM'), 0x801FED10 = deepest stack
if os.environ.get("DX_P2NO9A"):         # TEST builds: side 1 without 0x80009A00-9D00 (what --hookgate leaves), no gate code
    POOLS[1] = [p for p in POOLS[1] if p != (0x80009A00, 0x80009D00)]
if "--hookgate" in sys.argv:            # freeze worker (rc4 hook-lifecycle audit): 0x80009A00-9D00 = the kernel hook gate (hookgate.py)
    POOLS[1] = [p for p in POOLS[1] if p != (0x80009A00, 0x80009D00)]
if "--ach" in sys.argv:                 # freeze worker (achievements on rc4, SPEED_TEAM.md): the resident core lives in kernel
    for _lo, _hi in [(0x8000A900, 0x8000B000), (0x80007600, 0x80007A00), (0x8000B100, 0x8000B500)]:   # RAM given up
        POOLS = [[(x, y) for a, b in side for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x] for side in POOLS]
if "--vscpu" in sys.argv or os.environ.get("DIAG_NOVSCPU") == "1":   # (vs cpu lead; DIAG_NOVSCPU: test discs keep the span for --infmeter) the vs-CPU fight code + vars (common/mtap, mvcmtap.CFG_V) take
    for _lo, _hi in [(0x8000C6D0, 0x8000C800)]:                                   # the top 304 B of side 1's C100 pool
        POOLS = [[(x, y) for a, b in side for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x] for side in POOLS]
if "--menufont" in sys.argv:            # (2026-11-25) the ach core's mfont (menu font re-upload) needs 256 B more: side 1's
    for _lo, _hi in [(0x8000B500, 0x8000B800 if os.environ.get("DIAG_MENU") == "1" else (0x8000B700 if "--modreload2" in sys.argv else 0x8000B600))] + ([(0x8000C100, 0x8000C300)] if os.environ.get("DIAG_MENU") == "1" else []):   # B500 pool bottom (mvcore.spans; DIAG_MENU test discs: whole B500 pool)
        POOLS = [[(x, y) for a, b in side for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x] for side in POOLS]
if "--dxps3" in sys.argv:               # (2026-11-26) 0x8000B1A0-B7A8 = the PS2/PS3 PS1-mode kernel's device + file-descriptor table
    for _lo, _hi in [(0x8000B500, 0x8000B800)]:     # (memory ps3-ps1-kernel-ram): never stash there (dxahead has no ROM gate)
        POOLS = [[(x, y) for a, b in side for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x] for side in POOLS]
if "--duofix" in sys.argv:              # (2026-11-26, MvC 1.0.1 native Duo fixes) duofix.S lives at 0x8000C100-0x8000C500
    for _lo, _hi in [(0x8000C200, 0x8000C600) if "--duoc200" in sys.argv else (0x8000C100, 0x8000C500)]:
        POOLS = [[(x, y) for a, b in side for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x] for side in POOLS]
if "--vx" in sys.argv:                  # (2026-11-26, MvC 1.1 Variable Cross prototype) vx.S lives at 0x8000B500-0x8000B800
    for _lo, _hi in [(0x8000B500, 0x8000B800), (0x8000C100, 0x8000C600 if ("--vxflash" in sys.argv or "--vxskip" in sys.argv) else 0x8000C400)]:
        POOLS = [[(x, y) for a, b in side for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x] for side in POOLS]
if os.environ.get("DX_NOPOOL"):          # TEST builds (freeze worker, achievements RAM plan): drop pool RAM -> what the stash
    for _x in os.environ["DX_NOPOOL"].split(","):   # costs in fps.  "START" = the span starting there, "LO-HI" = cut that range
        _lo, _hi = (int(v, 16) for v in _x.split("-")) if "-" in _x else (int(_x, 16), None)
        _new = []
        for _side in POOLS:
            _out = []
            for a, b in _side:
                if _hi is None: _out += [] if a == _lo else [(a, b)]
                else: _out += [(x, y) for x, y in ((a, min(b, _lo)), (max(a, _hi), b)) if y > x]
            _new.append(_out)
        POOLS = _new
SPANS = [(CODE_AT, CODE_AT + 0x800), (AUX_AT, AUX_AT + 0x800), (ST, ST_END)] + [x for p in POOLS for x in p]
OBJS = [(0x8007be90, 0x8007c6f0), (0x8007c2a0, 0x8007caf8)]

BUILD_SRC = r"""
/* ================= BUILD: a0 = object, a1 = group, a2 = side struct, a3 = side -> tile list + stash places.  Leaf. */
BUILD:  sw    $zero, 12($a2)                   /* ndone = 0 first: DXD never sees half-built entries */
        sw    $zero, 8($a2)
        sw    $a0, 0($a2)
        sw    $a1, 4($a2)
        lui   $t0, %hi(DBG)
        lw    $t1, %lo(DBG + 16)($t0)
        nop
        addiu $t1, $t1, 1
        sw    $t1, %lo(DBG + 16)($t0)
        lbu   $t0, 0x73($a0)                   /* set slot */
        nop
        sltiu $t1, $t0, 16
        beqz  $t1, Bret
        sll   $t0, $t0, 2
        lui   $t1, 0x800a
        addu  $t1, $t1, $t0
        lw    $t2, -0x30c0($t1)                /* sec1 (groups) 0x8009cf40[slot] */
        lui   $t1, 0x8009
        addu  $t1, $t1, $t0
        lw    $t3, 0x2b90($t1)                 /* tile table 0x80092b90[slot] */
        lw    $t4, 0x2b30($t1)                 /* pixel section 0x80092b30[slot] */
        li    $t5, 0x400
        srl   $t6, $t2, 21
        bne   $t6, $t5, Bret
        srl   $t6, $t3, 21
        bne   $t6, $t5, Bret
        srl   $t6, $t4, 21
        bne   $t6, $t5, Bret
        andi  $t6, $t4, 3
        bnez  $t6, Bret
        nop
        lw    $t5, 0($t4)                      /* codec of the set -> cycles per byte for the time check */
        lui   $t6, 0x314d
        ori   $t6, $t6, 0x5344                 /* 'DSM1' */
        beq   $t5, $t6, 1f
        li    $v0, R_DSM
        lui   $t6, 0x3141
        ori   $t6, $t6, 0x5344                 /* 'DSA1' */
        beq   $t5, $t6, 1f
        li    $v0, R_DSA
        lui   $t6, 0x3148
        ori   $t6, $t6, 0x5344                 /* 'DSH1' (DSX: classes bit 15) */
        bne   $t5, $t6, 1f
        li    $v0, R_RLE
        lhu   $t5, 8($t4)
        li    $v0, R_DSX
        andi  $t5, $t5, 0x8000
        bnez  $t5, 1f                          /* DSX */
        nop
        li    $v0, R_DSH
1:      sw    $v0, 0x10($a2)
        sw    $t4, 0x14($a2)                   /* section (DSA1 slices) */
        lui   $t5, %hi(SL + 0x18)              /* slice state of this side: abandoned */
        beqz  $a3, 3f
        addiu $t5, $t5, %lo(SL + 0x18)
        addiu $t5, $t5, 0x130
3:      sw    $zero, 0($t5)
        addu  $t2, $t2, $a1                    /* group record (any alignment: byte loads) */
        lbu   $t5, 0($t2)                      /* parts */
        lbu   $t6, 1($t2)
        addiu $t2, $t2, 6
        sll   $t6, $t6, 8
        or    $t5, $t5, $t6
        sltiu $t6, $t5, 65
        bnez  $t6, 1f
        nop
        li    $t5, 64
1:      lui   $t6, %hi(POOLT)                  /* pool spans of this side: {start, end} .. 0 */
        addiu $t6, $t6, %lo(POOLT)
        sll   $t7, $a3, 6
        addu  $t6, $t6, $t7
        lw    $t7, 0($t6)                      /* cursor */
        lw    $t8, 4($t6)                      /* span end */
.if KOAHEAD
        lui   $at, %hi(MBX)                    /* freed-file span from kocache: half per side, before the static spans */
        lw    $t9, %lo(MBX)($at)
        lw    $t1, %lo(MBX + 4)($at)
        beqz  $t9, 8f
        addiu $t9, $t9, PF_SCR
        subu  $t0, $t1, $t9
        srl   $t0, $t0, 3
        sll   $t0, $t0, 2
        addu  $t0, $t9, $t0                    /* middle */
        addiu $t6, $t6, -8                     /* the static spans follow */
        beqz  $a3, 7f
        move  $t7, $t9
        move  $t7, $t0
        b     8f
        move  $t8, $t1
7:      move  $t8, $t0
8:
.endif
        move  $v1, $zero                       /* nent */
Bpart:  beqz  $t5, Bdone
        addiu $t5, $t5, -1
        lbu   $a1, 2($t2)
        lbu   $a0, 1($t2)
        lbu   $t9, 0($t2)                      /* part flags */
        sll   $a1, $a1, 8
        or    $a0, $a0, $a1                    /* tile | x mode << 12 | y mode << 14 */
        srl   $a1, $a0, 12
        andi  $a1, $a1, 3
        xori  $a1, $a1, 3
        sltiu $a1, $a1, 1                      /* x mode 3: s16 */
        addiu $a1, $a1, 6
        srl   $v0, $a0, 14
        xori  $v0, $v0, 3
        sltiu $v0, $v0, 1
        addu  $a1, $a1, $v0                    /* part size 6..8 */
        andi  $t9, $t9, 0x80                   /* reuse the previous decode: no tile */
        bnez  $t9, Bskip
        andi  $a0, $a0, 0xfff
        sll   $t9, $a0, 2
        addu  $t9, $t9, $a0
        addu  $t9, $t9, $t3                    /* tile entry (5 bytes) */
        lbu   $a0, 0($t9)
        lbu   $v0, 1($t9)
        nop
        sll   $v0, $v0, 8
        or    $a0, $a0, $v0
        lbu   $v0, 2($t9)
        nop
        andi  $v0, $v0, 0x3f
        sll   $v0, $v0, 16
        or    $a0, $a0, $v0                    /* offset */
        lbu   $v0, 3($t9)                      /* width bytes | half flag */
        lbu   $t9, 4($t9)                      /* rows (bit 7 = narrow when flagged) */
        andi  $at, $v0, 0x80
        beqz  $at, 2f
        andi  $v0, $v0, 0x7f
        andi  $t9, $t9, 0x7f
2:      multu $v0, $t9
        addu  $a0, $a0, $t4                    /* src */
        mflo  $v0                              /* n */
        beqz  $v0, Bskip
        nop
        addiu $t9, $a2, 0x20                   /* already listed? */
        move  $at, $v1
3:      beqz  $at, 4f
        nop
        lw    $a3, 0($t9)
        addiu $at, $at, -1
        beq   $a3, $a0, Bskip
        addiu $t9, $t9, 12
        b     3b
        nop
4:      addiu $a3, $v0, 19                     /* stash place: n + 16 slack, 4-aligned */
        srl   $a3, $a3, 2
        sll   $a3, $a3, 2
5:      addu  $at, $t7, $a3
        sltu  $at, $t8, $at
        beqz  $at, 6f
        nop
        addiu $t6, $t6, 8                      /* next span */
        lw    $t7, 0($t6)
        lw    $t8, 4($t6)
        bnez  $t7, 5b
        nop
        b     Bdone
        nop
6:      sll   $at, $v1, 3                      /* entry v1 = {src, n, dst} */
        sll   $t9, $v1, 2
        addu  $at, $at, $t9
        addu  $at, $at, $a2
        sw    $a0, 0x20($at)
        sw    $v0, 0x24($at)
        sw    $t7, 0x28($at)
        addu  $t7, $t7, $a3
        addiu $v1, $v1, 1
        sltiu $at, $v1, NE
        beqz  $at, Bdone
        nop
Bskip:  b     Bpart
        addu  $t2, $t2, $a1
Bdone:  sw    $v1, 8($a2)
Bret:   jr    $ra
        nop

        .align 3
POOLT:
"""

if "--dsr" in sys.argv:                            # CPU worker: the DSA1 slot holds DSR1 sections: magic + own rate (no slices)
    _a = """        lui   $t6, 0x3141
        ori   $t6, $t6, 0x5344                 /* 'DSA1' */
        beq   $t5, $t6, 1f
        li    $v0, R_DSA"""
    assert BUILD_SRC.count(_a) == 1
    BUILD_SRC = BUILD_SRC.replace(_a, """        lui   $t6, 0x3152
        ori   $t6, $t6, 0x5344                 /* 'DSR1' */
        beq   $t5, $t6, 1f
        li    $v0, R_DSR""")

SRC = r"""
/* ================= DXI: in place of jal DrawSync(0) at the frame end; pre-decode, then DrawSync */
DXI:    addiu $sp, $sp, -48
        sw    $ra, 44($sp)
        sw    $s0, 16($sp)
        sw    $s1, 20($sp)
        sw    $s2, 24($sp)
        sw    $s3, 28($sp)
.if AFTER
        jal   DRAWSYNC                         /* GPU done first: no bus contention with its drawing */
        move  $a0, $zero
.endif
        lui   $t0, %hi(DBG)
        lw    $t1, %lo(DBG)($t0)
        lui   $t2, 0x1f80
        lhu   $t2, 0x1110($t2)
        addiu $t1, $t1, 1
        sw    $t1, %lo(DBG)($t0)
        sw    $t2, %lo(DBG + 20)($t0)          /* last line count at entry */
        lui   $t0, %hi(TLDBG)
        lbu   $t0, %lo(TLDBG)($t0)
        li    $t1, 1
        bne   $t0, $t1, Idone
        lui   $t0, 0x8008
        lbu   $t1, 0x58ac($t0)                 /* LOADER_FULL */
        lbu   $t2, -0x48a3($t0)                /* 0x8007b75d tag rules flag (0 in a tag battle) */
        li    $t3, 3
        bne   $t1, $t3, Idone
        nop
        bnez  $t2, Idone
        move  $s0, $zero
        lbu   $t1, -0x4234($t0)                /* scene 0x8007bdcc == 8 and battle phase 0x8007b828 < 0x0a: the continue /  */
        li    $t3, 8                           /* game-over screens reuse the objects -> predictions from garbage scripts */
        bne   $t1, $t3, Idone                  /* hung the DSA1 row decoder (integrator, 2026-11-19 exit-to-menu freeze) */
        lbu   $t2, -0x47d8($t0)
        nop                                    /* load delay (freeze worker: without it R3000 tests the old t2) */
        sltiu $t2, $t2, 0x0a
        beqz  $t2, Idone
        nop
Iside:  lui   $s1, %hi(ST)
        addiu $s1, $s1, %lo(ST)
        sll   $t0, $s0, 9
        addu  $s1, $s1, $t0                    /* side struct */
        lui   $t0, %hi(OBJT)
        addiu $t0, $t0, %lo(OBJT)
        sll   $t1, $s0, 3
        addu  $t0, $t0, $t1
        lw    $a0, 0($t0)
        nop
        lbu   $t2, 0($a0)
        nop
        bnez  $t2, 1f
        nop
        lw    $a0, 4($t0)
        nop
        lbu   $t2, 0($a0)
        nop
        bnez  $t2, 1f
        nop
        sw    $zero, 12($s1)                   /* no active object on this side */
        sw    $zero, 8($s1)
        b     Inext
        sw    $zero, 0($s1)
1:      jal   PRED
        move  $s2, $a0
        bltz  $v0, Inext
        nop
        lw    $t0, 0($s1)
        lw    $t1, 4($s1)
        bne   $t0, $s2, 2f
        nop
        beq   $t1, $v0, Inext
        nop
2:      move  $a0, $s2
        move  $a1, $v0
        move  $a2, $s1
        jal   BUILD
        move  $a3, $s0
Inext:  addiu $s0, $s0, 1
        slti  $t0, $s0, 2
        bnez  $t0, Iside
        nop
/* work: the side whose object leaves its frame sooner first; one tile at a time while it fits before the vblank */
.if PREFILL
        jal   PFTRIG
        nop
.endif
Iwork:  lui   $s1, %hi(ST)
        addiu $s1, $s1, %lo(ST)
        addiu $s3, $s1, SSZ
        lw    $t0, 8($s1)
        lw    $t1, 12($s1)
        lw    $t2, 8($s3)
        lw    $t3, 12($s3)
        slt   $t0, $t1, $t0                    /* side 0 has work */
        slt   $t2, $t3, $t2                    /* side 1 has work */
        beqz  $t0, 3f
        nop
        beqz  $t2, 4f                          /* only side 0 */
        nop
        lw    $t4, 0($s1)                      /* both: compare the frames left (obj+0x3a) */
        lw    $t5, 0($s3)
        lbu   $t4, 0x3a($t4)
        lbu   $t5, 0x3a($t5)
        nop
        sltu  $t6, $t5, $t4
        beqz  $t6, 4f
        nop
        b     4f
        move  $s1, $s3
.if PREFILL
3:      beqz  $t2, PFst
.else
3:      beqz  $t2, Idone
.endif
        nop
        move  $s1, $s3
4:      lw    $t1, 12($s1)                     /* ndone */
        nop
        sll   $t2, $t1, 3
        sll   $t3, $t1, 2
        addu  $t2, $t2, $t3
        addu  $s2, $s1, $t2
        addiu $s2, $s2, 0x20                   /* entry {src, n, dst} */
        lw    $t4, 4($s2)
        lw    $t5, 0x10($s1)                   /* cycles per byte */
.if SLICE
        li    $t6, R_DSA
        beq   $t5, $t6, Islice                 /* DSA1: row slices (dss.S), a tile may span several frames */
        nop
.endif
        multu $t4, $t5
        jal   BUD
        nop
        mflo  $t6
        srl   $t6, $t6, 11                     /* ~lines (2152 cycles each) */
        addiu $t6, $t6, 4
        slt   $t7, $v0, $t6
        beqz  $t7, 5f
        nop
        lui   $t0, %hi(DBG)                    /* does not fit: stop for this frame */
        lw    $t1, %lo(DBG + 24)($t0)
        nop
        addiu $t1, $t1, 1
        b     Idone
        sw    $t1, %lo(DBG + 24)($t0)
5:      lw    $a0, 0($s2)
        lw    $a2, 4($s2)
        lw    $a1, 8($s2)
        jal   DEC
        nop
        lw    $t1, 12($s1)
        lui   $t0, %hi(DBG)
        addiu $t1, $t1, 1
        sw    $t1, 12($s1)
        lw    $t2, %lo(DBG + 4)($t0)
        nop
        addiu $t2, $t2, 1
        b     Iwork
        sw    $t2, %lo(DBG + 4)($t0)
Islice: jal   BUD
        nop
        lw    $t0, 0($s2)                      /* src: width byte first */
        addiu $v0, $v0, -4
        lbu   $t1, 0($t0)
        blez  $v0, Ibreak
        sll   $v0, $v0, 11                     /* cycles left (2048 per line, conservative) */
        li    $t2, R_DSA
        multu $t1, $t2
        mflo  $t2                              /* cycles per row */
        nop
        nop
        beqz  $t2, Ibreak
        nop
        divu  $v0, $t2
        mflo  $t3                              /* rows that fit */
        lui   $a0, %hi(SL)
        beqz  $t3, Ibreak
        addiu $a0, $a0, %lo(SL)
        lui   $t4, %hi(ST)
        addiu $t4, $t4, %lo(ST)
        beq   $s1, $t4, 1f
        nop
        addiu $a0, $a0, 0x130
1:      lw    $t5, 0x18($a0)                   /* slice started? */
        sw    $t3, 0x20($a0)
        bnez  $t5, 2f
        nop
        lw    $t6, 0($s2)
        lw    $t7, 4($s2)
        lw    $t8, 8($s2)
        lw    $t9, 0x14($s1)                   /* the set's DSA1 section */
        sw    $t6, 0($a0)
        sw    $t8, 4($a0)
        sw    $t7, 8($a0)
        sw    $t9, 0xc($a0)
2:      jal   DSS
        nop
        bnez  $v0, 5f                          /* finished: count it like a whole decode */
        nop
Ibreak: lui   $t0, %hi(DBG)
        lw    $t1, %lo(DBG + 24)($t0)
        nop
        addiu $t1, $t1, 1
        b     Idone
        sw    $t1, %lo(DBG + 24)($t0)
5:      lw    $t1, 12($s1)
        lui   $t0, %hi(DBG)
        addiu $t1, $t1, 1
        sw    $t1, 12($s1)
        lw    $t2, %lo(DBG + 32)($t0)
        nop
        addiu $t2, $t2, 1
        b     Iwork
        sw    $t2, %lo(DBG + 32)($t0)
Idone:
.if AFTER == 0
        jal   DRAWSYNC
        move  $a0, $zero
.endif
        lw    $ra, 44($sp)
        lw    $s0, 16($sp)
        lw    $s1, 20($sp)
        lw    $s2, 24($sp)
        lw    $s3, 28($sp)
        jr    $ra
        addiu $sp, $sp, 48

.if PREFILL
PFst:   j     PFSTEP
        nop
.endif

/* ================= DXV: in place of jal VSync(0) at the frame end: stamp hblank counter 1 at its return */
DXV:    addiu $sp, $sp, -24
        sw    $ra, 16($sp)
        jal   VSYNC
        nop
        lui   $t0, 0x1f80
        lhu   $t0, 0x1110($t0)
        lui   $t1, %hi(DBG)
        sw    $t0, %lo(DBG + 28)($t1)
.if PINP
        li    $t4, 100                         /* TEST (--pinpartners, postko.py discs): both partners' life >= 100 */
        lui   $t2, %hi(0x8007c984)             /* while alive, so only the mains can be KO'd by the scripted windows */
        lh    $t3, %lo(0x8007c984)($t2)        /* P1 partner 0x8007c6f0 + 0x294 */
        nop
        blez  $t3, 1f
        slti  $t5, $t3, 100
        beqz  $t5, 1f
        nop
        sh    $t4, %lo(0x8007c984)($t2)
1:      lui   $t2, %hi(0x8007cd8c)
        lh    $t3, %lo(0x8007cd8c)($t2)        /* P2 partner 0x8007caf8 + 0x294 */
        nop
        blez  $t3, 2f
        slti  $t5, $t3, 100
        beqz  $t5, 2f
        nop
        sh    $t4, %lo(0x8007cd8c)($t2)
2:      li    $t4, 0x99                        /* and the round clock held at 99 (no time-over in long scripted runs) */
        lui   $t2, %hi(0x8007b832)
        sb    $t4, %lo(0x8007b832)($t2)
.endif
        lw    $ra, 16($sp)
        nop
        jr    $ra
        addiu $sp, $sp, 24

/* ================= BUD: v0 = hblank lines left before the next vblank, minus MARGIN (signed) */
BUD:    lui   $t0, 0x1f80
        lhu   $t0, 0x1110($t0)
        lui   $t1, %hi(DBG)
        lw    $t1, %lo(DBG + 28)($t1)          /* counter 1 at the last VSync(0) return (DXV) */
        nop
        sltu  $t2, $t0, $t1
        bnez  $t2, 1f                          /* reset since (main loop ResetRCnt(1)): t0 = lines since then */
        addiu $t0, $t0, 2
        addiu $t0, $t0, -2
        subu  $t0, $t0, $t1
1:      li    $t1, 263
3:      sltu  $t2, $t0, $t1
        bnez  $t2, 2f
        nop
        b     3b
        subu  $t0, $t0, $t1
2:      subu  $v0, $t1, $t0
        jr    $ra
        addiu $v0, $v0, -MARGIN

/* ================= PRED: a0 = object -> v0 = sec1 offset of the next DIFFERENT frame group, or -1.  Leaf. */
PRED:   lw    $t2, 0x60($a0)                   /* animation blob (the engine's step 0x8003c054 uses obj+0x60) */
        li    $t4, 0x400
        srl   $t3, $t2, 21
        bne   $t3, $t4, Pfail
        andi  $t3, $t2, 3
        bnez  $t3, Pfail
        nop
        lw    $t3, 4($t2)
        lw    $t4, 8($t2)
        lw    $t5, 12($t2)
        addu  $t3, $t2, $t3                    /* records */
        addu  $t4, $t2, $t4                    /* frame table = end of the records */
        addu  $t5, $t2, $t5                    /* end of the frame table */
        andi  $t9, $t4, 1                      /* frame table: 2-byte aligned (lhu) */
        bnez  $t9, Pfail
        nop
        lhu   $t6, 0x3c($a0)                   /* current group */
        lw    $t7, 0x34($a0)                   /* next record */
        li    $t8, 6
Ploop:  sltu  $t9, $t7, $t3
        bnez  $t9, Pfail
        sltu  $t9, $t7, $t4
        beqz  $t9, Pfail
        andi  $t9, $t7, 1                      /* records are 2-byte aligned (lhu in the engine) */
        bnez  $t9, Pfail
        nop
        lhu   $t9, 0($t7)
        lhu   $v1, 2($t7)
        andi  $t9, $t9, 0xff                   /* frame = w0 & 0xff | (w1 & 0x7000) >> 4 (0x8003c0b8) */
        andi  $v0, $v1, 0x7000
        srl   $v0, $v0, 4
        or    $t9, $t9, $v0
        sll   $t9, $t9, 2
        addu  $t9, $t4, $t9
        sltu  $v0, $t9, $t5
        beqz  $v0, Pfail
        nop
        lhu   $v0, 0($t9)                      /* the frame's group */
        li    $t9, 0xffff
        beq   $v0, $t9, Pnext
        nop
        bne   $v0, $t6, Pok
        nop
Pnext:  andi  $t9, $v1, 0x8000
        beqz  $t9, 1f
        addiu $t7, $t7, 4
        lhu   $t9, 0($t7)                      /* end record: loop target (u32, 2-byte aligned) */
        lhu   $v0, 2($t7)
        nop
        sll   $v0, $v0, 16
        or    $t9, $t9, $v0
        addu  $t7, $t3, $t9
1:      addiu $t8, $t8, -1
        bnez  $t8, Ploop
        nop
Pfail:  li    $v0, -1
Pok:    jr    $ra
        nop

/* ================= DXD: in place of jal 0x8001bd48 at 0x8008c434 (a0 src, a1 dst, a2 n): stash hit -> copy */
DXD:    lui   $t0, %hi(TLDBG)
        lbu   $t0, %lo(TLDBG)($t0)
        li    $t1, 1
        bne   $t0, $t1, Dplain
        lui   $t9, 0x8009
        lw    $t9, 0x2bec($t9)                 /* object being drawn */
        lui   $t2, %hi(ST)
        addiu $t2, $t2, %lo(ST)
        li    $t3, 2
Dside:  lw    $t4, 12($t2)                     /* ndone */
        lw    $t0, 0($t2)
        addiu $t5, $t2, 0x20
        bne   $t0, $t9, Dns
        nop
Dl:     beqz  $t4, Dns
        nop
        lw    $t6, 0($t5)
        lw    $t7, 4($t5)
        bne   $t6, $a0, Dn
        nop
        beq   $t7, $a2, Dhit
        nop
Dn:     addiu $t4, $t4, -1
        b     Dl
        addiu $t5, $t5, 12
Dns:    addiu $t3, $t3, -1
        bnez  $t3, Dside
        addiu $t2, $t2, SSZ
Dplain: j     DEC
        nop
Dhit:   lw    $t6, 8($t5)
        andi  $t0, $a1, 3                      /* dst not word-aligned: bytes only */
        bnez  $t0, 2f
        move  $t7, $a2
        srl   $t7, $a2, 2
        beqz  $t7, 2f
        andi  $t7, $a2, 3
        srl   $t7, $a2, 2
1:      lw    $t8, 0($t6)
        addiu $t6, $t6, 4
        addiu $t7, $t7, -1
        sw    $t8, 0($a1)
        bnez  $t7, 1b
        addiu $a1, $a1, 4
        andi  $t7, $a2, 3
2:      beqz  $t7, 4f
        nop
3:      lbu   $t8, 0($t6)
        addiu $t6, $t6, 1
        addiu $t7, $t7, -1
        sb    $t8, 0($a1)
        bnez  $t7, 3b
        addiu $a1, $a1, 1
4:      lui   $t0, %hi(DBG)
        lw    $t1, %lo(DBG + 8)($t0)
        lw    $t2, %lo(DBG + 12)($t0)
        addiu $t1, $t1, 1
        addu  $t2, $t2, $a2
        sw    $t1, %lo(DBG + 8)($t0)
        jr    $ra
        sw    $t2, %lo(DBG + 12)($t0)

        .align 3
OBJT:   .word 0x8007be90, 0x8007c6f0, 0x8007c2a0, 0x8007caf8
MAINEND:
"""



if DSRS:                                           # DSR1 tiles go through the row slices at DSR1's rate (no DSA1 in --dsr builds)
    _o1 = """        li    $t6, R_DSA
        beq   $t5, $t6, Islice"""
    _o2 = """        li    $t2, R_DSA
        multu $t1, $t2"""
    assert SRC.count(_o1) == 1 and SRC.count(_o2) == 1
    SRC = SRC.replace(_o1, _o1.replace("R_DSA", "R_DSR")).replace(_o2, _o2.replace("R_DSA", "R_DSR"))

# Hook trampolines (freeze worker, 2026-11-19): the EXE hooks (H1 / H2 / H3) stay installed after a tag battle, but the
# main sector at CODE_AT (0x801FE000) is only battle-cold IN TAG BATTLES: a later stock-loader battle (attract after a
# game over, CPU-vs-CPU picks) or another scene's data overwrites it while present / the tile decoder keep jumping
# there -> the user's "NOW LOADING" freeze (rc2 hang state: 0x801fe000-0x801fe2f8 zeroed, EPC in 0x801fe1xx).  The hooks
# now enter here (kernel RAM, never loaded over): main sector only in the battle scene of a battle the tag loader
# loaded (scene 0x8007bdcc == 8 and tl_dbg[0] == 1; heapcap clears tl_dbg[0] at every battle load, Onslaught gets the
# stock words), else the stock call (DrawSync / VSync / tile decoder, arguments untouched; t0-t2 are free at a jal).
TRAMP_SRC = """
TDXI:   b     tgate
        ori   $t2, $zero, 0
TDXV:   b     tgate
        ori   $t2, $zero, 8
TDXD:   ori   $t2, $zero, 16
tgate:  lui   $t0, 0x8008
        lbu   $t0, -0x4234($t0)                /* scene 0x8007bdcc */
        lui   $t1, %hi(TLDBG)
        lbu   $t1, %lo(TLDBG)($t1)
        xori  $t0, $t0, 8
        xori  $t1, $t1, 1
        or    $t0, $t0, $t1
        sltu  $t0, $zero, $t0                  /* 1 = not a tag battle's battle scene: stock call */
        sll   $t0, $t0, 2
        addu  $t2, $t2, $t0
        lui   $t0, %hi(TTAB)
        addu  $t0, $t0, $t2
        lw    $t0, %lo(TTAB)($t0)
        nop
        jr    $t0
        nop
TTAB:   .word M_DXI, DRAWSYNC, M_DXV, VSYNC, M_DXD, DEC
"""


def aux(tldbg=0x8001b4e0, msym=None):
    """the aux sector at AUX_AT: hook trampolines + dsa/dss.S (row-resumable DSA1) + BUILD + the pool table -> (bytes,
    symbols); msym = the main sector's symbols (trampoline targets; None: placeholders of the same size)"""
    pools = b""
    for p in POOLS:
        w = []
        for a, b in p: w += [a, b]
        w += [0, 0]
        assert len(w) <= 16
        pools += struct.pack("<16I", *(w + [0] * (16 - len(w))))
    dss = open(os.path.join(HERE, "dsa", "dssr.S" if DSRS else "dss.S")).read()
    src = TRAMP_SRC + chr(10) + dss + chr(10) + BUILD_SRC
    defs = {"ST": ST, "DBG": DBG, "SL": SL, "NE": NE, "MBX": MBX, "KOAHEAD": KOAHEAD, "PF_SCR": MBX_STASH, **RATES,
            "TLDBG": tldbg, "DRAWSYNC": DRAWSYNC, "VSYNC": VSYNC, "DEC": DEC,
            "M_DXI": (msym or {}).get("DXI", CODE_AT), "M_DXV": (msym or {}).get("DXV", CODE_AT),
            "M_DXD": (msym or {}).get("DXD", CODE_AT)}
    c, sym = gas(src, AUX_AT, defs)
    c2, _ = gas(src, AUX_AT + 0x1000, defs)
    assert sym["POOLT"] - AUX_AT == len(c)
    c += pools
    assert len(c) <= 2048, len(c)
    return c, sym


def pfpart(main_sym):
    """the --koprefill sector at AUX2_AT -> (bytes, symbols)"""
    src = open(os.path.join(HERE, "koconv.S" if KOCONV else "pf.S")).read()
    defs = {"PF": PF, "MBX": MBX, "DBG": DBG, "DEC": DEC, "PREFILL2": PREFILL2, "PF_SCR": PF_SCR, "PF_BUDGET": PF_BUDGET,
            "DSS": aux()[1]["dssr_run" if DSRS else "dss_run"], **RATES}
    if KOCONV:
        import kox
        defs.update(DSR=int("--dsr" in sys.argv), FSB=kox.fsb(), CONV_LINES=int(os.environ.get("DX_CONVLINES", "300")))
    if PREFILL2:
        import importlib.util
        spec = importlib.util.spec_from_file_location("kocache", os.path.join(GAME, "tools", "tagload", "kocache.py"))
        ko = importlib.util.module_from_spec(spec); spec.loader.exec_module(ko)
        ksym = ko._asm(ko.KO_AT)[1]
        defs.update(KOKD=ksym["KD"], KOIDX=ko.IDX, KOIDXEND=ko.IDXEND)
    else:
        defs.update(KOKD=0, KOIDX=0, KOIDXEND=0)
    defs.update({k: main_sym.get(n, 0x80010000) for k, n in (("M_IDONE", "Idone"), ("M_BUD", "BUD"), ("M_OBJT", "OBJT"))})
    c, sym = gas(src, AUX2_AT, defs)
    assert sym["PFEND"] - AUX2_AT == len(c) and len(c) <= 2048, len(c)
    return c, sym


if "--l2g" in sys.argv:                 # fx worker, rc4 L2 (games/mvc/tools/l2): packed frame groups -> the group pointer
    _a = """        addu  $t2, $t2, $a1                    /* group record (any alignment: byte loads) */"""
    assert BUILD_SRC.count(_a) == 1      # comes from g2get (installed by tl_main: its jal is the word at 0x8008f694;
    BUILD_SRC = BUILD_SRC.replace(_a, """        lui   $t5, 0x8009                      /* 0 = not installed this battle -> stock pointer) */
        lw    $t5, -0x96c($t5)                 /* 0x8008f694: jal g2get or nop */
        nop
        beqz  $t5, 91f
        addu  $t2, $t2, $a1                    /* group record, stock layout (packed: g2get's copy below) */
        sll   $t5, $t5, 6
        srl   $t5, $t5, 4
        lui   $t6, 0x8000
        or    $t5, $t5, $t6                    /* g2get */
        addiu $sp, $sp, -8
        sw    $ra, 0($sp)
        move  $v0, $t2
        jalr  $t5
        move  $v1, $a1
        move  $t2, $v0
        lw    $ra, 0($sp)
        addiu $sp, $sp, 8
91:""")


def build(tldbg):
    ac, asym = aux(tldbg)
    defs = {"ST": ST, "DBG": DBG, "SSZ": SSZ, "NE": NE, "DEC": DEC, "DRAWSYNC": DRAWSYNC,
            "TLDBG": tldbg, "MARGIN": MARGIN, "VSYNC": VSYNC, "AFTER": AFTER, "SLICE": SLICE, "SL": SL, "PF": PF, "MBX": MBX,
            "PREFILL": PREFILL, "KOAHEAD": KOAHEAD, "PINP": PINP, "DSS": asym["dssr_run" if DSRS else "dss_run"], "BUILD": asym["BUILD"], **RATES}
    pc = b""
    if PREFILL:
        pc, psym = pfpart({})                                   # pass 1: PF addresses (sizes do not depend on M_*)
        defs.update(PFTRIG=psym["PFtrig"], PFSTEP=psym["PFstep"])
    code, sym = gas(SRC, CODE_AT, defs)
    if PREFILL:
        pc, psym = pfpart(sym)
        assert psym["PFtrig"] == defs["PFTRIG"] and psym["PFstep"] == defs["PFSTEP"]
        sym["_pf"] = pc
    assert sym["MAINEND"] - CODE_AT == len(code)
    assert len(code) <= 2048, len(code)
    assert 0x20 + 12 * NE <= SSZ and ST_END <= 0x80010000
    ac2, asym2 = aux(tldbg, sym)                                # pass 2: trampoline targets (same layout)
    assert len(ac2) == len(ac) and all(asym2[k] == asym[k] for k in asym if not k.startswith("M_DX"))
    sym["_aux"] = ac2; sym["_asym"] = asym2
    hz = hazards(code) + hazards_at(ac2[:asym2["POOLT"] - AUX_AT], AUX_AT)
    assert not hz, "dxahead load-delay hazards: " + "; ".join(hz)      # (a gate lbu in a delay slot slipped in once)
    return code, sym


def hazards_at(code, at):
    sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "decode"))
    import dlib
    return dlib.hazards(code, at)


def hazards(code):
    sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "decode"))
    import dlib
    return dlib.hazards(code, CODE_AT)


def header(msf, msf2, tldbg, msf3=0):
    code, sym = build(tldbg)
    jl = lambda t: 0x0C000000 | (t >> 2 & 0x3ffffff)
    d = [("DX_AT", CODE_AT), ("DX_MSF", msf), ("DX_SIZE", len(code)), ("DX_AT2", AUX_AT), ("DX_MSF2", msf2),
         ("DX_SIZE2", len(sym["_aux"])), ("DX_ST", ST), ("DX_NST", (ST_END - ST) // 4),
         ("DX_H1", H1), ("DX_H1W", jl(sym["_asym"]["TDXI"])), ("DX_H1W0", H1W0), ("DX_H2", H2),
         ("DX_H2W", jl(sym["_asym"]["TDXD"])), ("DX_H2W0", H2W0), ("DX_H3", H3), ("DX_H3W", jl(sym["_asym"]["TDXV"])),
         ("DX_H3W0", H3W0)]
    if PREFILL: d += [("DX_AT3", AUX2_AT), ("DX_MSF3", msf3), ("DX_SIZE3", len(sym["_pf"]))]
    return "".join("#define %s 0x%08xu" % kv + chr(10) for kv in d)


def sectors(tldbg):
    """[main, aux] (+ [pf] with --koprefill), 2048 bytes each"""
    code, sym = build(tldbg)
    out = [code + bytes(2048 - len(code)), sym["_aux"] + bytes(2048 - len(sym["_aux"]))]
    if PREFILL: out.append(sym["_pf"] + bytes(2048 - len(sym["_pf"])))
    return out


if __name__ == "__main__":
    c, s = build(0x8001b4e0)
    print("dxahead code %d B at %08x, aux (dss) %d B at %08x; DXI %08x DXD %08x; state %08x-%08x" % (len(c), CODE_AT, len(s["_aux"]), AUX_AT, s["DXI"], s["DXD"], ST, ST_END))
    h = hazards(c) + hazards_at(s["_aux"][:s["_asym"]["POOLT"] - AUX_AT], AUX_AT)
    print("load-delay hazards:", h or "none")

if "--vxalt" in sys.argv:              # (2026-11-26, MvC 1.1 Variable Cross speed lever) both objects of a side active (the
    _a = """        lw    $a0, 0($t0)
        nop
        lbu   $t2, 0($a0)
        nop
        bnez  $t2, 1f
        nop
        lw    $a0, 4($t0)"""         # Duo): predict main / partner on alternate main loops
    _b = """        lw    $a0, 0($t0)
        lw    $t3, 4($t0)
        lbu   $t2, 0($a0)
        lbu   $t4, 0($t3)
        beqz  $t2, 7f
        nop
        beqz  $t4, 1f                          /* only the main active: stock */
        lui   $t4, 0x8008
        lw    $t4, -0x48b4($t4)                /* main loops 0x8007b74c: odd -> the partner */
        nop
        andi  $t4, $t4, 1
        beqz  $t4, 1f
        nop
        b     1f
        move  $a0, $t3
7:      lw    $a0, 4($t0)"""
    assert SRC.count(_a) == 1, "dxahead Iside block"
    SRC = SRC.replace(_a, _b)
