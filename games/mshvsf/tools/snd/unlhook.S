# Runtime hook of the stock sound-bank unload 0x8007b06c(bank) (tools/snd/snd.c installs it at 0x801ff000 and puts
# `j 0x801ff000; nop` over the function's first two instructions).  Besides the stock work (the bank's entries in the
# table 0x8007d330), drop the bank's overflow entries OVF[0..OVFN): id table 0x8007e220[id] = 0 where it points at
# the entry, entry id 0, bank 0xff.  Then the two replaced instructions and back.  a0 (bank) is kept; t0-t9 only.
        .set noreorder
        .set noat
        .section .text
        .globl unlhook
unlhook:
        lui     $t0, 0x8020
        lw      $t1, -0x0f84($t0)       # OVFN 0x801ff07c
        addiu   $t2, $t0, -0x0f80       # OVF  0x801ff080
        andi    $t9, $a0, 0xff
1:      beqz    $t1, 3f
        nop
        lbu     $t3, 0x11($t2)
        lh      $t4, 0($t2)
        bne     $t3, $t9, 2f
        sll     $t5, $t4, 2
        lui     $t6, 0x8008
        addu    $t6, $t6, $t5
        lw      $t7, -0x1de0($t6)       # id table 0x8007e220
        nop
        bne     $t7, $t2, 21f
        nop
        sw      $zero, -0x1de0($t6)
21:     sh      $zero, 0($t2)
        ori     $t3, $zero, 0xff
        sb      $t3, 0x11($t2)
2:      addiu   $t2, $t2, 20
        b       1b
        addiu   $t1, $t1, -1
3:      addiu   $sp, $sp, -0x20
        j       0x8007b074
        move    $a1, $zero
