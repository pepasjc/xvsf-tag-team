# Frame cache: the rect allocator 0x8005883c found no room (its failure path at 0x80058ba4 jumps here).  If a
# resident rect could be dropped (fc_drop in draw.c), undo the allocator's frame (scratch stack S+0x70 -= 0x28,
# ra, s0, sp) and run it again from its entry with the same node; else its original failure path.
        .globl fc_evict
fc_evict:
        lw      $a0, 0x20($sp)             # the allocator's node (the request: +0xd w, +0xe h)
        jal     FC_DROP
        nop
        beqz    $v0, 1f
        lui     $a0, 0x8007
        lw      $a0, -0x5cc0($a0)          # S
        nop
        lw      $v1, 0x70($a0)
        nop
        addiu   $v1, $v1, -0x28
        sw      $v1, 0x70($a0)
        lw      $a0, 0x20($sp)
        lw      $ra, 0x1c($sp)
        lw      $s0, 0x18($sp)
        j       0x8005883c
        addiu   $sp, $sp, 0x20
1:      lw      $v0, 0x20($sp)             # the original failure path: 0x80055334, DrawSync loop, purge, retry
        jal     0x80055334
        sb      $zero, 9($v0)
        j       0x80058bb0
        nop
