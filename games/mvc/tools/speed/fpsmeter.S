# fpsmeter.S = meter.S chunks S / C + fpsmeter_r.S (user SPEED METER, --fpsmeter); regenerate when either changes.
# MvC on-screen speed meter (hardware measurement; port of games/mshvsf/tools/speed/meter/meter.S).  Shows, bottom
# left of the picture, in battle:
#     RR WW abcd     RR = main-loop iterations in the last 60 vblanks (60 = full speed), WW = worst such second
#                    since the round started, abcd = sprite tiers of P1 main, P1 partner, P2 main, P2 partner
#                    (tl_dbg of games/mvc/tools/tagload: index into mktag.py TIERS, blank = shared with another slot)
# On / off: the word mflag (EXE; mktag.py sets it).  Tiers show "----" in tag battles the loader did not reload
# (rematch).  DEBUG: in a battle under the stock rules (versus flag 0x8007b75d != 0 = the tag fell back) the line
# is  RR WW cccc..  = tl_dbg[0..3] in hex (tl_dbg[0] = the loader's decline code, tagload.c) + LOADER_FULL.
#
# Two parts:
#   STUB  (EXE, chunk S): replaces `jal PutDrawEnv` (0x80012094) in present 0x80022a0c (at 0x80022a84, after
#         DrawSync + VSync + the loop counter).  Only when fighting (0x8007b828 == 8), meter on (mflag) and the RAM part
#         carries its magic: jumps to it; else PutDrawEnv.
#   METER (RAM MRAM, in the loader's strong payload; copied by the loader in tag battles and, for every battle, by
#         MCOPY (chunk C, tail of the battle-init stub tools/gameplay/tagmode.py) from the loader blob still in the
#         arena).  Counts, then draws 10 7-segment glyphs as GPU rectangles straight into GP0 (GPU idle: DrawSync +
#         VSync done; the drawing environment is still the one of the frame about to be shown), then PutDrawEnv.
# Cost: off ~15 instructions per frame; on ~60 rectangles (~3-5K cycles) per frame.

#@S
mstub:
        lui     $t0, 0x8008
        lbu     $t1, -0x47d8($t0)               # battle phase 0x8007b828
        lbu     $t4, -0x4234($t0)               # scene 0x8007bdcc (8 = battle; the phase byte stays 8 afterwards)
        lui     $t3, %hi(mflag)
        lbu     $t3, %lo(mflag)($t3)            # 1 = meter on
        xori    $t1, $t1, 8
        xori    $t4, $t4, 8
        or      $t1, $t1, $t4
        sltiu   $t3, $t3, 1
        or      $t1, $t1, $t3
        lui     $t0, %hi(MRAM)
        bnez    $t1, 1f
        lw      $t2, %lo(MRAM)($t0)             # magic of the RAM part
        lui     $t3, %hi(MAGIC)
        ori     $t3, $t3, %lo(MAGIC)
        beq     $t2, $t3, 2f
        nop
1:      j       0x80012094                      # PutDrawEnv
        nop
2:      j       MRAM + 4
        nop
mflag:  .word   MFLAG0                          # byte 0: 1 = meter on

#@C
# ---------------------------------------------------------------- MCOPY: tail of the battle-init stub (tagmode.py),
# once per battle after the characters are loaded: the meter part of the strong payload, from the loader blob that
# is still in the sprite arena, to MRAM (whatever loader ran).  Then the stock return.
mcopy:
        lui     $t0, %hi(BLOBMETER)
        addiu   $t0, $t0, %lo(BLOBMETER)
        lui     $t2, %hi(MAGIC)
        lw      $t1, 0($t0)
        ori     $t2, $t2, %lo(MAGIC)
        bne     $t1, $t2, 9f
        lui     $t3, %hi(MRAM)
        addiu   $t3, $t3, %lo(MRAM)
        addiu   $t4, $t3, MSIZE
1:      lw      $t1, 0($t0)
        addiu   $t0, $t0, 4
        sw      $t1, 0($t3)
        addiu   $t3, $t3, 4
        bne     $t3, $t4, 1b
        nop
        addiu   $sp, $sp, -24
        sw      $ra, 20($sp)
        jal     FLUSHCACHE
        nop
        lw      $ra, 20($sp)
        addiu   $sp, $sp, 24
9:      jr      $ra
        nop

#@R
# ---------------------------------------------------------------- user SPEED METER (--fpsmeter, dx worker 2026-11-20).
# Every drawn loop (present):
#   logic passes = main-loop counter 0x8007b74c + the sum of the engine's catch-up pending count 0x8007b75b seen here
#   (FRAME SKIP's logic-only passes; exact vs a counter on the logic call 0x80022ff4, work/meter/fsloops.py)
#   every >= 30 vblanks: rate = passes in the last two half windows * 60 / their vblanks (rounded), the same for the
#   drawn loops.  The free-on-KO watcher is called every time (kocache needs it; meter shown or not).  Drawing only
#   when the option byte OPTB != 0: bottom left, "GG" = game loops / s; with FRAME SKIP on (FSB != 0) and fewer drawn
#   than logic loops, "GG DD" (DD = pictures / s).
mram:   .word   MAGIC
meter:
        addiu   $sp, $sp, -40
        sw      $ra, 36($sp)
        sw      $a0, 32($sp)
        sw      $s0, 28($sp)
        sw      $s1, 24($sp)
        sw      $s2, 20($sp)
        la      $s0, mst
        lui     $t0, 0x8008
        lbu     $t3, -0x48a5($t0)               # catch-up pending 0x8007b75b
        lw      $t4, 16($s0)                    # sum of pending
        lw      $t1, -0x48b8($t0)               # VSync(-1) count 0x8007b748
        lw      $t6, -0x48b4($t0)               # main-loop counter 0x8007b74c (drawn loops)
        addu    $t4, $t4, $t3
        sw      $t4, 16($s0)
        addu    $t2, $t6, $t4                   # logic passes
        lw      $t5, 0($s0)                     # vcount at the last sample
        nop
        subu    $t7, $t1, $t5                   # vblanks since
        sltiu   $t8, $t7, 30
        bnez    $t8, 6f
        nop
        lw      $t9, 4($s0)                     # logic at the last sample
        lw      $a1, 8($s0)                     # drawn at the last sample
        sw      $t1, 0($s0)
        sw      $t2, 4($s0)
        beqz    $t5, 6f                         # first sample of this battle
        sw      $t6, 8($s0)
        subu    $t9, $t2, $t9                   # logic in this half
        subu    $a1, $t6, $a1                   # drawn in this half
        lw      $a2, 12($s0)                    # previous half: logic
        lw      $a3, 20($s0)                    #                drawn
        lw      $v1, 24($s0)                    #                vblanks
        sw      $t9, 12($s0)
        sw      $a1, 20($s0)
        sw      $t7, 24($s0)
        beqz    $v1, 6f                         # need two halves
        addu    $t9, $t9, $a2
        addu    $a1, $a1, $a3
        addu    $v1, $v1, $t7                   # window vblanks
        srl     $v0, $v1, 1
        sll     $t8, $t9, 6
        sll     $t9, $t9, 2
        subu    $t9, $t8, $t9                   # * 60
        addu    $t9, $t9, $v0
        divu    $zero, $t9, $v1
        sll     $t8, $a1, 6
        sll     $a1, $a1, 2
        subu    $a1, $t8, $a1
        addu    $a1, $a1, $v0
        mflo    $t9
        nop
        nop
        divu    $zero, $a1, $v1
        sw      $t9, 28($s0)                    # game loops / s
        mflo    $a1
        nop
        sw      $a1, 32($s0)                    # pictures / s
6:      lui     $t0, %hi(KOAT)                  # free-on-KO watcher (tools/tagload/kocache.py) when present
        lw      $t1, %lo(KOAT)($t0)
        lui     $t2, %hi(KOMAGIC)
        ori     $t2, $t2, %lo(KOMAGIC)
        bne     $t1, $t2, 7f
        nop
        jal     KOAT + 4
        nop
7:      lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)($t0)             # SPEED METER option (0 = off)
        nop
        beqz    $t1, 99f
        nop
        jal     mdraw
        nop
99:     lw      $ra, 36($sp)
        lw      $a0, 32($sp)
        lw      $s0, 28($sp)
        lw      $s1, 24($sp)
        lw      $s2, 20($sp)
        j       0x80012094                      # PutDrawEnv(a0), returns to present
        addiu   $sp, $sp, 40

# ---------------------------------------------------------------- draw: digits as 7-segment GPU rectangles straight
# into GP0 (GPU idle after DrawSync + VSync), background box first.
mdraw:
        la      $t9, mdig
        ori     $t2, $zero, 10
        ori     $s2, $zero, 2                   # cells
        lw      $t1, 28($s0)
        nop
        beqz    $t1, 40f                        # no rate yet: nothing
        sltiu   $t3, $t1, 61
        bnez    $t3, 1f
        nop
        ori     $t1, $zero, 60                  # FRAME SKIP catch-up bursts run > 60 passes / s: shown as 60
1:      divu    $zero, $t1, $t2
        mflo    $t3
        mfhi    $t4
        bnez    $t3, 2f
        nop
        ori     $t3, $zero, 16                  # leading blank
2:      sb      $t3, 0($t9)
        sb      $t4, 1($t9)
        lui     $t0, %hi(FSB)
        lbu     $t0, %lo(FSB)($t0)              # FRAME SKIP mode (0 = off)
        lw      $t5, 32($s0)
        andi    $t0, $t0, FSMASK                # 0 when the build has no FRAME SKIP row
        beqz    $t0, 30f
        sltu    $t6, $t5, $t1                   # drawn < logic
        beqz    $t6, 30f
        nop
        ori     $s2, $zero, 5
        ori     $t3, $zero, 16
        sb      $t3, 2($t9)
        divu    $zero, $t5, $t2
        mflo    $t3
        mfhi    $t4
        bnez    $t3, 3f
        nop
        ori     $t3, $zero, 16
3:      sb      $t3, 3($t9)
        sb      $t4, 4($t9)
30:
        lui     $a2, 0x1f80                     # GPU ports
        lui     $a3, 0x0400                     # GPUSTAT bit 26: ready for a command word
        lui     $t0, 0x6010                     # background: dark, (X0 - 2, Y0 - 2)
        ori     $t0, $t0, 0x1010
        ori     $t1, $zero, X0 - 2
        lui     $t2, Y0 - 2
        or      $t1, $t1, $t2
        sll     $t2, $s2, 3
        addiu   $t2, $t2, 2                     # width: 8 per cell + 2
        lui     $t3, 14
        or      $t2, $t2, $t3
1:      lw      $t3, 0x1814($a2)
        nop
        and     $t3, $t3, $a3
        beqz    $t3, 1b
        nop
        sw      $t0, 0x1810($a2)
        sw      $t1, 0x1810($a2)
        sw      $t2, 0x1810($a2)
        ori     $t8, $zero, X0                  # x of the cell
        addu    $t7, $t9, $s2
2:      lbu     $t1, 0($t9)
        la      $t2, mfont
        addu    $t2, $t2, $t1
        lbu     $t1, 0($t2)                     # segment mask
        la      $t6, mseg
3:      andi    $t3, $t1, 1
        beqz    $t3, 5f
        lbu     $t4, 0($t6)                     # sx
        lbu     $t5, 1($t6)                     # sy
        addu    $t4, $t4, $t8
        addiu   $t5, $t5, Y0
        sll     $t5, $t5, 16
        or      $t4, $t4, $t5                   # y << 16 | x
        lbu     $t5, 2($t6)                     # w
        lbu     $t3, 3($t6)                     # h
        lui     $t0, 0x60ff
        sll     $t3, $t3, 16
        or      $t5, $t5, $t3
        ori     $t0, $t0, 0xffff                # white
4:      lw      $t3, 0x1814($a2)
        nop
        and     $t3, $t3, $a3
        beqz    $t3, 4b
        nop
        sw      $t0, 0x1810($a2)
        sw      $t4, 0x1810($a2)
        sw      $t5, 0x1810($a2)
5:      srl     $t1, $t1, 1
        bnez    $t1, 3b
        addiu   $t6, $t6, 4
        addiu   $t9, $t9, 1
        bne     $t9, $t7, 2b
        addiu   $t8, $t8, 8
40:     jr      $ra
        nop

mfont:  .byte   0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71, 0, 0x40
mseg:   .byte   0, 0, 6, 2,   4, 0, 2, 5,   4, 5, 2, 5,   0, 8, 6, 2,   0, 5, 2, 5,   0, 0, 2, 5,   0, 4, 6, 2
mdig:   .byte   0, 0, 0, 0, 0, 0, 0, 0
        .align  2
mst:    .word   0, 0, 0, 0, 0, 0, 0, 0, 0
mram_end:
