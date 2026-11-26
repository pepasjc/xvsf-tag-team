# Entry of the RAM swap code (linked right after struct swd at 0x801fe800): called by the EXE stub (stubs.S) with the
# play function's arguments untouched; saves them, runs snd_swapchk(id), then the play function's two replaced
# instructions and back into it.
        .set noreorder
        .set noat
        .section .text.entry, "ax"
        .globl swentry
swentry:
        addiu   $sp, $sp, -0x28
        sw      $ra, 0x10($sp)
        sw      $a0, 0x14($sp)
        sw      $a1, 0x18($sp)
        sw      $a2, 0x1c($sp)
        jal     snd_swapchk
        sw      $a3, 0x20($sp)
        lw      $ra, 0x10($sp)
        lw      $a0, 0x14($sp)
        lw      $a1, 0x18($sp)
        lw      $a2, 0x1c($sp)
        lw      $a3, 0x20($sp)
        addiu   $sp, $sp, 0x28
        addiu   $sp, $sp, -0x88
        j       0x80086af0
        andi    $a1, $a1, 0xff00
