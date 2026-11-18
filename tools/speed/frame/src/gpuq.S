# Region 0x80018510-0x800187f0: libgpu _addque (entry 0x80018510) rewritten without the stock's redundant
# reloads, REGISTER-EXACT: on every path it leaves the caller-saved registers as the stock code does (the game
# reads registers left over by libgpu calls - e.g. 0x80075550 uses an uninitialised a2 for its bonus flags), so
# only at, v0, v1, a0..a3, t0 are written, with the stock final values.  Freed space: the DrawOTag shim and the early-BG data (EBV).
# Globals: W 0x80022628, R 0x8002262c, masks 0x80022630, last started 0x80022618/1c/20, 0x8002252c, 0x80022530,
# 0x80022525 queue enable, 0x80022604 -> DMA2 CHCR, 0x800225f8 -> GPUSTAT, entries 0x80025f88 + 0x60 i.

addque:                                 # _addque(func a0, arg a1, size a2, a3)
    addiu $sp, $sp, -0x28
    sw    $s3, 0x1c($sp)
    move  $s3, $a0
    sw    $s0, 0x10($sp)
    move  $s0, $a1
    sw    $s1, 0x14($sp)
    move  $s1, $a2
    sw    $s2, 0x18($sp)
    sw    $ra, 0x20($sp)
    jal   0x80018d80                    # start the timeout
    move  $s2, $a3
    b     21f
    lui   $v1, 0x8002
1:  jal   0x80018db4                    # timed out?
    nop
    bnez  $v0, 9f
    addiu $v0, $zero, -1
    jal   exeque
    nop
2:  lui   $v1, 0x8002
21: lw    $v0, 0x2628($v1)
    lw    $v1, 0x262c($v1)
    addiu $v0, $v0, 1
    andi  $v0, $v0, 0x3f
    beq   $v0, $v1, 1b                  # queue full: wait
    nop
    jal   0x80011cc0                    # SetIntrMask(0)
    move  $a0, $zero
    lui   $at, 0x8002
    lbu   $v1, 0x2525($at)
    sw    $v0, 0x2630($at)
    addiu $v0, $zero, 1                 # (stock: queue disabled, 0x80022525 == 0 -> direct; this game's ResetGraph
    sw    $v0, 0x252c($at)              #  always enables it - the only writer stores 1 - so that test is dropped)
    lw    $v1, 0x2628($at)
    lw    $v0, 0x262c($at)
    nop
    bne   $v1, $v0, 5f
    nop
    lw    $v0, 0x2604($at)
    nop
    lw    $v0, 0($v0)
    lui   $v1, 0x0100
    and   $v0, $v0, $v1
    bnez  $v0, 5f
    nop
    lw    $v0, 0x2530($at)
    nop
    bnez  $v0, 5f
    lw    $v1, 0x25f8($at)
    nop                                 # (load delay: v1)
    lw    $v0, 0($v1)                   # (read twice: the first read may predate the last GP0 transfer)
    lw    $v0, 0($v1)                   # queue enabled, empty, DMA idle, but the GPU still busy (the first DrawOTag
    nop                                 # after the flip: the screen clear, 30-40K): queue it instead of spinning;
    sll   $v0, $v0, 5                   # the next libgpu call / the DMA IRQ / DrawSync starts it
    bgez  $v0, 5f                       # (GPUSTAT bit 26 clear)
    nop
3:  lui   $a0, 0x0400                   # direct: wait GPU ready, start now (v1 = GPUSTAT pointer, loaded above)
4:  lw    $v0, 0($v1)
    nop
    and   $v0, $v0, $a0
    beqz  $v0, 4b
    nop
    move  $a0, $s0
    jalr  $s3
    move  $a1, $s2
    lui   $at, 0x8002
    lw    $a0, 0x2630($at)
    sw    $s3, 0x2618($at)
    sw    $s0, 0x261c($at)
    jal   0x80011cc0                    # SetIntrMask(saved)
    sw    $s2, 0x2620($at)
    b     9f
    move  $v0, $zero
5:  lui   $a1, 0x8002                   # queue it
    addiu $a1, $a1, -0x7810             # 0x800187f0
    jal   0x80011ba4                    # DMACallback(2, _exeque)
    addiu $a0, $zero, 2
    beqz  $s1, 7f
    move  $a2, $zero                    # (stock: a2 = 0 here on both paths)
    lui   $t0, 0x8002
    addiu $t0, $t0, 0x5f94
    move  $a3, $s0
    move  $v0, $s1
    bgez  $v0, 6f
    nop
    addiu $v0, $v0, 3
6:  sra   $v0, $v0, 2                   # n = size / 4 (C division); stock ends with a2 = n, a3 = arg + 4n, t0
    lui   $at, 0x8002
    lw    $v1, 0x2628($at)
    nop
    sll   $at, $v1, 1
    addu  $at, $at, $v1
    sll   $at, $at, 5
    addu  $at, $at, $t0                 # copy area of entry W
    slt   $a0, $a2, $v0
61: beqz  $a0, 8f
    nop
    lw    $a1, 0($a3)
    addiu $a3, $a3, 4
    sw    $a1, 0($at)
    addiu $at, $at, 4
    addiu $a2, $a2, 1
    b     61b
    slt   $a0, $a2, $v0
8:  sll   $v0, $v1, 1
    addu  $v0, $v0, $v1
    sll   $v0, $v0, 5
    b     71f
    addu  $v0, $v0, $t0                 # arg = copy area
7:  lui   $v1, 0x8002
    lw    $v1, 0x2628($v1)
    move  $v0, $s0                      # arg itself
71: sll   $at, $v1, 1                   # (at / v0 / v1 / a0 are all rewritten below or by the calls, as in stock)
    addu  $at, $at, $v1
    sll   $at, $at, 5
    lui   $v1, 0x8002
    addu  $at, $at, $v1
    sw    $v0, 0x5f8c($at)
    sw    $s2, 0x5f90($at)
    sw    $s3, 0x5f88($at)
    lui   $at, 0x8002
    lw    $v0, 0x2628($at)
    lw    $a0, 0x2630($at)
    addiu $v0, $v0, 1
    andi  $v0, $v0, 0x3f
    jal   0x80011cc0                    # SetIntrMask(saved)
    sw    $v0, 0x2628($at)
    jal   exeque                        # non-blocking (EBV+36 != 0): does not wait for a busy GPU
    sw    $s3, %lo(EBV)+36($at)         # (at = 0x80020000: SetIntrMask keeps it)
    lui   $v0, 0x8002                   # (the drawsync callback exeque may call can change at)
    sw    $zero, %lo(EBV)+36($v0)
    lw    $v0, 0x2628($v0)
    lui   $v1, 0x8002
    lw    $v1, 0x262c($v1)
    nop
    subu  $v0, $v0, $v1
    andi  $v0, $v0, 0x3f
9:  lw    $ra, 0x20($sp)
    lw    $s3, 0x1c($sp)
    lw    $s2, 0x18($sp)
    lw    $s1, 0x14($sp)
    lw    $s0, 0x10($sp)
    jr    $ra
    addiu $sp, $sp, 0x28
addque_end:

# DrawOTag shim (0x80016a54 starts with `j shim`): EBV mode 1 = record the OT head instead of drawing it
shim:                                  # pass-through touches only v0, v1 (stock DrawOTag writes v0 first; v1 is
    lui   $v0, %hi(EBV)                 # written by _addque before it is read, not read by DrawOTag)
    lw    $v0, %lo(EBV)($v0)
    nop
    bnez  $v0, 2f
    lui   $v1, %hi(EBV)
    lui   $v0, 0x8002
    j     0x80016a5c
    lbu   $v0, 0x2526($v0)
2:  lw    $v0, %lo(EBV)+8($v1)          # mode 1: record the OT head (<= 4 BG layers)
    nop
    addiu $v0, $v0, 1
    sw    $v0, %lo(EBV)+8($v1)          # count + 1
    sll   $v0, $v0, 2
    addu  $v0, $v0, $v1
    sw    $a0, %lo(EBV)+12($v0)         # head n at +16 + 4n
    sw    $zero, %lo(EBV)+16($v0)       # zero-terminated list
    jr    $ra
    move  $v0, $zero
# AHEAD hook, called by present.S after the early BG, before the frame's DrawSync / VSync(0): tail-calls the
# callback at EBV+12 (if non-zero) with a0 = deadline (hblank counter value = last flip + AHEAD_LINES; + 263 per
# vblank already passed: a1 = vblanks since the last flip, 0 = frame on time).  See work/speed/frame/AHEAD.md.
ahook:
    lui   $t9, %hi(EBV)
    lw    $t8, %lo(EBV)+12($t9)
    lui   $t0, 0x8002
    lw    $t2, 0x20c8($t0)              # Vcount
    lw    $t3, 0xfb0($t0)               # Vcount at the last VSync(0) return
    beqz  $t8, 9f
    lw    $a0, 0xfac($t0)               # hblank counter at the last VSync(0) return (the last flip vblank)
    subu  $a1, $t2, $t3
    jr    $t8                           # tail call: the callback returns to present.S
    addiu $a0, $a0, AHEAD_LINES
9:  jr    $ra
    nop
EBV:                                   # +0 mode (1 = defer DrawOTag), +4 done, +8 count, +0xc AHEAD CALLBACK,
    .word 0, 0, 0, 0                   # +0x10 recorded OT heads (<= 4 BG layers) + terminator,
    .word 0, 0, 0, 0, 0                # +0x24 non-blocking exeque flag (set by addque around its exeque call)
    .word 0
gpuq1_end:
