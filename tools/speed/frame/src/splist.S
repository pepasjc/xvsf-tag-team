# Region 0x8002e6bc-0x8002e924 (stock: sprite-list dispatcher 0x8002e6bc + four list walkers 0x8002e784 /
# 0x8002e7ec / 0x8002e854 / 0x8002e8bc).  Rewritten: same dispatcher logic and call order, one generic walker,
# and in the freed space RAM versions of the BIOS A0 memory functions (bcopy 27h, bzero 28h, memcpy 2Ah,
# memset 2Bh) that the stubs at 0x80019290.. jump to.
# Assembled at 0x8002e6bc (.set noreorder: every delay slot is explicit).

# ---------------------------------------------------------------- sprite list (stock 0x8002e6bc)
splist:
    addiu $sp, $sp, -0x18
    lui   $v1, 0x8004
    lh    $v1, 0x2774($v1)
    ori   $v0, $zero, 8
    bne   $v1, $v0, 1f
    sw    $ra, 0x10($sp)
    lui   $v0, 0x8004
    lb    $v0, 0x2781($v0)
    nop
    beqz  $v0, 2f
    nop
1:  lui   $v0, 0x8004                   # path A: 8bc, 854, 7ec, 924, 784
    lh    $v0, 0x212a($v0)
    nop
    bltz  $v0, 9f
    nop
    jal   w8bc
    nop
    jal   w854
    nop
    jal   w7ec
    nop
    jal   0x8002e924
    nop
    b     8f
    nop
2:  lui   $v0, 0x8004                   # path B: [8bc, 854], 924, [7ec, 784]
    lh    $v0, 0x212a($v0)
    nop
    bltz  $v0, 3f
    nop
    jal   w8bc
    nop
    jal   w854
    nop
3:  jal   0x8002e924
    nop
    lui   $v0, 0x8004
    lh    $v0, 0x212a($v0)
    nop
    bltz  $v0, 9f
    nop
    jal   w7ec
    nop
8:  jal   w784
    nop
9:  lw    $ra, 0x10($sp)
    addiu $sp, $sp, 0x18
    jr    $ra
    nop

# stock walkers: n = *(s16 *)cnt; for (i = 0, p = end; i < n (re-read every time); i++) 0x80059e60(*--p)
w784:
    lui   $a0, 0x8004
    addiu $a0, $a0, 0x1de4
    lui   $a1, 0x8004
    b     walk
    addiu $a1, $a1, 0x26c0
w7ec:
    lui   $a0, 0x8004
    addiu $a0, $a0, 0x1de6
    lui   $a1, 0x8004
    b     walk
    addiu $a1, $a1, 0x2730
w854:
    lui   $a0, 0x8004
    addiu $a0, $a0, 0x1de8
    lui   $a1, 0x8004
    b     walk
    addiu $a1, $a1, 0x2770
w8bc:
    lui   $a0, 0x8004
    addiu $a0, $a0, 0x1e10
    lui   $a1, 0x8004
    addiu $a1, $a1, 0x27d8
walk:                                   # a0 = count address, a1 = end of the pointer array; frame as stock (0x28)
    lh    $v0, 0($a0)
    addiu $sp, $sp, -0x28
    sw    $s1, 0x1c($sp)
    move  $s1, $a1
    sw    $s0, 0x18($sp)
    move  $s0, $zero
    sw    $s2, 0x24($sp)
    move  $s2, $a0
    blez  $v0, 2f
    sw    $ra, 0x20($sp)
    addiu $s1, $s1, -4
1:  lw    $a0, 0($s1)
    jal   0x80059e60
    addiu $s0, $s0, 1
    lh    $v0, 0($s2)
    nop
    slt   $v0, $s0, $v0
    bnez  $v0, 1b
    addiu $s1, $s1, -4
2:  lw    $ra, 0x20($sp)
    lw    $s2, 0x24($sp)
    lw    $s1, 0x1c($sp)
    lw    $s0, 0x18($sp)
    jr    $ra
    addiu $sp, $sp, 0x28

# ---------------------------------------------------------------- BIOS A0 memory functions in RAM
# Entered from the game's stubs as `j f_xxx; addiu $t1, $zero, N` (N = A0 function number, as the stock stub
# loads it).  Results, final a0..a2 / v0 / v1 / t6, and the A0 dispatcher's t0 (= A0 table entry), t1 (= N*4),
# t2 (= 0xa0) are exactly those of the BIOS routines (scph1001/5501/7001: byte loops, forward).  Registers
# touched are a subset of the ones the BIOS path touches.

f_bcopy:                                # bcopy(src a0, dst a1, n a2) -> src
    bnez  $a0, 1f
    nop
    j     mret0
    nop
1:  move  $v1, $a0
    blez  $a2, 2f
    nop
copy:                                   # a0 src, a1 dst, a2 n > 0; temps v0, t0, t6
    subu  $v0, $a1, $a0
    sltiu $v0, $v0, 4
    bnez  $v0, cbyte                    # dst - src in 0..3: forward byte copy (overlap semantics of word moves)
    andi  $v0, $a1, 3
    beqz  $v0, calig
    nop
chead:
    lbu   $t6, 0($a0)
    addiu $a0, $a0, 1
    addiu $a2, $a2, -1
    sb    $t6, 0($a1)
    beqz  $a2, cend
    addiu $a1, $a1, 1
    andi  $v0, $a1, 3
    bnez  $v0, chead
    nop
calig:
    sltiu $v0, $a2, 4
    bnez  $v0, cbyte4
    andi  $v0, $a0, 3
    bnez  $v0, cunal
    nop
cword:                                  # both aligned
    lw    $t6, 0($a0)
    addiu $a2, $a2, -4
    addiu $a0, $a0, 4
    sw    $t6, 0($a1)
    sltiu $v0, $a2, 4
    beqz  $v0, cword
    addiu $a1, $a1, 4
    b     cbyte4
    nop
cunal:                                  # dst aligned, src not
    lwr   $t6, 0($a0)
    lwl   $t6, 3($a0)
    addiu $a2, $a2, -4
    addiu $a0, $a0, 4
    sw    $t6, 0($a1)
    sltiu $v0, $a2, 4
    beqz  $v0, cunal
    addiu $a1, $a1, 4
cbyte4:
    beqz  $a2, cend
    nop
cbyte:
    lbu   $t6, 0($a0)
    addiu $a0, $a0, 1
    addiu $a2, $a2, -1
    sb    $t6, 0($a1)
    bnez  $a2, cbyte
    addiu $a1, $a1, 1
cend:
    lbu   $t6, -1($a1)                  # BIOS leaves the last byte in t6
    ori   $v0, $zero, 0x2a
    bne   $t1, $v0, 2f
    move  $t0, $a0                      # memcpy: swap back (a0 = dst end, a1 = src end)
    move  $a0, $a1
    move  $a1, $t0
2:  j     mdone
    nop

splist_end:
