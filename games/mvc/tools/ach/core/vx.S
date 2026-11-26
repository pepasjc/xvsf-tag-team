# MvC 1.1 Variable Cross (Duo Team Attack) prototype - mktag --vx (2026-11-26).  Arcade (FBNeo mvsc): QCB + HP+HK,
# LEVEL >= 2, all levels used, partner joins, both on screen for 72 + 163 * LEVEL frames with unlimited meter, then the
# original point tags out and the partner stays.  Only with ARCADE BALANCE = ON (EX byte ARCBAL); otherwise stock paths.
# LEVEL = obj +0x298 (gauge +0x296; partners mirror).  p1-p8 used +0x2e1 by mistake (a per-object counter, not the level).
# Prototype: the engine makes the woken partner the point (player input) and the original runs as the second fighter.
#
# hooks (copied by the achievements core boot stub):
#   0x80031fbc  team controller (per side point, s1 = point, a3 = partner): `lb v0,0(a3)` -> j vx_ctrl
#   0x80056088  tag check human path: `jal 0x80057c8c` (HP+HK pressed) -> jal vx_tag
# state per side (8 bytes at VXS + side * 16): +0 on, +1 qcb stage, +2 qcb timer, +4 timer (half), +8 orig obj (word)

        .set    ARCBAL, 0x80011761
        .set    BTN,    0x80057c8c
        .set    ACTIV,  0x80032224
        .set    TAGRES, 0x80032260
        .set    C_RES,  0x80031fc4
        .set    C_EXIT, 0x80032210

        .set    SETMOVE, 0x8003d04c
        .set    VXS, 0x8000C100         # vxg.S segment start (fixed)

vx_tagchk:                              # 0x80055fa8 tag-check entry (any obj a0): no tag on a side with the Duo on
        lb      $t0, 2($a0)
        lui     $t9, %hi(VXS)
        addiu   $t9, $t9, %lo(VXS)
        sll     $t0, $t0, 4
        addu    $t9, $t9, $t0
        lbu     $t0, 0($t9)
        lui     $v0, 0x8008
        bnez    $t0, 1f
        nop
        j       0x80055fb0
        lb      $v0, -0x48a3($v0)
1:      lui     $t1, 0x8008             # only the four fighter objects 0x8007be90..0x8007cef8 (+0x2a8 = their partner)
        addiu   $t1, $t1, -0x4170
        sltu    $t0, $a0, $t1
        bnez    $t0, 2f
        addiu   $t1, $t1, 0x1068
        sltu    $t0, $a0, $t1
        beqz    $t0, 2f
        li      $t0, 1
        sb      $t0, 0x187($a0)
        lw      $t1, 0x2a8($a0)
        nop
        sb      $t0, 0x187($t1)
2:      jr      $ra
        move    $v0, $zero

vx_ctrl:                                # in the controller after its prologue (ra, s0, s1 saved on its frame)
        lb      $t0, 2($s1)             # side
        lui     $t9, %hi(VXS)
        addiu   $t9, $t9, %lo(VXS)
        sll     $t1, $t0, 4
        addu    $t9, $t9, $t1           # t9 = side state
        # ---- QCB history from the point's input (+0xe8: 1 R, 2 L, 4 D, 8 U), back = away from facing (+0x47: 1 = right)
        lhu     $t2, 0xe8($s1)
        lb      $t3, 0x47($s1)
        andi    $t2, $t2, 0xf
        li      $t4, 2                  # back = left when facing right
        bnez    $t3, 1f
        nop
        li      $t4, 1
1:      lbu     $t5, 1($t9)             # stage
        lbu     $t6, 2($t9)             # timer
        li      $t7, 4
        bne     $t2, $t7, 2f            # down
        nop
        li      $t5, 1
        b       5f
        li      $t6, 15
2:      or      $t7, $t4, 4
        bne     $t2, $t7, 3f            # down + back
        nop
        beqz    $t5, 4f
        nop
        li      $t5, 2
        b       5f
        li      $t6, 15
3:      bne     $t2, $t4, 4f            # back
        nop
        slti    $t8, $t5, 2
        bnez    $t8, 4f
        nop
        li      $t5, 3
        b       5f
        li      $t6, 15
4:      beqz    $t6, 6f                 # nothing new: count down, then forget
        nop
        addiu   $t6, $t6, -1
        b       5f
        nop
6:      move    $t5, $zero
5:      sb      $t5, 1($t9)
        sb      $t6, 2($t9)
        # ---- Duo running on this side: both fighters stay (no resolution); timer / meter / end in vx_frame
        lbu     $t1, 0($t9)
        beqz    $t1, stock
        nop
        j       C_EXIT
        nop
stock:  lb      $v0, 0($a3)             # original 0x80031fbc
        j       C_RES
        nop

vx_tag:                                 # a0 = obj, a1 = 0x440 (HP+HK): stock button test, then maybe the Duo
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x10($sp)
        sw      $s0, 0x14($sp)
        sw      $s1, 0x18($sp)
        move    $s0, $a0
        jal     BTN
        nop
        beqz    $v0, tret               # no HP+HK: nothing
        nop
        lui     $t0, %hi(ARCBAL)
        lbu     $t0, %lo(ARCBAL)($t0)
        nop
        beqz    $t0, tret               # ARCADE BALANCE OFF: stock tag
        nop
        lb      $t0, 2($s0)
        lui     $t9, %hi(VXS)
        addiu   $t9, $t9, %lo(VXS)
        sll     $t0, $t0, 4
        addu    $t9, $t9, $t0
        lbu     $t1, 0($t9)
        nop
        bnez    $t1, tno                # Duo already on: no tag
        nop
        lbu     $t1, 1($t9)
        li      $t2, 3
        bne     $t1, $t2, tret          # no QCB just before: stock tag
        nop
        lb      $t1, 0x298($s0)
        nop
        slti    $t2, $t1, 2
        bnez    $t2, tret               # LEVEL < 2: stock tag (as the arcade)
        nop
        jal     vx_start                # (a0 = the point) shared with the CPU decision in vx_frame
        move    $a0, $s0
tno:    move    $v0, $zero
tret:   lw      $ra, 0x10($sp)
        lw      $s0, 0x14($sp)
        lw      $s1, 0x18($sp)
        jr      $ra
        addiu   $sp, $sp, 0x20


vx_start:                               # a0 = point (LEVEL >= 2 checked by the caller): start the Duo on its side
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x10($sp)
        sw      $s0, 0x14($sp)
        sw      $s1, 0x18($sp)
        move    $s0, $a0
        lb      $t0, 2($s0)
        lui     $t9, %hi(VXS)
        addiu   $t9, $t9, %lo(VXS)
        sll     $t0, $t0, 4
        addu    $t9, $t9, $t0
        lb      $t1, 0x298($s0)
        nop
        li      $t2, 163
        mult    $t1, $t2
        mflo    $t2
        addiu   $t2, $t2, 72
        sh      $t2, 4($t9)
        sh      $t2, 6($t9)             # start value (TIME gauge)
        sw      $s0, 8($t9)
        li      $t2, 1
        sb      $t2, 0($t9)
        sh      $zero, 0x296($s0)
        sb      $zero, 0x298($s0)
        li      $t2, 6                  # grace frames: the Duo input wins over the point's own QCB + K special (vx_frame)
        sb      $t2, 14($t9)
        lw      $s1, 0x2a8($s0)         # partner (kept in s1 across the set-move call)
        nop
        move    $a0, $s1
        li      $t2, 1                  # wake without the activator's +0x28a tag-in countdown
        sb      $t2, 0($a0)
        li      $t2, 2
        sh      $t2, 4($a0)
        sh      $zero, 6($a0)
        jal     0x8003d04c              # set-move(partner, 0)
        move    $a1, $zero
        move    $a0, $s1
        lb      $t2, 3($a0)             # the partner's human flag, restored at the end (CPU AI drives it during the Duo)
        nop
        sb      $t2, 12($t9)
        sb      $zero, 0x2a3($a0)       # not benched
        lh      $t2, 0xc($s0)           # x: 48 behind the point
        lb      $t3, 0x47($s0)
        nop
        bnez    $t3, 8f
        addiu   $t4, $t2, -48
        addiu   $t4, $t2, 48
8:      sh      $t4, 0xc($a0)
        lw      $ra, 0x10($sp)
        lw      $s0, 0x14($sp)
        lw      $s1, 0x18($sp)
        jr      $ra
        addiu   $sp, $sp, 0x20
