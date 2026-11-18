# MSHvSF menus (tools/gameplay/menus.py): extra OPTION-menu lines.  Pieces are packed into free EXE ranges by
# tools/speed/slib.pack (only j / jal / la between pieces).
#
# OPTION-line API (also in docs/GAMEPLAY.md, "Extra option lines"):
#   optlines: NLINES entries of 3 words  { label (0 = unused), flag byte address, show-if byte address (0 = always) }
#   An entry is shown when label != 0 and (show-if == 0 or *show-if != 0).  Shown lines get the option cursor
#   values 14, 15, ... after MEMORY CARD (13), in table order, drawn at y 0xd8, 0xe0 (x 0x80, ON / OFF at
#   0x120 / 0x138, the game's own strings and colours).  LEFT / RIGHT / CROSS on a line toggles its flag byte
#   (0 / 1, 1 = ON) with the game's cursor sound (pad 1).  Nothing else reads the flags: their owners do.
#   Values live in RAM for the session (the game's option block 0x8002506c.. is what MEMORY CARD saves; the
#   extra flags are not in it).

# ---------------------------------------------------------------- v0 = number of shown extra lines
optcount:
        la      $t0, optlines
        la      $t3, optlines + 12 * NLINES
        move    $v0, $zero
1:      lw      $t1, 0($t0)                     # label
        lw      $t2, 8($t0)                     # show-if byte
        beqz    $t1, 2f
        ori     $t1, $zero, 1
        beqz    $t2, 3f
        nop
        lbu     $t1, 0($t2)
        nop
3:      sltu    $t1, $zero, $t1
        addu    $v0, $v0, $t1
2:      addiu   $t0, $t0, 12
        bne     $t0, $t3, 1b
        nop
        jr      $ra
        nop

# ---------------------------------------------------------------- WRAP: the option cursor wrap (overlay
# 0x8009a1d8: jal optwrap; 0x8009a1e0: j 0x8009a370 / li v0, 2): cursor in 0 .. 13 + shown extra lines
optwrap:
        addiu   $sp, $sp, -24
        sw      $ra, 20($sp)
        jal     optcount
        nop
        lui     $t0, 0x8002
        lb      $t1, 0x504d($t0)                # option cursor
        addiu   $v0, $v0, 14                    # N items
        bgez    $t1, 1f
        slt     $t2, $t1, $v0
        addiu   $t1, $v0, -1                    # < 0: last
        b       2f
        sb      $t1, 0x504d($t0)
1:      bnez    $t2, 2f
        nop
        sb      $zero, 0x504d($t0)              # >= N: first
2:      lw      $ra, 20($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24

# ---------------------------------------------------------------- DRAW: end of the option-screen draw routine
# 0x800994e8 (overlay 0x80099b3c `jr ra` -> `j optdraw`; its registers are restored already): draw the shown
# lines, toggle the flag of the selected one on a new LEFT / RIGHT / CROSS (pad 1)
optdraw:
        addiu   $sp, $sp, -32
        sw      $ra, 28($sp)
        sw      $s0, 24($sp)
        sw      $s1, 20($sp)
        la      $s0, optlines
        ori     $s1, $zero, 14                  # cursor value of the next shown line (y = 8 * s1 + 0x68)
1:      jal     optshown
        move    $a0, $s0
        beqz    $v0, 8f
        nop
        jal     optline
        move    $a0, $s0
        jal     optval
        move    $a0, $s0
        addiu   $s1, $s1, 1
8:      la      $t0, optlines + 12 * NLINES
        addiu   $s0, $s0, 12
        bne     $s0, $t0, 1b
        nop
        lw      $ra, 28($sp)
        lw      $s0, 24($sp)
        lw      $s1, 20($sp)
        jr      $ra
        addiu   $sp, $sp, 32

# ---------------------------------------------------------------- v0 = entry a0 shown (label set, show-if 0 or set)
optshown:
        lw      $v0, 0($a0)
        lw      $t2, 8($a0)
        beqz    $v0, 1f
        nop
        beqz    $t2, 1f
        nop
        lbu     $v0, 0($t2)
1:      jr      $ra
        nop

# ---------------------------------------------------------------- label of entry a0 (+ its key), s1 = its cursor value
optline:
        addiu   $sp, $sp, -24
        lui     $t0, 0x8002
        lb      $t0, 0x504d($t0)                # option cursor
        lw      $t1, 0($a0)                     # label
        sw      $ra, 20($sp)
        sw      $t1, 16($sp)
        bne     $t0, $s1, 1f
        ori     $a2, $zero, 0x23
        jal     optkey
        nop
        ori     $a2, $zero, 0x20                # selected: bright
1:      lw      $a0, 16($sp)
        jal     optprint
        ori     $a1, $zero, 0x80
        lw      $ra, 20($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24

# ---------------------------------------------------------------- the ON / OFF of entry a0 (s1 = its cursor value)
optval:
        addiu   $sp, $sp, -24
        sw      $ra, 20($sp)
        lw      $t1, 4($a0)
        nop
        lbu     $t1, 0($t1)                     # 1 = ON
        lui     $a0, 0x8009
        sll     $t2, $t1, 1
        addu    $t2, $t2, $t1                   # 3 * flag
        sw      $t2, 16($sp)
        ori     $a2, $zero, 0x23
        subu    $a2, $a2, $t2                   # ON bright (0x20) when set
        addiu   $a0, $a0, 0x4b88                # "ON" (OPDEMO)
        jal     optprint
        ori     $a1, $zero, 0x120
        lw      $t2, 16($sp)
        lui     $a0, 0x8009
        addiu   $a2, $t2, 0x20                  # OFF bright when clear
        addiu   $a0, $a0, 0x4b8c                # "OFF"
        jal     optprint
        ori     $a1, $zero, 0x138
        lw      $ra, 20($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24

# ---------------------------------------------------------------- the game's text routine at (a1 = x, y of line s1),
# colour a2
optprint:
        sll     $t0, $s1, 3
        addiu   $t0, $t0, 0x68                  # y = 0xd8 + 8 * (s1 - 14)
        sll     $a1, $a1, 16
        or      $a1, $a1, $t0
        sll     $a2, $a2, 16
        lui     $t0, 0x0800
        ori     $t0, $t0, 1
        j       0x80022e20
        or      $a2, $a2, $t0

# ---------------------------------------------------------------- toggle the flag of entry a0 on a new LEFT /
# RIGHT / CROSS (pad 1), with the game's cursor sound
optkey:
        lui     $t2, 0x8002                     # new presses on pad 1: now & ~before
        lhu     $t3, 0x7d60($t2)
        lhu     $t4, 0x7db8($t2)
        nop
        nor     $t4, $t4, $zero
        and     $t3, $t3, $t4
        andi    $t3, $t3, 0xa040                # LEFT, RIGHT, CROSS
        beqz    $t3, 1f
        lw      $t1, 4($a0)
        nop
        lbu     $t3, 0($t1)
        nop
        xori    $t3, $t3, 1
        sb      $t3, 0($t1)
        j       0x8007b2cc                      # the game's cursor sound (returns to our caller)
        ori     $a0, $zero, 0x84
1:      jr      $ra
        nop

# ---------------------------------------------------------------- the line table and label(s)
optlines:
        .if     METER
        .word   lbl_meter, MFLAG, 0
        .else
        .word   0, 0, 0
        .endif
        .if     AP8                             # the 8 MB build's line (tools/ap8/mkap8.py sets menus.AP8)
        .word   lbl_ap8, AP8FLAG, AP8SHOW
        .else
        .word   0, 0, 0
        .endif

# ---------------------------------------------------------------- label text(s)
lbl_meter:
        .asciz  "SPEED METER"
        .align  2

# ---------------------------------------------------------------- label of the 8 MB line (empty without AP8)
lbl_ap8:
        .if     AP8
        .asciz  "ARCADE FRAMES"
        .align  2
        .endif
