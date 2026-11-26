"""VRAM-resident decoded-tile cache v4 (FIFO ring, 16-row pieces); derived from v3 ("vcache", MvC PS1 tag hack).

Hook: player tile path 0x8008c5cc `jal 0x8008c318` (decode) -> `jal VC`.  Only while the phase byte 0x8007b828 == 8
(fight); any call outside the fight invalidates everything once (generation + 1) and takes the normal path.
Free VRAM (lockstep fill probes, every stage 0-8 + ARCADE / VERSUS / continue flows, tools/vcache2/vcstrip.py,
vcfill.py): shelves of 32 rows: x 128-383 y 480-511 and x 960-1023 y 432-463 / 464-495 (24 KB).
Tiles: a tile of h rows is stored as ceil(h / 32) pieces of 32 rows side by side in one shelf.
Hit: MoveImage(slot pieces -> cell RECT), no decode, no LoadImage, no arena use; return to 0x8008c624.
Miss: decode + LoadImage as the game, then (when not full) MoveImage(cell -> slot pieces); return to 0x8008c5ec.
Policy: fill until full, then freeze; when full and fewer than 8 of the last 32 lookups hit, reset (generation + 1).
Key = stream address (set pointer 0x80092b30[set] + tile offset).  Index: NIDX direct-mapped entries
{key, gen (16), pos (16)}; generation 0 never valid (wrap clears the index).
Stackless: ra and s2-s5 parked in the state block.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "speed", "frame"), os.path.join(ROOT, "tools", "speed", "decode")]
from gas import gas
SITE, SITEW0, DEC, LOADIMAGE, MOVEIMAGE, ARENA = 0x8008c5cc, 0x0c0230c6, 0x8008c318, 0x80011b10, 0x80011bd0, 0x80092c40
# free battle VRAM (SPEED_TEAM.md map), shelves of 16 rows: x 128-383 y 480-511, x 960-1023 y 432-511 (26 KB)
SHELVES = [(128, 480, 256), (128, 496, 256), (960, 432, 64), (960, 448, 64), (960, 464, 64), (960, 480, 64), (960, 496, 64)]
# stage 8 with --pal8: x 128-383 y 480-511 + x 960-1023 y 432-471 hold the fade CLUT rows; VC keeps x 960-1023 y 472-511
SHELVES8 = [(960, 472, 64), (960, 488, 64)]      # x 960-1023 y 472-503 (y 504-511 unused)
if "--vcnox960" in sys.argv:          # (2026-11-26) the native Duo cut-in keeps its compressed BG images in VRAM x960-1023 y256-511
    SHELVES = [(128, 480, 256), (128, 496, 256)]  # (StoreImage 0x80044f44 -> decode at the cut-in): no shelves there
    SHELVES8 = []                     # stage 8 + pal8: no cache (its remainder shelves were in that column too)
if "--vcduo" in sys.argv:             # (2026-11-26) the native Duo cut-in parks its compressed BG image (id >= 1) in VRAM
    SHELVES = [(128, 480, 64), (128, 496, 64)] + SHELVES[2:]   # x192-383 y480-511 (StoreImage 0x80044f44): keep it
TABLES = [SHELVES, SHELVES8]
STAGE_MAP = [0] * 16; STAGE_MAP[8] = 1            # per-stage VRAM budget: stage -> table
PH = 16
NIDX = 256
# state block offsets
CUR, RA, R, HITS, MISS, KEY, ENT, WIN, CNT, NS, FULL, GEN, DIRTY, S2, S3, S4, S5, NEED = (
    0x00, 0x04, 0x08, 0x10, 0x14, 0x18, 0x1c, 0x20, 0x24, 0x28, 0x2c, 0x30, 0x34, 0x38, 0x3c, 0x40, 0x44, 0x48)
VBAD, VOK, VRA, VSKIP, VSZ, VBUF = 0x50, 0x54, 0x58, 0x5c, 0x60, 0x64
MAGIC_OFF, MAGIC = 0x68, 0x34414356   # 'VCA4'
NEXT = 0x6c                           # chain word: next module or the decoder (vmove / fxskip set it)
SKIPMAGIC = 0x504b4356                # 'VCKP': v0 of a chained module that placed the tile in the cell itself at ST + 0x68: the EXE stub only jumps in when it is there
SHP, TT = 0x70, 0x74                  # current shelf table pointer + ring size (per stage, chosen at the first insert)
STSZ = 0x78
# --vxpri (MvC 1.1 Duo; s5 = the drawn object at the decode site): VXS state 0x8000C100 (+0 on, +8 original point, 16 per side); partner = orig +0x2a8
VXPRI_SRC = r"""
        lui   $t5, 0x8001
        lbu   $t6, -0x3f00($t5)
        lw    $t7, -0x3ef8($t5)
        beqz  $t6, 7f
        nop
        lw    $t7, 0x2a8($t7)
        nop
        beq   $t7, $s5, mdone
        nop
7:      lbu   $t6, -0x3ef0($t5)
        lw    $t7, -0x3ee8($t5)
        beqz  $t6, 8f
        nop
        lw    $t7, 0x2a8($t7)
        nop
        beq   $t7, $s5, mdone
        nop
8:
"""
SRC = r"""
        .globl vc
/* ---- entry ---- */
vc:     lui   $t9, %hi(ST)
        lui   $t1, 0x8008
        lbu   $t1, -0x47d8($t1)         /* phase 0x8007b828 */
        addiu $t2, $zero, 8
        beq   $t1, $t2, fight
        lw    $t0, 0x30($s0)
        lw    $t3, %lo(ST+DIRTY)($t9)   /* not fighting: every entry invalid once (cursor + T + 1), normal path */
        lw    $t4, %lo(ST+CUR)($t9)
        beqz  $t3, 1f
        nop
        addiu $t4, $t4, MAXT+1
        sw    $t4, %lo(ST+CUR)($t9)
        sw    $zero, %lo(ST+DIRTY)($t9)
1:      lw    $t1, %lo(ST+NEXT)($t9)    /* chain: next module (vmove / fxskip) or the decoder */
        nop
        jr    $t1
        nop

fight:  lw    $t3, %lo(ST+DIRTY)($t9)
        lui   $t1, 0x8008
        bnez  $t3, 2f
        lbu   $t1, -0x4227($t1)         /* stage 0x8007bdd9 */
        addiu $t2, $zero, 8             /* stage 8 with --pal8 ('PLA8' at P8AT): the fade rows own most */
        bne   $t1, $t2, 4f              /* of the free VRAM -> table 1 (remainder); else table 0 (all 26 KB) */
        move  $t2, $zero
        lui   $t3, %hi(P8AT)
        lw    $t3, %lo(P8AT)($t3)       /* pal8's magic word (its address comes from pal8.code at build time) */
        lui   $t4, 0x3841
        ori   $t4, $t4, 0x4c50
        bne   $t3, $t4, 4f
        nop
        addiu $t2, $zero, 1
4:
        lui   $t3, %hi(TTAB)
        sll   $t2, $t2, 3
        addu  $t3, $t3, $t2
        lw    $t4, %lo(TTAB)($t3)       /* shelf list */
        lw    $t5, %lo(TTAB+4)($t3)     /* T (0: no cache on this stage) */
        lui   $t1, 0x8008
        lbu   $t1, -0x48c0($t1)         /* mode 0x8007b740: 0 ARCADE, 1 VERSUS; other modes (training...) unprobed */
        nop
        sltiu $t1, $t1, 2
        bnez  $t1, 3f
        nop
        move  $t5, $zero
3:      sw    $t4, %lo(ST+SHP)($t9)
        sw    $t5, %lo(ST+TT)($t9)
2:      lw    $t1, 0x44($s0)
        lui   $t2, 0x8009
        lbu   $t1, 0xd($t1)
        lh    $t4, 4($s1)               /* w (halfwords) */
        sll   $t1, $t1, 2
        addu  $t1, $t1, $t2
        lw    $t1, 0x2b30($t1)          /* set pointer */
        lh    $t2, 6($s1)               /* h */
        addu  $t0, $t0, $t1             /* key = stream address */
        slti  $t5, $t2, MAXH+1
        bnez  $t5, 1f
        nop
        lw    $t1, %lo(ST+NEXT)($t9)    /* taller than MAXH: normal path */
        nop
        jr    $t1
        nop
1:
        srl   $t3, $t0, 9
        xor   $t3, $t3, $t0
        srl   $t5, $t0, 18
        xor   $t3, $t3, $t5
@@ASSOC@@
/* ---- hit: pieces slot -> cell ---- */
        sw    $ra, %lo(ST+RA)($t9)
        sw    $s2, %lo(ST+S2)($t9)
        sw    $s3, %lo(ST+S3)($t9)
        sw    $s4, %lo(ST+S4)($t9)
        sw    $s5, %lo(ST+S5)($t9)
        lw    $a0, 4($t3)               /* abs pos */
        move  $s2, $t2                  /* rows left */
        jal   slot                      /* a0 pos -> v0 x | y << 16 */
        move  $s3, $t4                  /* w */
        move  $s4, $v0
        lh    $s5, 2($s1)               /* cell y */
2:      lui   $t9, %hi(ST)
        sw    $s4, %lo(ST+R)($t9)       /* src x, y */
        slti  $t1, $s2, PH
        bnez  $t1, 3f
        move  $t2, $s2
        addiu $t2, $zero, PH
3:      sh    $s3, %lo(ST+R+4)($t9)
        sh    $t2, %lo(ST+R+6)($t9)
        addiu $a0, $t9, %lo(ST+R)
        lh    $a1, 0($s1)
        jal   MOVEIMAGE
        move  $a2, $s5
        addiu $s2, $s2, -PH
        addu  $s4, $s4, $s3
        bgtz  $s2, 2b
        addiu $s5, $s5, PH
.if VERIFY
        jal   verify
        nop
.endif
        lui   $t9, %hi(ST)
        lw    $t0, %lo(ST+HITS)($t9)
        nop
        addiu $t0, $t0, 1
        sw    $t0, %lo(ST+HITS)($t9)
        lw    $s2, %lo(ST+S2)($t9)
        lw    $s3, %lo(ST+S3)($t9)
        lw    $s4, %lo(ST+S4)($t9)
        lw    $s5, %lo(ST+S5)($t9)
        lw    $ra, %lo(ST+RA)($t9)
        nop
        addiu $ra, $ra, 0x50            /* -> 0x8008c624: no LoadImage, no arena advance */
        jr    $ra
        nop

/* ---- miss: decode + LoadImage as the game, then store ---- */
miss:   sw    $ra, %lo(ST+RA)($t9)
        sw    $t0, %lo(ST+KEY)($t9)
        lw    $t1, %lo(ST+NEXT)($t9)
        nop
        jalr  $t1
        sw    $t3, %lo(ST+ENT)($t9)
        lui   $t1, %hi(SKIPMAGIC)       /* the next module put the tile into the cell itself: no LoadImage */
        ori   $t1, $t1, %lo(SKIPMAGIC)
        beq   $v0, $t1, 1f
        nop
        lui   $a1, %hi(ARENA)
        addiu $a1, $a1, %lo(ARENA)
        lw    $v0, 0x68($s0)
        move  $a0, $s1
        jal   LOADIMAGE
        addu  $a1, $a1, $v0
1:      lui   $t9, %hi(ST)
        lw    $t0, %lo(ST+MISS)($t9)
        lh    $t4, 4($s1)               /* w */
        addiu $t0, $t0, 1
        sw    $t0, %lo(ST+MISS)($t9)
        lh    $t2, 6($s1)               /* h */
        nop
        addiu $t1, $t2, PH-1
        srl   $t1, $t1, PHS             /* pieces */
        mult  $t1, $t4
        lw    $a0, %lo(ST+CUR)($t9)     /* abs cursor */
        addiu $t8, $zero, NSH+1         /* tries */
        mflo  $t1                       /* need (columns) */
        sltiu $t3, $t1, MAXSH+1
        beqz  $t3, mdone                /* wider than any shelf: not cached */
        lw    $t3, %lo(ST+TT)($t9)
        nop
        beqz  $t3, mdone                /* no cache area on this stage */
        nop
/* r = abs mod T; shelf with start <= r < end; does need fit before its end?  else skip to the end */
4:      lw    $t3, %lo(ST+TT)($t9)
        lw    $t5, %lo(ST+SHP)($t9)
        divu  $zero, $a0, $t3
        mfhi  $t3                       /* r */
5:      lhu   $t7, 6($t5)
        nop
        sltu  $t6, $t3, $t7
        bnez  $t6, 6f
        nop
        b     5b
        addiu $t5, $t5, 8
6:      addu  $t6, $t3, $t1
        sltu  $t6, $t7, $t6             /* end < r + need */
        beqz  $t6, 7f
        subu  $t6, $t7, $t3
        addiu $t8, $t8, -1
        beqz  $t8, mdone
        nop
        b     4b
        addu  $a0, $a0, $t6             /* skip the shelf rest */
7:      addu  $t3, $a0, $t1
        sw    $t3, %lo(ST+CUR)($t9)
        addiu $t3, $zero, 1
        sw    $t3, %lo(ST+DIRTY)($t9)
        lw    $t3, %lo(ST+ENT)($t9)
        lw    $t0, %lo(ST+KEY)($t9)
        nop
        sw    $t0, 0($t3)
        sw    $a0, 4($t3)
        sw    $s2, %lo(ST+S2)($t9)
        sw    $s3, %lo(ST+S3)($t9)
        sw    $s4, %lo(ST+S4)($t9)
        sw    $s5, %lo(ST+S5)($t9)
        move  $s2, $t2                  /* rows left */
        jal   slot
        move  $s3, $t4                  /* w */
        move  $s4, $v0                  /* slot x | y << 16 */
        lh    $s5, 2($s1)               /* cell y */
9:      lui   $t9, %hi(ST)
        lw    $t0, 0($s1)               /* cell x, y */
        nop
        andi  $t0, $t0, 0xffff
        sll   $t1, $s5, 16
        or    $t0, $t0, $t1
        sw    $t0, %lo(ST+R)($t9)
        slti  $t1, $s2, PH
        bnez  $t1, 8f
        move  $t2, $s2
        addiu $t2, $zero, PH
8:      sh    $s3, %lo(ST+R+4)($t9)
        sh    $t2, %lo(ST+R+6)($t9)
        addiu $a0, $t9, %lo(ST+R)
        andi  $a1, $s4, 0xffff
        jal   MOVEIMAGE
        srl   $a2, $s4, 16
        addiu $s2, $s2, -PH
        addu  $s4, $s4, $s3
        bgtz  $s2, 9b
        addiu $s5, $s5, PH
        lui   $t9, %hi(ST)
        lw    $s2, %lo(ST+S2)($t9)
        lw    $s3, %lo(ST+S3)($t9)
        lw    $s4, %lo(ST+S4)($t9)
        lw    $s5, %lo(ST+S5)($t9)
mdone:  lw    $ra, %lo(ST+RA)($t9)
        nop
        addiu $ra, $ra, 0x18            /* -> 0x8008c5ec: the game's arena advance */
        jr    $ra
        nop
/* ---- slot: a0 = abs position -> v0 = x | y << 16 (t5-t7) ---- */
slot:   lui   $t5, %hi(ST)
        lw    $t6, %lo(ST+TT)($t5)
        lw    $t5, %lo(ST+SHP)($t5)
        divu  $zero, $a0, $t6
        mfhi  $a0
1:      lhu   $t7, 6($t5)
        nop
        sltu  $t6, $a0, $t7
        bnez  $t6, 2f
        nop
        b     1b
        addiu $t5, $t5, 8
2:      lhu   $t6, 4($t5)
        lw    $v0, 0($t5)
        subu  $t6, $a0, $t6
        jr    $ra
        addu  $v0, $v0, $t6

.if VERIFY
/* test only: decode the tile as the game would, StoreImage the cell after the MoveImages, byte compare */
verify: lui   $t9, %hi(ST)
        sw    $ra, %lo(ST+VRA)($t9)
        lw    $t1, %lo(ST+NEXT)($t9)    /* the chain's next module (CHK / decoder), as a miss would */
        lui   $a0, 0x8009
        lw    $a0, 0x2a54($a0)
        jalr  $t1
        lw    $a1, 0x68($s0)
        jal   DRAWSYNC
        move  $a0, $zero
        lh    $t0, 4($s1)
        lh    $t1, 6($s1)
        nop
        mult  $t0, $t1
        lw    $t2, 0x68($s0)
        lui   $t3, %hi(ARENA)
        addiu $t3, $t3, %lo(ARENA)
        mflo  $t4
        sll   $t4, $t4, 1
        lui   $t9, %hi(ST)
        sw    $t4, %lo(ST+VSZ)($t9)
        slt   $t5, $t2, $t4
        beqz  $t5, 1f
        move  $a1, $t3
        addu  $a1, $t3, $t2
        addu  $a1, $a1, $t4
        addiu $a1, $a1, 3
        srl   $a1, $a1, 2
        sll   $a1, $a1, 2
        addu  $t6, $t2, $t4
        addu  $t6, $t6, $t4
        addiu $t6, $t6, 4
        slti  $t6, $t6, 0x2400
        bnez  $t6, 1f
        nop
        lw    $t0, %lo(ST+VSKIP)($t9)
        nop
        addiu $t0, $t0, 1
        b     9f
        sw    $t0, %lo(ST+VSKIP)($t9)
1:      sw    $a1, %lo(ST+VBUF)($t9)
        jal   STOREIMAGE
        move  $a0, $s1
        jal   DRAWSYNC
        move  $a0, $zero
        lui   $t9, %hi(ST)
        lw    $a1, %lo(ST+VBUF)($t9)
        lw    $t4, %lo(ST+VSZ)($t9)
        lw    $t2, 0x68($s0)
        lui   $t3, %hi(ARENA)
        addiu $t3, $t3, %lo(ARENA)
        addu  $t3, $t3, $t2
        move  $t7, $zero
2:      lbu   $t0, 0($a1)
        lbu   $t1, 0($t3)
        addiu $a1, $a1, 1
        addiu $t3, $t3, 1
        addiu $t4, $t4, -1
        beq   $t0, $t1, 3f
        nop
        addiu $t7, $t7, 1
3:      bnez  $t4, 2b
        nop
        lw    $t0, %lo(ST+VBAD)($t9)
        lw    $t1, %lo(ST+VOK)($t9)
        sltu  $t7, $zero, $t7
        addu  $t0, $t0, $t7
        addiu $t1, $t1, 1
        sw    $t0, %lo(ST+VBAD)($t9)
        sw    $t1, %lo(ST+VOK)($t9)
9:      lw    $ra, %lo(ST+VRA)($t9)
        nop
        jr    $ra
        nop
.endif
vc_end:
"""


P8AT = None                                       # set by mktag (--pal8) to pal8's magic word address


OLD_LOOKUP = '        andi  $t3, $t3, NIDX-1\n        sll   $t3, $t3, 3\n        lui   $t5, %hi(IDX)\n        addiu $t5, $t5, %lo(IDX)\n        addu  $t3, $t3, $t5             /* entry */\n        lw    $t5, 0($t3)\n        lw    $t6, 4($t3)               /* abs position */\n        lw    $t7, %lo(ST+CUR)($t9)\n        lw    $t8, %lo(ST+TT)($t9)\n        bne   $t5, $t0, miss\n        subu  $t7, $t7, $t6\n        sltu  $t7, $t8, $t7             /* cur - pos > T: overwritten */\n        bnez  $t7, miss\n        nop\n'
ASSOC_LOOKUP = '        andi  $t3, $t3, NIDX/WAYS-1     /* --vcassoc (dx worker): WAYS-way set, same NIDX entries */\n        sll   $t3, $t3, 3+WAYSH\n        lui   $t5, %hi(IDX)\n        addiu $t5, $t5, %lo(IDX)\n        addu  $t3, $t3, $t5             /* set */\n        lw    $t7, %lo(ST+CUR)($t9)\n        lw    $t8, %lo(ST+TT)($t9)\n        addiu $t1, $zero, WAYS\n        sw    $zero, %lo(ST+NEED)($t9)  /* oldest age so far (victim = largest cur - pos; stale ones first) */\n        sw    $t3, %lo(ST+ENT)($t9)\naw:     lw    $t5, 0($t3)\n        lw    $t6, 4($t3)               /* abs position */\n        nop\n        subu  $t6, $t7, $t6             /* age */\n        bne   $t5, $t0, an\n        sltu  $t5, $t8, $t6             /* cur - pos > T: overwritten */\n        beqz  $t5, ahit\n        nop\nan:     lw    $t5, %lo(ST+NEED)($t9)\n        nop\n        sltu  $t5, $t5, $t6\n        beqz  $t5, ax\n        nop\n        sw    $t6, %lo(ST+NEED)($t9)\n        sw    $t3, %lo(ST+ENT)($t9)\nax:     addiu $t1, $t1, -1\n        bnez  $t1, aw\n        addiu $t3, $t3, 8\n        lw    $t3, %lo(ST+ENT)($t9)     /* victim way for the miss path */\n        b     miss\n        nop\nahit:\n'


def build(base, shelves=None, nidx=NIDX, verify=0, thr=None, ways=1):
    """image at base: state | stage map (16 B) | table list {shelf list, T} | shelf lists | code | index (zero)
    ways > 1 (--vcassoc, dx worker): the index is ways-way set-associative (same nidx entries / RAM)"""
    thr = thr or int(os.environ.get('VC_THR', '8'))
    tables = [shelves] if shelves else TABLES
    smap = bytes(16) if shelves else bytes(STAGE_MAP)
    st = base; stab = st + STSZ; ttab = stab + 16; lists = ttab + 8 * len(tables)
    body = b""; tt = b""; a_ = lists
    for t in tables:
        sh = b""; c = 0
        for x, y, w in t:
            sh += struct.pack("<4H", x, y, c, c + w); c += w
        sh += bytes(8)
        tt += struct.pack("<2I", a_, c); body += sh; a_ += len(sh)
    code_at = a_
    allsh = [sh_ for t in tables for sh_ in t]
    defs = dict(ST=st, STAB=stab, TTAB=ttab, SHELF=lists, NIDX=nidx, DEC=DEC, LOADIMAGE=LOADIMAGE, MOVEIMAGE=MOVEIMAGE, ARENA=ARENA,
                CUR=CUR, RA=RA, R=R, HITS=HITS, MISS=MISS, KEY=KEY, ENT=ENT, WIN=WIN, CNT=CNT, NS=NS, FULL=FULL,
                GEN=GEN, DIRTY=DIRTY, S2=S2, S3=S3, S4=S4, S5=S5, NEED=NEED, IDX=0, NEXT=NEXT, SKIPMAGIC=SKIPMAGIC, SHP=SHP, TT=TT,
                THR=thr, MAXH=int(os.environ.get('VC_MAXH', '128')), PH=PH, PHS=PH.bit_length() - 1, MAXT=4095,
                NSH=max(len(t) for t in tables), MAXSH=max(w for _, _, w in allsh), VERIFY=verify, DRAWSYNC=0x80011864,
                STOREIMAGE=0x80011b70, P8AT=P8AT or (st + NEXT), VBAD=VBAD, VOK=VOK, VRA=VRA, VSKIP=VSKIP, VSZ=VSZ, VBUF=VBUF)
    hdr = smap + tt + body
    src = SRC.replace("@@ASSOC@@", OLD_LOOKUP if ways == 1 else ASSOC_LOOKUP)
    if "--vxpri" in sys.argv:                            # MvC 1.1 Variable Cross: the Duo partner's tiles never stored
        a = "1:      lui   $t9, %hi(ST)\n        lw    $t0, %lo(ST+MISS)($t9)\n"
        assert src.count(a) == 1
        src = src.replace(a, "1:      lui   $t9, %hi(ST)\n" + VXPRI_SRC + "        lw    $t0, %lo(ST+MISS)($t9)\n")
    defs.update(WAYS=ways, WAYSH=ways.bit_length() - 1)
    code, sym = gas(src, code_at, defs)                  # pass 1: code size
    idx = (code_at + len(code) + 7) & ~7
    defs["IDX"] = idx
    code, sym = gas(src, code_at, defs)
    import dlib
    hz = dlib.hazards(code, code_at)
    assert not hz, hz
    state = bytearray(STSZ); struct.pack_into("<2I", state, SHP, *struct.unpack_from("<2I", tt, 0)); struct.pack_into("<I", state, MAGIC_OFF, MAGIC); struct.pack_into("<I", state, NEXT, DEC)
    img = bytes(state) + hdr + code
    img += bytes(idx - base - len(img))
    sym.update(_st=st, _idx=idx, _end=idx + 8 * nidx, _img=len(img))
    return img + bytes(8 * nidx), sym


def install(e, base=0x8000C800, verify=0):
    shl = os.environ.get("VC_SHELVES")
    img, sym = build(base, verify=verify, ways=int(os.environ.get("VC_WAYS", "1")), **({"shelves": [tuple(int(v) for v in x.split(",")) for x in shl.split()]} if shl else {}))
    assert sym["_end"] <= 0x8000DF80 or base > 0x80090000
    e.poke(base, img); e.step(1, "", "")
    e.poke(SITE, struct.pack("<I", 0x0c000000 | (sym["vc"] >> 2 & 0x3ffffff)))
    return sym["_st"]


def vstats(e, st):
    return struct.unpack_from("<4I", e.ram(st + VBAD, 16))


def stats(e, st):
    return struct.unpack_from("<I", e.ram(st + HITS, 4))[0], struct.unpack_from("<I", e.ram(st + MISS, 4))[0]


if __name__ == "__main__":
    img, sym = build(0x80094c40)
    print("image", len(img), "code+tables", sym["_img"], "vc", hex(sym["vc"]), "end", hex(sym["_end"]))
