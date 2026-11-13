# _exeque at 0x800187f0: start queued GPU operations while DMA2 is idle.  Register-exact like _addque (gpuq.S):
# writes only at, v0, v1, a0, a1 (+ s0 saved), with the stock final values on every path.
exeque:
    lui   $v0, 0x8002
    lw    $v0, 0x2604($v0)
    addiu $sp, $sp, -0x18
    sw    $ra, 0x14($sp)
    sw    $s0, 0x10($sp)
    lw    $v0, 0($v0)
    lui   $s0, 0x0100
    and   $v0, $v0, $s0
    bnez  $v0, 9f
    addiu $v0, $zero, 1
    jal   0x80011cc0                    # SetIntrMask(0)
    move  $a0, $zero
    lui   $at, 0x8002
    lw    $a0, 0x2628($at)
    lw    $v1, 0x262c($at)
    sw    $v0, 0x2634($at)
    beq   $a0, $v1, 5f
    nop
    lw    $v0, 0x2604($at)
    nop
    lw    $v0, 0($v0)
    nop
    and   $v0, $v0, $s0
    bnez  $v0, 5f
    nop
1:  lw    $v0, 0x262c($at)              # (at = 0x80020000 here)
    lw    $v1, 0x2628($at)
    addiu $v0, $v0, 1
    andi  $v0, $v0, 0x3f
    bne   $v0, $v1, 2f                  # starting the last queued entry:
    nop
    lw    $v0, 0x2530($at)
    nop
    bnez  $v0, 2f
    addiu $a0, $zero, 2
    jal   0x80011ba4                    # DMACallback(2, 0)
    move  $a1, $zero
2:  lui   $a0, 0x8002
    lw    $a0, 0x25f8($a0)
    nop
    lw    $v0, 0($a0)
    lui   $v1, 0x0400
    and   $v0, $v0, $v1
    bnez  $v0, 4f
    move  $v1, $a0
    j     kchk                          # GPU busy: kchk (gpuq3.S) leaves the entry queued when called non-blocking
    lui   $at, 0x8002                   # from addque (-> exq5; it reads at), else back to exq3 (at is rewritten after the call)
exq3:
    lui   $a0, 0x0400
3:  lw    $v0, 0($v1)
    nop
    and   $v0, $v0, $a0
    beqz  $v0, 3b
    nop
4:  lui   $v1, 0x8002
    lw    $v1, 0x262c($v1)
    nop
    sll   $at, $v1, 1
    addu  $at, $at, $v1
    sll   $v1, $at, 5                   # v1 = R * 0x60 (as stock at the call)
    lui   $at, 0x8002
    addu  $at, $at, $v1
    lw    $a0, 0x5f8c($at)
    lw    $a1, 0x5f90($at)
    lw    $v0, 0x5f88($at)
    nop
    jalr  $v0
    nop
    lui   $at, 0x8002                   # after the call stock writes only v0, v1, at
    lw    $v1, 0x262c($at)
    nop
    sll   $v0, $v1, 1
    addu  $v0, $v0, $v1
    sll   $v0, $v0, 5
    addu  $v0, $v0, $at
    lw    $v1, 0x5f88($v0)
    nop
    sw    $v1, 0x2618($at)
    lw    $v1, 0x5f8c($v0)
    nop
    sw    $v1, 0x261c($at)
    lw    $v1, 0x5f90($v0)
    nop
    sw    $v1, 0x2620($at)
    lw    $v0, 0x262c($at)
    nop
    addiu $v0, $v0, 1
    andi  $v0, $v0, 0x3f
    sw    $v0, 0x262c($at)
    lw    $v1, 0x2628($at)
    nop
    beq   $v1, $v0, 5f
    nop
    lw    $v0, 0x2604($at)
    nop
    lw    $v0, 0($v0)
    lui   $v1, 0x0100
    and   $v0, $v0, $v1
    beqz  $v0, 1b
    nop
5:
exq5:
    lui   $a0, 0x8002
    lw    $a0, 0x2634($a0)
    jal   0x80011cc0                    # SetIntrMask(saved) (keeps at = 0x80020000)
    nop
    lw    $v1, 0x2628($at)
    lw    $v0, 0x262c($at)
    nop
    bne   $v1, $v0, 8f
    nop
    lw    $v0, 0x2604($at)
    nop
    lw    $v0, 0($v0)
    lui   $v1, 0x0100
    and   $v0, $v0, $v1
    bnez  $v0, 8f
    nop
    addiu $v1, $at, 0x252c
    lw    $v0, 0($v1)
    nop
    beqz  $v0, 8f
    nop
    lw    $v0, 0x2530($at)
    nop
    beqz  $v0, 8f
    nop
    sw    $zero, 0($v1)
    jalr  $v0                           # drawsync callback
    nop
8:  lui   $v0, 0x8002
    lw    $v0, 0x2628($v0)
    lui   $v1, 0x8002
    lw    $v1, 0x262c($v1)
    nop
    subu  $v0, $v0, $v1
    andi  $v0, $v0, 0x3f
9:  lw    $ra, 0x14($sp)
    lw    $s0, 0x10($sp)
    jr    $ra
    addiu $sp, $sp, 0x18
exeque_end:

# ---------------------------------------------------------------- early BG (called from present.S)
# v0 = 1 when the next frame's BG may be built now (present.S builds it, DrawOTag deferred by the shim).
# Conditions: battle (0x800421ad == 1), no one-shot pending (0x8004218f == 0), frame skip off (0x800421c2 == 0,
# always in battle), stage in EB_STAGES, and no pending or running libgpu queue entry whose argument lies in
# the stage overlay (= this frame's BG OTs: their prims are about to be rewritten).
ebg:
    lui   $a3, 0x8004
    lb    $v0, 0x21ad($a3)
    lbu   $v1, 0x218f($a3)
    addiu $v0, $v0, -1
    or    $v0, $v0, $v1
    lb    $v1, 0x21c2($a3)
    nop
    or    $v0, $v0, $v1
    bnez  $v0, 9f
    lb    $v1, 0x2781($a3)
    ori   $v0, $zero, EB_STAGES
    srlv  $v0, $v0, $v1
    andi  $v0, $v0, 1
    beqz  $v0, 9f
    lui   $t1, 0x8002
    lw    $t2, 0x262c($t1)
    lw    $t3, 0x2628($t1)
    lui   $t5, 0x8009
    ori   $t5, $t5, 0x8000              # overlay base 0x80098000
    lui   $t6, 1
    ori   $t6, $t6, 0x8000              # overlay span 0x18000
1:  beq   $t2, $t3, 3f
    sll   $t4, $t2, 1
    addu  $t4, $t4, $t2
    sll   $t4, $t4, 5
    addu  $t4, $t4, $t1
    lw    $a0, 0x5f8c($t4)
    addiu $t2, $t2, 1
    andi  $t2, $t2, 0x3f
    subu  $a0, $a0, $t5
    sltu  $a0, $a0, $t6
    bnez  $a0, 9f
    nop
    b     1b
    nop
3:  lw    $t4, 0x2604($t1)
    lw    $a0, 0x261c($t1)
    lw    $t4, 0($t4)
    subu  $a0, $a0, $t5
    sltu  $a0, $a0, $t6
    srl   $t4, $t4, 24
    and   $a0, $a0, $t4
    jr    $ra                           # a0 is 0 or 1
    xori  $v0, $a0, 1
9:  jr    $ra
    move  $v0, $zero
gpuq2_end:
