# MSHvSF 1.1 options, EXE part (games/mshvsf/tools/gameplay/exopt.py; mktag.py --exopt / --frameskip / --stageanim).
# Pieces (split at the '# ----' lines) are packed by slib.pack into the EXE ranges exopt.RANGES (the 1.0 OPTION-line
# ranges of menus.py, free under --exopt, + the stock pause-menu draw routines, rewritten here as one routine).
# Option block OPTB (exopt.py: the word after the speed meter's flag, meter chunk S, dead span 0x80024378-0x800243d0):
#   +0 SPEED METER (the meter's own flag byte, 1 = on)   +1 FRAME SKIP (0 OFF, 1 AUTO, 2 MAX)   +2 STAGE ANIM (0 ON,
#   1 OFF)   +3 ACHIEVEMENT POPUP (0 ON, 1 OFF; read by the achievements runtime, port.c)   +4 FRAME SKIP: this pass
#   draws nothing   +5 passes skipped in a row   +8 (word) FRAME SKIP baseline of (vblanks - loops)
# Defines: OPTB, FS (FRAME SKIP built), SA (STAGE ANIM built), NPR (pause-menu rows: 3 stock + ours), PRE (stock target
# of the main loop's pre-decode call 0x80020c44), PRINT, SFX, PAD1 (0x8002370c: new press of one button on a pad).

# ---------------------------------------------------------------- FRAME SKIP, decision (main frame 0x80020ba8: was
# lh v0,0x75a(v0), v0 = 0x80070000; the frame draws when the result is >= 0).  In a fight with the option on, the lag
# e = vblanks - main loops (0x8001e364 Vcount, 0x800250b8) is compared with its baseline B (lowest e seen, reset outside running
# fights and pauses): d = e - B > 0 vblanks behind -> this pass runs the logic only (no sprite list, no draw, no present; the
# loop counter still counts it) while fewer than CAP passes in a row were skipped.  AUTO: CAP 1 (at least every other
# picture is drawn), MAX: CAP 3; lag above CAP + 1 is forgiven (B moves up: the stock slowdown).  OFF: the stock path.
fs_d:   lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)+1($t0)           # FRAME SKIP
        lh      $v0, 0x75a($v0)                 # the replaced load
        beqz    $t1, 9f
        sb      $zero, %lo(OPTB)+4($t0)         # this pass draws (until decided otherwise)
        lui     $t2, 0x8007
        lbu     $t3, 0x778($t2)                 # battle phase (8 = fighting)
        lh      $t4, 0xa94($t2)                 # scene (8 = battle)
        lui     $t5, 0x8002
        lbu     $t6, 0x5040($t5)                # game state (1 = the fight runs, 2 = paused)
        xori    $t3, $t3, 8
        xori    $t4, $t4, 8
        or      $t3, $t3, $t4
        xori    $t6, $t6, 1
        or      $t3, $t3, $t6                   # 0 = a running fight
        lw      $t6, 0x50b8($t5)                # main loops
        lw      $t7, -0x1c9c($t5)               # Vcount
        j       fs_d1
        sltiu   $t1, $t1, 2                     # 1 = AUTO
9:      jr      $ra
        nop

# ---------------------------------------------------------------- INFINITE SUPER METER (--infmeter): main frame
# 0x80020ba8 (was lh v0,0x75a(v0); v0 = 0x80070000 from the lui at 0x80020ba4, kept for the load), then FRAME SKIP's
# fs_d (with --frameskip: this piece sits at exopt.IM2, 18 words) or the replaced load.  Option byte OPTB+IMO 1 = ON:
# while fighting (battle phase 0x80070778 == 8) every fighter object (P1 0x80070b50, P2 0x80070f10, P1 partner
# 0x80071310, P2 partner 0x800716c8) gets level 3 (+0x258, the maximum) and meter 0 (+0x256, the game's own capped
# state at level 3), human and CPU.  OFF: one byte test.
im_d:   lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)+IMO($t0)
        lbu     $t3, 0x778($v0)                 # battle phase (8 = fighting)
        ori     $t5, $zero, 3
        beqz    $t1, 9f
        addiu   $t3, $t3, -8
        bnez    $t3, 9f
        nop
        sh      $zero, 0xb50+0x256($v0)
        sb      $t5, 0xb50+0x258($v0)
        sh      $zero, 0xf10+0x256($v0)
        sb      $t5, 0xf10+0x258($v0)
        sh      $zero, 0x1310+0x256($v0)
        sb      $t5, 0x1310+0x258($v0)
        sh      $zero, 0x16c8+0x256($v0)
        sb      $t5, 0x16c8+0x258($v0)
9:
        .if     FS
        j       fs_d
        nop
        .else
        lh      $v0, 0x75a($v0)                 # the replaced load (its use is after our return: no load-delay hazard)
        jr      $ra
        nop
        .endif

# ---------------------------------------------------------------- FRAME SKIP, decision part 1
fs_d1:  lw      $t8, %lo(OPTB)+8($t0)           # B
        subu    $t7, $t7, $t6                   # e
        bnez    $t3, 8f
        subu    $t9, $t7, $t8                   # d
        blez    $t9, 8f
        nop
        j       fs_d2
        sll     $t1, $t1, 1
8:      sw      $t7, %lo(OPTB)+8($t0)           # not fighting / not behind: B = e, no skip in a row
        jr      $ra
        sb      $zero, %lo(OPTB)+5($t0)

# ---------------------------------------------------------------- FRAME SKIP, decision part 2 (t9 = d > 0)
fs_d2:  ori     $t3, $zero, 3
        lbu     $t6, %lo(OPTB)+5($t0)           # skipped in a row
        subu    $t3, $t3, $t1                   # CAP: 1 AUTO, 3 MAX
        addiu   $t4, $t3, 1                     # bank
        slt     $t5, $t4, $t9
        beqz    $t5, 1f
        nop
        subu    $t8, $t7, $t4                   # forgive the lag above the bank
        sw      $t8, %lo(OPTB)+8($t0)
1:      slt     $t5, $t6, $t3
        beqz    $t5, 2f
        addiu   $t6, $t6, 1
        sb      $t6, %lo(OPTB)+5($t0)
        ori     $t5, $zero, 1
        sb      $t5, %lo(OPTB)+4($t0)           # skip this pass's picture
        jr      $ra
        addiu   $v0, $zero, -1
2:      jr      $ra                             # CAP reached: draw
        sb      $zero, %lo(OPTB)+5($t0)

# ---------------------------------------------------------------- FRAME SKIP, the pre-decode (main frame 0x80020c44,
# was jal PRE): not in a pass that draws nothing (the queue is fed by the sprite list; decode-ahead would idle on to
# the vblank)
fs_pre: lui     $t0, %hi(OPTB)
        lbu     $t0, %lo(OPTB)+4($t0)
        nop
        bnez    $t0, 1f
        nop
        j       PRE
        nop
1:      jr      $ra
        nop

# ---------------------------------------------------------------- FRAME SKIP, present (main frame 0x80020c54, was
# jal 0x800208c8).  A pass that draws nothing does present's bookkeeping only: the DrawSync call (or what replaced it
# at 0x800208d4: the achievements' evaluation), vblank count 0x800250b4, loop counter 0x800250b8 + 1; no VSync wait,
# no buffer flip.
fs_prs: lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)+4($t0)
        lui     $t2, 0x8002
        bnez    $t1, 1f
        lw      $t3, 0x50b8($t2)
        j       0x800208c8                      # present
        nop
1:      lw      $t4, -0x1c9c($t2)               # Vcount
        addiu   $t3, $t3, 1
        sw      $t3, 0x50b8($t2)
        sw      $t4, 0x50b4($t2)
        lw      $t5, 0x8d4($t2)                 # jal at 0x800208d4: DrawSync or the achievements' idle hook
        lui     $t6, 0x8000
        sll     $t5, $t5, 6
        srl     $t5, $t5, 4
        or      $t5, $t5, $t6
        jr      $t5                             # (a0 = 0), returns to the main frame
        move    $a0, $zero

# ---------------------------------------------------------------- STAGE ANIM OFF: the animation step 0x8004a070
# (obj+0x3a -= 1, next record at 0; entry `addiu sp,sp,-0x18; sw ra,0x10(sp)` -> `j sa_tk; nop`).  In a fight (phase 8,
# scene 8), for objects run by the stage overlay's handler (object type obj+0x5c -> handler table 0x80065450, entry
# 0x80094804) the step does nothing (returns 0 = no new record): the stage's objects keep their frame and still run
# (movement, state).  ON / not a stage object: the stock step.
sa_tk:  lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)+2($t0)           # STAGE ANIM: 0 ON
        lui     $t3, 0x8007
        beqz    $t1, 9f
        lbu     $t4, 0x778($t3)                 # battle phase
        lh      $t5, 0xa94($t3)                 # scene
        xori    $t4, $t4, 8
        xori    $t5, $t5, 8
        or      $t4, $t4, $t5
        bnez    $t4, 9f
        lh      $t6, 0x5c($a0)                  # object type
        lui     $t7, 0x8006
        sra     $t6, $t6, 2
        sll     $t6, $t6, 2
        addu    $t7, $t7, $t6
        lw      $t7, 0x5450($t7)                # its handler (as the walker 0x8002b9a0 picks it)
        lui     $t8, 0x8009
        ori     $t8, $t8, 0x4804
        bne     $t7, $t8, 9f
        nop
        jr      $ra                             # a stage object: hold
        move    $v0, $zero
9:      addiu   $sp, $sp, -0x18
        j       0x8004a078
        sw      $ra, 0x10($sp)

# ---------------------------------------------------------------- pause menu (START, then SELECT): the stock input
# routine 0x80029554 (caller 0x80029a00) rewritten with the same calls and stores: UP / DOWN (sounds 0x84 / 0x85),
# else CROSS (new press, bit 0x40) on CONTINUE (sub-state 0), KEY CONFIG* (obj+0xb2/b3 = 0, sub-state 3), QUIT
# (obj+0x10 = 2, sub-state + 1), each after 0x8007bdcc(0); cursor obj+0x1c wraps in 0 .. NPR - 1; then the draw.  Our
# rows (cursor >= 3): LEFT / RIGHT change the value (xkey) instead of CROSS.  a0 = the pause object (+0x6e = the
# pausing player's pad).
pmenu:  addiu   $sp, $sp, -32
        sw      $ra, 28($sp)
        sw      $s0, 24($sp)
        sw      $s1, 20($sp)
        sw      $s2, 16($sp)
        move    $s1, $a0
        lb      $s0, 0x6e($s1)
        lbu     $s2, 0x1c($s1)                  # cursor
        move    $a0, $s0
        jal     PAD1
        ori     $a1, $zero, 0x1000              # UP
        addiu   $t0, $s2, -1
        bnez    $v0, 2f
        ori     $a0, $zero, 0x84
        move    $a0, $s0
        jal     PAD1
        ori     $a1, $zero, 0x4000              # DOWN
        addiu   $t0, $s2, 1
        beqz    $v0, 3f
        ori     $a0, $zero, 0x85
2:      jal     SFX
        sb      $t0, 0x1c($s1)
        b       8f
        nop
3:      sltiu   $t0, $s2, 3
        bnez    $t0, 5f
        move    $a0, $s0
        jal     PAD1                            # our rows: RIGHT / LEFT
        ori     $a1, $zero, 0x2000
        bnez    $v0, 4f
        ori     $a1, $zero, 1
        move    $a0, $s0
        jal     PAD1
        ori     $a1, $zero, 0x8000
        beqz    $v0, 8f
        addiu   $a1, $zero, -1
4:      addiu   $t0, $s2, -3
        sll     $t1, $t0, 2
        sll     $t0, $t0, 4
        addu    $t0, $t0, $t1
        la      $a0, PROWS
        jal     xkey
        addu    $a0, $a0, $t0                   # the row's record
        b       8f
        nop
5:      sll     $t0, $s0, 1                     # stock rows: CROSS
        lui     $t1, 0x8002
        addu    $t1, $t1, $t0
        lhu     $t2, 0x7d60($t1)                # now
        lhu     $t3, 0x7db8($t1)                # before
        andi    $t2, $t2, 0x40
        beqz    $t2, 8f
        andi    $t3, $t3, 0x40
        bnez    $t3, 8f
        nop
        jal     0x8007bdcc
        move    $a0, $zero
        ori     $t1, $zero, 1
        beq     $s2, $t1, 6f
        ori     $t1, $zero, 2
        beq     $s2, $t1, 7f
        nop
        b       8f                              # CONTINUE: sub-state 0
        sb      $zero, 3($s1)
6:      sb      $zero, 0xb3($s1)                # KEY CONFIG*
        sb      $zero, 0xb2($s1)
        ori     $t1, $zero, 3
        b       8f
        sb      $t1, 3($s1)
7:      lbu     $t1, 3($s1)                     # QUIT: the question
        sb      $s2, 0x10($s1)
        addiu   $t1, $t1, 1
        sb      $t1, 3($s1)
8:      lb      $t0, 0x1c($s1)                  # wrap
        nop
        bgez    $t0, 1f
        slti    $t1, $t0, NPR
        ori     $t0, $zero, NPR - 1
        b       9f
        sb      $t0, 0x1c($s1)
1:      bnez    $t1, 9f
        nop
        sb      $zero, 0x1c($s1)
9:      jal     pdraw
        move    $a0, $s1
        lw      $ra, 28($sp)
        lw      $s0, 24($sp)
        lw      $s1, 20($sp)
        lw      $s2, 16($sp)
        jr      $ra
        addiu   $sp, $sp, 32

# ---------------------------------------------------------------- pause menu draw: the stock routines 0x80029404
# (CONTINUE / KEY CONFIG* / QUIT, cursor obj+0x1c) and 0x800294a8 (QUIT GAME! / YES / NO, cursor obj+0x10, the first
# line always bright) as one routine with the same calls (text at x 0xb0, y 0x58 + 0x20 * row, colour 0x24 bright /
# 0x27, 0x10004001), + our rows after QUIT: label at PLX, value at PVX.  pconf: caller 0x80029830 (was jal 0x800294a8).
pdraw:  ori     $t9, $zero, 0x1c
        lui     $t8, 0x8006
        addiu   $t8, $t8, 0x5038
        ori     $t7, $zero, NPR
        b       pd0
        addiu   $t6, $zero, -1                  # no always-bright row
pconf:  ori     $t9, $zero, 0x10
        lui     $t8, 0x8006
        addiu   $t8, $t8, 0x5044
        ori     $t7, $zero, 3
        move    $t6, $zero                      # row 0 always bright
pd0:    addiu   $sp, $sp, -40
        sw      $ra, 36($sp)
        sw      $s0, 32($sp)
        sw      $s1, 28($sp)
        sw      $s2, 24($sp)
        sw      $s3, 20($sp)
        sw      $s4, 16($sp)
        sw      $s5, 12($sp)
        addu    $s3, $a0, $t9                   # the cursor byte
        move    $s1, $t8                        # stock strings
        move    $s4, $t7                        # rows
        move    $s5, $t6
        move    $s0, $zero
1:      lb      $t0, 0($s3)
        ori     $a2, $zero, 0x24
        beq     $t0, $s0, 2f
        nop
        beq     $s5, $s0, 2f
        nop
        ori     $a2, $zero, 0x27
2:      sll     $a2, $a2, 16
        lui     $t1, 0x1000
        ori     $t1, $t1, 0x4001
        or      $a2, $a2, $t1
        sll     $s2, $s0, 5
        addiu   $s2, $s2, 0x58                  # y
        slti    $t0, $s0, 3
        beqz    $t0, 3f
        lui     $a1, 0xb0
        lw      $a0, 0($s1)
        jal     PRINT
        or      $a1, $a1, $s2
        b       4f
        addiu   $s1, $s1, 4
3:      addiu   $t0, $s0, -3                    # our row: label, value
        sll     $t1, $t0, 2
        sll     $t0, $t0, 4
        addu    $t0, $t0, $t1
        la      $s1, PROWS
        addu    $s1, $s1, $t0
        sw      $a2, 8($sp)
        lw      $a0, 0($s1)
        lui     $a1, PLX
        jal     PRINT
        or      $a1, $a1, $s2
        jal     rowval
        move    $a0, $s1
        sll     $v0, $v0, 2
        addu    $v0, $v0, $s1
        lw      $a0, 8($v0)
        lw      $a2, 8($sp)
        lui     $a1, PVX
        jal     PRINT
        or      $a1, $a1, $s2
4:      addiu   $s0, $s0, 1
        slt     $t0, $s0, $s4
        bnez    $t0, 1b
        nop
        lw      $ra, 36($sp)
        lw      $s0, 32($sp)
        lw      $s1, 28($sp)
        lw      $s2, 24($sp)
        lw      $s3, 20($sp)
        lw      $s4, 16($sp)
        lw      $s5, 12($sp)
        jr      $ra
        addiu   $sp, $sp, 40

# ---------------------------------------------------------------- v0 = value of record a0 (byte OPTB + rec[4])
rowval: lbu     $t0, 4($a0)
        lui     $t1, %hi(OPTB)
        addu    $t1, $t1, $t0
        lbu     $v0, %lo(OPTB)($t1)
        jr      $ra                             # (callers use v0 at once: not loaded in the delay slot)
        nop

# ---------------------------------------------------------------- value of record a0 + a1 (+1 / -1), wrapped in
# 0 .. rec[5] - 1, with the cursor sound (also called by the EX OPTIONS screen, exopt.S)
xkey:   lbu     $t0, 4($a0)
        lbu     $t1, 5($a0)
        lui     $t2, %hi(OPTB)
        addu    $t2, $t2, $t0
        lbu     $t3, %lo(OPTB)($t2)
        nop
        addu    $t3, $t3, $a1
        bltz    $t3, 1f
        addiu   $t4, $t1, -1                    # below the first -> the last
        sltu    $t4, $t3, $t1
        subu    $t4, $zero, $t4
        and     $t4, $t4, $t3                   # past the last -> the first
1:      sb      $t4, %lo(OPTB)($t2)
        j       SFX
        ori     $a0, $zero, 0x84

# ---------------------------------------------------------------- pause rows: {label, u8 option offset, u8 values,
# 2 pad, value strings x 3}
PROWS:
        .if     FS
        .word   pl_fs
        .byte   1, 3, 0, 0
        .word   pv_off, pv_auto, MAXSTR
        .endif
        .if     SM
        .word   pl_sm
        .byte   0, 2, 0, 0
        .word   pv_off, pv_on, 0
        .endif
pl_fs:  .asciz  "FRAME SKIP"
pl_sm:  .asciz  "SPEED METER"
pv_off: .asciz  "OFF"
pv_on:  .asciz  "ON"
pv_auto: .asciz "AUTO"
        .align  2
