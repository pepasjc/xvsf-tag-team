"""SPU store RAM front end (mktag.py --spustore): sits in dshptr in front of the DSH1/DSX decoder.

The tag loader turns table entries of tiles stored in SPU RAM into proxies  src = 0x80210000 + (class << 16 | spu >> 3), class 0-7 = 1,2,3,4,6,8,16,32 x 64 B; offset < 2 MB (--chk owns bit 21)
(never a RAM address).  Decoder slot 11 (0x80092b5c, unused by the game in every mode) holds a fake 'DSH1' section at
FAKE = 0x8020F700 (the 2 MB RAM mirror of DATA; the loader also writes it there for 8 MB machines) whose size reaches
0x81000000, so the stock dispatch (common/dsp/dsmdec.S) routes exactly the proxies here (a3 = FAKE):

    a3 != FAKE              -> j saved decoder (unchanged path; 3 instructions)
    a3 == FAKE, proxy       -> owner slot by SPU address, SPU DMA (libspu's register sequence) of len64 * 64 bytes
                               into the staging buffer, a0 = staging, a3 = owner's section, j saved decoder
    a3 == FAKE, no proxy / no owner -> error count, return (dst untouched)

DATA (0x8000FF40): +0 'DSH1' +4 size +8 saved decoder +12 staging +16 fetches +20 bytes +24 errors +28 bytes stored
                   +32 owners[4] {spu_lo, spu_hi, section, streams}
Data in the hardware-proven kernel span 0x8000F040-0x8000FFE0 (TAGLOAD.md), after kocache (F040-F557) and the dx
state (F840-FF28).  Code (position-independent) in the loader region right after the staging buffer.
Caller-saved registers only, no stack.
    header(path)  -> writes spsfe.h for tagload.c
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "speed", "frame"), os.path.join(ROOT, "tools", "speed", "decode")]
from gas import gas

AT, DATA, FAKE, WB = 0x80100000, 0x8000FF40, 0x8020FF40, 0x80210000   # AT: any (position-independent; checked)
SRC = r"""
fe:     lui   $t0, %hi(FAKE)
        addiu $t0, $t0, %lo(FAKE)
        bne   $a3, $t0, real
        lui   $t1, %hi(WB)
        sltu  $t1, $a0, $t1
        bnez  $t1, err
        andi  $t3, $a0, 0xffff
        sll   $t3, $t3, 3                /* SPU address */
        lui   $t4, %hi(DATA + 32)
        addiu $t4, $t4, %lo(DATA + 32)
        li    $t5, 4
1:      lw    $t6, 0($t4)
        lw    $t7, 4($t4)
        sltu  $t8, $t3, $t6
        bnez  $t8, 2f
        sltu  $t8, $t3, $t7
        bnez  $t8, 3f
        nop
2:      addiu $t5, $t5, -1
        bnez  $t5, 1b
        addiu $t4, $t4, 16
err:    lui   $t0, %hi(DATA)
        lw    $t1, %lo(DATA + 24)($t0)
        nop
        addiu $t1, $t1, 1
        jr    $ra
        sw    $t1, %lo(DATA + 24)($t0)
3:      lui   $t2, %hi(WB)
        subu  $t2, $a0, $t2
        srl   $t2, $t2, 16           /* length class 0..7 */
        lui   $t7, %hi(DATA + 0x60)
        addu  $t7, $t7, $t2
        lbu   $t2, %lo(DATA + 0x60)($t7)   /* 64-byte blocks */
        nop
        lui   $t0, 0x1f80
FIXBUSY
        lw    $t9, 0x1014($t0)           /* SPU memory delay: libspu sets 0x22xxxxxx for DMA reads */
        lui   $t8, 0xf0ff
        ori   $t8, $t8, 0xffff
        and   $t8, $t9, $t8
        lui   $t7, 0x2200
        or    $t8, $t8, $t7
        sw    $t8, 0x1014($t0)
        lhu   $t1, 0x1daa($t0)           /* SPUCNT (restored at the end) */
FIXSAVE
        srl   $t6, $t3, 3
        sh    $t6, 0x1da6($t0)           /* transfer address / 8 */
        andi  $t6, $t1, 0xffcf
        ori   $t6, $t6, 0x30             /* DMA read */
        sh    $t6, 0x1daa($t0)
        andi  $t6, $t6, 0x3f
4:      lhu   $t7, 0x1dae($t0)           /* SPUSTAT mode bits follow SPUCNT */
        nop
        andi  $t7, $t7, 0x3f
        bne   $t7, $t6, 4b
        nop
        lui   $t7, %hi(DATA)
        lw    $a0, %lo(DATA + 12)($t7)   /* staging buffer */
        nop
FIXDICR0
        sw    $a0, 0x10c0($t0)           /* DMA4 MADR */
        sll   $t7, $t2, 16
        ori   $t7, $t7, 0x10
        sw    $t7, 0x10c4($t0)           /* BCR: blocks x 16 words */
        lui   $t7, 0x0100
        ori   $t7, $t7, 0x0200
        sw    $t7, 0x10c8($t0)           /* CHCR: SPU -> RAM, sync mode 1, start */
        lui   $t8, 0x0100
5:      lw    $t7, 0x10c8($t0)
        nop
        and   $t7, $t7, $t8
        bnez  $t7, 5b
        nop
FIXDICR1
        sh    $t1, 0x1daa($t0)
FIXREST
        sw    $t9, 0x1014($t0)
        lui   $t7, %hi(DATA)
        lw    $t6, %lo(DATA + 16)($t7)
        lw    $t5, %lo(DATA + 20)($t7)
        addiu $t6, $t6, 1
        sll   $t2, $t2, 6
        addu  $t5, $t5, $t2
        sw    $t6, %lo(DATA + 16)($t7)
        sw    $t5, %lo(DATA + 20)($t7)
        lw    $a3, 8($t4)                /* owner's section */
RLEJUMP
real:   lui   $t9, %hi(DATA)
        lw    $t9, %lo(DATA + 8)($t9)    /* saved decoder */
        nop
        jr    $t9
        nop
end:
"""

# dshptr target: a kernel-RAM trampoline (persistent across scenes).  Ordinary decodes (a3 != FAKE) go straight to
# the saved decoder; only proxies (in-battle only) go to the region front end.  After the battle the region is reused
# (results screen GPU packets, CPU worker 2026-11-19 17:45), but nothing reaches it any more.
TRAMP = DATA + 0x6c                              # DATA+0x60 block table (8 B), +0x68 front-end address
TSRC = r"""
tr:     lui   $t0, %hi(FAKE)
        addiu $t0, $t0, %lo(FAKE)
        bne   $a3, $t0, 1f
        lui   $t9, %hi(DATA)
        lw    $t9, %lo(DATA + 0x68)($t9)   /* front end (proxy path) */
        nop
        jr    $t9
        nop
1:      lw    $t9, %lo(DATA + 8)($t9)      /* saved decoder */
        nop
        jr    $t9
        nop
tend:
"""


# --spsfix (rc4, Onslaught-ending freeze): a fetch must never touch the SPU while the game's own SPU DMA runs (dxahead
# decodes stale proxies during the next battle's load in scene 8 -> the fetch's DMA read cut the COMMON upload after
# ~8 KB -> RAM table and SPU COMMON at different sound levels -> a looping voice in the ending): DMA4 busy -> error
# return (no fetch); the SPU transfer address register is put back after the fetch.
FIX = {"FIXBUSY": """        lw    $t7, 0x10c8($t0)           /* DMA4 CHCR: the game's own SPU transfer in flight -> no fetch */
        lui   $t6, 0x0100
        and   $t7, $t7, $t6
        bnez  $t7, err
        nop""",
       "FIXSAVE": """        lhu   $t5, 0x1da6($t0)           /* the game's transfer address (put back below) */""",
       "FIXREST": """        sh    $t5, 0x1da6($t0)""",
       # the root cause (2026-11-20): libspu waits for its "SPU transfer done" BIOS event (TestEvent 0xF1000000),
       # raised by the DMA4 IRQ; our raw DMA4 raised it too -> the game's next SpuRead / SpuWrite saw a stale event,
       # returned while its DMA still ran, and the following transfer cut it short (COMMON uploads, sound list reads,
       # kind-6 set reads).  No IRQ for our DMA: ch4 enable (DICR bit 20) off, then flag 28 acked and enable back.
       "FIXDICR0": """        lw    $t7, 0x10f4($t0)           /* DICR: DMA4 IRQ off for our transfer (flags not acked) */
        lui   $t6, 0x00ef
        ori   $t6, $t6, 0xffff
        and   $t7, $t7, $t6
        sw    $t7, 0x10f4($t0)""",
       "FIXDICR1": """        lw    $t7, 0x10f4($t0)           /* DICR: ack DMA4's flag, DMA4 IRQ back on */
        lui   $t6, 0x00ff
        ori   $t6, $t6, 0xffff
        and   $t7, $t7, $t6
        lui   $t6, 0x1010
        or    $t7, $t7, $t6
        sw    $t7, 0x10f4($t0)"""}


# --asrle (asdip lead, rc4.6): an owner whose section word has bit 0 set holds RLE streams (assist RLE tier in SPU):
# after the fetch, a0 = staging -> the game's byte RLE decoder (dsmdec.S label rle, fixed address in the entry unit)
RLEJ = """        nop
        andi  $t7, $a3, 1
        beqz  $t7, real
        lui   $t9, %hi(RLE)
        addiu $t9, $t9, %lo(RLE)
        jr    $t9
        nop"""


# --asgov (asdip lead, rc4.7): assist draw governor, appended to this (position-independent) block.  The loader calls
# gvinst once after copying the block: the 6 object-draw call sites (jal 0x8008f1f4, tools/speed/fxscan.py DRAWS) ->
# jal gov.  gov, for the two assist objects (*(P1 / P2 main + 0x2f0)) only: when the picture changes and the frame has
# fewer than GOVLIM hblank lines left before the next vblank (dxahead DXV stamp) or the other assist decoded in this
# loop, the object is drawn once more with the picture it showed in the previous loop (VRAM cell cache: no decode) and
# its group is put back right after the draw (logic, hit boxes untouched).  Never two loops in a row, never on the first
# frame of a call (not drawn in the previous loop).  Battle phase 0x8007b828 > 8 or scene != 8 (battle over /
# interrupted): the sites
# go back to stock (+ FlushCache) at that first draw, before anything can reuse the region.
GDRAW, GSITES = 0x8008f1f4, (0x80047d98, 0x80047e3c, 0x80047ea8, 0x80047eec, 0x80047f58, 0x800906d0)
GSTAMP = 0x8000FC5C                              # dxahead DBG + 28: hblank counter 1 at the last VSync(0) return
GOVLIM = int(os.environ.get("ASGOV_LIM", "120"))
GOV = r"""
gvinst: addiu $sp, $sp, -24
        sw    $ra, 16($sp)
        bal   1f
        nop
1:      addiu $t0, $ra, gov - 1b
        sll   $t0, $t0, 4
        srl   $t0, $t0, 6                       /* jal target field */
        lui   $t1, 0x0c00
        or    $t1, $t1, $t0                     /* jal gov */
        addiu $t2, $ra, gvst - 1b
        li    $t3, 24
2:      sw    $zero, 0($t2)
        addiu $t3, $t3, -1
        bnez  $t3, 2b
        addiu $t2, $t2, 4
SITESW
        li    $t2, 0xa0
        jalr  $t2                               /* FlushCache */
        li    $t1, 0x44
        lw    $ra, 16($sp)
        nop
        jr    $ra
        addiu $sp, $sp, 24
gov:    lui   $t0, 0x8008
        lbu   $t1, -0x47d8($t0)                 /* battle phase 0x8007b828 */
        lbu   $t3, -0x4234($t0)                 /* scene 0x8007bdcc */
        li    $t2, 8
        bne   $t3, $t2, gvoff                   /* left the battle scene */
        sltu  $t3, $t2, $t1
        bnez  $t3, gvoff                        /* battle over (phase > 8) */
        nop
        bne   $t1, $t2, gvdraw                  /* intro phases: stock draw */
        nop
        lw    $t1, -0x3e80($t0)                 /* *(P1 main 0x8007be90 + 0x2f0) */
        lw    $t2, -0x3a70($t0)                 /* *(P2 main 0x8007c2a0 + 0x2f0) */
        beq   $a0, $t1, 1f
        move  $t3, $zero
        beq   $a0, $t2, 1f
        li    $t3, 32
gvdraw: j     GDRAW
        nop
1:      move  $t9, $ra
        bal   2f
        nop
2:      addiu $t4, $ra, gvst - 2b
        move  $ra, $t9
        move  $t9, $t4                          /* state base (+64: loop of the last assist decode) */
        addu  $t4, $t4, $t3
        lhu   $t5, 0x3c($a0)                    /* group to show */
        lw    $t6, 0($t4)                       /* group drawn last */
        lw    $t7, 4($t4)                       /* loop of the last draw */
        lw    $t8, -0x48b4($t0)                 /* loop counter 0x8007b74c */
        lw    $t1, 8($t4)                       /* deferred last time */
        sw    $t8, 4($t4)
        beq   $t5, $t6, gvdraw                  /* same picture: the cached draw anyway */
        addiu $t7, $t7, 1
        bne   $t7, $t8, gvdec                   /* not drawn in the previous loop: decode */
        nop
        bnez  $t1, gvdec                        /* deferred once already: decode now */
        nop
        lw    $t1, 64($t9)                      /* loop in which an assist decoded */
        nop
        beq   $t1, $t8, gvdef
        nop
        lui   $t1, 0x1f80
        lhu   $t1, 0x1110($t1)
        lui   $t2, %hi(GSTAMP)
        lw    $t2, %lo(GSTAMP)($t2)
        nop
        sltu  $t3, $t1, $t2
        bnez  $t3, 3f
        addiu $t1, $t1, 2
        addiu $t1, $t1, -2
        subu  $t1, $t1, $t2
3:      li    $t2, 263
4:      sltu  $t3, $t1, $t2
        bnez  $t3, 5f
        nop
        b     4b
        subu  $t1, $t1, $t2
5:      subu  $t1, $t2, $t1                     /* lines left before the next vblank */
        sltiu $t1, $t1, GOVLIM
        bnez  $t1, gvdef
        nop
gvdec:  sw    $t5, 0($t4)
        sw    $zero, 8($t4)
        b     gvdraw
        sw    $t8, 64($t9)
gvdef:  li    $t1, 1
        sw    $t1, 8($t4)
        addiu $sp, $sp, -24
        sw    $ra, 16($sp)
        sw    $a0, 20($sp)
        sh    $t6, 0x3c($a0)                    /* the previous loop's picture (cell cache) */
        jal   GDRAW
        sw    $t5, 12($sp)
        lw    $a0, 20($sp)
        lw    $t5, 12($sp)
        lw    $ra, 16($sp)
        sh    $t5, 0x3c($a0)                    /* the animation's group back */
        jr    $ra
        addiu $sp, $sp, 24
gvoff:  lui   $t1, 0x0c02
        ori   $t1, $t1, 0x3c7d                  /* jal 0x8008f1f4: the sites back to stock */
SITESR
        addiu $sp, $sp, -24
        sw    $ra, 16($sp)
        sw    $a0, 20($sp)
        li    $t2, 0xa0
        jalr  $t2                               /* FlushCache */
        li    $t1, 0x44
        lw    $a0, 20($sp)
        lw    $ra, 16($sp)
        b     gvdraw
        addiu $sp, $sp, 24
gvst:   .space 96
"""


def _sites():
    out = []
    for a in GSITES: out += ["        lui   $t2, 0x%04x" % ((a + 0x8000) >> 16 & 0xffff), "        sw    $t1, %d($t2)" % ((a & 0xffff) - (0x10000 if a & 0x8000 else 0))]
    return chr(10).join(out)


def src(fix, rle=None, gov=False):
    t = SRC
    for k, v in FIX.items(): t = t.replace(k, v if fix else "")
    if gov: t = t.replace(chr(10) + "end:", GOV.replace("SITESW", _sites()).replace("SITESR", _sites()) + chr(10) + "end:")
    t = t.replace("RLEJUMP", RLEJ if rle else "")
    # --spsfifo (2026-11-25, MiSTer 2 MB freeze): the MiSTer PSX core fills its SPU read FIFO continuously in transfer
    # mode 3 and clears it ONLY on a mode 11 -> 00 change (not on entering mode 3, not on a new transfer address), so
    # after a read the prefetched tail stays and the NEXT read's first block is stale data from the old address ->
    # garbage tile -> decoder crash.  Here: 11 -> 00 before setting the address (drops what any earlier SpuRead left)
    # and 11 -> 00 after the DMA (drops our own tail) before SPUCNT is restored.  A real SPU just sees two extra mode
    # writes (stop, set read, stop) around the same transfer.
    if "--spspost" in sys.argv:                     # (2026-11-25) MiSTer core: DMA4 SPU -> RAM reports done when its RAM-side
        n = chr(10)                                 # FIFO is NEAR empty: the last words may reach the staging buffer after
        k = "        bnez  $t7, 5b" + n + "        nop" + n   # CHCR clears -> short fixed wait before anything reads it
        assert t.count(k) == 1, "spspost: DMA loop site"
        t = t.replace(k, k + "        li    $t7, %d" % int(os.environ.get("SPS_SPIN", "256")) + n + "pw1:    addiu $t7, $t7, -1" + n + "        bnez  $t7, pw1" + n + "        nop" + n)
    # --spssent (2026-11-25) HARMFUL ON THE MiSTer, do not ship: mvc_1_0t froze 3/3 (a CPU store into the DMA destination can
    # land in SDRAM after the DMA words there).  Kept for the record.  Idea: before the DMA the last two
    # words of the staging destination get two different sentinels; after the CHCR done-poll we wait (bounded, 65536
    # polls in all) until both changed.  DMA4 writes in order, so the last word landing means the whole tile landed.
    # A real PS1 (and Beetle) has the data in RAM when CHCR clears: both compares succeed at once.  t3 (dead after the
    # SPU address) = end of the transfer, kept across the DMA.
    if "--spssent" in sys.argv:
        n = chr(10)
        k = "        lw    $a0, %lo(DATA + 12)($t7)   /* staging buffer */" + n + "        nop" + n
        assert t.count(k) == 1, "spssent: staging site"
        t = t.replace(k, k + "        sll   $t3, $t2, 6" + n + "        addu  $t3, $t3, $a0" + n
                      + "        lui   $t6, 0x5e1a" + n + "        ori   $t6, $t6, 0x7c3d" + n
                      + "        sw    $t6, -8($t3)" + n + "        nor   $t6, $t6, $zero" + n + "        sw    $t6, -4($t3)" + n)
        k = "        bnez  $t7, 5b" + n + "        nop" + n
        assert t.count(k) == 1, "spssent: DMA loop site"
        t = t.replace(k, k + "        lui   $t6, 0x5e1a" + n + "        ori   $t6, $t6, 0x7c3d" + n + "        lui   $t7, 1" + n
                      + "sn1:    lw    $t8, -8($t3)" + n + "        addiu $t7, $t7, -1" + n + "        bne   $t8, $t6, sn2" + n
                      + "        nop" + n + "        bnez  $t7, sn1" + n + "        nop" + n
                      + "sn2:    beqz  $t7, sn4" + n + "        nor   $t6, $t6, $zero" + n
                      + "sn3:    lw    $t8, -4($t3)" + n + "        addiu $t7, $t7, -1" + n + "        bne   $t8, $t6, sn4" + n
                      + "        nop" + n + "        bnez  $t7, sn3" + n + "        nop" + n + "sn4:" + n)
    if "--spsdrain" in sys.argv:                    # (2026-11-25) the MiSTer core's SPU write FIFO may still hold the tail
        n = chr(10)                                 # of an upload (a mid-fight SpuWrite): it would drain to OUR read address.
        k = "        lhu   $t1, 0x1daa($t0)           /* SPUCNT (restored at the end) */" + n   # wait while SPUSTAT bit 10
        assert t.count(k) == 1, "spsdrain: SPUCNT site"                                         # (transfer busy) is set,
        t = t.replace(k, k + "        lui   $t7, 1" + n                                          # at most 65536 polls
                      + "dw1:    lhu   $t6, 0x1dae($t0)" + n + "        addiu $t7, $t7, -1" + n
                      + "        andi  $t6, $t6, 0x400" + n + "        beqz  $t6, dw2" + n + "        nop" + n
                      + "        bnez  $t7, dw1" + n + "        nop" + n + "dw2:" + n)
    if "--spsfifo" in sys.argv:
        n = chr(10)
        k = "        srl   $t6, $t3, 3" + n + "        sh    $t6, 0x1da6($t0)           /* transfer address / 8 */"
        assert t.count(k) == 1, "spsfifo: address site"
        t = t.replace(k, "        andi  $t6, $t1, 0xffcf" + n + "        ori   $t7, $t6, 0x30" + n
                      + "        sh    $t7, 0x1daa($t0)           /* (spsfifo) mode 11 ... */" + n
                      + "        sh    $t6, 0x1daa($t0)           /* ... -> 00: the core's read FIFO is cleared */" + n + k)
        k2 = "        bnez  $t7, 5b" + n + "        nop" + n
        assert t.count(k2) == 1, "spsfifo: DMA loop site"
        t = t.replace(k2, k2 + "        andi  $t6, $t1, 0xffcf" + n + "        ori   $t7, $t6, 0x30" + n
                      + "        sh    $t7, 0x1daa($t0)           /* (spsfifo) 11 ... */" + n
                      + "        sh    $t6, 0x1daa($t0)           /* ... -> 00 after the DMA: our prefetched tail dropped */" + n)
    # --spsverify (2026-11-25, MiSTer 2 MB freeze): the core can hand back bad SPU -> RAM data inside a transfer; every
    # fetch is done twice (whole register sequence again) and the staging buffer word-summed after each; different
    # sums -> error path (the tile is skipped this time, nothing reaches the decoder).  v0 = pass, v1 = first sum
    # (not decoder inputs).  A real SPU returns the same bytes twice: same decode as before, one extra small DMA.
    if "--spsverify" in sys.argv:
        n = chr(10)
        k = "        lui   $t0, 0x1f80" + n
        assert t.count(k) == 1, "spsverify: start site"
        t = t.replace(k, "        move  $v0, $zero" + n + "again:  lui   $t0, 0x1f80" + n)
        k = "        sw    $t9, 0x1014($t0)" + n
        assert t.count(k) == 1, "spsverify: end site"
        t = t.replace(k, k + "        move  $t6, $a0" + n + "        sll   $t7, $t2, 6" + n + "        addu  $t7, $t6, $t7" + n
                      + "        move  $t8, $zero" + n
                      + "9:      lw    $t1, 0($t6)" + n + "        addiu $t6, $t6, 4" + n + "        addu  $t8, $t8, $t1" + n
                      + "        bne   $t6, $t7, 9b" + n + "        nop" + n
                      + "        bnez  $v0, 8f" + n + "        nop" + n
                      + "        move  $v1, $t8" + n + "        b     again" + n + "        li    $v0, 1" + n
                      + "8:      beq   $t8, $v1, vok" + n + "        nop" + n
                      # mismatch: count it (DATA+20, the bytes statistic: not accumulated in this mode), retry until two
                      # consecutive reads agree, at most 4 reads, else the error path
                      + "        lui   $t7, %hi(DATA)" + n + "        lw    $t6, %lo(DATA + 20)($t7)" + n
                      + "        move  $v1, $t8" + n + "        addiu $t6, $t6, 1" + n
                      + "        sw    $t6, %lo(DATA + 20)($t7)" + n
                      + "        addiu $v0, $v0, 1" + n + "        slti  $t6, $v0, 4" + n
                      + "        bnez  $t6, again" + n + "        nop" + n
                      + "        b     err" + n + "        nop" + n
                      + "vok:" + n)
        k = "        addu  $t5, $t5, $t2" + n
        assert t.count(k) == 1, "spsverify: bytes statistic site"
        t = t.replace(k, "        nop" + n)

    # --spsdetect (2026-11-25, MiSTer 2 MB freeze): the store-fetch spin (--spspost, SPS_SPIN) costs real-PS1 speed
    # (2048: +3.2 % vblanks in a heavy fight), so it runs only on the MiSTer PSX core, detected once per power-on by a
    # deterministic core signature (rtl/spu.vhd): the SPU read FIFO keeps what it prefetched when only the transfer
    # address changes (it is reset only by a CNT mode 11 -> 00 write).  Test at the first fetch, DMA4 IRQ off, three
    # 1-block (64 B) reads into our own staging buffer (no CPU store into a DMA destination):
    #   X  = mode 11 at A, prefetch wait, address := B (no mode change), read      (core: A's data, real SPU: B's)
    #   RA = clean read of A, RB = clean read of B (B = A + 0x400)
    # FLAG 0x8000FFDC (free word after the dshptr trampoline, inside the proven kernel span) := 'REAL' only when
    # RA != RB and X == RB (and != RA); everything else 'CORE'.  The spin runs unless FLAG == 'REAL' (untested = spin).
    if "--spsdetect" in sys.argv:
        assert "--spspost" in sys.argv, "--spsdetect gates the --spspost spin"
        n = chr(10)
        L = lambda *x: n.join(x) + n
        k = "        li    $t7, %d" % int(os.environ.get("SPS_SPIN", "256")) + n + "pw1:"
        assert t.count(k) == 1, "spsdetect: spin site"
        t = t.replace(k, L("        lui   $t7, 0x8001", "        lw    $t7, -0x24($t7)          /* FLAG */",
                           "        lui   $t6, 0x5245", "        ori   $t6, $t6, 0x414c          /* 'REAL' */",
                           "        beq   $t7, $t6, pwx", "        nop")
                      + k)
        k = "        bnez  $t7, pw1" + n + "        nop" + n
        assert t.count(k) == 1
        t = t.replace(k, k + "pwx:" + n)
        d0 = FIX["FIXDICR0"] + n if fix else ""
        d1 = FIX["FIXDICR1"] + n if fix else ""
        det = (L("        lui   $t7, 0x8001", "        lw    $t7, -0x24($t7)          /* FLAG */",
                 "        lui   $t6, 0x5245", "        ori   $t6, $t6, 0x414c", "        beq   $t7, $t6, dtx",
                 "        lui   $t6, 0x434f", "        ori   $t6, $t6, 0x5245          /* 'CORE' */",
                 "        beq   $t7, $t6, dtx", "        nop")
               + d0
               + L("        move  $v0, $ra",
                   "        ori   $a0, $t3, 1               /* X: quirk read A -> B */",
                   "        bal   dts", "        nop",
                   "        lui   $t6, 0x8001", "        sw    $t8, -0x24($t6)          /* X (temporary) */",
                   "        move  $a0, $t3", "        bal   dts", "        nop", "        move  $v1, $t8               /* RA */",
                   "        addiu $a0, $t3, 0x400", "        bal   dts", "        nop                               /* t8 = RB */",
                   "        lui   $t6, 0x8001", "        lw    $t6, -0x24($t6)          /* X */",
                   "        lui   $t7, 0x434f", "        ori   $t7, $t7, 0x5245          /* 'CORE' */",
                   "        beq   $v1, $t8, dtw              /* RA == RB: inconclusive */", "        nop",
                   "        beq   $t6, $v1, dtw              /* X == RA: core FIFO */", "        nop",
                   "        bne   $t6, $t8, dtw              /* X != RB: inconclusive */", "        nop",
                   "        lui   $t7, 0x5245", "        ori   $t7, $t7, 0x414c          /* 'REAL' */",
                   "dtw:    lui   $t6, 0x8001", "        sw    $t7, -0x24($t6)",
                   "        b     dtd", "        move  $ra, $v0",
                   # dts: one 1-block read; a0 = SPU byte address (bit 0: quirk, B = a0 + 0x400 after a prefetch wait)
                   "dts:    andi  $t6, $t1, 0xffcf", "        sh    $t6, 0x1daa($t0)           /* mode 00 */",
                   "        srl   $t7, $a0, 3", "        sh    $t7, 0x1da6($t0)",
                   "        ori   $t6, $t6, 0x30", "        sh    $t6, 0x1daa($t0)           /* mode 11 */",
                   "        andi  $t8, $t6, 0x3f",
                   "dt1:    lhu   $t7, 0x1dae($t0)", "        nop", "        andi  $t7, $t7, 0x3f",
                   "        bne   $t7, $t8, dt1", "        nop",
                   "        andi  $t7, $a0, 1", "        beqz  $t7, dt3", "        nop",
                   "        li    $t7, 4096", "dt2:    addiu $t7, $t7, -1", "        bnez  $t7, dt2", "        nop",
                   "        addiu $t7, $a0, 0x400", "        srl   $t7, $t7, 3", "        sh    $t7, 0x1da6($t0)           /* B, mode unchanged */",
                   "dt3:    lui   $t7, %hi(DATA)", "        lw    $t7, %lo(DATA + 12)($t7)   /* staging */", "        nop",
                   "        sw    $t7, 0x10c0($t0)", "        lui   $t8, 1", "        ori   $t8, $t8, 0x10",
                   "        sw    $t8, 0x10c4($t0)           /* 1 block x 16 words */",
                   "        lui   $t8, 0x0100", "        ori   $t8, $t8, 0x0200", "        sw    $t8, 0x10c8($t0)",
                   "        lui   $t6, 0x0100",
                   "dt4:    lw    $t8, 0x10c8($t0)", "        nop", "        and   $t8, $t8, $t6", "        bnez  $t8, dt4", "        nop",
                   "        li    $t8, 2048", "dt5:    addiu $t8, $t8, -1", "        bnez  $t8, dt5", "        nop",
                   "        andi  $t6, $t1, 0xffcf", "        sh    $t6, 0x1daa($t0)           /* mode 00: FIFO reset */",
                   "        lw    $t8, 0($t7)", "        jr    $ra", "        nop",
                   "dtd:")
               + d1
               + L("dtx:"))
        k = "        srl   $t6, $t3, 3" + n + "        sh    $t6, 0x1da6($t0)           /* transfer address / 8 */"
        assert t.count(k) == 1, "spsdetect: address site"
        if os.environ.get("SPSDET_DBG") == "1":     # test builds only: X / RA / RB in DATA+20 / +28 / +24 (stats lost)
            det = det.replace("        lui   $t7, 0x434f" + n + "        ori   $t7, $t7, 0x5245          /* 'CORE' */" + n + "        beq   $v1, $t8, dtw",
                              "        lui   $t7, %hi(DATA)" + n + "        sw    $t6, %lo(DATA + 20)($t7)" + n
                              + "        sw    $v1, %lo(DATA + 28)($t7)" + n + "        sw    $t8, %lo(DATA + 24)($t7)" + n
                              + "        lui   $t7, 0x434f" + n + "        ori   $t7, $t7, 0x5245          /* 'CORE' */" + n + "        beq   $v1, $t8, dtw")
            assert "DATA + 28" in det
        t = t.replace(k, det + k)
    #   SPSFE_NOFETCH=1  every proxy takes the error path (no SPU DMA at all; stored tiles are not drawn)
    #   SPSFE_ATOMIC=1   interrupts off (COP0 SR IEc) from the owner hit to the decoder jump / error return
    if os.environ.get("SPSFE_NOFETCH") == "1":
        k = "3:      lui   $t2, %hi(WB)"; assert t.count(k) == 1
        t = t.replace(k, "3:      b     err" + chr(10) + "        nop" + chr(10) + "        lui   $t2, %hi(WB)")
    if os.environ.get("SPSFE_BOUND") == "1":        # both spin loops capped (t3 = counter, dead after the SPU address);
        n = chr(10)                                 # timeout -> DMA4 stopped, registers restored, error path (no decode)
        k = "4:      lhu   $t7, 0x1dae($t0)           /* SPUSTAT mode bits follow SPUCNT */"; assert t.count(k) == 1
        t = t.replace(k, "        lui   $t3, 1" + n + "4:      addiu $t3, $t3, -1" + n + "        beqz  $t3, 7f" + n + "        nop" + n
                      + "        lhu   $t7, 0x1dae($t0)")
        k = "5:      lw    $t7, 0x10c8($t0)"; assert t.count(k) == 1
        t = t.replace(k, "        lui   $t3, 1" + n + "5:      addiu $t3, $t3, -1" + n + "        beqz  $t3, 6f" + n + "        nop" + n
                      + "        lw    $t7, 0x10c8($t0)")
        k = "        bnez  $t7, 5b" + n + "        nop" + n; assert t.count(k) == 1
        t = t.replace(k, k + "        b     7f" + n + "        nop" + n + "6:      sw    $zero, 0x10c8($t0)        /* stop DMA4 */" + n
                      + "7:" + n)
        k = "        lw    $a3, 8($t4)                /* owner's section */"; assert t.count(k) == 1
        t = t.replace(k, "        beqz  $t3, err" + n + "        nop" + n + k)
    if os.environ.get("SPSFE_BOUND") == "1" and os.environ.get("SPSFE_DIAG") == "1":   # timeouts counted in DATA+20
        n = chr(10)                                 # (loop 4: +1, loop 5: +0x100; the bytes statistic is dropped)
        k = "        beqz  $t3, 7f" + n + "        nop" + n + "        lhu   $t7, 0x1dae($t0)"; assert t.count(k) == 1
        t = t.replace(k, "        beqz  $t3, 8f" + n + "        nop" + n + "        lhu   $t7, 0x1dae($t0)")
        k = "6:      sw    $zero, 0x10c8($t0)        /* stop DMA4 */" + n + "7:" + n; assert t.count(k) == 1
        cnt = lambda v: ("        lui   $t7, %hi(DATA)" + n + "        lw    $t8, %lo(DATA + 20)($t7)" + n + "        nop" + n
                         + "        addiu $t8, $t8, " + v + n + "        sw    $t8, %lo(DATA + 20)($t7)" + n)
        t = t.replace(k, "6:      sw    $zero, 0x10c8($t0)        /* stop DMA4 */" + n + cnt("0x100") + "        b     7f" + n + "        nop" + n
                      + "8:" + n + cnt("1") + "7:" + n)
        k = "        addu  $t5, $t5, $t2" + n; assert t.count(k) == 1
        t = t.replace(k, "        nop" + n)
    if os.environ.get("SPSFE_ATOMIC") == "1":       # SR in t3 (dead after the SPU address), t7 free there
        k = "        srl   $t6, $t3, 3"; assert t.count(k) == 1
        t = t.replace(k, k + chr(10) + "        mfc0  $t3, $12" + chr(10) + "        nop" + chr(10) + "        srl   $t7, $t3, 1"
                      + chr(10) + "        sll   $t7, $t7, 1" + chr(10) + "        mtc0  $t7, $12" + chr(10) + "        nop" + chr(10) + "        nop")
        k = "        lw    $a3, 8($t4)                /* owner's section */"; assert t.count(k) == 1
        t = t.replace(k, "        mtc0  $t3, $12" + chr(10) + k)
    return t


# --spsguard (asdip lead, hwfix 2026-11-22; MiSTer class-A freeze: a proxy reached the real DSH decoder with a3 !=
# FAKE): route by the SOURCE instead of the section the dispatch picked.  Every source >= 0x80200000 (proxies 0x8021..;
# nothing legit on a 2 MB machine) goes to the front end with a3 forced to FAKE (it fetches, or counts an error and
# returns: never a real decoder on a mirror address); everything else to the saved decoder.  Same 12 words.
TSRC_G = r"""
tr:     lui   $t0, 0x8020
        sltu  $t0, $a0, $t0
        bnez  $t0, 1f                      /* below 0x80200000: a RAM source */
        lui   $t9, %hi(DATA)
        lw    $t9, %lo(DATA + 0x68)($t9)   /* proxy (or a mirror address): front end, a3 = FAKE */
        lui   $a3, %hi(FAKE)
        jr    $t9
        addiu $a3, $a3, %lo(FAKE)
1:      lw    $t9, %lo(DATA + 8)($t9)      /* saved decoder */
        nop
        jr    $t9
        nop
tend:
"""
GUARD = False


def tramp():
    code, sym = gas(TSRC_G if GUARD else TSRC, TRAMP, {"FAKE": FAKE, "DATA": DATA})
    assert TRAMP + len(code) <= 0x8000FFE0, hex(TRAMP + len(code))
    import dlib
    assert not dlib.hazards(code, TRAMP)
    return code


def build(fix=False, rle=None, gov=False):
    V = {"FAKE": FAKE, "DATA": DATA, "WB": WB}
    if rle: V["RLE"] = rle
    if gov: V.update(GDRAW=GDRAW, GSTAMP=GSTAMP, GOVLIM=GOVLIM)
    code, sym = gas(src(fix, rle, gov), AT, V)
    assert gas(src(fix, rle, gov), AT + 0x1230, V)[0] == code, "not position-independent"
    assert sym["end"] - AT == len(code) and DATA + 0x60 <= 0x8000FFE0, len(code)
    import dlib
    bad = dlib.hazards(code, AT)
    assert not bad, bad
    return code, sym


def header(path, fix=False, rle=None, gov=False, guard=False):
    global GUARD
    GUARD = guard
    code, sym = build(fix, rle, gov)
    w = struct.unpack("<%dI" % (len(code) // 4), code)
    nl = chr(10)
    open(path, "w").write("/* generated by mktag.py --spustore from tools/spustore/spsfe.py */" + nl
                          + "#define SPS_AT 0x%08xu%s#define SPS_DATA 0x%08xu%s#define SPS_FAKE 0x%08xu%s#define SPS_WB 0x%08xu%s#define SPS_N %d%s"
                          % (AT, nl, DATA, nl, FAKE, nl, WB, nl, len(w), nl)
                          + "static const u32 sps_code[%d] = {" % len(w) + ", ".join("0x%08x" % x for x in w) + "};" + nl
                          + ("#define SPS_GOVI 0x%x%s" % (sym["gvinst"] - AT, nl) if gov else "")
                          + "#define SPS_TRAMP 0x%08xu%s" % (TRAMP, nl)
                          + "static const u32 sps_tramp[%d] = {" % (len(tramp()) // 4) + ", ".join("0x%08x" % x for x in struct.unpack("<%dI" % (len(tramp()) // 4), tramp())) + "};" + nl)
    return len(code)


if __name__ == "__main__":
    print(len(build()[0]), "bytes")
