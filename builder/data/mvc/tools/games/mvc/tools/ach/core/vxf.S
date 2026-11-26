# MvC 1.1 Variable Cross: stage colour flash during the Duo (mktag --vx --vxflash), segment 0x8000C400-0x8000C500.
# Arcade: the stage is recoloured with cycling bright colours for the whole Duo.  Here: one additive full-screen TILE with
# a cycling colour, drawn (DrawOTag, immediate like the fighter lists) right before sprite layer 3 = above the stage,
# under every sprite.  Hook: 0x80047b84 `jal 0x80047d38` (delay slot a0 = 3 kept) -> jal vx_flash.
# --vxskip (user 2026-11-26: forced FRAME SKIP only while a Duo runs): the engine's catch-up as tools/hwprof/frameskip.S
# AUTO (at most 1 logic-only pass per drawn frame, debt bank 2), on only while a side's Duo is on and the phase is the
# fight (8); otherwise the stock paths and the debt cleared.  Hooks 0x80022d74 (lb v0,-0x48bb(v0) -> jal vs_gate) and
# 0x80022ecc (sra v0,v0,16; li v1,1 -> jal vs_lag; sra v0,v0,16), the same sites as frameskip.py.

        .set    LAYER,   0x80047d38
        .set    DRAWOTAG, 0x80011e58

vx_flash:
        lui     $t0, 0x8001
        lbu     $t1, -0x3f00($t0)       # VXS side 0 on (0x8000C100)
        lbu     $t2, -0x3ef0($t0)       # VXS side 1 on (0x8000C110)
        nop
        or      $t1, $t1, $t2
        beqz    $t1, 9f
        lui     $t2, 0x8008
        lbu     $t2, -0x48be($t2)       # pause owner 0x8007b742 (0xff = not paused): no flash on the pause screen
        nop
        addiu   $t2, $t2, -0xff
        bnez    $t2, 9f
        nop
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x10($sp)
        sw      $a0, 0x14($sp)
        lui     $t3, 0x8008
        lw      $t3, -0x48b4($t3)       # main loops 0x8007b74c
        lui     $t4, %hi(cols)
        srl     $t3, $t3, 2
        andi    $t3, $t3, 7
        sll     $t3, $t3, 2
        addiu   $t4, $t4, %lo(cols)
        addu    $t4, $t4, $t3
        lw      $t5, 0($t4)
        lui     $a0, %hi(prim)
        addiu   $a0, $a0, %lo(prim)
        jal     DRAWOTAG
        sw      $t5, 8($a0)
        lw      $ra, 0x10($sp)
        lw      $a0, 0x14($sp)
        addiu   $sp, $sp, 0x20
9:      j       LAYER
        nop

        .if VXSKIP
vs_gate:                                # from 0x80022d74, v0 = 0x80080000
        lb      $v0, -0x48bb($v0)       # game mode (1 = battle)
        lui     $t0, 0x8001
        addiu   $t2, $v0, -1
        bnez    $t2, 9f                 # not battle: stock
        lbu     $t1, -0x3f00($t0)
        lbu     $t3, -0x3ef0($t0)
        lui     $t4, 0x8008
        or      $t1, $t1, $t3
        beqz    $t1, 8f                 # no Duo: stock
        lbu     $t4, -0x47d8($t4)       # phase 0x8007b828
        nop
        addiu   $t4, $t4, -8
        bnez    $t4, 8f                 # not the fight: stock
        lui     $t4, 0x8008
        lbu     $t4, -0x48be($t4)       # pause owner 0x8007b742 (0xff = not paused)
        nop
        addiu   $t4, $t4, -0xff
        bnez    $t4, 8f                 # paused: stock
        nop
        jr      $ra
        move    $v0, $zero              # Duo: take the catch-up path
8:      lui     $t4, %hi(debt)
        sb      $zero, %lo(debt)($t4)
9:      jr      $ra
        nop

vs_lag:                                 # from 0x80022ecc (v0 = lag, sign-extended in the delay slot)
        lui     $t0, 0x8008
        lb      $t2, -0x48bb($t0)
        ori     $v1, $zero, 1           # stock: catch up a lag of exactly 1
        addiu   $t2, $t2, -1
        bnez    $t2, 9f                 # not battle: stock (in battle only via vs_gate = Duo)
        lui     $t9, %hi(debt)
        lbu     $t6, %lo(debt)($t9)
        blez    $v0, 1f
        nop
        addu    $t6, $t6, $v0           # debt += lag
1:      slti    $t3, $t6, 3
        bnez    $t3, 2f
        nop
        li      $t6, 2                  # forgive debt above the bank (2)
2:      move    $t4, $t6
        slti    $t3, $t6, 2
        bnez    $t3, 3f
        nop
        li      $t4, 1                  # P = min(debt, 1)
3:      subu    $t6, $t6, $t4
        sb      $t6, %lo(debt)($t9)
        move    $v0, $t4
        move    $s0, $t4                # the caller stores s0 as the pending count when v0 == v1
        beqz    $t4, 9f
        nop
        move    $v1, $t4
9:      jr      $ra
        nop
debt:   .word   0
        .endif

        .align  2
prim:   .word   0x04ffffff              # 4 words, end of list
        .word   0xe1000620              # draw mode: additive (ABR 1), dither, draw to display area
        .word   0x62004040              # TILE semi-transparent, colour (set per frame)
        .word   0x00000000              # x 0, y 0
        .word   0x01000200              # w 512, h 256 (the drawing area clips)
cols:   .word   0x62005050, 0x62006830, 0x62305818, 0x62584810, 0x62603000, 0x62482030, 0x62304848, 0x62105858
