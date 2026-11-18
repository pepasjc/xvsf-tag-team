# MSHvSF on-screen speed meter (hardware measurement).  Shows, bottom left of the picture, in battle:
#     RR WW abcd     RR = main-loop iterations in the last 60 vblanks (60 = full speed), WW = worst such second
#                    since the round started, abcd = sprite tiers of P1 main, P1 partner, P2 main, P2 partner
#                    (tl_dbg: 0 DSH1 with cut tiles, 1 DSH1, 2-5 DSH1+hot4/8/16/32, 6 DSM1, 7-9 DSM1+hot16/32/64,
#                    A stock RLE, blank = shares another slot's data)
# On / off: the byte mflag (EXE, 1 = on, 0 at load = off), switched by the OPTION menu line "SPEED METER"
# (tools/gameplay/menus.py, which owns the option-line table); mktag --meteron sets it to 1 in the EXE.
# Tiers show "----" in battles the tag loader did not load (stock loader: char 00, attract demo, fall-backs).
#
# Two parts:
#   STUB  (EXE, chunk S): replaces `jal PutDispEnv` in present 0x80020940.  Only when fighting (0x80070778 == 8),
#         meter on (mflag) and the RAM part carries its magic: jumps to it; else PutDispEnv.
#   METER (RAM 0x801fe640, behind the DSH1 decoder in the loader's strong payload; copied by the loader in tag
#         battles and, for every battle, by the battle-init tail MCOPY from the loader blob still in the arena;
#         state zeroed with it).  Counts, then draws 10 7-segment glyphs as GPU rectangles straight into GP0 (the GPU is
#         idle here: present did DrawSync + VSync; the drawing environment is still the frame about to be shown),
#         bottom left, then PutDispEnv.  No RAM buffer (0x801fec00.. looked unused but holds static pointers).
# Cost: off ~15 instructions per frame; on ~60 rectangles (~3-5K cycles) per frame.

#@S
mstub:
        lui     $t0, 0x8007
        lbu     $t1, 0x778($t0)                 # battle phase
        lui     $t3, %hi(mflag)
        lbu     $t3, %lo(mflag)($t3)            # 1 = meter on
        xori    $t1, $t1, 8
        sltiu   $t3, $t3, 1
        or      $t1, $t1, $t3
        lui     $t0, %hi(MRAM)
        bnez    $t1, 1f
        lw      $t2, %lo(MRAM)($t0)             # magic of the RAM part
        lui     $t3, %hi(MAGIC)
        ori     $t3, $t3, %lo(MAGIC)
        beq     $t2, $t3, 2f
        nop
1:      j       0x80011414                      # PutDispEnv
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
mram:   .word   MAGIC
meter:
        addiu   $sp, $sp, -40
        sw      $ra, 36($sp)
        sw      $a0, 32($sp)
        sw      $s0, 28($sp)
        sw      $s1, 24($sp)
        sw      $s2, 20($sp)
        la      $s0, mst
        lui     $t0, 0x8002                     # loops per 60 vblanks
        lw      $t1, -0x1c9c($t0)               # Vcount
        lw      $t2, 0x50b8($t0)                # main-loop counter
        lw      $t5, 0($s0)
        lw      $t6, 4($s0)
        subu    $t7, $t1, $t5
        sltiu   $t7, $t7, 60
        bnez    $t7, 6f
        nop
        sw      $t1, 0($s0)
        sw      $t2, 4($s0)
        beqz    $t5, 6f                         # first sample of this battle
        subu    $t8, $t2, $t6                   # rate
        sltiu   $t7, $t8, 100
        bnez    $t7, 5f
        nop
        ori     $t8, $zero, 99
5:      sw      $t8, 8($s0)
        lui     $t0, 0x8007
        lbu     $t9, 0x782($t0)                 # round clock: 0x99 at the start of a round
        lw      $t3, 12($s0)
        xori    $t9, $t9, 0x99
        beqz    $t9, 55f
        sltu    $t7, $t8, $t3
        beqz    $t3, 55f
        nop
        beqz    $t7, 6f
        nop
55:     sw      $t8, 12($s0)                    # worst
6:      jal     mdraw
        nop
99:     lw      $ra, 36($sp)
        lw      $a0, 32($sp)
        lw      $s0, 28($sp)
        lw      $s1, 24($sp)
        lw      $s2, 20($sp)
        j       0x80011414                      # PutDispEnv(a0), returns to present
        addiu   $sp, $sp, 40

# ---------------------------------------------------------------- draw the text of mst: 7-segment digits as GPU
# monochrome rectangles (GP0 0x60) written straight to GP0.  Called after DrawSync + VSync (GPU idle), before
# PutDispEnv / PutDrawEnv: the drawing environment is still the one of the frame about to be shown.
mdraw:
        la      $t9, mdig                       # 10 glyph codes (10 = blank)
        lw      $t1, 8($s0)                     # rate
        ori     $t2, $zero, 10
        divu    $t1, $t2
        mflo    $t3
        mfhi    $t4
        sb      $t3, 0($t9)
        sb      $t4, 1($t9)
        sb      $t2, 2($t9)
        lw      $t1, 12($s0)                    # worst
        nop
        divu    $t1, $t2
        mflo    $t3
        mfhi    $t4
        sb      $t3, 3($t9)
        sb      $t4, 4($t9)
        sb      $t2, 5($t9)
        lui     $t1, %hi(TLDBG)
        lbu     $t5, %lo(TLDBG)($t1)            # loader status: 1 = tag battle, else tiers "----"
        lbu     $t3, %lo(TLDBG)+1($t1)
        lbu     $t4, %lo(TLDBG)+2($t1)
        xori    $t5, $t5, 1
        beqz    $t5, 1f
        nop
        ori     $t3, $zero, 0xbb                # glyph 11 = dash
        ori     $t4, $zero, 0xbb
1:      andi    $t5, $t3, 15
        srl     $t3, $t3, 4
        sb      $t5, 6($t9)
        sb      $t3, 7($t9)
        andi    $t5, $t4, 15
        srl     $t4, $t4, 4
        sb      $t5, 8($t9)
        sb      $t4, 9($t9)
        lui     $a2, 0x1f80                     # GPU ports
        lui     $a3, 0x0400                     # GPUSTAT bit 26: ready for a command word
        lui     $t0, 0x6040                     # background: dark blue, (4, 194) 84 x 14
        ori     $t1, $zero, 4
        lui     $t2, 194
        or      $t1, $t1, $t2
        lui     $t2, 14
        ori     $t2, $t2, 84
1:      lw      $t3, 0x1814($a2)
        nop
        and     $t3, $t3, $a3
        beqz    $t3, 1b
        nop
        sw      $t0, 0x1810($a2)
        sw      $t1, 0x1810($a2)
        sw      $t2, 0x1810($a2)
        ori     $t8, $zero, 8                   # x of the cell
        addiu   $t7, $t9, 10
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
        addiu   $t5, $t5, 196
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
7:      addiu   $t9, $t9, 1
        bne     $t9, $t7, 2b
        addiu   $t8, $t8, 8
        jr      $ra
        nop

mfont:  .byte   0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f, 0x77, 0x40, 0, 0, 0, 0     # 10 'A' (stock RLE tier), 11 dash, 12-15 blank (15: shared slot)
mseg:   .byte   0, 0, 6, 2,   4, 0, 2, 5,   4, 5, 2, 5,   0, 8, 6, 2,   0, 5, 2, 5,   0, 0, 2, 5,   0, 4, 6, 2
mdig:   .byte   0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .align  2
mst:    .word   0, 0, 0, 0, 0                   # +0 Vcount at the last sample, +4 loop counter then, +8 rate,
                                                # +12 worst
mram_end:
