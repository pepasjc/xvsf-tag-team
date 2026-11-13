# Region 0x80028b58-0x80028d60: stock draw + present 0x80028b58 rewritten compactly (same calls, same order,
# same stores), plus EARLY BG: the next frame's BG layers (0x80028908 = bsp) are built while the GPU draws
# this frame's sprites (the DrawSync wait), their DrawOTag calls recorded instead of issued (DrawOTag shim),
# and issued at the stock point (after flip, CLUT upload, palette animation) in the same order.
# Taken only when: battle mode (0x800421ad == 1), stage in EB_STAGES (BG code calls only TermPrim/DrawOTag and
# touches nothing the code between the two points reads or writes - static check work/speed/frame/bgdeps.py),
# no one-shot pending (0x8004218f == 0), and no pending or running libgpu queue entry has an argument inside
# the stage overlay (this frame's BG OTs are done, their prims may be rewritten).  ebg is in logic.S, the
# DrawOTag shim in entry.S.  Symbols from other regions: bsp, fromidx, oneshot, ebg (passed with .set).

present:
    lui   $a3, 0x8004
    lb    $v0, -0x2ec3($a3)            # 0x8003d13d frame-skip flag (0 in battle)
    addiu $sp, $sp, -0x18
    sw    $ra, 0x14($sp)
    bnez  $v0, 1f
    sw    $s0, 0x10($sp)
    lw    $v0, -0x2ecc($a3)            # 0x8003d134 current draw/disp env
    lui   $a0, 0x8006
    addiu $a0, $a0, -0x2648            # 0x8005d9b8
    bne   $v0, $a0, 2f
    nop
    addiu $a0, $a0, 0x70
2:  jal   fromidx
    sw    $a0, -0x2ecc($a3)
1:  jal   0x8006dfd4
    nop
    jal   0x80011960                   # VSync(-1)
    addiu $a0, $zero, -1
    jal   0x8002c960
    move  $s0, $v0
    lui   $v0, 0x8004
    lb    $v0, -0x2ec3($v0)
    nop
    bnez  $v0, 3f
    nop
    jal   ebg                          # early BG allowed now?
    nop
    beqz  $v0, 7f
    lui   $t9, %hi(EBV)
    sw    $v0, %lo(EBV)($t9)           # mode 1: the shim records the DrawOTag heads
    sw    $zero, %lo(EBV)+8($t9)
    lui   $a0, 0x8004
    jal   bsp
    lw    $a0, -0x2ecc($a0)
    lui   $t9, %hi(EBV)
    sw    $zero, %lo(EBV)($t9)
    sw    $t9, %lo(EBV)+4($t9)         # done (non-zero): issue at the stock point
7:  jal   ahook                        # AHEAD hook (gpuq.S): callback(a0 = deadline, a1 = late) if installed
    nop
  jal   oneshot
    nop
    jal   0x80016454                   # DrawSync(0)
    move  $a0, $zero
    jal   0x80011960                   # VSync(0)
    move  $a0, $zero
    lui   $a0, 0x8004
    lw    $a0, -0x2ecc($a0)
    jal   0x80016d20                   # PutDispEnv
    addiu $a0, $a0, 0x5c
    lui   $a0, 0x8004
    jal   0x80016ac8                   # PutDrawEnv
    lw    $a0, -0x2ecc($a0)
3:  jal   0x80057a00
    nop
    lui   $a3, 0x8004
    lb    $v0, 0x21c2($a3)
    sb    $zero, -0x2ec3($a3)
    beqz  $v0, 4f
    nop
    lh    $v0, 0x212a($a3)
    nop
    bltz  $v0, 4f
    nop
    lb    $v0, -0x2ec4($a3)            # 0x8003d13c
    nop
    slti  $v0, $v0, 2
    bnez  $v0, 4f
    nop
    lw    $v0, -0x2ec8($a3)            # 0x8003d138
    nop
    subu  $v0, $s0, $v0
    sltiu $v0, $v0, 2
    bnez  $v0, 4f
    ori   $v0, $zero, 1
    sb    $v0, -0x2ec3($a3)
    sb    $zero, -0x2ec4($a3)
4:  lbu   $v0, -0x2ec4($a3)
    sw    $s0, -0x2ec8($a3)
    addiu $v0, $v0, 1
    jal   0x8002c1a8
    sb    $v0, -0x2ec4($a3)
    lui   $a3, 0x8004                  # scroll copies 0x80041e24.. -> 0x80041e2c..
    lhu   $v0, 0x1e24($a3)
    lhu   $v1, 0x1e28($a3)
    lhu   $a0, 0x1ebc($a3)
    lhu   $a1, 0x1ec0($a3)
    lhu   $a2, 0x1f34($a3)
    lhu   $t0, 0x1f38($a3)
    lhu   $t1, 0x1fac($a3)
    lhu   $t3, 0x1fb0($a3)
    lb    $t2, -0x2ec3($a3)
    sh    $v0, 0x1e2c($a3)
    sh    $v1, 0x1e2e($a3)
    sh    $a0, 0x1ec4($a3)
    sh    $a1, 0x1ec6($a3)
    sh    $a2, 0x1f3c($a3)
    sh    $t0, 0x1f3e($a3)
    sh    $t1, 0x1fb4($a3)
    bnez  $t2, 9f
    sh    $t3, 0x1fb6($a3)
    jal   0x8002a840
    lui   $s0, %hi(EBV)                # (s0 is preserved by the callee; its VSync value is stored already)
    lw    $v0, %lo(EBV)+4($s0)         # early BG done this frame?
    lui   $a0, 0x8004
    beqz  $v0, 6f
    lw    $a0, -0x2ecc($a0)
    sw    $zero, %lo(EBV)+4($s0)
    addiu $s0, $s0, %lo(EBV)+16        # issue the recorded DrawOTags in order
5:  lui   $v0, %hi(EBV)
55: lw    $v0, %lo(EBV)+8($v0)         # count
    lui   $v1, %hi(EBV)
    addiu $v1, $v1, %lo(EBV)+16
    sll   $v0, $v0, 2
    addu  $v0, $v0, $v1
    sltu  $v0, $s0, $v0
    beqz  $v0, 9f
    nop
    lw    $a0, 0($s0)
    jal   0x80016a54
    addiu $s0, $s0, 4
    b     55b
    lui   $v0, %hi(EBV)
6:  jal   bsp                          # stock path
    nop
9:  jal   0x8004e94c
    nop
    lw    $ra, 0x14($sp)
    lw    $s0, 0x10($sp)
    jr    $ra
    addiu $sp, $sp, 0x18

present_end:
