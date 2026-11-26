/* DSR1 tile decoder (format: tools/codec2/dsr.py, layout v3), MIPS R3000.  Derived from common/dsp/dsadec.S (DSA1):
 * same entry (a0 = src: width byte + range-coder bytes, a1 = dst, a2 = nbytes, a3 = DSR1 pixel section), same range
 * coder, node words and row buffer; adds the run mode.  Writes exactly nbytes.  Caller-saved registers only, no stack,
 * no calls outside itself (the bit decoder is a local routine reached with bal; the caller's ra is kept in scratchpad
 * 0x1f8003fc), position-independent (only PC-relative branches; the scratchpad lui is the one absolute constant).
 * Scratchpad 0x1f800300 .. 0x300 + W + 3 (W <= 240): one byte per column, low nibble = row y-1, high = row y-2; 0x3fc ra.
 *
 * a0 stream   a1 dst   a2 end of output   a3 &node[0] (cont[256] at -640, entry u16[64] at -384, jump u8[256] at -256)
 * t0 code   t1 range   t2 &rb[x]   t3 &rb[W] | known-not-U flag (bit 0; &rb[W] is 4-aligned)
 * t4 window L | state << 4 | UL << 8 | LL << 16 | ULL << 24   (state = 0: no run, 1..4: in a run, pos = state - 1)
 * t5 leaf records (17 B: p[0..15], lprob)   t6 rb[x] (U | UU << 4)   t7 V / literal index   t8 node / record ptr,
 * new state << 4 at store   t9 node word / probability   v0 v1 at temps */
        .set    noreorder
        .set    noat
        .text
        .globl  dsr_dec, dsr_end

dsr_dec:
        lui     $t9, 0x1f80
        sw      $ra, 0x3fc($t9)         /* caller's ra (bal below clobbers it) */
        lhu     $v0, 8($a3)             /* 4 * node count */
        addiu   $a3, $a3, 656           /* &node[0] */
        addu    $t5, $a3, $v0           /* leaf records */
        lbu     $t3, 0($a0)             /* width in bytes */
        lbu     $t0, 1($a0)             /* code byte 0 */
        addiu   $a0, $a0, 2
        bal     norm3                   /* range 1: the renormalisation loop shifts in exactly 3 more bytes */
        ori     $t1, $zero, 1
        addiu   $t1, $zero, -1          /* range */
        addu    $a2, $a1, $a2
        sll     $t3, $t3, 1             /* W pixels (multiple of 4) */
        ori     $t2, $t9, 0x0300
        addu    $t3, $t2, $t3           /* &rb[W] */
        addiu   $v0, $zero, -1
        move    $t8, $t2
0:      sw      $v0, 0($t8)             /* rb[0 .. W+7] = 0xff (ends <= 0x3f7) */
        sltu    $v1, $t3, $t8
        beqz    $v1, 0b
        addiu   $t8, $t8, 4

row:    lui     $t4, 0x0f0f             /* L, UL, LL, ULL = 15, state 0 */
        ori     $t4, $t4, 0x0f0f
        lui     $t2, 0x1f80
        ori     $t2, $t2, 0x0300
pix:    lbu     $t6, 0($t2)             /* U | UU << 4 */
pix2:   andi    $v0, $t4, 0xf0          /* state << 4 */
        beqz    $v0, full
        andi    $v0, $t6, 15            /* (delay) U */
/* ---- in a run: continue bit, context from the rows above */
        srl     $at, $t4, 8
        andi    $at, $at, 15            /* UL */
        xor     $at, $at, $v0
        sltiu   $t9, $at, 1             /* U == UL */
        lbu     $t8, 1($t2)             /* UR | UUR << 4 */
        lbu     $v1, 2($t2)             /* URR */
        andi    $at, $t8, 15            /* UR */
        srl     $t8, $t8, 4             /* UUR */
        xor     $t8, $t8, $at
        sltiu   $t8, $t8, 1
        sll     $t8, $t8, 7
        or      $t9, $t9, $t8           /* UUR == UR */
        andi    $v1, $v1, 15
        xor     $v1, $v1, $at
        sltiu   $v1, $v1, 1
        sll     $v1, $v1, 5
        or      $t9, $t9, $v1           /* URR == UR */
        srl     $v1, $t6, 4             /* UU */
        xor     $v1, $v1, $v0
        sltiu   $v1, $v1, 1
        sll     $v1, $v1, 6
        or      $t9, $t9, $v1           /* UU == U */
        xor     $at, $at, $v0
        sltiu   $at, $at, 1
        sll     $at, $at, 1
        or      $t9, $t9, $at           /* UR == U */
        sltiu   $at, $v0, 15
        sll     $at, $at, 2
        or      $t9, $t9, $at           /* U != 15 */
        andi    $at, $t4, 0xf0
        srl     $at, $at, 1             /* state << 3 = (pos << 3) + 8 (add: state 4 overlaps bit 5) */
        addu    $t9, $t9, $at
        addu    $at, $a3, $t9
        bal     bit
        lbu     $t9, -648($at)          /* (delay) cont[c] (-640 - 8) */
        bnez    $at, rcont
        andi    $at, $t4, 0xf0          /* (delay) state << 4 */
        xor     $t4, $t4, $at           /* run ends: state 0 (V below needs nibble 1 clear), pixel != U */
        b       full
        ori     $t3, $t3, 1             /* known != U */
rcont:  sltiu   $t8, $at, 0x40          /* continue: pixel = U (v0), state + 1 (max 4) */
        sll     $t8, $t8, 4
        b       store
        addu    $t8, $t8, $at

/* ---- tree walk from entry[jump[L << 4 | U]] */
full:   andi    $at, $t4, 15            /* L */
        sll     $at, $at, 4
        or      $at, $at, $v0           /* L << 4 | U   (v0 = U from pix2) */
        addu    $at, $a3, $at
        lbu     $t8, -256($at)          /* jump: 2 * entry index */
        lbu     $v1, 1($t2)             /* UR */
        addu    $t8, $a3, $t8
        lhu     $t8, -384($t8)          /* 4 * start node index */
        lbu     $at, 2($t2)             /* URR */
        sll     $t7, $v0, 4
        or      $t7, $t7, $t4
        srl     $v0, $t6, 4
        sll     $v0, $v0, 20
        or      $t7, $t7, $v0
        andi    $v1, $v1, 15
        sll     $v1, $v1, 12
        or      $t7, $t7, $v1
        sll     $at, $at, 28
        or      $t7, $t7, $at           /* V */
        addu    $t8, $a3, $t8
walk:   lw      $t9, 0($t8)
        addiu   $t8, $t8, 4
        andi    $v1, $t9, 0x8c00
        srlv    $v0, $t7, $t9
        bnez    $v1, wspec
        andi    $at, $v0, 1
wtest:  beqz    $at, walk
        srl     $v0, $t9, 14
        b       walk
        addu    $t8, $a3, $v0
wspec:  andi    $at, $t9, 0x8000
        bnez    $at, leaf
        andi    $at, $t9, 0x0800
        bnez    $at, wpair
        andi    $v0, $v0, 15
        xori    $v0, $v0, 15
        b       wtest
        sltiu   $at, $v0, 1
wpair:  srl     $v1, $t9, 5
        srlv    $v1, $t7, $v1
        xor     $v0, $v0, $v1
        andi    $v0, $v0, 15
        b       wtest
        sltiu   $at, $v0, 1

leaf:   andi    $t9, $t9, 0x7fff        /* 17 * leaf (record offset) */
        andi    $at, $t3, 1
        bnez    $at, lit_k              /* known != U: no e bit */
        addu    $t8, $t5, $t9           /* (delay) record */
        bal     bit
        lbu     $t9, 0($t8)             /* (delay) p[0] */
        beqz    $at, litL
        andi    $v0, $t6, 15            /* (delay) U */
        b       store                   /* pixel = U, run starts */
        ori     $t8, $zero, 0x10
lit_k:  xori    $t3, $t3, 1
litL:   andi    $v0, $t4, 15            /* L */
        andi    $at, $t6, 15            /* U */
        beq     $v0, $at, lit4b         /* L == U: no L bit */
        ori     $t7, $zero, 1           /* (delay) idx */
        bal     bit
        lbu     $t9, 16($t8)            /* (delay) lprob */
        beqz    $at, lit4
        andi    $v0, $t4, 15            /* (delay) L */
        b       store                   /* pixel = L */
        move    $t8, $zero
lit4:                                   /* t7 = 1 (set in the L-check delay slot) */
lit4b:  addu    $at, $t8, $t7
lit:    sll     $t7, $t7, 1
        bal     bit
        lbu     $t9, 0($at)             /* (delay) p[idx] */
        or      $t7, $t7, $at
        sltiu   $at, $t7, 16
        bnez    $at, lit
        addu    $at, $t8, $t7           /* (delay) next p[idx] address */
        addiu   $v0, $t7, -16
        b       store
        move    $t8, $zero

/* ---- bit: t9 = P(bit 0) * 256 -> at = bit; clobbers v1 (range-coder state t0 / t1, stream a0) */
bit:    srl     $v1, $t1, 8
        multu   $t9, $v1
        mflo    $v1
        sltu    $at, $t0, $v1
        bnez    $at, 1f
        xori    $at, $at, 1             /* (delay) at = bit */
        subu    $t0, $t0, $v1           /* bit 1 */
        b       2f
        subu    $t1, $t1, $v1
1:      move    $t1, $v1                /* bit 0 */
2:      srl     $v1, $t1, 24
        bnez    $v1, 4f
        nop
norm3:
3:      lbu     $v1, 0($a0)
        sll     $t1, $t1, 8
        sll     $t0, $t0, 8
        or      $t0, $t0, $v1
        srl     $v1, $t1, 24
        beqz    $v1, 3b
        addiu   $a0, $a0, 1
4:      jr      $ra
        nop

/* ---- v0 = pixel, t8 = new state << 4 */
store:  andi    $v1, $t6, 15            /* U */
        sll     $at, $v1, 4
        or      $at, $at, $v0
        sb      $at, 0($t2)             /* rb[x] = pixel | U << 4 */
        andi    $at, $t2, 1
        beqz    $at, 6f
        sll     $v1, $v1, 8
        andi    $at, $t4, 15            /* x odd: byte = L | pixel << 4 */
        sll     $t9, $v0, 4
        or      $at, $at, $t9
        sb      $at, 0($a1)
        addiu   $a1, $a1, 1
6:      andi    $t9, $t4, 0x0f0f
        sll     $t9, $t9, 16
        or      $t4, $v0, $v1
        or      $t4, $t4, $t9
        or      $t4, $t4, $t8           /* L = pixel, UL = U, LL = L, ULL = UL, state */
        addiu   $t2, $t2, 1
        bne     $t2, $t3, pix2
        lbu     $t6, 0($t2)             /* (delay) next pixel's U | UU; harmless at the row end */
        bne     $a1, $a2, row
        lui     $t9, 0x1f80             /* (delay, harmless) */
        lw      $ra, 0x3fc($t9)
        nop
        jr      $ra
        nop
dsr_end:
