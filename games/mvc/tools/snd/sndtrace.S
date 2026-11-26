# Test-only tracer of MvC sound requests: hook inside the play function at 0x80086af0 (after its first two
# instructions, i.e. after the sound module's stub / swap: the trace resolves what the play function will use).
# Ring of 32 x 8 bytes at RING: u16 id, u8 a1>>8, u8 a2, u32 ra.  Counter at RING - 4.
        .set noreorder
        .set noat
        .globl sndtrace
sndtrace:
        lui     $t8, %hi(RING)
        addiu   $t8, $t8, %lo(RING)
        lw      $t9, -4($t8)
        nop
        andi    $t7, $t9, 31
        sll     $t7, $t7, 3
        addu    $t7, $t7, $t8
        sh      $a0, 0($t7)
        srl     $t6, $a1, 8
        sb      $t6, 2($t7)
        sb      $a2, 3($t7)
        sw      $ra, 4($t7)
        addiu   $t9, $t9, 1
        sw      $t9, -4($t8)
        sw      $s6, 0x78($sp)
        j       0x80086af8
        srl     $s6, $a1, 8
