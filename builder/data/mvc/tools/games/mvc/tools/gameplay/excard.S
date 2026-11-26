# EX OPTIONS rows on the memory card (games/mvc/tools/gameplay/excard.py, mktag.py --excard; user 2026-11-24).
# MvC's own save (OPTION -> MEMORY CARD, OPDEMO.ARC): file "BASLUS-01059", 0x500 bytes written / read in one call; game
# data = file 0x100 .. 0x4fb (options, key config, ranking up to 0x21c, then zero padding), XOR of those bytes at
# 0x4fc (0x8009f510 sets it, 0x8009f570 checks it).  Ours: file 0x4f0 'X' 'O' 1, then the row bytes SA IN AF AP AS AB IM
# (inside the XOR range: the game's own checksum covers them).
#   svhook: OPDEMO 0x8009ec28 `jal 0x8009f510` (a0 = file image) -> stamp, then the stock checksum setter
#   ldhook: OPDEMO 0x8009edb8 `jal 0x8009f570` (a0 = image + 0x100, s2 = image; after the sync read) -> stock check; valid
#           + ours -> bytes back; valid without ours (stock / older save) -> defaults; invalid -> nothing (the game says so)
# AF (8 MB ARCADE FRAMES, upper RAM) only when the 8 MB menu hook is live (word HOOKA == HOOKW).  Resident: EXE dead
# spans (the 2026-11-17 8 MB menu spans, stock in every final; asserted by excard.py).  v0 is kept for the caller.

#@E
svhook: lui     $t9, 0x8008
        lbu     $t1, 0x58c9($t9)                # SA
        lbu     $t2, 0x58cb($t9)                # IN
        lui     $t9, 0x8001
        lbu     $t3, 0x175d($t9)                # AP
        lbu     $t4, 0x1760($t9)                # AS
        lbu     $t5, 0x1761($t9)                # AB
        lbu     $t6, 0x1763($t9)                # IM
        li      $t0, 0x58                       # 'X'
        sb      $t0, 0x4f0($a0)
        li      $t0, 0x4f                       # 'O'
        sb      $t0, 0x4f1($a0)
        j       sv2
        li      $t0, 1                          # layout version

#@B
sv2:    sb      $t0, 0x4f2($a0)
        sb      $t1, 0x4f3($a0)
        sb      $t2, 0x4f4($a0)
        sb      $t3, 0x4f6($a0)
        sb      $t4, 0x4f7($a0)
        sb      $t5, 0x4f8($a0)
        sb      $t6, 0x4f9($a0)
        lui     $t8, %hi(HOOKA)
        lw      $t8, %lo(HOOKA)($t8)
        lui     $t9, %hi(HOOKW)
        ori     $t9, $t9, %lo(HOOKW)
        j       sv3
        move    $t7, $zero

#@C
sv3:    bne     $t8, $t9, 1f                    # 2 MB: AF 0
        lui     $t9, 0x807e
        lbu     $t7, -0xc0($t9)                 # 0x807dff40
        nop
1:      sb      $t7, 0x4f5($a0)
        j       0x8009f510                      # the stock checksum (ra = the save routine)
        nop

#@D
ldhook: addiu   $sp, $sp, -8
        sw      $ra, 0($sp)
        jal     0x8009f570                      # stock XOR check: 0 = valid
        nop
        lw      $ra, 0($sp)
        addiu   $sp, $sp, 8
        sll     $t0, $v0, 24
        bnez    $t0, 9f                         # invalid: the game reports it, nothing restored
        lbu     $t0, 0x4f0($s2)
        lbu     $t1, 0x4f1($s2)
        lbu     $t2, 0x4f2($s2)
        j       ld2
        xori    $t0, $t0, 0x58
9:      jr      $ra
        nop

#@A
ld2:    xori    $t1, $t1, 0x4f
        xori    $t2, $t2, 1
        or      $t0, $t0, $t1
        or      $t0, $t0, $t2
        beqz    $t0, 1f
        nop
        j       lddef                           # no EX block (stock / older save): defaults
        nop
1:      lbu     $t1, 0x4f3($s2)
        lbu     $t2, 0x4f4($s2)
        lbu     $t3, 0x4f6($s2)
        lbu     $t4, 0x4f7($s2)
        lbu     $t5, 0x4f8($s2)
        lbu     $t6, 0x4f9($s2)
        j       ldput
        lbu     $t7, 0x4f5($s2)

#@F
lddef:  move    $t1, $zero                      # SA FULL
        li      $t2, INDEF                      # INTRO power-on value (2 MB build; the 8 MB boot stub sets STOCK)
        move    $t3, $zero                      # ACHIEVEMENT POPUP ON
        move    $t4, $zero                      # ASSISTS ROULETTE
        move    $t5, $zero                      # ARCADE BALANCE OFF
        move    $t6, $zero                      # INFINITE SUPER METER OFF
        move    $t7, $zero                      # ARCADE FRAMES ON
        lui     $t8, %hi(HOOKA)
        lw      $t8, %lo(HOOKA)($t8)
        lui     $t9, %hi(HOOKW)
        ori     $t9, $t9, %lo(HOOKW)
        bne     $t8, $t9, 1f                    # 8 MB: INTRO STOCK (ld3 forces it too)
        nop
        move    $t2, $zero
1:      j       ldput
        nop

#@G
ldput:  lui     $t9, 0x8008
        sb      $t1, 0x58c9($t9)
        sb      $t2, 0x58cb($t9)
        lui     $t9, 0x8001
        sb      $t3, 0x175d($t9)
        sb      $t4, 0x1760($t9)
        sb      $t5, 0x1761($t9)
        sb      $t6, 0x1763($t9)
        lui     $t8, %hi(HOOKA)
        lw      $t8, %lo(HOOKA)($t8)
        j       ld3
        lui     $t9, %hi(HOOKW)

#@H
ld3:    ori     $t9, $t9, %lo(HOOKW)
        bne     $t8, $t9, 1f                    # AF only with 8 MB RAM (the address does not exist on 2 MB)
        lui     $t9, 0x807e
        sb      $t7, -0xc0($t9)
        lui     $t9, 0x8008                     # 8 MB: intros always full (a 2 MB save's INTRO SIMPLE is ignored)
        sb      $zero, 0x58cb($t9)
1:      jr      $ra
        nop
