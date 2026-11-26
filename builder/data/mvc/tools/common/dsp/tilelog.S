/* Test-only wrapper around the tile decoder (common/dsp/tilecheck.py): the game's jal sites are pointed here.
 * Calls DEC(a0, a1, a2), then logs (src, n, checksum of dst[0..n)) at LOG+4+12*count (count at LOG, capped at
 * MAXN; the harness reads and resets it every frame).  checksum: s = s*33 + byte, 32 bits. */
        .set    noreorder
        .set    noat
        .text
        .globl  wrap
wrap:   lui     $t9, %hi(SAVE)
        addiu   $t9, $t9, %lo(SAVE)
        sw      $ra, 12($t9)
        sw      $a0, 0($t9)
        sw      $a1, 4($t9)
        jal     DEC
        sw      $a2, 8($t9)
        lui     $t9, %hi(SAVE)
        addiu   $t9, $t9, %lo(SAVE)
        lw      $a1, 4($t9)
        lw      $a2, 8($t9)
        move    $t0, $zero
        blez    $a2, 2f
        addu    $t2, $a1, $a2
1:      lbu     $t3, 0($a1)
        addiu   $a1, $a1, 1
        sll     $t4, $t0, 5
        addu    $t0, $t4, $t0
        bne     $a1, $t2, 1b
        addu    $t0, $t0, $t3
2:      lui     $t5, %hi(LOG)
        addiu   $t5, $t5, %lo(LOG)
        lw      $t6, 0($t5)
        lw      $a0, 0($t9)
        sltiu   $at, $t6, MAXN
        beqz    $at, 3f
        sll     $t7, $t6, 1
        addu    $t7, $t7, $t6
        sll     $t7, $t7, 2
        addu    $t7, $t7, $t5
        sw      $a0, 4($t7)
        sw      $a2, 8($t7)
        sw      $t0, 12($t7)
3:      addiu   $t6, $t6, 1
        sw      $t6, 0($t5)
        lw      $ra, 12($t9)
        nop
        jr      $ra
        nop
