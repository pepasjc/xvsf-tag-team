# Region 0x80028868-0x80028b58 (stock: layer dispatch 0x80028868, layers-before-sprites 0x80028908,
# layers-from-index 0x80028994, DrawSync + one-shot dispatcher 0x80028a1c).  Rewritten compactly with the
# same behaviour; entry points move (their only callers are in 0x80028b58 and are re-pointed by frame.py).
# The one-shot dispatcher's jump table 0x800280e8 (13 words, only read by 0x80028a1c) now holds the
# called functions themselves (bit 0 set = pass a0 = 0x80042180, 0 = no call).
# Freed space: BIOS A0 memcpy entry and bzero / memset (see splist.S for the conventions).
# Assembled at 0x80028868.

layer:                                  # layer(type a0, buf a1): stock 0x80028868
    addiu $sp, $sp, -0x18
    bnez  $a0, 1f
    sw    $ra, 0x10($sp)
    jal   0x8002d100                    # 0: sprites
    nop
    jal   0x8002e6bc
    nop
    jal   0x80057ad8
    nop
    jal   0x8002d134
    nop
    b     9f
    nop
1:  addiu $v0, $a0, -1                  # 1..4: 0x8001b094 + (type-1) * 0x90 (a0 = buf)
    sltiu $v1, $v0, 4
    beqz  $v1, 9f
    sll   $v1, $v0, 4
    sll   $v0, $v0, 7
    addu  $v0, $v0, $v1
    lui   $v1, 0x8002
    addiu $v1, $v1, -0x4f6c
    addu  $v0, $v0, $v1
    jalr  $v0
    move  $a0, $a1
9:  lw    $ra, 0x10($sp)
    addiu $sp, $sp, 0x18
    jr    $ra
    nop

bsp:                                    # stock 0x80028908(buf): index 0x80040db8 = 0, run layers until a 0 entry
    lui   $v0, 0x8004
    lb    $v0, 0xdb0($v0)
    addiu $sp, $sp, -0x18
    sw    $s0, 0x10($sp)
    sw    $ra, 0x14($sp)
    lui   $v1, 0x8004
    sb    $zero, 0xdb8($v1)
    beqz  $v0, 9f
    move  $s0, $a0
1:  lb    $v0, 0xdb8($v1)                # v1 = 0x80040000 here
    nop
    addu  $v0, $v0, $v1
    lb    $a0, 0xdb0($v0)
    jal   layer
    move  $a1, $s0
    lui   $v1, 0x8004
    lbu   $v0, 0xdb8($v1)
    nop
    addiu $v0, $v0, 1
    sb    $v0, 0xdb8($v1)
    sll   $v0, $v0, 24
    sra   $v0, $v0, 24
    addu  $v0, $v0, $v1
    lb    $v0, 0xdb0($v0)
    nop
    bnez  $v0, 1b
    nop
9:  lw    $ra, 0x14($sp)
    lw    $s0, 0x10($sp)
    jr    $ra
    addiu $sp, $sp, 0x18

fromidx:                                # stock 0x80028994(buf): run layers from index 0x80040db8 up to 4
    lui   $v1, 0x8004
    lb    $v0, 0xdb8($v1)
    addiu $sp, $sp, -0x20
    sw    $s0, 0x18($sp)
    move  $s0, $a0
    slti  $v0, $v0, 5
    beqz  $v0, 9f
    sw    $ra, 0x1c($sp)
1:  lb    $v0, 0xdb8($v1)                # v1 = 0x80040000 here
    nop
    addu  $v0, $v0, $v1
    lb    $a0, 0xdb0($v0)
    jal   layer
    move  $a1, $s0
    lui   $v1, 0x8004
    lbu   $v0, 0xdb8($v1)
    nop
    addiu $v0, $v0, 1
    sb    $v0, 0xdb8($v1)
    sll   $v0, $v0, 24
    sra   $v0, $v0, 24
    slti  $v0, $v0, 5
    bnez  $v0, 1b
    nop
9:  lw    $ra, 0x1c($sp)
    lw    $s0, 0x18($sp)
    jr    $ra
    addiu $sp, $sp, 0x20

oneshot:                                # stock 0x80028a1c
    lui   $v0, 0x8004
    lh    $v0, 0x212a($v0)
    addiu $sp, $sp, -0x18
    bltz  $v0, 9f
    sw    $ra, 0x10($sp)
    ori   $v0, $zero, 1
    lui   $at, 0x8004
    sb    $v0, -0x26e8($at)
    jal   0x80016454                    # DrawSync(0)
    move  $a0, $zero
    lui   $v0, 0x8004
    lbu   $v0, 0x218f($v0)
    nop
    addiu $v0, $v0, -1
    sll   $v0, $v0, 24
    sra   $v1, $v0, 24
    sltiu $v0, $v1, 13
    beqz  $v0, 9f
    sll   $v0, $v1, 2
    lui   $at, 0x8003
    addu  $at, $at, $v0
    lw    $v0, -0x7f18($at)
    nop
    beqz  $v0, 9f
    andi  $a0, $v0, 1
    beqz  $a0, 1f
    xor   $v0, $v0, $a0
    lui   $a0, 0x8004
    addiu $a0, $a0, 0x2180
1:  jalr  $v0
    nop
9:  lui   $at, 0x8004
    sb    $zero, 0x218f($at)
    lw    $ra, 0x10($sp)
    sb    $zero, -0x26e8($at)
    jr    $ra
    addiu $sp, $sp, 0x18

# ---------------------------------------------------------------- BIOS A0 functions (see splist.S)
f_memcpy:                               # memcpy(dst a0, src a1, n a2) -> dst
    beqz  $a0, mret0
    nop
    move  $v1, $a0
    blez  $a2, mdone
    move  $t0, $a0                      # swap: the core copies a0 -> a1
    move  $a0, $a1
    j     copy
    move  $a1, $t0

f_bzero:                                # bzero(dst a0, n a1) -> dst
    beqz  $a0, mret0
    nop
    blez  $a1, mret0
    nop
    move  $v1, $a0
    move  $t2, $a1
    b     fill
    move  $t0, $zero
f_memset:                               # memset(dst a0, c a1, n a2) -> dst
    beqz  $a0, mret0
    andi  $a1, $a1, 0xff
    blez  $a2, mret0
    nop
    move  $v1, $a0
    sll   $t0, $a1, 8
    or    $t0, $t0, $a1
    sll   $v0, $t0, 16
    or    $t0, $t0, $v0
    move  $t2, $a2
fill:                                   # a0 dst, t0 pattern, t2 n > 0; temp v0
    andi  $v0, $a0, 3
    beqz  $v0, falig
    nop
    sb    $t0, 0($a0)
    addiu $t2, $t2, -1
    bnez  $t2, fill
    addiu $a0, $a0, 1
falig:                                  # (also reached with t2 = 0 from the head loop)
    sltiu $v0, $t2, 16
    bnez  $v0, fbyte4
    nop
fword:
    sw    $t0, 0($a0)
    sw    $t0, 4($a0)
    sw    $t0, 8($a0)
    sw    $t0, 12($a0)
    addiu $t2, $t2, -16
    sltiu $v0, $t2, 16
    beqz  $v0, fword
    addiu $a0, $a0, 16
fbyte4:
    beqz  $t2, fend
    nop
fbyte:
    sb    $t0, 0($a0)
    addiu $t2, $t2, -1
    bnez  $t2, fbyte
    addiu $a0, $a0, 1
fend:
    ori   $v0, $zero, 0x28
    beq   $t1, $v0, 1f
    nop
    b     mdone
    move  $a2, $zero                    # memset: a2 = 0
1:  move  $a1, $zero                    # bzero: a1 = 0
mdone:
    move  $v0, $v1
mret:                                   # A0 dispatcher registers as the BIOS path leaves them
    sll   $t1, $t1, 2
    lw    $t0, 0x200($t1)
    jr    $ra
    ori   $t2, $zero, 0xa0
mret0:
    b     mret
    move  $v0, $zero
region_b_end:
