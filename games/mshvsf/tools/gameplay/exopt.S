# MSHvSF 1.1 EX OPTIONS screen (games/mshvsf/tools/gameplay/exopt.py, mktag.py --exopt): a main-menu state of its own.
# Lives in the last-sector slack of OPE.ARC (the game loads the whole archive, menu overlay OPDEMO = entry 0, to
# 0x800947cc, so the slack after the last entry lands at 0x801f1260.. with it; the menu never writes there).  The menu's
# state table entry (menus.py; with --ach the runtime's port.c) points at exst, which runs in the menu dispatcher's
# frame and leaves through its epilogue 0x80099e98.
# Rows (ROWS, built by exopt.py): {label, u8 option offset (OPTB + n), u8 values, u8 x of value 1, u8 x of value 2
# (8-pixel cells after VX), value strings x 3}.  UP / DOWN cursor (wraps), LEFT / RIGHT value (wraps, xkey in the
# EXE), START / TRIANGLE / CIRCLE back to the main menu.  Values are effective at once (fixed RAM bytes).
# Menu block 0x80025040: +0 state, +1 our init flag, +2 our cursor (both zeroed with the state on entry and exit).

#@X
exst:   jal     exscr
        nop
        j       0x80099e98
        nop

exscr:  addiu   $sp, $sp, -48
        sw      $ra, 44($sp)
        sw      $s0, 40($sp)
        sw      $s1, 36($sp)
        sw      $s2, 32($sp)
        sw      $s3, 28($sp)
        sw      $s4, 24($sp)
        lui     $s0, 0x8002
        addiu   $s0, $s0, 0x5040
        lbu     $t0, 1($s0)
        ori     $t1, $zero, 1
        bnez    $t0, 1f
        nop
        sb      $t1, 1($s0)                     # first frame: cursor 0
        sb      $zero, 2($s0)
1:      lui     $t0, 0x8002                     # new presses of pad 1 | pad 2
        lhu     $s1, 0x7d60($t0)
        lhu     $t1, 0x7db8($t0)
        lhu     $t2, 0x7d62($t0)
        lhu     $t3, 0x7dba($t0)
        nor     $t1, $t1, $zero
        and     $s1, $s1, $t1
        nor     $t3, $t3, $zero
        and     $t2, $t2, $t3
        or      $s1, $s1, $t2
        andi    $t0, $s1, 0x0830                # START / TRIANGLE / CIRCLE
        beqz    $t0, 2f
        nop
        jal     SFX
        ori     $a0, $zero, 0x82
        b       9f
        sw      $zero, 0($s0)                   # state, +1..+3 = 0: back to the main menu
2:      lbu     $s2, 2($s0)                     # cursor
        andi    $t0, $s1, 0x5000                # UP / DOWN
        beqz    $t0, 4f
        andi    $t1, $s1, 0x1000
        beqz    $t1, 3f
        addiu   $s2, $s2, 1                     # DOWN
        addiu   $s2, $s2, NROWS - 2             # UP: -1 (mod NROWS)
3:      sltiu   $t0, $s2, NROWS
        bnez    $t0, 31f
        nop
        addiu   $s2, $s2, -NROWS
31:     sb      $s2, 2($s0)
        jal     SFX
        ori     $a0, $zero, 0x84
4:      sll     $t0, $s2, 2
        sll     $a0, $s2, 4
        addu    $a0, $a0, $t0
        lui     $t0, %hi(ROWS)
        addiu   $t0, $t0, %lo(ROWS)
        addu    $a0, $a0, $t0                   # the cursor row's record
        andi    $t0, $s1, 0x2000                # RIGHT
        bnez    $t0, 5f
        ori     $a1, $zero, 1
        andi    $t0, $s1, 0x8000                # LEFT
        beqz    $t0, 6f
        addiu   $a1, $zero, -1
5:      jal     XKEY
        nop
ABCALL
6:      lui     $a0, %hi(TITLE)
        addiu   $a0, $a0, %lo(TITLE)
        lui     $a1, TITLEX
        ori     $a1, $a1, 0x30
        lui     $a2, 0x1024
        jal     PRINT                           # title, the big font (the pause menu's)
        ori     $a2, $a2, 0x4001
        lui     $a0, 0x8002
        addiu   $a0, $a0, 0x7eec                # "PRESS START BUTTON TO EXIT" (EXE string)
        lui     $a1, FOOTX
        ori     $a1, $a1, FOOTY
        lui     $a2, 0x0823
        jal     PRINT
        ori     $a2, $a2, 1
        lui     $s1, %hi(ROWS)
        addiu   $s1, $s1, %lo(ROWS)
        move    $s3, $zero                      # row
7:      sll     $s4, $s3, 4                     # y = Y0 + DY * row
        addu    $s4, $s4, $s3
        addu    $s4, $s4, $s3
        addu    $s4, $s4, $s3
        addu    $s4, $s4, $s3                   # 20 * row
        addiu   $s4, $s4, Y0
        ori     $a2, $zero, 0x23
        bne     $s3, $s2, 71f
        nop
        ori     $a2, $zero, 0x20                # the cursor row: bright label
71:     sll     $a2, $a2, 16
        lui     $t0, 0x0800
        ori     $t0, $t0, 1
        or      $a2, $a2, $t0
        lw      $a0, 0($s1)
        lui     $a1, LX
        jal     PRINT                           # label
        or      $a1, $a1, $s4
        jal     ROWVAL
        move    $a0, $s1
        jal     exvals
        move    $a0, $v0
        addiu   $s3, $s3, 1
        slti    $t0, $s3, NROWS
        bnez    $t0, 7b
        addiu   $s1, $s1, 20
9:      lw      $ra, 44($sp)
        lw      $s0, 40($sp)
        lw      $s1, 36($sp)
        lw      $s2, 32($sp)
        lw      $s3, 28($sp)
        lw      $s4, 24($sp)
        jr      $ra
        addiu   $sp, $sp, 48

# the value strings of record s1 at y s4, a0 = the chosen one (bright 0x20, the others 0x22)
exvals: addiu   $sp, $sp, -32
        sw      $ra, 28($sp)
        sw      $s0, 24($sp)
        sw      $s2, 20($sp)
        sw      $s3, 16($sp)
        move    $s2, $a0
        move    $s0, $zero
1:      ori     $a2, $zero, 0x22
        bne     $s0, $s2, 2f
        nop
        ori     $a2, $zero, 0x20
2:      sll     $a2, $a2, 16
        lui     $t0, 0x0800
        ori     $t0, $t0, 1
        or      $a2, $a2, $t0
        addu    $t1, $s1, $s0
        lbu     $t1, 5($t1)                     # x cell of value s0 (+5: value 0 = 0, the count byte is skipped)
        sltiu   $t2, $s0, 1
        beqz    $t2, 3f
        sll     $t1, $t1, 3
        move    $t1, $zero
3:      addiu   $t1, $t1, VX
        sll     $a1, $t1, 16
        or      $a1, $a1, $s4
        sll     $t0, $s0, 2
        addu    $t0, $t0, $s1
        jal     PRINT
        lw      $a0, 8($t0)
        lbu     $t0, 5($s1)                     # values
        addiu   $s0, $s0, 1
        slt     $t0, $s0, $t0
        bnez    $t0, 1b
        nop
        lw      $ra, 28($sp)
        lw      $s0, 24($sp)
        lw      $s2, 20($sp)
        lw      $s3, 16($sp)
        jr      $ra
        addiu   $sp, $sp, 32

ABCODE
        .align  2
ROWS:   ROWTAB
