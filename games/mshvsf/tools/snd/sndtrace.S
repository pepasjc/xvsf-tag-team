# Test-only tracer of sound requests: hook at the play function 0x8007a920 (j sndtrace; nop).
# Ring of 32 x 8 bytes at RING: u16 id, u8 a1>>8 (pan / side), u8 a2, u32 ra.  Counter at RING - 4.
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
        addiu   $sp, $sp, -0x80
        j       0x8007a928
        andi    $a1, $a1, 0xff00
