/* XvSF speed 1.1 - "logic" part.  Hand-written R3000 code; load-delay slots filled by hand (checked by lhazard.py).
 * One section .text.f<addr> per patched address (tools/speed/logic.py FUNCS). */
        .set    noreorder
        .set    noat
        .set    nomacro

/* ---- 0x800303f0 drawlist_add(obj): put obj into the draw list (8-byte records: word obj, u16 key = obj->4a),
 * kept sorted by key: the new record goes in at the head and moves back past every record with a smaller key.
 * Same memory and v0 as the original (which swapped neighbour records through stack temporaries). ---- */
        .section .text.f800303f0,"ax",@progbits
        .globl  drawlist_add
drawlist_add:
        lui     $v1, 0x8005
        lh      $t0, -0x3d54($v1)       # n (0x8004c2ac)
        lui     $t2, 0x8004
        lb      $at, 0x2352($t2)        # "check for duplicates" flag 0x80042352
        slti    $v0, $t0, 0x60
        beq     $v0, $zero, 9f          # list full: return 0
        lw      $a2, -0x3a98($v1)       # head (0x8004c568)
        bne     $at, $zero, 5f
        nop
1:      lhu     $t1, 0x4a($a0)          # key
        addiu   $a2, $a2, -8
        addiu   $t3, $t0, 1
        sh      $t3, -0x3d54($v1)
        sw      $a2, -0x3a98($v1)
        sw      $a0, 0($a2)
        sh      $t1, 4($a2)
        sll     $t3, $t3, 16
        sra     $t3, $t3, 16            # n + 1 as s16
        slti    $at, $t3, 2
        bne     $at, $zero, 9f          # one record: return n + 1 - 1 (the original's v0)
        addiu   $v0, $t3, -1
        or      $t3, $v0, $zero         # at most n moves
2:      lhu     $t4, 0xc($a2)           # key of the next record
        lw      $t5, 8($a2)
        sltu    $v0, $t4, $t1
        beq     $v0, $zero, 9f          # next key >= ours: in place, return 0
        addiu   $t3, $t3, -1
        sw      $t5, 0($a2)             # move the next record forward, ours back
        sh      $t4, 4($a2)
        sw      $a0, 8($a2)
        sh      $t1, 0xc($a2)
        bgtz    $t3, 2b
        addiu   $a2, $a2, 8
        or      $v0, $zero, $zero       # moved n times: return 0
9:      jr      $ra
        nop
5:      blez    $t0, 1b                 # duplicate check: already in the list -> return obj
        or      $t6, $a2, $zero
        or      $t7, $t0, $zero
6:      lw      $v0, 0($t6)
        addiu   $t7, $t7, -1
        beq     $v0, $a0, 9b
        addiu   $t6, $t6, 8
        bgtz    $t7, 6b
        nop
        b       1b
        nop

/* ---- 0x8007d100 cmd_match(obj, cmd, state): command matcher of the move parser.  Nearly every call is a human
 * player (obj->3 != 0) at step state[0] >= 0 whose handler (table 0x80094d8c[*(s16 *)cmd][step / 2]) is 0x8007d1c4
 * and whose input does not match the command's next element: state[2..3] = 0, state[0] = 0, return 0.  That case
 * now runs without the 6-register frame (head here + cmd_tail); everything else goes to cmd_slow = the original
 * prologue + CPU branch (moved to a statically dead range), then the original code from 0x8007d168, which is
 * unchanged.  (0x8007d1c4 writes state+2 first, so the slow path repeats an identical store.) ---- */
        .section .text.f8007d100,"ax",@progbits
        .globl  cmd_match
cmd_match:
        lb      $v0, 3($a0)
        lb      $t2, 0($a2)             # step
        beq     $v0, $zero, cmd_slow    # CPU object
        lh      $t1, 0($a1)             # command type
        bltz    $t2, cmd_slow
        lui     $at, 0x8009
        sll     $t1, $t1, 2
        addu    $at, $at, $t1
        lw      $t1, 0x4d8c($at)        # handler table of this command type
        sra     $t3, $t2, 1             # step / 2
        beq     $t1, $zero, cmd_ret0    # no table: return 0
        sll     $t4, $t3, 2
        addu    $t4, $t4, $t1
        lw      $t4, 0($t4)
        lui     $t5, 0x8008
        addiu   $t5, $t5, -0x2e3c       # 0x8007d1c4
        bne     $t4, $t5, cmd_slow
        sll     $t7, $t3, 1
        sh      $zero, 2($a2)           # handler 0x8007d1c4
        lhu     $t5, 0xd2($a0)
        lh      $t6, 2($a1)
        addu    $t7, $t7, $a1
        lh      $t4, 8($t7)             # element step / 2
        srav    $t6, $t6, $t3
        j       cmd_tail
        andi    $t5, $t5, 0xf           # input direction
2:                                      # = 0x8007d168

        .section .text.f8006b6a4,"ax",@progbits
cmd_tail:
        andi    $t6, $t6, 1
        bne     $t6, $zero, cmd_slow    # flagged element: original code
        nop
        beq     $t4, $t5, cmd_slow      # input matches: original code
        nop
        sb      $zero, 0($a2)
cmd_ret0:
        jr      $ra
        or      $v0, $zero, $zero

        .section .text.f8006cdec,"ax",@progbits
        .globl  cmd_slow
cmd_slow:                               # v0 = obj->3
        addiu   $sp, $sp, -0x30         # original prologue 0x8007d100..
        sw      $s1, 0x1c($sp)
        or      $s1, $a0, $zero
        sw      $s0, 0x18($sp)
        or      $s0, $a1, $zero
        sw      $ra, 0x2c($sp)
        sw      $s4, 0x28($sp)
        sw      $s3, 0x24($sp)
        sw      $s2, 0x20($sp)
        beq     $v0, $zero, 2f
        or      $s2, $a2, $zero
        j       0x8007d168              # human: original code
        nop
2:      lb      $v0, 0x27f($s1)         # CPU: original 0x8007d134..0x8007d164
        nop
        beq     $v0, $zero, 1f
        or      $v0, $zero, $zero
        lbu     $v1, 0xe2($s1)
        lh      $v0, 4($s0)
        nop
        bne     $v1, $v0, 1f
        or      $v0, $zero, $zero
        or      $a0, $s1, $zero
        or      $a1, $s0, $zero
        j       0x8007d4b8
        or      $a2, $a1, $zero
1:      j       0x8007d510
        nop
