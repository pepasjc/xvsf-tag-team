# EX OPTIONS screen (games/mvc/tools/gameplay/exopt.py, fx worker 2026-11-20; mktag.py --exopt).
# A main-menu state of its own (menus.py / mvcach.py point the item's state-table entry at exst), drawn and driven like
# the stock hidden EX OPTION screen (0x800a1bfc / 0x800a18a8): big title, footer "PRESS START OR [icon] BUTTON TO EXIT",
# rows "LABEL  value value value" (label bright on the cursor row, the chosen value bright), UP / DOWN cursor, LEFT /
# RIGHT value, START / TRIANGLE back to the main menu.  Values live in fixed RAM bytes (optrows.BYTES), effective at
# once.  Linked into OPDEMO.ARC's last-sector slack (the menu overlay; optrows' old home, stock OPTION MODE is clean).
# Row record (ROWS, 24 B): byte address, value count, label, value strings x 3.

#@O
exst:   jal     exopt                           # state-table target (inside the menu dispatcher's frame)
        nop
        j       0x800a2df8                      # the dispatcher's epilogue
        nop

exopt:  addiu   $sp, $sp, -56
        sw      $ra, 48($sp)
        sw      $s0, 44($sp)
        sw      $s1, 40($sp)
        sw      $s2, 36($sp)
        lui     $s0, 0x8008
        addiu   $s0, $s0, -0x4918               # menu block 0x8007b6e8
        lbu     $t0, 1($s0)
        nop
        bnez    $t0, 1f
        li      $t0, 1
        sb      $zero, 0xd($s0)                 # first frame: cursor 0
        sb      $t0, 1($s0)
1:      jal     exdraw
        nop
        lb      $s1, 0x59($s0)                  # the pad that drives the menu
        nop
        move    $a0, $s1
        jal     PAD
        li      $a1, 0x1000                     # UP
        beqz    $v0, 2f
        lbu     $v0, 0xd($s0)
        j       3f
        addiu   $v0, $v0, -1
2:      move    $a0, $s1
        jal     PAD
        li      $a1, 0x4000                     # DOWN
        beqz    $v0, 4f
        lbu     $v0, 0xd($s0)
        nop
        addiu   $v0, $v0, 1
3:      sb      $v0, 0xd($s0)
        jal     SND_MOVE
        move    $a0, $zero
        j       8f
        nop
4:      move    $a0, $s1
        jal     PAD
        li      $a1, 0x2000                     # RIGHT
        bnez    $v0, 5f
        li      $s2, 1
        move    $a0, $s1
        jal     PAD
        li      $a1, 0x8000                     # LEFT
        beqz    $v0, 8f
        li      $s2, -1
5:      jal     rowrec                          # v0 = record of the cursor row
        nop
        lw      $t2, 0($v0)                     # value byte
        lw      $t4, 4($v0)                     # value count
        lbu     $t3, 0($t2)
        nop
        addu    $t3, $t3, $s2
        bgez    $t3, 6f
        slt     $t5, $t3, $t4
        addiu   $t3, $t4, -1                    # below the first -> last
        li      $t5, 1
6:      bnez    $t5, 7f
        nop
        move    $t3, $zero                      # past the last -> first
7:      sb      $t3, 0($t2)
        .if ASROW1                              # (assists row) --asrow1: ASSIST (0x8001175f) = (ASSISTS row == OFF),
        lui     $t0, 0x8001                     # for the readers of the old ON / OFF byte (asopt clr, asarc)
        lbu     $t1, 0x1760($t0)
        nop
        xori    $t1, $t1, 2
        sltiu   $t1, $t1, 1
        sb      $t1, 0x175f($t0)
        .endif
        jal     SND_VAL
        move    $a0, $zero
8:      lb      $v1, 0xd($s0)                   # cursor wrap
        nop
        bgez    $v1, 9f
        slti    $t0, $v1, NROWS
        li      $v1, NROWS - 1
        sb      $v1, 0xd($s0)
        li      $t0, 1
9:      bnez    $t0, 10f
        nop
        sb      $zero, 0xd($s0)
10:     move    $a0, $s1
        jal     PAD
        li      $a1, 0x800                      # START
        bnez    $v0, 11f
        move    $a0, $s1
        jal     PAD
        li      $a1, 0x10                       # TRIANGLE
        beqz    $v0, 12f
        nop
11:     jal     SND_EXIT
        li      $a0, 0x33
        sb      $zero, 3($s0)                   # back to the main menu (as the stock EX OPTION exit)
        sb      $zero, 2($s0)
        sb      $zero, 1($s0)
        sb      $zero, 0($s0)
12:     lw      $ra, 48($sp)
        lw      $s0, 44($sp)
        lw      $s1, 40($sp)
        lw      $s2, 36($sp)
        jr      $ra
        addiu   $sp, $sp, 56

rowrec: lb      $t0, 0xd($s0)                   # -> v0 = ROWS + 24 * cursor (cursor kept in range by the wrap)
        lui     $v0, %hi(ROWS)
        addiu   $v0, $v0, %lo(ROWS)
        sll     $t1, $t0, 4
        sll     $t0, $t0, 3
        addu    $v0, $v0, $t1
        jr      $ra
        addu    $v0, $v0, $t0

exdraw: addiu   $sp, $sp, -72
        sw      $ra, 64($sp)
        sw      $s0, 60($sp)
        sw      $s1, 56($sp)
        sw      $s2, 52($sp)
        sw      $s3, 48($sp)
        sw      $s4, 44($sp)
        sw      $s5, 40($sp)
        lui     $a0, %hi(TITLE)
        addiu   $a0, $a0, %lo(TITLE)
        lui     $a1, TITLEX
        ori     $a1, $a1, 0x30
        lui     $a2, 0x1024
        jal     FONT                            # title (the stock EX OPTION style)
        ori     $a2, $a2, 0x2001
        lui     $a0, %hi(FOOTER)
        addiu   $a0, $a0, %lo(FOOTER)
        lui     $a1, 0x84
        ori     $a1, $a1, 0xe0
        lui     $a2, 0x820
        jal     FONT                            # "PRESS START OR   BUTTON TO EXIT" (stock string)
        ori     $a2, $a2, 1
        li      $a0, 0xfc                       # the button icon in the gap (stock arguments)
        li      $a1, 0xe0
        li      $a2, 8
        move    $a3, $a2
        li      $v0, 0xe0
        sw      $v0, 16($sp)
        li      $v0, 0x98
        sw      $v0, 20($sp)
        li      $v0, 9
        sw      $v0, 24($sp)
        li      $v0, 0x28
        sw      $v0, 28($sp)
        li      $v0, 1
        jal     ICON
        sw      $v0, 32($sp)
        lui     $a0, %hi(VER)
        addiu   $a0, $a0, %lo(VER)
        lui     $a1, VERX
        ori     $a1, $a1, VERY
        lui     $a2, 0x823
        jal     FONT                            # version line (moved here from the main menu)
        ori     $a2, $a2, 1
        lui     $s1, %hi(ROWS)
        addiu   $s1, $s1, %lo(ROWS)
        move    $s2, $zero                      # row
        li      $s3, Y0                         # y
1:      lui     $t0, 0x8008
        lb      $t1, -0x490b($t0)               # cursor 0x8007b6f5
        li      $a2, 0x23
        bne     $t1, $s2, 2f
        nop
        li      $a2, 0x20
2:      sll     $a2, $a2, 16
        lui     $t0, 0x800
        ori     $t0, $t0, 1
        or      $a2, $a2, $t0
        lw      $a0, 8($s1)
        lui     $a1, LX
        jal     FONT                            # label
        or      $a1, $a1, $s3
        lw      $t2, 0($s1)
        nop
        lbu     $s4, 0($t2)                     # value
        move    $s0, $zero                      # alternative
        li      $s5, VX                         # x
3:      sll     $t0, $s0, 2
        addu    $t0, $t0, $s1
        lw      $a0, 12($t0)
        li      $a2, 0x23
        bne     $s0, $s4, 4f
        nop
        li      $a2, 0x20
4:      sll     $a2, $a2, 16
        lui     $t0, 0x800
        ori     $t0, $t0, 1
        or      $a2, $a2, $t0
        sll     $a1, $s5, 16
        jal     FONT                            # value alternative
        or      $a1, $a1, $s3
        sll     $t0, $s0, 2
        addu    $t0, $t0, $s1
        jal     STRLEN
        lw      $a0, 12($t0)
        addiu   $v0, $v0, 1
        sll     $v0, $v0, 3
        addu    $s5, $s5, $v0                   # next alternative: (len + 1) * 8 pixels on
        lw      $t0, 4($s1)
        addiu   $s0, $s0, 1
        slt     $t0, $s0, $t0
        bnez    $t0, 3b
        nop
        addiu   $s2, $s2, 1
        addiu   $s3, $s3, DY
        slti    $t0, $s2, NROWS
        bnez    $t0, 1b
        addiu   $s1, $s1, 24
        lw      $ra, 64($sp)
        lw      $s0, 60($sp)
        lw      $s1, 56($sp)
        lw      $s2, 52($sp)
        lw      $s3, 48($sp)
        lw      $s4, 44($sp)
        lw      $s5, 40($sp)
        jr      $ra
        addiu   $sp, $sp, 72

        .align  2
ROWS:   ROWTAB
