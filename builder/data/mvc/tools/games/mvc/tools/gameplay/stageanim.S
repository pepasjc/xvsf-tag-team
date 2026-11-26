# STAGE ANIM option (games/mvc/tools/gameplay/stageanim.py, 2026-11-19): OPTION MODE line "STAGE ANIM  FULL / REDUCED /
# OFF" (mode byte 0x8007b708 = option block 0x8007b6e8 + 0x11 + cursor 15: the stock LEFT / RIGHT code changes it) and
# the battle part: objects whose type is in the stage's spawn list (EXE 0x8006edf0[stage]) get their animation timer
# obj+0x3a held (OFF: never below 8 = the current frame stays; REDUCED: +1 every other logic frame = ~half speed).  The
# objects keep running and drawing (no holes).  Chunks A-D, S: EXE dead spans (fnscan.py); R: RAM after the meter.

#@A
optdraw:                                        # from OPDEMO 0x800a29cc (was lbu v0,0xd(s0)); s0 = 0x8007b6e8
        .if     FS05                            # fs05: mode byte 0x800858c9 (block + 0x20 is the stock join mask)
        lui     $t0, 0x8008
        addiu   $sp, $sp, -24
        lb      $t1, 0x58c9($t0)                # mode (LEFT / RIGHT add -1 / +1, frameskip rbase): wrap 0..2
        sw      $ra, 16($sp)
        .else
        addiu   $sp, $sp, -24
        sw      $ra, 16($sp)
        lb      $t1, 0x20($s0)                  # mode (LEFT / RIGHT add -1 / +1): wrap 0..2
        nop
        .endif
        bgez    $t1, 1f
        slti    $t2, $t1, 3
        li      $t2, 1
        li      $t1, 2
1:      bnez    $t2, 2f
        nop
        move    $t1, $zero
2:      j       od2
        .if     FS05
        sb      $t1, 0x58c9($t0)
        .else
        sb      $t1, 0x20($s0)
        .endif

#@B
od2:    lb      $t1, 0xd($s0)                   # cursor 15 = our line: bright
        li      $t2, 15
        lui     $a2, 0x0823
        bne     $t1, $t2, 3f
        ori     $a2, $a2, 1
        lui     $a2, 0x0820
        ori     $a2, $a2, 1
3:      sw      $a2, 20($sp)
        lui     $a0, %hi(LBL)
        addiu   $a0, $a0, %lo(LBL)
        lui     $a1, 0x90
        j       od3
        ori     $a1, $a1, 0xc8

#@C
od3:    jal     FONT                            # label at x 0x90, y 0xc8
        nop
        .if     FS05
        lui     $t1, 0x8008
        lb      $t1, 0x58c9($t1)
        .else
        lb      $t1, 0x20($s0)
        .endif
        lui     $t2, %hi(VSTR)
        sll     $t1, $t1, 2
        addu    $t2, $t2, $t1
        lw      $a0, %lo(VSTR)($t2)
        lw      $a2, 20($sp)
        lui     $a1, 0x120
        j       od4
        ori     $a1, $a1, 0xc8

#@D
od4:    jal     FONT                            # value at x 0x120
        nop
        lw      $ra, 16($sp)
        lbu     $v0, 0xd($s0)                   # the replaced instruction
        jr      $ra
        addiu   $sp, $sp, 24
        .align  2
VSTR:   .word   STR_FULL, RED, STR_OFF
RED:    .asciz  "REDUCED"

#@S
sa_stub:                                        # from the object walkers (was jalr v0; a0 = object)
        lui     $t9, 0x8008
        lbu     $t9, -0x4227($t9)               # stage 0x8007bdd9: 9 (Onslaught) owns the RAM part's area
        li      $t8, 9
        beq     $t9, $t8, 1f
        lui     $t9, %hi(SA)
        lw      $t9, %lo(SA)($t9)
        li      $t8, SAMAGIC
        bne     $t9, $t8, 1f
        nop
        j       SA + 4
        nop
1:      jr      $v0
        nop

#@R
SA:     .word   SAMAGIC
        lui     $t0, 0x8008
        .if     FS05
        lbu     $t1, 0x58c9($t0)                # mode (fs05 byte): 0 FULL, 1 REDUCED, 2 OFF
        .else
        lbu     $t1, -0x48f8($t0)               # mode 0x8007b708: 0 FULL, 1 REDUCED, 2 OFF
        .endif
        lbu     $t2, -0x4227($t0)               # stage
        lbu     $t3, -0x4234($t0)               # scene 0x8007bdcc: 8 = battle (intro, fight, win); select / VS /
        beqz    $t1, go                         # title / continue screens run the same walkers: never touched
        lw      $t8, -0x48b4($t0)               # main-loop counter 0x8007b74c
        xori    $t3, $t3, 8
        bnez    $t3, go
        srl     $t9, $t1, 1                     # t9 = OFF
        andi    $t8, $t8, 1
        or      $t8, $t8, $t9                   # t8 = hold this call (OFF, or REDUCED on odd frames)
        ori     $t7, $zero, 0xffff              # per-stage words held at a fixed value (OFF and REDUCED): BG-layer
                                                # animation state written by stage objects; applied before every
        lui     $t3, %hi(HOLDS)                 # object call, so the last object of the frame leaves them held
        addiu   $t3, $t3, %lo(HOLDS)            # for the BG builder.  Entry {u16 stage, u16 value, u32 addr}
5:      lhu     $t4, 0($t3)
        lhu     $t6, 2($t3)
        lw      $t5, 4($t3)
        beq     $t4, $t7, 6f
        addiu   $t3, $t3, 8
        bne     $t4, $t2, 5b
        nop
        b       5b
        sh      $t6, 0($t5)
6:      sll     $t2, $t2, 2
        lui     $t3, %hi(SPAWN)
        addu    $t3, $t3, $t2
        lw      $t3, %lo(SPAWN)($t3)            # the stage's spawn list: 16-B records, u16 type at +2, 0xffff ends
        lhu     $t4, 0x5c($a0)                  # object type
        beqz    $t3, go
        ori     $t7, $zero, 0xffff
4:      lhu     $t6, 0($t3)
        lhu     $t5, 2($t3)
        beq     $t6, $t7, go
        addiu   $t3, $t3, 16
        bne     $t5, $t4, 4b
        nop
        lhu     $t5, 0x3a($a0)                  # stage object: animation timer (counts down by elapsed vblanks)
        beqz    $t8, go
        nop
        beqz    $t5, go
        addiu   $t5, $t5, 1                     # REDUCED odd frame / OFF: +1 (cancels this frame's tick)
        beqz    $t9, 9f
        sltiu   $t6, $t5, 8
        beqz    $t6, 9f                         # OFF: never below 8 (2-vblank frames tick twice)
        nop
        li      $t5, 8
9:      sh      $t5, 0x3a($a0)
go:     jr      $v0
        nop
        .align  2
HOLDS:  HOLDTAB
