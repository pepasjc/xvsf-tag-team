# Post-boss scene with the winner's partner on point (mshfeat 2026-11-21; games/mshvsf/tools/gameplay/cyswap.py,
# mktag --cyswap).  Region: the stock "on point / bench pointer" routines 0x8002d43c (P1), 0x8002d4a4 (P2) and their
# wrapper 0x8002d50c (both), rewritten as one routine with the same stores; the four callers' delay slots pass the side.
#
# setp(a0): side = a0 & 1 (0 P1, 1 P2), a0 & 2 = then side 0 too (the wrapper), a0 & 4 = force (cyhook).
#   main = 0x80070b50 + side * 0x3c0, partner = main + 0x7c0; on point = the main unless main+0x263 (benched) is set;
#   match +0xa0 / +0xa8 = on point, +0xa4 / +0xac = bench; both objects of the other side get +0xbc = the on-point
#   object, +0xc0 = its id.  (Stock: two copies of this, P1 / P2.)
#   force, partner on point: first make the main the one on point - main+0x263 = 0, partner+0x263 = 1, main shown
#   (+0) at the partner's place (+0xc / +0x10), partner off, match ids +0x7a / +0x7e (on point) and +0x7c / +0x80
#   (bench) = the objects' ids.
#
# cyhook (the match-end handler's entry in the phase table, word 0x8006afac, was 0x80056c94; runs right before it):
#   after the final boss (0x80070aa9 != 0) and a side won (match+5 = 1 / 2): setp(side | force).  The stock post-boss
#   scene assumes the assist rules (main on point): it loads the FIXED partner object's character into the P2 slot at the
#   stock addresses 0x801448e0.., shows the BENCH member (+0xa4 / +0x7c) there and switches the partner objects off.
#   After the force it plays as when the main won on point (the only case 1.0 got right).

setp:   lui     $t0, 0x8007
1:      andi    $t7, $a0, 1                     # side
        sll     $t1, $t7, 10
        sll     $t2, $t7, 6
        subu    $t1, $t1, $t2                   # side * 0x3c0
        addiu   $t3, $t0, 0x0b50
        addu    $a1, $t3, $t1                   # main: 0x80070b50 / 0x80070f10
        lb      $v0, 0x263($a1)
        sll     $t4, $t7, 3                     # side * 8
        addiu   $a2, $a1, 0x7c0
        subu    $a2, $a2, $t4                   # partner: 0x80071310 / 0x800716c8 (main + 0x7c0 / + 0x7b8)
        beqz    $v0, 3f                         # main on point
        andi    $t6, $a0, 4
        beqz    $t6, 2f
        sll     $t8, $t7, 2
        sb      $zero, 0x263($a1)               # force: the main on point, shown at the partner's place
        sb      $v0, 0x263($a2)                 # (v0 = the bench flag, 1)
        sb      $v0, 0($a1)
        sb      $zero, 0($a2)
        lw      $t6, 0xc($a2)
        lw      $t9, 0x10($a2)
        sw      $t6, 0xc($a1)
        sw      $t9, 0x10($a1)
        addu    $t8, $t8, $t0
        lhu     $t9, 0x4e($a1)
        lhu     $t6, 0x4e($a2)
        sh      $t9, 0x7f2($t8)                 # +0x7a / +0x7e
        b       3f
        sh      $t6, 0x7f4($t8)                 # +0x7c / +0x80
2:      move    $v1, $a1                        # partner on point
        move    $a1, $a2
        move    $a2, $v1
3:      addu    $t4, $t4, $t0
        sw      $a1, 0x818($t4)                 # +0xa0 / +0xa8 on point
        sw      $a2, 0x81c($t4)                 # +0xa4 / +0xac bench
        subu    $t5, $t3, $t1                   # (other main = t5 + 0x3c0, other partner = t5 + 0xb78 + side * 8)
        lhu     $v0, 0x4e($a1)
        subu    $t6, $t4, $t0
        addu    $t6, $t6, $t5
        sw      $a1, 0x47c($t5)                 # the other side's main +0xbc
        sw      $a1, 0xc34($t6)                 # and partner +0xbc
        sh      $v0, 0x480($t5)                 # +0xc0
        sh      $v0, 0xc38($t6)
        andi    $t6, $a0, 2
        bnez    $t6, 1b                         # the wrapper: side 1 done, now side 0
        move    $a0, $zero
        jr      $ra
        nop

cyhook: addiu   $sp, $sp, -24
        sw      $ra, 16($sp)
        sw      $a0, 20($sp)                    # the match block (the handler's argument)
        lui     $t0, 0x8007
        lbu     $t1, 0xaa9($t0)                 # after the final boss
        lb      $a0, 0x77d($t0)                 # result: 1 P1 won, 2 P2 won
        beqz    $t1, 9f
        addiu   $a0, $a0, -1                    # side (a result other than 1 / 2 leaves the CPU side alone: its
        jal     setp                            # main is never benched)
        ori     $a0, $a0, 4
9:      lw      $a0, 20($sp)
        lw      $ra, 16($sp)
        j       0x80056c94                      # the stock handler
        addiu   $sp, $sp, 24
