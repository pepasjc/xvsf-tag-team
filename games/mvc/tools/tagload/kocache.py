"""Free-on-KO tile cache ("kocache", 2026-11-18; v2: lives in the loader's strong payload, for dx09's memory map).

When a character is KO'd (no revive in MvC) and no living object uses its character any more (mirror / shared
characters share one slot: obj+0x73), its sprite file (the tier file tl_main read for that slot) becomes a decoded-tile
cache (index + ring; front end = the old kofe.S, now part of this code and run in place) in front of the strong
decoders (dshptr / dsaptr routes: DSX / DSH1 / DSA1, and whatever front end sits there, e.g. the dx worker's).  From then
on every survivor tile on a slow tier is decoded once and copied afterwards.  No conversion pass, no disc reads in the
fight.

Memory (dx09: the hardware-proven kernel spans are taken by --dxahead): everything sits in the loader's strong payload,
at its end below the meter (KO_AT .. MRAM 0x801fdc00), copied by tl_main every tag battle (per-battle state fresh).
tl_main (blob) only copies the slots' file entries {msf, size} into the payload image (KO_FOFF); the file start is the
slot table entry 0x80092b30[s] - 0x14.

  * KOW (called by the speed meter's RAM part every fighting frame when the word at KO_AT is the magic; the meter stub
    only runs in phase 8 / scene 8, Onslaught battles have no payload): only when tl_dbg[0] == 1.  Object i counts
    frames while life <= 0, inactive (+0 == 0) and benched (+0x2a3 == 1) = the state after the KO hand-over; after HOLD
    frames its slot is released IF NO object with that slot is alive.
  * activation (once per battle): control + index cleared at B = the file start, ring = largest power of 2 that fits,
    the current dshptr / dsaptr become the cache's decoders, the file loader entry 0x80024800 is hooked (j KOR),
    FlushCache, then dshptr / dsaptr -> FE_DSH / FE_DSA (word stores between decodes).
  * KOR (the file loader's entry, only while hooked): at the first file load OUTSIDE the fight (phase != 8) - continue /
    rematch reuse the characters without the tag loader - the loader entry is unhooked + FlushCache, the decoder
    pointers restored, the released file read back (SPARE file entry patched with its msf / size), then the load goes on.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "speed", "frame")]
from gas import gas

MRAM, STRONG_AT = 0x801fdc00, 0x801fd400
MAGIC = 0x314f434b                 # 'KCO1'
TLDBG, DSHPTR, DSAPTR, FLUSH = 0x8001b4e0, 0x8001b4f0, 0x8001b4f4, 0x8001b454
RDF = 0x80024800                   # file loader RD(index, dst); entry words below
RDW = (0x~~~~~~~~, 0x~~~~~~~~)
SPARE = 0x1ab
FTAB_SPARE = 0x800255e4 + 8 * SPARE
PHASE, SLOTS = 0x8007b828, 0x80092b30
HOLD = 150
HSITE = 0x8002b528                # `jal heapcap` (glue.S) at the end of every battle's stage load
IDX, IDXEND = 0x20, 0x4020         # control 0..0x1f, index 2048 x 8 B, ring from IDXEND

SRC = r"""
KO:     .word MAGIC
KOW:    lui   $t0, %hi(TLDBG)
        lbu   $t0, %lo(TLDBG)($t0)
        li    $t1, 1
        bne   $t0, $t1, kret
        lui   $t9, %hi(KD)
        addiu $t9, $t9, %lo(KD)
        lw    $t1, 16($t9)              /* done */
        nop
        bnez  $t1, kret
        move  $t8, $zero
oloop:  sll   $t0, $t8, 2
        lui   $t1, %hi(OBJT)
        addu  $t1, $t1, $t0
        lw    $t2, %lo(OBJT)($t1)
        addu  $t3, $t9, $t0             /* &cnt[i] */
        lh    $t4, 0x294($t2)
        lbu   $t5, 0($t2)
        lbu   $t6, 0x2a3($t2)
        bgtz  $t4, reset
        nop
        bnez  $t5, reset
        nop
        beqz  $t6, reset
        nop
        lw    $t4, 0($t3)
        nop
        addiu $t4, $t4, 1
        sw    $t4, 0($t3)
        sltiu $t5, $t4, HOLD
        bnez  $t5, onext
        nop
        lbu   $t7, 0x73($t2)            /* slot */
        nop
        sltiu $t5, $t7, 4
        beqz  $t5, onext
        sll   $t0, $t7, 2               /* t3 = the slot's sprite set: mirror characters have their own slot */
        lui   $t1, %hi(SLOTS)           /* index but share the file (slot table entries equal) */
        addu  $t1, $t1, $t0
        lw    $t3, %lo(SLOTS)($t1)
        move  $t6, $zero
jloop:  sll   $t0, $t6, 2
        lui   $t1, %hi(OBJT)
        addu  $t1, $t1, $t0
        lw    $t2, %lo(OBJT)($t1)
        nop
        lbu   $t4, 0x73($t2)
        lh    $t5, 0x294($t2)
        sltiu $t0, $t4, 4
        beqz  $t0, jnext
        sll   $t4, $t4, 2
        lui   $t1, %hi(SLOTS)
        addu  $t1, $t1, $t4
        lw    $t4, %lo(SLOTS)($t1)
        nop
        bne   $t4, $t3, jnext           /* another character */
        nop
        bgtz  $t5, onext                /* the same character still alive: keep its data */
        nop
jnext:  addiu $t6, $t6, 1
        sltiu $t0, $t6, 4
        bnez  $t0, jloop
        nop
        sll   $t0, $t7, 3               /* fent[s] */
        addu  $t0, $t0, $t9
        lw    $t2, 32($t0)              /* size */
        sll   $t1, $t7, 2
        beqz  $t2, onext                /* no file for this slot */
        lui   $t4, %hi(SLOTS)
        addu  $t4, $t4, $t1
        lw    $t1, %lo(SLOTS)($t4)
        lui   $t4, %hi(DSHPTR)
        lw    $t5, %lo(DSHPTR)($t4)
        lw    $t6, %lo(DSAPTR)($t4)
        addiu $t1, $t1, -0x14           /* B = the file start */
        beqz  $t5, done1                /* no strong decoder in this battle */
        addiu $t2, $t2, -IDXEND
        bltz  $t2, done1
        lui   $t3, 4                    /* R = 256 KB, halved until it fits */
1:      sltu  $t4, $t2, $t3
        bnez  $t4, 1b
        srl   $t3, $t3, 1
        sll   $t3, $t3, 1
        sltiu $t4, $t3, 0x4000
        bnez  $t4, done1
        nop
        sw    $t7, 20($t9)              /* slot */
        sw    $t1, 24($t9)              /* B = control block */
        move  $t0, $t1
        li    $t4, IDXEND / 4
4:      sw    $zero, 0($t0)
        addiu $t4, $t4, -1
        bnez  $t4, 4b
        addiu $t0, $t0, 4
        lw    $t0, 16($t9)              /* first release only (--ko2: the second instance chains in front) */
        nop
        bnez  $t0, 3f
        lui   $t0, %hi(KS)
        sw    $t6, %lo(KS)($t0)         /* the battle's own decoders, kept in kernel RAM (freeze worker 2026-11-19) */
        sw    $t5, %lo(KS + 4)($t0)
        lui   $t4, 0x8008               /* the battle's TEAM (0x8007b8aa, 4 x u16) + stage (0x8007bdd9) -> KT: KOR */
        lbu   $t2, -0x4227($t4)         /* reads the file back only for the same battle (rematch / continue), */
        addiu $t4, $t4, -0x4756         /* never into an unrelated load (integrator, 2026-11-19) */
        lui   $t0, %hi(KT)
        addiu $t0, $t0, %lo(KT)
        sh    $t2, 8($t0)
        li    $t8, 4
7:      lhu   $t2, 0($t4)
        addiu $t4, $t4, 2
        addiu $t8, $t8, -1
        sh    $t2, 0($t0)
        bnez  $t8, 7b
        addiu $t0, $t0, 2
3:
        sw    $t3, 4($t1)               /* R */
        sw    $t6, 24($t1)              /* DSA decoder */
        sw    $t5, 28($t1)              /* DSH / DSX decoder */
        lui   $t0, %hi(HSITE)           /* battle-load hook: jal heapcap -> jal KOR */
        lw    $t2, %lo(HSITE)($t0)
        lui   $t4, %hi(KHOOK)
        addiu $t4, $t4, %lo(KHOOK)
        sw    $t2, 60($t9)
        sw    $t4, %lo(HSITE)($t0)
        addiu $sp, $sp, -24
        sw    $ra, 16($sp)
        jal   FLUSH
        nop
        lw    $ra, 16($sp)
        addiu $sp, $sp, 24
        lui   $t9, %hi(KD)
        addiu $t9, $t9, %lo(KD)
        lw    $t1, 24($t9)
        lui   $t4, %hi(DSHPTR)
        lw    $t6, 24($t1)
        lui   $t0, %hi(FE_DSH)
        addiu $t0, $t0, %lo(FE_DSH)
        sw    $t0, %lo(DSHPTR)($t4)
        lui   $t0, %hi(FE_DSA)
        beqz  $t6, done1
        addiu $t0, $t0, %lo(FE_DSA)
        sw    $t0, %lo(DSAPTR)($t4)
done1:  li    $t0, 1
        b     kret
        sw    $t0, 16($t9)
reset:  sw    $zero, 0($t3)
onext:  addiu $t8, $t8, 1
        sltiu $t0, $t8, 4
        bnez  $t0, oloop
        nop
kret:   jr    $ra
        nop

/* ---- the next battle load (0x8002b528 `jal heapcap`, end of the stage load; every battle: rematch, challenger,
   next match, tag or not) while hooked: unhook, decoders back, the released file read back unless the new stage
   pool reaches into it (hcguard then makes the character loader reload anyway), then heapcap(a0, a1) ---- */
KOR:    addiu $sp, $sp, -48
        sw    $ra, 16($sp)
        sw    $a0, 20($sp)
        sw    $a1, 24($sp)
        lui   $t9, %hi(KD)
        addiu $t9, $t9, %lo(KD)
        lw    $t1, 60($t9)              /* the stock word */
        lui   $t0, %hi(HSITE)
        sw    $t1, %lo(HSITE)($t0)
        jal   FLUSH
        sw    $t1, 36($sp)
        lui   $t9, %hi(KD)
        addiu $t9, $t9, %lo(KD)
        lw    $a1, 24($t9)              /* B = file start = control block */
        lw    $t1, 20($t9)              /* slot */
        lui   $t2, %hi(KS)
        lw    $t3, %lo(KS)($t2)         /* decoders from kernel RAM (the control block may be reused memory) */
        lw    $t2, %lo(KS + 4)($t2)
        lui   $t5, %hi(DSHPTR)
        sw    $t2, %lo(DSHPTR)($t5)     /* decoders back */
        sw    $t3, %lo(DSAPTR)($t5)
        sw    $zero, 16($t9)            /* re-armed */
        lui   $t5, 0x8008               /* same team + stage as the released battle? else no read-back */
        lbu   $t2, -0x4227($t5)
        lui   $t6, %hi(KT)
        addiu $t6, $t6, %lo(KT)
        lhu   $t3, 8($t6)
        addiu $t5, $t5, -0x4756
        bne   $t2, $t3, kskip
        li    $t4, 4
8:      lhu   $t2, 0($t5)
        lhu   $t3, 0($t6)
        addiu $t5, $t5, 2
        addiu $t6, $t6, 2
        bne   $t2, $t3, kskip
        addiu $t4, $t4, -1
        bnez  $t4, 8b
        nop
        lw    $a0, 20($sp)
        lw    $t0, 24($sp)
        nop
        addu  $t0, $a0, $t0             /* new stage pool end */
        sltu  $t0, $a1, $t0
        bnez  $t0, kskip
        sll   $t4, $t1, 3
        addu  $t4, $t4, $t9
        lw    $t6, 28($t4)              /* msf */
        lw    $t7, 32($t4)              /* size */
        lui   $t8, %hi(FTAB_SPARE)
        lw    $t2, %lo(FTAB_SPARE)($t8)
        lw    $t3, %lo(FTAB_SPARE + 4)($t8)
        sw    $t6, %lo(FTAB_SPARE)($t8)
        sw    $t7, %lo(FTAB_SPARE + 4)($t8)
        sw    $t2, 28($sp)
        sw    $t3, 32($sp)
        addu  $t0, $a1, $t7             /* the read writes whole sectors: save what lies after the file end */
        srl   $t0, $t0, 2               /* (the next item's live data) in the tile arena, free during loads */
        sll   $t0, $t0, 2
        sw    $t0, 40($sp)
        lui   $t4, %hi(TARENA)
        addiu $t4, $t4, %lo(TARENA)
        li    $t5, 513
5:      lw    $t6, 0($t0)
        addiu $t5, $t5, -1
        sw    $t6, 0($t4)
        addiu $t0, $t0, 4
        bnez  $t5, 5b
        addiu $t4, $t4, 4
        jal   RDF
        li    $a0, SPARE
        lw    $t2, 28($sp)
        lw    $t3, 32($sp)
        lui   $t8, %hi(FTAB_SPARE)
        sw    $t2, %lo(FTAB_SPARE)($t8)
        sw    $t3, %lo(FTAB_SPARE + 4)($t8)
        lw    $t0, 40($sp)
        lui   $t4, %hi(TARENA)
        addiu $t4, $t4, %lo(TARENA)
        li    $t5, 513
6:      lw    $t6, 0($t4)
        addiu $t5, $t5, -1
        sw    $t6, 0($t0)
        addiu $t4, $t4, 4
        bnez  $t5, 6b
        addiu $t0, $t0, 4
kskip:  lw    $t1, 36($sp)
        lw    $ra, 16($sp)
        lw    $a0, 20($sp)
        lw    $a1, 24($sp)
        sll   $t1, $t1, 6               /* jal target */
        srl   $t1, $t1, 4
        lui   $t2, 0x8000
        or    $t1, $t1, $t2
        jr    $t1
        addiu $sp, $sp, 48

/* ---- front end bypass outside the battle scene (shared by --ko2's second front end): v1 = 24 (DSA) / 28 (DSH) ->
   the decoder saved at KS + 0 / + 4 */
kbyp:   lui   $t9, %hi(KS - 24)
        addu  $t9, $t9, $v1
        lw    $t9, %lo(KS - 24)($t9)
        nop
        jr    $t9
        nop

/* ---- decoded-tile cache front end (was kofe.S / fecache.S; runs in place, control block pointer = KD+24):
   B+0 A  +4 R  +8 ra  +12 src  +16 dst  +20 n  +24 DSA1 decoder  +28 DSH1 / DSX decoder
   B+IDX index 2048 x {src, A}   B+IDXEND ring entries {src, n, data rounded up to 4} ---- */
FE_DSH: lui   $t6, %hi(KD + 24)
        lw    $t6, %lo(KD + 24)($t6)
        b     fe0
        ori   $v1, $zero, 28
FE_DSA: lui   $t6, %hi(KD + 24)
        lw    $t6, %lo(KD + 24)($t6)
        ori   $v1, $zero, 24
fe0:    lui   $t9, 0x8008
        lbu   $t9, -0x4234($t9)         /* scene 0x8007bdcc */
        addu  $at, $t6, $v1
        xori  $t9, $t9, 8
        bnez  $t9, kbyp                 /* not the battle scene: the file may be reused memory */
        nop
        lw    $t9, 0($at)               /* the real decoder */
        sltiu $at, $a2, 4097
        beqz  $at, go                   /* big decodes are not cached */
        srl   $t0, $a0, 2
        srl   $t1, $a0, 11
        xor   $t0, $t0, $t1
        andi  $t0, $t0, 2047
        sll   $t0, $t0, 3
        addu  $t0, $t0, $t6
        lw    $t1, IDX($t0)             /* key */
        lw    $t2, IDX+4($t0)           /* pos */
        bne   $t1, $a0, miss
        lw    $t3, 0($t6)               /* A */
        lw    $t4, 4($t6)               /* R */
        subu  $t3, $t3, $t2
        sltu  $at, $t4, $t3
        bnez  $at, miss                 /* overwritten since */
        addiu $t4, $t4, -1
        and   $t2, $t2, $t4
        addu  $t2, $t2, $t6
        lw    $t1, IDXEND($t2)          /* entry src */
        lw    $t5, IDXEND+4($t2)        /* entry n */
        bne   $t1, $a0, miss
        addiu $t3, $a2, 3
        bne   $t5, $a2, miss
        srl   $t3, $t3, 2               /* words */
        addiu $t2, $t2, IDXEND+8
2:      lw    $t1, 0($t2)               /* hit: copy (dst any alignment) */
        addiu $t3, $t3, -1
        swl   $t1, 3($a1)
        swr   $t1, 0($a1)
        addiu $t2, $t2, 4
        bnez  $t3, 2b
        addiu $a1, $a1, 4
        jr    $ra
        nop
go:     jr    $t9
        nop
miss:   sw    $ra, 8($t6)
        sw    $a0, 12($t6)
        sw    $a1, 16($t6)
        jalr  $t9
        sw    $a2, 20($t6)
        lui   $t6, %hi(KD + 24)
        lw    $t6, %lo(KD + 24)($t6)
        nop
        lw    $a0, 12($t6)
        lw    $a1, 16($t6)
        lw    $a2, 20($t6)
        lw    $t3, 0($t6)               /* A */
        lw    $t4, 4($t6)               /* R */
        addiu $t5, $a2, 11
        srl   $t5, $t5, 2
        sll   $t5, $t5, 2               /* L = 8 + n rounded up to 4 */
        addiu $t1, $t4, -1
        and   $t0, $t3, $t1             /* ring offset */
        addu  $t2, $t0, $t5
        sltu  $at, $t4, $t2
        beqz  $at, 4f
        srl   $t2, $a0, 2
        or    $t3, $t3, $t1             /* would cross the end: next lap */
        addiu $t3, $t3, 1
        move  $t0, $zero
4:      srl   $t7, $a0, 11
        xor   $t2, $t2, $t7
        andi  $t2, $t2, 2047
        sll   $t2, $t2, 3
        addu  $t2, $t2, $t6
        sw    $a0, IDX($t2)
        sw    $t3, IDX+4($t2)
        addu  $t0, $t0, $t6
        sw    $a0, IDXEND($t0)
        sw    $a2, IDXEND+4($t0)
        addu  $t3, $t3, $t5
        sw    $t3, 0($t6)               /* A += L */
        addiu $t0, $t0, IDXEND+8
        addiu $t5, $t5, -8
5:      lwl   $t1, 3($a1)               /* store the decoder's output */
        lwr   $t1, 0($a1)
        addiu $t5, $t5, -4
        sw    $t1, 0($t0)
        addiu $a1, $a1, 4
        bnez  $t5, 5b
        addiu $t0, $t0, 4
        lw    $ra, 8($t6)
        nop
        jr    $ra
        nop

        .align 2
OBJT:   .word 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~
/* data: cnt[4] +0, done +16, slot +20, B +24, fent[4] {msf, size} +28 (tl_main writes it) */
KD:     .word 0, 0, 0, 0, 0, 0, 0
KF:     .word 0, 0, 0, 0, 0, 0, 0, 0
KH:     .word 0                         /* +60: the stock word at HSITE while hooked */
KS:     .word 0, 0                      /* the battle's DSA1 / DSH1 decoders at the first release (KOR, FE outside scene 8) */
KT:     .word 0, 0, 0                   /* the released battle's TEAM (4 x u16) + stage: KOR's same-battle check */
KEND:
"""


def _src():
    """SRC, or with the dx worker's extensions (tools/speed4/kox.py) when --koahead / --ko2 are on; --koreload (memory
    worker, tools/koreload): KOW's exit tail-calls krl_frame (same instruction count)"""
    src = _src0()
    if "--koreload" in sys.argv:
        old, new = "kret:   jr    $ra", "kret:   j     KRLF"
        assert src.count(old) == 1
        src = src.replace(old, new)
    return src


def _src0():
    ka, k2, kc = "--koahead" in sys.argv, "--ko2" in sys.argv, "--koconv" in sys.argv
    if not (ka or k2 or kc): return SRC
    sys.path.insert(0, os.path.join(GAME, "tools", "speed4"))
    import kox
    return kox.transform(SRC, ka, k2, kc)


def _asm(at):
    SRC = _src()
    syms = {"MBX": 0x8000FC70, "MAGIC": MAGIC, "TLDBG": TLDBG, "DSHPTR": DSHPTR, "DSAPTR": DSAPTR, "FLUSH": FLUSH, "RDF": RDF, "RDW0": RDW[0],
            "RDW1": RDW[1], "SPARE": SPARE, "FTAB_SPARE": FTAB_SPARE, "PHASE": PHASE, "HSITE": HSITE, "TARENA": 0x80092c40, "SLOTS": SLOTS, "HOLD": HOLD,
            "IDX": IDX, "IDXEND": IDXEND}
    if "--koreload" in sys.argv:                 # tools/koreload: resident krl_frame (fixed address)
        sys.path.insert(0, os.path.join(GAME, "tools", "koreload"))
        import build as krlbuild
        syms["KRLF"] = krlbuild.image()[1]["krl_frame"]
    if "--koconv" in sys.argv:                   # dx worker's converter (tools/speed4/kox.py, koconv.S): FRAME SKIP restore
        import kox
        syms.update(FSSAVE=kox.FSSAVE, FSB=kox.fsb())
    c0, s0 = gas((SRC.replace("bnez  $t0, kskip", "b     kskip") if os.environ.get("KO_NOREAD") else SRC).replace("%hi(KHOOK)", "0").replace("%lo(KHOOK)", "0"), at, syms)
    syms["KHOOK"] = 0x0c000000 | (s0["KOR"] >> 2 & 0x3ffffff)
    src = SRC.replace("bnez  $t0, kskip", "b     kskip") if os.environ.get("KO_NOREAD") else SRC   # TEST only
    code, sym = gas(src, at, syms)
    assert len(code) == sym["KEND"] - at and sym["KF"] == sym["KD"] + 28 and sym["KH"] == sym["KD"] + 60
    return code, sym


KO_AT = 0x8000F040                 # kernel span left to kocache by the dx worker (TAGLOAD.md 2026-11-18 21:55; dx10 map)
SIZE = (len(_asm(KO_AT)[0]) + 7) & ~7
assert KO_AT + SIZE <= 0x8000F840      # dx state from 0x8000F840


def build():
    code, sym = _asm(KO_AT)
    assert len(code) <= SIZE and sym["KO"] == KO_AT
    import importlib.util
    spec = importlib.util.spec_from_file_location("dlib", os.path.join(ROOT, "tools", "speed", "decode", "dlib.py"))
    dl = importlib.util.module_from_spec(spec); spec.loader.exec_module(dl)
    hz = dl.hazards(code[4:sym["OBJT"] - KO_AT], KO_AT + 4)
    assert not hz, hz
    return code + bytes(SIZE - len(code)), sym


def sector():
    code, sym = build()
    return code + bytes(2048 - len(code))


def header(msf):
    code, sym = build()
    return "#define KO_AT 0x%08xu\n#define KO_MSF 0x%08xu\n#define KO_SIZE %d\n#define KO_FOFF %d\n" % (KO_AT, msf, len(code), sym["KF"] - KO_AT)


if __name__ == "__main__":
    c, s = build()
    print("kocache %d B at %08x-%08x (KOW %08x KOR %08x FE_DSH %08x FE_DSA %08x KD %08x KF %08x)" % (
        len(c), KO_AT, MRAM, s["KOW"], s["KOR"], s["FE_DSH"], s["FE_DSA"], s["KD"], s["KF"]))
