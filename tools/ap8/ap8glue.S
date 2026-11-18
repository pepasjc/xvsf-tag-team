        .set noreorder
/* EXE side: the two hook entries (the battle loader's frame holds the character list at sp+0x38) */
        .section .chunkj_head, "ax"
#ifndef MODULE
        .globl glue8, effglue8, modent
glue8:  j       hook8
        addiu   $a1, $sp, 0x38
effglue8:
        j       effhook8
        addiu   $a2, $sp, 0x38
        .section .chunki_data, "aw"
        .balign 8
        .space 4                        /* file entries must sit at 4 mod 8 (same residue as the game file table) */
modent: .space 8                        /* MSF + size of the module (disc builder) */

#else
/* module side: vectors at MOD+0 (eff), MOD+8 (hook), MOD+16 (sel), MOD+24 (menu), then the file tables at MOD+0x24 (4 mod 8) */
        .section .modhead, "ax"
        .globl T
        j       mod_eff
        nop
        j       mod_hook
        nop
        j       mod_sel
        nop
        j       mod_menu
        nop
        .word   0
T:      .space  (19 * 5 + 7) * 8 + 19 * 4 + 39 * 4 + 20 * 2 + 7 * 4 + 4 + 8 + 8 + 19 * 8 + 4 + 4 * EFFHMAX

/* decoded-tile cache (ap8mod.c rawsetup / rawundo).  State fields: +0x1b0 rawoff, +0x1b4 rawcur (battle copies grow
 * down from here), +0x1b8 rawlo, +0x1bc rsn (cached sets), +0x1c0 decw, +0x1d0 ra / v0 / a0 / a1 / a2 of raw_dec,
 * +0x1e4 rs[5] = { sec1 table, entries, sec2 } */
        .equ    RUNAT, STATEA + 0x1000
        .equ    TRAMP, STATEA + 0x11f0
        .equ    JRUNAT, 0x08000000 | ((RUNAT >> 2) & 0x3ffffff)
        .text
        .set    noat
        .globl  raw_dec, rawhook, raw_end
rawhook:                                /* a0 = state.  raw_dec runs from a copy at RUNAT (state page: a battle load re-reads
                                           the module while loading screens still decode tiles); 0x8001b5b0 -> j RUNAT,
                                           the decoder's two first words (decw) -> TRAMP + j 0x8001b5b8 */
        lui     $t0, 0x8002
        lw      $t1, -0x4a50($t0)
        lw      $t2, -0x4a4c($t0)
        lui     $t3, %hi(JRUNAT)
        ori     $t3, $t3, %lo(JRUNAT)
        beq     $t1, $t3, 1f            /* hooked before: decw holds the decoder's words */
        nop
        sw      $t1, 0x1c0($a0)
        sw      $t2, 0x1c4($a0)
1:      lw      $t1, 0x1c0($a0)
        lw      $t2, 0x1c4($a0)
        lui     $t6, %hi(TRAMP)
        addiu   $t6, $t6, %lo(TRAMP)
        sw      $t1, 0($t6)
        sw      $t2, 4($t6)
        lui     $t7, 0x0800
        ori     $t7, $t7, 0x6d6e        /* j 0x8001b5b8 */
        sw      $t7, 8($t6)
        sw      $zero, 12($t6)
        lui     $t4, %hi(raw_dec)
        addiu   $t4, $t4, %lo(raw_dec)
        lui     $t5, %hi(raw_end)
        addiu   $t5, $t5, %lo(raw_end)
        lui     $t6, %hi(RUNAT)
        addiu   $t6, $t6, %lo(RUNAT)
2:      lw      $t7, 0($t4)
        addiu   $t4, $t4, 4
        sw      $t7, 0($t6)
        bne     $t4, $t5, 2b
        addiu   $t6, $t6, 4
        sw      $zero, -0x4a4c($t0)
        sw      $t3, -0x4a50($t0)
        j       flushcache
        nop

/* raw_dec(a0 src, a1 dst, a2 n): the tile decoder 0x8001b5b0 as every caller sees it (runs from RUNAT, no stack).
 * 'XRAW' tile (word aligned, tag then the pixels): copy n bytes.  Else the decoder; then, when the tile's sec1 entry
 * (scratch ctx +0x88, set by the sec1 parser) belongs to a cached set and n is its full size, the decoded bytes are
 * copied into the cache (rawcur down to rawlo) as  old offset | 0 | -1 | 'XRAW' | pixels  and the entry points at the tag. */
raw_dec:
        andi    $t0, $a0, 3
        bnez    $t0, 5f
        lui     $t1, 0x5741
        lw      $t2, 0($a0)
        ori     $t1, $t1, 0x5258        /* 'XRAW' */
        bne     $t2, $t1, 5f
        lui     $t9, %hi(STATEA)
        lw      $t0, %lo(STATEA) + 0x1c8($t9)   /* rawskip: return address of the stock pre-decode's call (0 = none) */
        nop
        beq     $t0, $ra, 3f            /* the upload loops take a RAW tile from the cache, not from this block: no copy */
        nop
4:      lw      $t3, 4($a0)             /* cached tile: copy n bytes */
        addiu   $a2, $a2, -4
        addiu   $a0, $a0, 4
        sw      $t3, 0($a1)
        bgtz    $a2, 4b
        addiu   $a1, $a1, 4
3:      jr      $ra
        move    $v0, $zero
5:      lui     $t9, %hi(STATEA)
        addiu   $t9, $t9, %lo(STATEA)
        sw      $ra, 0x1d0($t9)
        sw      $a0, 0x1d8($t9)
        sw      $a1, 0x1dc($t9)
        sw      $a2, 0x1e0($t9)
        lui     $t0, %hi(TRAMP)
        addiu   $t0, $t0, %lo(TRAMP)
        jalr    $t0                     /* the decoder as it was */
        nop
        lui     $t9, %hi(STATEA)
        addiu   $t9, $t9, %lo(STATEA)
        sw      $v0, 0x1d4($t9)
        lw      $a0, 0x1d8($t9)
        lw      $a1, 0x1dc($t9)
        lw      $a2, 0x1e0($t9)
        lw      $t0, 0x1b0($t9)         /* rawoff */
        lw      $t8, 0x1bc($t9)         /* rsn */
        bnez    $t0, 9f
        lui     $t1, 0x8007
        beqz    $t8, 9f
        lw      $t1, -0x5cc0($t1)       /* scratch context */
        nop
        lw      $t2, 0x88($t1)          /* its sec1 entry pointer (sec1 parser 0x80057f48) */
        lui     $t4, 0x3f
        andi    $t3, $t2, 3
        bnez    $t3, 9f
        ori     $t4, $t4, 0xffff
        lw      $t3, 0($t2)             /* w */
        nop
        srl     $t5, $t3, 24
        andi    $t5, $t5, 15
        addiu   $t5, $t5, 1
        srl     $t6, $t3, 28
        addiu   $t6, $t6, 1
        mult    $t5, $t6
        and     $t5, $t3, $t4
        subu    $t5, $a0, $t5           /* base = src - offset */
        mflo    $t6
        sll     $t6, $t6, 7             /* e8 * e9 */
        bne     $t6, $a2, 9f
        addiu   $t7, $t9, 0x1e4         /* rs[] */
6:      lw      $t6, 8($t7)             /* rs[k].s2 */
        addiu   $t8, $t8, -1
        beq     $t6, $t5, 7f
        addiu   $t7, $t7, 12
        bgtz    $t8, 6b
        nop
9:      lw      $ra, 0x1d0($t9)
        lw      $v0, 0x1d4($t9)
        jr      $ra
        nop
7:      lw      $t6, 0x1b4($t9)         /* rawcur */
        lw      $t7, 0x1b8($t9)         /* rawlo */
        subu    $t6, $t6, $a2
        addiu   $t6, $t6, -16           /* header here (old offset, check, tile), tag at +12, pixels at +16 */
        sltu    $at, $t6, $t7
        bnez    $at, 9b                 /* full */
        subu    $t0, $t6, $t5
        addiu   $t0, $t0, 12            /* new offset = tag - base */
        sltu    $at, $t4, $t0
        bnez    $at, 9b                 /* beyond 22 bits (or below the set's sec2) */
        nop
        sw      $t6, 0x1b4($t9)
        and     $t1, $t3, $t4
        sw      $t1, 0($t6)             /* old offset (rawundo) */
        sw      $zero, 4($t6)           /* no check, no tile: never salvaged */
        addiu   $t1, $zero, -1
        sw      $t1, 8($t6)
        lui     $t1, 0x5741
        ori     $t1, $t1, 0x5258
        sw      $t1, 12($t6)
        lui     $t1, 0xffc0
        and     $t1, $t3, $t1
        or      $t1, $t1, $t0
        sw      $t1, 0($t2)             /* the entry now points at the copy */
        addiu   $t6, $t6, 12
8:      lw      $t1, 0($a1)
        addiu   $a2, $a2, -4
        addiu   $a1, $a1, 4
        addiu   $t6, $t6, 4
        bgtz    $a2, 8b
        sw      $t1, 0($t6)
        b       9b
        nop
raw_end:                                /* raw_dec must fit RUNAT..TRAMP (0x1f0 bytes; checked by the build) */
        .set    at

/* LOADFILE (0x8002de3c) without the file cache: its two first instructions (replaced by `j mod_loadfile`), then the rest */
        .text
        .globl  orig_loadfile
orig_loadfile:
        addiu   $sp, $sp, -0x20
        j       0x8002de44
        sw      $s0, 0x10($sp)
#endif
