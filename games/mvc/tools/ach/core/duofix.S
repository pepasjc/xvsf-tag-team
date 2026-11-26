# MvC 1.0.1 native Duo Team Attack fixes (mktag --duofix, 2026-11-26).  The PS1 engine has the Duo (QCB + HP+HK, level
# +0x298 >= 2); in our tag layout (1) its cut-in shows the OPPONENT main's portrait (stock Cross Over assumption: the other
# side's SPVC set) and (2) the CPU never uses it.  (The cut-in background stripes = vcache over the parked BG image:
# vc4.py --vcduo.)
#   duo_case  jump table 0x8006b98c (team-super state 2 = Duo start, s0 = starter): remember the starter's side
#   duo_cut   0x80023974 `jal 0x80045124` (cut-in BG load, a0 = image id): once per Duo, the other side's SPVC set
#             (14 + side ^ 1) gets the starter's entries in the 6 per-set tables -> both halves = the starter's portrait
#   duo_end   0x80023b48 `jal 0x80023a30` (cut-in end): put the saved entries back
#   duo_in    0x8002dc68 (fighter input routine entry, a0 = object): CPU point, ARCADE BALANCE ON, level >= 2, partner
#             benched + alive, move < MOVEMAX, fight running, not paused, CPUP / 65536 chance per frame -> for 14 frames
#             the object is 'human' (+3 = 1) on its side's pad word = QCB + HP+HK; the native command path starts the Duo;
#             afterwards +3 = 0 and the pad word cleared (checked on every fighter's input call).
        .set    ARCBAL, 0x80011761
        .set    CASE2,  0x80033298
        .set    CUTLD,  0x80045124
        .set    CUTEND, 0x80023a30

DST:    .byte   0, 0, 0, 0              # +0 starter side + 1, +1 swapped set + 1, +2 / +3 injection frames left (side 0 / 1)
SAVE:   .word   0, 0, 0, 0, 0, 0        # the other set's entries: 5 word tables + 1 half table
INJ:    .word   0, 0                    # +28 / +32: the injected CPU object per side (0 = none)

duo_case:
        lb      $t0, 2($s0)
        lui     $t1, %hi(DST)
        addiu   $t0, $t0, 1
        j       CASE2
        sb      $t0, %lo(DST)($t1)

# ---- per-set tables: word tables T0-T4, half table TH
        .set    T0, 0x80092b30
        .set    T1, 0x8009cf40
        .set    T2, 0x80092b90
        .set    T3, 0x8009c210
        .set    T4, 0x80092bf0
        .set    TH, 0x80092b70

duo_cut:                                # (v1 is dead at the call site: it keeps ra across the swapw calls)
        move    $v1, $ra
        lui     $t9, %hi(DST)
        addiu   $t9, $t9, %lo(DST)
        lbu     $t0, 0($t9)
        lbu     $t1, 1($t9)
        beqz    $t0, 9f                 # no Duo start seen: stock
        sb      $zero, 0($t9)
        bnez    $t1, 9f                 # already swapped
        addiu   $t0, $t0, 13            # own set (14 + side)
        xori    $t1, $t0, 1             # the other side's set
        addiu   $t2, $t1, 1
        sb      $t2, 1($t9)
        sll     $t3, $t0, 2
        sll     $t4, $t1, 2
        lui     $t5, %hi(T0)
        addiu   $t5, $t5, %lo(T0)
        jal     swapw
        addiu   $t8, $t9, 4
        lui     $t5, %hi(T1)
        addiu   $t5, $t5, %lo(T1)
        jal     swapw
        addiu   $t8, $t9, 8
        lui     $t5, %hi(T2)
        addiu   $t5, $t5, %lo(T2)
        jal     swapw
        addiu   $t8, $t9, 12
        lui     $t5, %hi(T3)
        addiu   $t5, $t5, %lo(T3)
        jal     swapw
        addiu   $t8, $t9, 16
        lui     $t5, %hi(T4)
        addiu   $t5, $t5, %lo(T4)
        jal     swapw
        addiu   $t8, $t9, 20
        lui     $t5, %hi(TH)            # half table
        addiu   $t5, $t5, %lo(TH)
        sll     $t6, $t0, 1
        addu    $t6, $t5, $t6
        lhu     $t7, 0($t6)
        sll     $t6, $t1, 1
        addu    $t6, $t5, $t6
        lhu     $t2, 0($t6)
        sh      $t7, 0($t6)
        sw      $t2, 24($t9)
9:      j       CUTLD                   # ra = the caller's (jal site 0x80023974)
        move    $ra, $v1

swapw:                                  # t5 table, t3 own * 4, t4 other * 4, t8 save slot; t6 t7 t2 scratch (stackless)
        addu    $t6, $t5, $t3
        lw      $t7, 0($t6)
        addu    $t6, $t5, $t4
        lw      $t2, 0($t6)
        sw      $t7, 0($t6)
        jr      $ra
        sw      $t2, 0($t8)

duo_end:
        addiu   $sp, $sp, -0x18
        sw      $ra, 0x10($sp)
        jal     CUTEND
        nop
        lui     $t9, %hi(DST)
        addiu   $t9, $t9, %lo(DST)
        lbu     $t1, 1($t9)
        sb      $zero, 0($t9)
        beqz    $t1, 8f
        sb      $zero, 1($t9)
        addiu   $t1, $t1, -1            # the other set
        sll     $t4, $t1, 2
        lui     $t5, %hi(T0)
        addiu   $t5, $t5, %lo(T0)
        lw      $t2, 4($t9)
        addu    $t6, $t5, $t4
        sw      $t2, 0($t6)
        lui     $t5, %hi(T1)
        addiu   $t5, $t5, %lo(T1)
        lw      $t2, 8($t9)
        addu    $t6, $t5, $t4
        sw      $t2, 0($t6)
        lui     $t5, %hi(T2)
        addiu   $t5, $t5, %lo(T2)
        lw      $t2, 12($t9)
        addu    $t6, $t5, $t4
        sw      $t2, 0($t6)
        lui     $t5, %hi(T3)
        addiu   $t5, $t5, %lo(T3)
        lw      $t2, 16($t9)
        addu    $t6, $t5, $t4
        sw      $t2, 0($t6)
        lui     $t5, %hi(T4)
        addiu   $t5, $t5, %lo(T4)
        lw      $t2, 20($t9)
        addu    $t6, $t5, $t4
        sw      $t2, 0($t6)
        lui     $t5, %hi(TH)
        addiu   $t5, $t5, %lo(TH)
        lw      $t2, 24($t9)
        sll     $t6, $t1, 1
        addu    $t6, $t5, $t6
        sh      $t2, 0($t6)
8:      lw      $ra, 0x10($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 0x18

duo_in:                                 # a0 = object (fighter update: input routine entry); t-regs only, v0 set at the end
        lui     $t4, %hi(ARCBAL)        # (HW attract fix) ARCADE BALANCE OFF: the stock path at once, nothing read or written
        lbu     $t4, %lo(ARCBAL)($t4)
        nop
        beqz    $t4, 9f
        nop
        lui     $t9, %hi(DST)
        addiu   $t9, $t9, %lo(DST)
        lui     $t5, 0x8008
        addiu   $t5, $t5, 0x5040        # pads (game bits) 0x80085040 + side * 2
        li      $t1, 0                  # cleanup: a finished injection gives the object back to the AI
6:      addu    $t2, $t9, $t1
        lbu     $t3, 2($t2)
        sll     $t8, $t1, 2
        addu    $t8, $t9, $t8
        bnez    $t3, 7f
        lw      $t4, 28($t8)
        nop
        beqz    $t4, 7f
        sll     $t6, $t1, 1
        sb      $zero, 3($t4)           # AI again
        sw      $zero, 28($t8)
        addu    $t6, $t5, $t6
        sh      $zero, 0($t6)
7:      bnez    $t1, 8f
        nop
        b       6b
        li      $t1, 1
8:      lb      $t1, 2($a0)             # side
        nop
        addu    $t2, $t9, $t1
        sll     $t8, $t1, 2
        addu    $t8, $t9, $t8
        lbu     $t3, 2($t2)             # injection frames left
        lw      $t4, 28($t8)
        bnez    $t3, inj
        lb      $t0, 3($a0)
        nop
        bnez    $t0, 9f                 # human: stock
        lui     $t4, %hi(ARCBAL)
        lbu     $t4, %lo(ARCBAL)($t4)
        lui     $t6, 0x8008
        beqz    $t4, 9f                 # arcade rules off
        lbu     $t4, -0x47d8($t6)       # phase 0x8007b828
        lbu     $t7, -0x48be($t6)       # pause owner 0x8007b742
        addiu   $t4, $t4, -8
        bnez    $t4, 9f
        addiu   $t7, $t7, -0xff
        bnez    $t7, 9f
        lbu     $t4, 0($a0)
        lbu     $t7, 0x2a3($a0)
        beqz    $t4, 9f                 # not on screen
        lb      $t4, 0x298($a0)
        bnez    $t7, 9f                 # benched
        slti    $t4, $t4, 2
        bnez    $t4, 9f                 # LEVEL < 2
        lbu     $t4, 0xc8($a0)
        nop
        sltiu   $t4, $t4, MOVEMAX
        beqz    $t4, 9f                 # busy (attacking, hit, ...)
        lw      $t4, 0x2a8($a0)         # partner
        nop
        lbu     $t7, 0($t4)
        lh      $t0, 0x294($t4)
        bnez    $t7, 9f                 # partner on screen
        nop
        blez    $t0, 9f                 # partner KO
        lw      $t4, -0x48b4($t6)       # main loops 0x8007b74c
        lui     $t7, 0x41c6
        ori     $t7, $t7, 0x4e6d
        addu    $t4, $t4, $a0
        multu   $t4, $t7
        mflo    $t4
        srl     $t4, $t4, 16
        sltiu   $t4, $t4, CPUP          # chance CPUP / 65536 per eligible frame
        beqz    $t4, 9f
        li      $t3, 14
        sw      $a0, 28($t8)            # the CPU point takes "pad" input for 14 frames
        li      $t4, 1
        sb      $t4, 3($a0)
        move    $t4, $a0
inj:    bne     $t4, $a0, 9f            # only the injected object
        addiu   $t3, $t3, -1
        sb      $t3, 2($t2)
        lb      $t4, 0x47($a0)          # facing (1 = right): back = left (2), else right (1)
        li      $t0, 2
        bnez    $t4, 1f
        nop
        li      $t0, 1
1:      sltiu   $t6, $t3, 5             # frames left 13..0: 13-11 down, 10-8 down + back, 7-5 back, 4-0 back + HP + HK
        bnez    $t6, 2f
        sltiu   $t6, $t3, 8
        bnez    $t6, 3f
        sltiu   $t6, $t3, 11
        bnez    $t6, 4f
        nop
        b       5f
        li      $t7, 4
4:      b       5f
        ori     $t7, $t0, 4
3:      b       5f
        move    $t7, $t0
2:      ori     $t7, $t0, 0x440
5:      sll     $t6, $t1, 1
        addu    $t6, $t5, $t6
        sh      $t7, 0($t6)             # the input routine reads it right after (human path)
9:      j       0x8002dc6c
        lui     $v0, 0x8008
