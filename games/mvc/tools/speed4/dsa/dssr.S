/* dssr.S (dx worker, 2026-11-19): row-resumable DSR1 decoder for decode-ahead slices.  Same algorithm and register use
 * as tools/codec2/dsrdec.S (v3, the CPU worker's), wrapped like dss.S (DSA1): dssr_run(a0 = state) decodes at most
 * state+0x20 rows, then suspends at a row boundary (DSR1's run state resets at every row start and the "known != U" flag
 * is always consumed inside the row, so a row boundary holds only: stream, dst, end, model pointers, code, range and
 * the row buffer).  Returns v0 = 1 when the tile is complete, 0 when suspended.
 * State (0x130 B, dss.S layout): +0 src (stream) +4 dst +8 n (start) / end (resumed) +0xc pixel section (start) /
 * &node[0] (resumed) +0x10 code +0x14 range +0x18 W bytes of rb (0 = not started) +0x1c leaf records +0x20 rows allowed
 * +0x2c saved s2 +0x30.. rb[0 .. W+7].  Scratchpad 0x1f800300.. rb, 0x1f8003fc caller's ra (bal clobbers ra).
 * Caller-saved registers + s2 (saved in the state), no stack, position-independent. */
        .set    noreorder
        .set    noat
        .text
        .globl  dssr_run

dssr_run:
        lui     $t9, 0x1f80
        sw      $ra, 0x3fc($t9)
        sw      $s2, 0x2c($a0)
        move    $s2, $a0
        lw      $t3, 0x18($s2)          /* rb bytes, 0 = start */
        lw      $a1, 4($s2)
        bnez    $t3, resume
        lw      $a2, 8($s2)
        lw      $a3, 0xc($s2)           /* pixel section */
        lw      $a0, 0($s2)
        lhu     $v0, 8($a3)             /* 4 * node count */
        addiu   $a3, $a3, 656           /* &node[0] */
        addu    $t5, $a3, $v0           /* leaf records */
        lbu     $t3, 0($a0)             /* width in bytes */
        lbu     $t0, 1($a0)
        addiu   $a0, $a0, 2
        bal     norm3
        ori     $t1, $zero, 1
        addiu   $t1, $zero, -1
        addu    $a2, $a1, $a2           /* end of output */
        sll     $t3, $t3, 1
        lui     $t9, 0x1f80
        ori     $t2, $t9, 0x0300
        addu    $t3, $t2, $t3           /* &rb[W] */
        addiu   $v0, $zero, -1
        move    $t8, $t2
0:      sw      $v0, 0($t8)             /* rb[0 .. W+7] = 0xff */
        sltu    $v1, $t3, $t8
        beqz    $v1, 0b
        addiu   $t8, $t8, 4
        b       row
        nop

resume: lw      $a0, 0($s2)
        lw      $a3, 0xc($s2)
        lw      $t0, 0x10($s2)
        lw      $t1, 0x14($s2)
        lw      $t5, 0x1c($s2)
        lui     $t2, 0x1f80
        ori     $t2, $t2, 0x0300
        addu    $t3, $t2, $t3           /* &rb[W] */
        addiu   $t8, $s2, 0x30
        move    $t9, $t2
1:      lw      $v0, 0($t8)             /* rb[0 .. W+7] back */
        addiu   $t8, $t8, 4
        sw      $v0, 0($t9)
        sltu    $v1, $t3, $t9
        beqz    $v1, 1b
        addiu   $t9, $t9, 4

row:    lui     $t4, 0x0f0f
        ori     $t4, $t4, 0x0f0f
        lui     $t2, 0x1f80
        ori     $t2, $t2, 0x0300
pix:    lbu     $t6, 0($t2)
pix2:   andi    $v0, $t4, 0xf0
        beqz    $v0, full
        andi    $v0, $t6, 15
        srl     $at, $t4, 8
        andi    $at, $at, 15
        xor     $at, $at, $v0
        sltiu   $t9, $at, 1
        lbu     $t8, 1($t2)
        lbu     $v1, 2($t2)
        andi    $at, $t8, 15
        srl     $t8, $t8, 4
        xor     $t8, $t8, $at
        sltiu   $t8, $t8, 1
        sll     $t8, $t8, 7
        or      $t9, $t9, $t8
        andi    $v1, $v1, 15
        xor     $v1, $v1, $at
        sltiu   $v1, $v1, 1
        sll     $v1, $v1, 5
        or      $t9, $t9, $v1
        srl     $v1, $t6, 4
        xor     $v1, $v1, $v0
        sltiu   $v1, $v1, 1
        sll     $v1, $v1, 6
        or      $t9, $t9, $v1
        xor     $at, $at, $v0
        sltiu   $at, $at, 1
        sll     $at, $at, 1
        or      $t9, $t9, $at
        sltiu   $at, $v0, 15
        sll     $at, $at, 2
        or      $t9, $t9, $at
        andi    $at, $t4, 0xf0
        srl     $at, $at, 1
        addu    $t9, $t9, $at
        addu    $at, $a3, $t9
        bal     bit
        lbu     $t9, -648($at)
        bnez    $at, rcont
        andi    $at, $t4, 0xf0
        xor     $t4, $t4, $at
        b       full
        ori     $t3, $t3, 1
rcont:  sltiu   $t8, $at, 0x40
        sll     $t8, $t8, 4
        b       store
        addu    $t8, $t8, $at

full:   andi    $at, $t4, 15
        sll     $at, $at, 4
        or      $at, $at, $v0
        addu    $at, $a3, $at
        lbu     $t8, -256($at)
        lbu     $v1, 1($t2)
        addu    $t8, $a3, $t8
        lhu     $t8, -384($t8)
        lbu     $at, 2($t2)
        sll     $t7, $v0, 4
        or      $t7, $t7, $t4
        srl     $v0, $t6, 4
        sll     $v0, $v0, 20
        or      $t7, $t7, $v0
        andi    $v1, $v1, 15
        sll     $v1, $v1, 12
        or      $t7, $t7, $v1
        sll     $at, $at, 28
        or      $t7, $t7, $at
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

leaf:   andi    $t9, $t9, 0x7fff
        andi    $at, $t3, 1
        bnez    $at, lit_k
        addu    $t8, $t5, $t9
        bal     bit
        lbu     $t9, 0($t8)
        beqz    $at, litL
        andi    $v0, $t6, 15
        b       store
        ori     $t8, $zero, 0x10
lit_k:  xori    $t3, $t3, 1
litL:   andi    $v0, $t4, 15
        andi    $at, $t6, 15
        beq     $v0, $at, lit4b
        ori     $t7, $zero, 1
        bal     bit
        lbu     $t9, 16($t8)
        beqz    $at, lit4
        andi    $v0, $t4, 15
        b       store
        move    $t8, $zero
lit4:
lit4b:  addu    $at, $t8, $t7
lit:    sll     $t7, $t7, 1
        bal     bit
        lbu     $t9, 0($at)
        or      $t7, $t7, $at
        sltiu   $at, $t7, 16
        bnez    $at, lit
        addu    $at, $t8, $t7
        addiu   $v0, $t7, -16
        b       store
        move    $t8, $zero

bit:    srl     $v1, $t1, 8
        multu   $t9, $v1
        mflo    $v1
        sltu    $at, $t0, $v1
        bnez    $at, 1f
        xori    $at, $at, 1
        subu    $t0, $t0, $v1
        b       2f
        subu    $t1, $t1, $v1
1:      move    $t1, $v1
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

store:  andi    $v1, $t6, 15
        sll     $at, $v1, 4
        or      $at, $at, $v0
        sb      $at, 0($t2)
        andi    $at, $t2, 1
        beqz    $at, 6f
        sll     $v1, $v1, 8
        andi    $at, $t4, 15
        sll     $t9, $v0, 4
        or      $at, $at, $t9
        sb      $at, 0($a1)
        addiu   $a1, $a1, 1
6:      andi    $t9, $t4, 0x0f0f
        sll     $t9, $t9, 16
        or      $t4, $v0, $v1
        or      $t4, $t4, $t9
        or      $t4, $t4, $t8
        addiu   $t2, $t2, 1
        bne     $t2, $t3, pix2
        lbu     $t6, 0($t2)
/* row end: tile done, or one more row allowed, or suspend */
        beq     $a1, $a2, done
        nop
        lw      $v0, 0x20($s2)
        nop
        addiu   $v0, $v0, -1
        bgtz    $v0, row
        sw      $v0, 0x20($s2)
        sw      $a0, 0($s2)             /* suspend */
        sw      $a1, 4($s2)
        sw      $a2, 8($s2)
        sw      $a3, 0xc($s2)
        sw      $t0, 0x10($s2)
        sw      $t1, 0x14($s2)
        sw      $t5, 0x1c($s2)
        lui     $t2, 0x1f80
        ori     $t2, $t2, 0x0300
        subu    $v0, $t3, $t2
        sw      $v0, 0x18($s2)          /* rb bytes (W, non-zero: started) */
        addiu   $t8, $s2, 0x30
        move    $t9, $t2
5:      lw      $v0, 0($t9)             /* rb[0 .. W+7] -> state */
        addiu   $t9, $t9, 4
        sw      $v0, 0($t8)
        sltu    $v1, $t3, $t9
        beqz    $v1, 5b
        addiu   $t8, $t8, 4
        b       exit
        move    $v0, $zero
done:   sw      $zero, 0x18($s2)
        ori     $v0, $zero, 1
exit:   lui     $t9, 0x1f80
        lw      $ra, 0x3fc($t9)
        lw      $s2, 0x2c($s2)
        jr      $ra
        nop
dssr_end:
