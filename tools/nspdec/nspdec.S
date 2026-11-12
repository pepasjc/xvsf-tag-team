/* XVH1 tile decoder for X-Men vs. Street Fighter (SLUS-00627).  Format: tools/nsp_huff.py.
 *
 * Lives over uncalled libgpu helper/debug-dump functions:
 *     chunk Z  0x800158f4-0x80015a68   xvf_dec (XVF1, speed-first codec)
 *     (0x80015a68-0x80015bac live code, untouched)
 *     chunk X  0x80015bac-0x80015d9c   nsp_dec main loop (XVH1) + XVF1 overflow
 *     (0x80015d9c-0x80015dd4 is a LIVE function and is left untouched: "hole")
 *     chunk Y  0x80015dd4-0x80015f94   run handling, dispatch stub, run-length table
 * Entered by `j dec_entry` written over the first instruction of the game's RLE tile decoder
 * 0x8001b5b0(a0=src, a1=dst, a2=nbytes).  Uses only caller-saved registers plus s0/s1 (saved),
 * no $gp, no calls.  Every load-delay slot is respected (R3000).
 */
        .set    noreorder
        .set    noat
        .text
        .globl  nsp_dec, xvm_dec, msym, dec_entry, holeS_start, holeS_end, endS, endZ, endX, hole0_start, hole0_end, hole_start, hole_end, blob_end

#define FRAME 280               /* rb[0..259] at sp+0, s0 at 272, s1 at 276 */

/* ---------------------------------------------------------------- chunk S (0x80010440-0x80010508) */
/* XVM1 (default codec, format: tools/nsp_mid.py): set-up part.
 * a0 src, a1 dst, a2 nbytes (>0), a3 model
 * t0 bit buffer (MSB first)   t1 bits available - 16   t2 offset from dst to the byte above
 * t3 (previous byte >> 4) << 8   t4 previous byte   t5 end of output   t6 fallback records
 * t7 current table   a2 current limit (end of row 0, then end of output)
 * Row 0 reads its "row above" from a 0xFF-filled buffer on the stack. */
xvm_dec:
        lbu     $v0, 0($a0)             /* first 32 stream bits, big endian */
        lbu     $v1, 1($a0)
        lbu     $t8, 2($a0)
        lbu     $t9, 3($a0)
        sll     $v0, $v0, 24
        sll     $v1, $v1, 16
        sll     $t8, $t8, 8
        or      $v0, $v0, $v1
        or      $t8, $t8, $t9
        or      $t0, $v0, $t8
        addiu   $a0, $a0, 4
        srl     $t3, $t0, 28
        addiu   $t3, $t3, 1
        sll     $t3, $t3, 3             /* W bytes */
        sll     $t0, $t0, 4
        ori     $t1, $zero, 12
        addiu   $sp, $sp, -136
        addu    $t5, $a1, $a2           /* end of output */
        addu    $a2, $a1, $t3           /* end of row 0 */
        subu    $v0, $zero, $t3
        sw      $v0, 128($sp)           /* -W: offset to the row above for rows >= 1 */
        subu    $t2, $sp, $a1           /* row 0: dst + t2 = stack buffer */
        addiu   $v0, $zero, -1
        addu    $v1, $sp, $t3
        move    $t8, $sp
1:      sw      $v0, 0($t8)
        addiu   $t8, $t8, 4
        bne     $t8, $v1, 1b
        nop
        lhu     $t6, 8($a3)
        ori     $t4, $zero, 0xff
        addu    $t6, $t6, $a3
        j       msym
        ori     $t3, $zero, 0xf00

endS:
        .org    0x80010508 - 0x80010440
holeS_start:
        .space  0x800158f4 - 0x80010508         /* game code and data: not patched */
holeS_end:

/* ---------------------------------------------------------------- chunk Z (0x800158f4-0x80015a68) */
msym:   addu    $t9, $a1, $t2
msym1:  lbu     $v0, 0($t9)             /* U = byte above */
        srl     $t8, $t0, 25
        or      $v0, $v0, $t3
        addu    $v0, $v0, $a3
        lbu     $t7, 76($v0)            /* table = map[(P>>4)<<8 | U] */
        andi    $t8, $t8, 0x7e          /* next 6 bits * 2 */
        sll     $v0, $t7, 7
        addu    $v0, $v0, $t8
        addu    $v0, $v0, $a3
        lh      $v0, 4172($v0)          /* LUT entry */
        addiu   $a1, $a1, 1
mgot:   bltz    $v0, mspecial
        andi    $v1, $v0, 15            /* code length */
        srl     $t4, $v0, 4             /* literal byte */
        sllv    $t0, $t0, $v1
        subu    $t1, $t1, $v1
        andi    $t3, $v0, 0xf00
        bltz    $t1, mrefill
        sb      $t4, -1($a1)
mchk:   bne     $a1, $a2, msym1
        addu    $t9, $a1, $t2
        beq     $a2, $t5, mdone
        lw      $t2, 128($sp)           /* row 0 finished: read the real row above from now on */
        b       msym
        move    $a2, $t5
mdone:  jr      $ra
        addiu   $sp, $sp, 136
mchkr:  bgez    $t1, mchk
        nop
mrefill:
        lbu     $v0, 0($a0)             /* 16 more bits */
        lbu     $v1, 1($a0)
        subu    $t9, $zero, $t1
        sll     $v0, $v0, 8
        or      $v0, $v0, $v1
        sllv    $v0, $v0, $t9
        or      $t0, $t0, $v0
        addiu   $a0, $a0, 2
        b       mchk
        addiu   $t1, $t1, 16
mspecial:
        sll     $t9, $v0, 17
        bltz    $t9, mlong              /* bit 14: code longer than 6 bits */
        sll     $t9, $v0, 19
        sllv    $t0, $t0, $v1
        bltz    $t9, mesc               /* bit 12: escape */
        subu    $t1, $t1, $v1
        srl     $t8, $v0, 3
        andi    $t8, $t8, 0x3e
        addu    $t8, $t8, $a3
        lhu     $t8, 12($t8)            /* run length */
        andi    $v0, $v0, 0x2000
        addiu   $a1, $a1, -1            /* undo the literal pre-increment */
        bnez    $v0, mrep
        addu    $t8, $a1, $t8           /* end of run */
        addu    $t9, $a1, $t2           /* copy from the row above */
        subu    $v1, $t8, $a1
        srl     $v1, $v1, 2
        beqz    $v1, mu1
        sll     $v1, $v1, 2
        addu    $v1, $a1, $v1
mu4:    lwl     $v0, 3($t9)
        lwr     $v0, 0($t9)
        addiu   $a1, $a1, 4
        swl     $v0, -1($a1)
        swr     $v0, -4($a1)
        bne     $a1, $v1, mu4
        addiu   $t9, $t9, 4
mu1:    beq     $a1, $t8, mud
        nop
mub:    lbu     $v0, 0($t9)
        addiu   $a1, $a1, 1
        addiu   $t9, $t9, 1
        bne     $a1, $t8, mub
        sb      $v0, -1($a1)
mud:    lbu     $t4, -1($a1)            /* context from the last copied byte */
        nop
        andi    $t3, $t4, 0xf0
        b       mchkr
        sll     $t3, $t3, 4
mrep:   addiu   $a1, $a1, 1             /* repeat the previous byte */
        bne     $a1, $t8, mrep
        sb      $t4, -1($a1)
        b       mchkr
        nop
mesc:   srl     $t4, $t0, 24            /* escape: 8 raw bits */
        sll     $t0, $t0, 8
        addiu   $t1, $t1, -8
        andi    $t3, $t4, 0xf0
        sll     $t3, $t3, 4
        b       mchkr
        sb      $t4, -1($a1)

endZ:
        .org    0x80015a68 - 0x80010440
hole0_start:
        .space  0x80015bac - 0x80015a68         /* live game code: not patched */
hole0_end:

/* ---------------------------------------------------------------- chunk X */
/* a0 src, a1 dst, a2 nbytes (>0), a3 model (sec2 start)
 * t0 bit buffer (left aligned, sentinel bit below the data)   t1 &rb[x]   t2 &rb[W]
 * t3 L<<8   t4 UL   t5 pending low nibble   t6 map2   t7 tabofs
 * rb[x] = pixel above x (the previous row, overwritten as the row is decoded); rb[W] = 15 */
nsp_dec:
        addiu   $sp, $sp, -FRAME
        sw      $s0, 272($sp)
        sw      $s1, 276($sp)
        lbu     $t0, 0($a0)             /* first byte: width code in the high nibble */
        addiu   $a0, $a0, 1
        addu    $a2, $a1, $a2           /* a2 = end of output */
        srl     $t2, $t0, 4
        addiu   $t2, $t2, 1
        sll     $t2, $t2, 4             /* W pixels */
        sll     $t0, $t0, 28
        lui     $v0, 0x0800
        or      $t0, $t0, $v0           /* 4 data bits + sentinel */
        lui     $v0, 0x0f0f
        ori     $v0, $v0, 0x0f0f
        addu    $t2, $sp, $t2           /* &rb[W] */
        move    $t1, $sp
1:      sw      $v0, 0($t1)             /* rb[0..W+3] = 15 */
        sltu    $v1, $t1, $t2
        bnez    $v1, 1b
        addiu   $t1, $t1, 4
        lhu     $t6, 8($a3)
        lhu     $t7, 10($a3)
        move    $t1, $sp
        addu    $t6, $a3, $t6
        addu    $t7, $a3, $t7
        ori     $t3, $zero, 0xf00
        ori     $t4, $zero, 15

sym:    lbu     $t8, 0($t1)             /* U */
        lbu     $t9, 1($t1)             /* UR */
        sll     $v0, $t8, 4
        or      $v0, $v0, $t3
        or      $v0, $v0, $t4
        addu    $v0, $v0, $a3
        lbu     $v0, 12($v0)            /* class = map1[L<<8 | U<<4 | UL] */
        move    $v1, $zero              /* d = 0 */
        sll     $v0, $v0, 4
        or      $v0, $v0, $t9
        addu    $v0, $v0, $t6
        lbu     $v0, 0($v0)             /* table = map2[class<<4 | UR] */
        nop
        sll     $v0, $v0, 1
        addu    $v0, $v0, $t7
        lhu     $v0, 0($v0)             /* record offset */
        nop
        addu    $s0, $a3, $v0           /* s0 -> cnt[len] */
        addiu   $s1, $s0, 12            /* s1 -> symbols of the current length */

bit:    sll     $t9, $t0, 1
        beqz    $t9, refill             /* only the sentinel left */
        srl     $v0, $t0, 31            /* next bit */
gotbit: lbu     $at, 0($s0)             /* number of codes of this length */
        sll     $v1, $v1, 1
        addu    $v1, $v1, $v0           /* d = d*2 + bit */
        sltu    $v0, $v1, $at
        bnez    $v0, found
        move    $t0, $t9
        subu    $v1, $v1, $at
        addiu   $s0, $s0, 1
        b       bit
        addu    $s1, $s1, $at

refill: lbu     $t0, 0($a0)
        lui     $v0, 0x0080
        addiu   $a0, $a0, 1
        sll     $t0, $t0, 24
        or      $t0, $t0, $v0
        sll     $t9, $t0, 1
        b       gotbit
        srl     $v0, $t0, 31

found:  addu    $v0, $s1, $v1
        lbu     $v0, 0($v0)             /* symbol */
        andi    $v1, $t1, 1             /* x odd?  (rb is at an even address) */
        sltiu   $t9, $v0, 16
        beqz    $t9, isrun
        sll     $t3, $v0, 8             /* L = p<<8 (recomputed after a run) */
        sb      $v0, 0($t1)             /* literal pixel: rb[x] = p */
        beqz    $v1, even
        addiu   $t1, $t1, 1
        sll     $v0, $v0, 4
        or      $v0, $v0, $t5
        sb      $v0, 0($a1)             /* byte = low | p<<4 */
        addiu   $a1, $a1, 1
        beq     $t1, $t2, rowend
        move    $t4, $t8                /* UL = U */
next:   sltu    $v0, $a1, $a2
        bnez    $v0, sym
        nop
        lw      $s0, 272($sp)
        lw      $s1, 276($sp)
        jr      $ra
        addiu   $sp, $sp, FRAME
even:   move    $t5, $v0                /* keep the low nibble; never a row or tile end */
        b       sym
        move    $t4, $t8
rowend: move    $t1, $sp
        ori     $t3, $zero, 0xf00
        b       next
        ori     $t4, $zero, 15

/* XVM1: codes longer than 6 bits - canonical walk over the table's fallback record
 * (per length 7..12: u16 limit left-justified to 12 bits, s16 entry-list adjust) */
mlong:  srl     $t8, $t0, 20            /* next 12 bits */
        sll     $t9, $t7, 5
        addu    $t9, $t9, $t6
        ori     $v1, $zero, 6
1:      lhu     $v0, 0($t9)
        addiu   $t9, $t9, 4
        sltu    $v0, $t8, $v0
        beqz    $v0, 1b
        addiu   $v1, $v1, -1            /* v1 = 12 - length */
        lh      $v0, -2($t9)
        srlv    $t8, $t8, $v1
        sll     $t8, $t8, 1
        addu    $v0, $v0, $t8
        addu    $v0, $v0, $a3
        lh      $v0, 0($v0)             /* entry (its length field is the full code length) */
        b       mgot
        nop

endX:
        .org    0x80015d9c - 0x80010440
hole_start:
        .space  0x80015dd4 - 0x80015d9c         /* live game function: not patched */
hole_end:

/* ---------------------------------------------------------------- chunk Y */
/* copy `run` pixels from the row above (rb is left unchanged).  v0 = symbol, v1 = x&1 */
isrun:  sll     $v0, $v0, 1
        lui     $t9, %hi(RUNS - 32)
        addu    $t9, $t9, $v0
        lhu     $t9, %lo(RUNS - 32)($t9)        /* run length in pixels */
        beqz    $v1, 4f
        nop
        lbu     $v0, 0($t1)             /* x odd: complete the pending byte */
        addiu   $t1, $t1, 1
        addiu   $t9, $t9, -1
        sll     $v0, $v0, 4
        or      $v0, $v0, $t5
        sb      $v0, 0($a1)
        bne     $t1, $t2, 4f
        addiu   $a1, $a1, 1
        move    $t1, $sp
4:      sltiu   $v0, $t9, 2
        bnez    $v0, 6f
        nop
5:      lbu     $v0, 0($t1)             /* whole bytes (x even) */
        lbu     $v1, 1($t1)
        addiu   $t1, $t1, 2
        addiu   $t9, $t9, -2
        sll     $v1, $v1, 4
        or      $v0, $v0, $v1
        sb      $v0, 0($a1)
        bne     $t1, $t2, 55f
        addiu   $a1, $a1, 1
        move    $t1, $sp
55:     sltiu   $v0, $t9, 2
        beqz    $v0, 5b
        nop
6:      beqz    $t9, 7f
        nop
        lbu     $t5, 0($t1)             /* one pixel left: x even, cannot wrap */
        addiu   $t1, $t1, 1
7:      beq     $t1, $sp, 8f            /* context for the next symbol */
        ori     $t4, $zero, 15          /* row start: L = UL = 15 */
        lbu     $t4, -1($t1)            /* else L = UL = rb[x-1] */
        nop
8:      j       next
        sll     $t3, $t4, 8

/* dispatch: is a0 inside the sec2 of a loaded XVH1 character file?  (file ids 0..0x12; the
 * section pointer table 0x8005c830 is written by the NSP loader 0x80053f78).  Among matches
 * the highest sec2 start wins (guards against a stale pointer whose header is still intact). */
dec_entry:
        blez    $a2, 9f
        lui     $t1, 0x8006
        addiu   $t1, $t1, -0x37d0       /* 0x8005c830 */
        addiu   $t2, $t1, 19*4          /* ids 0..0x12 = SP_PLxx.NSP; then 0x26 = resident effects */
        addiu   $t5, $t1, 0x27*4
        lui     $t4, 0x3148
        ori     $t4, $t4, 0x5658        /* 'XVH1' */
        lui     $t6, 0x0005             /* 'XVH1' ^ 'XVM1' */
        move    $a3, $zero
1:      lw      $v0, 0($t1)
        addiu   $t1, $t1, 4
        beqz    $v0, 2f
        sltu    $v1, $a0, $v0           /* src below this sec2? */
        bnez    $v1, 2f
        sltu    $v1, $v0, $a3           /* below the best match so far? */
        bnez    $v1, 2f
        nop
        lw      $v1, 0($v0)             /* magic */
        lw      $t3, 4($v0)             /* sec2 size */
        xor     $v1, $v1, $t4
        beqz    $v1, 4f
        addu    $t3, $v0, $t3
        bne     $v1, $t6, 2f
        nop
4:      sltu    $v1, $a0, $t3
        beqz    $v1, 2f
        nop
        move    $a3, $v0
2:      bne     $t1, $t2, 1b
        nop
        addiu   $t1, $t5, -4            /* one more round for set 0x26 */
        bne     $t2, $t5, 1b
        move    $t2, $t5
        beqz    $a3, 3f
        nop
        lw      $v1, 0($a3)             /* a3 = model: which codec? */
        nop
        beq     $v1, $t4, nsp_dec
        nop
        j       xvm_dec
        nop
3:      lui     $t0, 0x8002             /* not ours: the original RLE decoder */
        j       0x8001b5b8
        addiu   $t0, $t0, -0x49f8
9:      jr      $ra
        nop

RUNS:   .half   1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16
        .half   24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 2048, 4096
blob_end:
