# --vx second segment (0x8000C100): vx_guard(a0, a1) - an object in the tag-out move 0x40 during the Duo is put back
        .set    SETMOVE, 0x8003d04c
        .set    TAGRES, 0x80032260
        .set    ARCBAL, 0x80011761
VXS:    .space  32                      # fixed at 0x8000C100 (segment start)



vx_frame:                               # 0x80031e9c entry hook (every frame, no args): per side Duo timer / meter / end
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x10($sp)
        sw      $s0, 0x14($sp)
        sw      $s1, 0x18($sp)
        lui     $s0, %hi(VXS)
        addiu   $s0, $s0, %lo(VXS)
        li      $s1, 2
fside:  lbu     $t1, 0($s0)
        nop
        beqz    $t1, fcpu
        nop
        lw      $t2, 8($s0)             # the original point
        nop
        lw      $t3, 0x2a8($t2)         # its partner (the Duo partner)
        lh      $t4, 0x294($t2)
        nop
        beqz    $t4, fko                # KO of either: end (stock logic takes over)
        nop
        lh      $t4, 0x294($t3)
        nop
        beqz    $t4, fko
        nop
        move    $a0, $t3                # guard: neither fighter may be sent out (tag-out move 0x40) while the Duo lasts
        jal     vx_guard
        move    $a1, $t2
        lw      $t2, 8($s0)
        nop
        lw      $t3, 0x2a8($t2)
        li      $t4, 1                  # +0x187 on both: the engine keeps two active fighters of one side (no flip-flop)
        sb      $t4, 0x187($t2)
        sb      $t4, 0x187($t3)
        lbu     $t4, 14($s0)            # grace: the point's special started by the Duo input -> neutral
        nop
        beqz    $t4, 3f
        addiu   $t4, $t4, -1
        sb      $t4, 14($s0)
        lbu     $t4, 0xc8($t2)
        nop
        beqz    $t4, 3f
        nop
        move    $a0, $t2
        jal     SETMOVE
        move    $a1, $zero
        lw      $t2, 8($s0)
        nop
        lw      $t3, 0x2a8($t2)
3:      sb      $zero, 3($t3)           # partner = CPU (AI 0x8003da94 runs for +3 == 0 and not benched)
        sb      $zero, 0x2a3($t2)       # neither benched: both get input (0x8004ff40); the point selector keeps the original
        sb      $zero, 0x2a3($t3)
        lhu     $t4, 4($s0)             # meter bar = TIME gauge (timer * 0x1c0 / start), level held at 3 = unlimited hypers
        lhu     $t5, 6($s0)
        li      $t6, 0x1c0
        multu   $t4, $t6
        mflo    $t4
        bnez    $t5, 4f
        nop
        li      $t5, 1
4:      divu    $t4, $t5
        mflo    $t4
        sh      $t4, 0x296($t2)
        sh      $t4, 0x296($t3)
        li      $t4, 3
        sb      $t4, 0x298($t2)
        sb      $t4, 0x298($t3)
        lhu     $t4, 4($s0)
        nop
        beqz    $t4, fend
        addiu   $t4, $t4, -1
        sh      $t4, 4($s0)
        b       fnext
        nop
fend:   lb      $t4, 12($s0)            # the partner's human flag back
        nop
        sb      $t4, 3($t3)
        sb      $zero, 0x187($t2)
        sb      $zero, 0x187($t3)
        sb      $zero, 0($s0)           # time over: the original point tags out (stock tag routine), meter empty
        sh      $zero, 0x296($t2)
        sb      $zero, 0x298($t2)
        sh      $zero, 0x296($t3)
        sb      $zero, 0x298($t3)
        li      $t4, 1
        sb      $t4, 0x2a3($t2)         # the original is benched now, the partner is the point (point selector)
        sb      $zero, 0x2a3($t3)
        move    $a0, $t3                # (a0 = the one who stays, a1 = the one who leaves)
        jal     TAGRES
        move    $a1, $t2
        b       fnext
        nop
fko:   lb      $t4, 12($s0)            # the partner's human flag back
        nop
        sb      $t4, 3($t3)
        sb      $zero, 0x187($t2)
        sb      $zero, 0x187($t3)
        sb      $zero, 0($s0)
        b       fnext
        nop
fcpu:   lui     $t2, %hi(ARCBAL)        # ---- the CPU uses the Duo (arcade rule set only): CPU point, LEVEL >= 2, fight running,
        lbu     $t2, %lo(ARCBAL)($t2)   # partner alive, about once per 512 frames while that holds
        lui     $t3, 0x8008
        beqz    $t2, fnext
        lb      $t2, -0x47d8($t3)       # phase 0x8007b828
        li      $t4, 8
        bne     $t2, $t4, fnext
        lw      $t2, -0x48b4($t3)       # main loops 0x8007b74c (2 - s1 = side, pointer table 0x8007b8c8 + side * 8)
        nop
        andi    $t2, $t2, 0x1ff
        bnez    $t2, fnext
        li      $t4, 2
        subu    $t4, $t4, $s1           # side
        sll     $t4, $t4, 3
        addu    $t4, $t4, $t3
        lw      $a0, -0x4738($t4)       # side point
        nop
        lb      $t2, 3($a0)
        lb      $t5, 0($a0)
        bnez    $t2, fnext              # human point: no
        lb      $t2, 0x298($a0)
        beqz    $t5, fnext
        slti    $t2, $t2, 2
        bnez    $t2, fnext
        lw      $t2, 0x2a8($a0)
        nop
        lb      $t5, 0($t2)             # partner must be off screen (no Duo right after the last one / during a tag)
        lh      $t2, 0x294($t2)
        bnez    $t5, fnext
        nop
        beqz    $t2, fnext
        nop
        jal     VXSTART
        nop
fnext:  addiu   $s1, $s1, -1
        bnez    $s1, fside
        addiu   $s0, $s0, 16
        lw      $ra, 0x10($sp)
        lw      $s0, 0x14($sp)
        lw      $s1, 0x18($sp)
        addiu   $sp, $sp, 0x20
        lui     $v0, 0x8008             # original 0x80031e9c / 0x80031ea0
        j       0x80031ea4
        lb      $v0, -0x48a3($v0)



vx_guard:
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x10($sp)
        sw      $a1, 0x14($sp)
        jal     g1
        nop
        lw      $a0, 0x14($sp)
        jal     g1
        nop
        lw      $ra, 0x10($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 0x20
g1:     lbu     $t0, 0xc8($a0)
        li      $t1, 0x40
        bne     $t0, $t1, 9f
        nop
        li      $t1, 1
        sb      $t1, 0($a0)
        sb      $zero, 0x2a3($a0)
        li      $t1, 2
        sh      $t1, 4($a0)
        sh      $zero, 6($a0)
        j       SETMOVE                 # tail call: set-move(a0, 0) = neutral
        move    $a1, $zero
9:      jr      $ra
        nop
