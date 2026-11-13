/* XvSF speed 1.1 - "quad" part, hand-written R3000 code (load-delay slots filled by hand; checked by
 * tools/speed/quad/hazard.py).  Same interface, results and memory writes as the originals; see quad.c for the
 * same logic in C (reference).  ctx = *(u32 *)0x8006a340 (= scratchpad 0x1f800000), w = ctx->0x70 (work frame,
 * scratchpad).  Common path of quad_part: leaf, no stack frame; the rare paths that call DrawSync / 0x80015a68 /
 * 0x80016a54 keep everything they need in the work frame and reload it.
 *
 *   quad_part(o)   replaces 0x80056340 (and folds in 0x80055c34)
 *   sec0_parse()   replaces 0x80057be4
 *   sec1_parse()   replaces 0x80057f48
 */
        .set    noreorder
        .set    noat
        .set    nomacro

/* ------------------------------------------------------------------------------------------------------------------ */
        .section .text.quad_part,"ax",@progbits
        .globl  quad_part
        .ent    quad_part
/* registers on the common path: a0 o (later U), a1 ctx, a2 w, a3 typ (later the packet), t0 e8, t1 e9, t2 fx,
   t3 fy, t4 o->50 word (later V), t5 X, t6 Y (low 16 bits valid), t7 palette, t8 x68, t9 x6a, v0 c94 */
quad_part:
        lui     $a1, 0x8007
        lw      $a1, -0x5cc0($a1)       # ctx
        lw      $t4, 0x50($a0)          # o50 | o51 << 8
        lw      $a2, 0x70($a1)          # w
        lw      $v0, 0x90($a1)
        lhu     $t7, 0xf6($a1)          # f6
        lbu     $t0, 0xe8($a1)
        lbu     $a3, 0xb($v0)           # typ
        addiu   $v1, $a2, 0xb4
        sw      $v1, 0x70($a1)
        sll     $t0, $t0, 1
        andi    $t0, $t0, 0xff          # e8 * 2
        addiu   $v1, $a3, -1
        beq     $v1, $zero, typ1a       # typ 1: w->34 = ctx->164 + 8
        sb      $t0, 0xe8($a1)
t1back: srl     $v0, $t4, 8
        andi    $v1, $v0, 2             # my (0 / 2)
        andi    $v0, $v0, 1             # mx
        sh      $v1, 0x4e($a2)
        sh      $v0, 0x4c($a2)
        srl     $t2, $t7, 5
        xor     $t2, $t2, $v0
        andi    $t2, $t2, 1             # fx = f6 bit 5 ^ mx
        lhu     $at, 0xf0($a1)          # f0
        lhu     $t5, 0xc($a0)           # o->0c
        lbu     $t1, 0xe9($a1)          # e9
        subu    $v0, $zero, $v0         # mx mask
        and     $t3, $t0, $v0
        addu    $at, $at, $t3
        xor     $at, $at, $v0
        subu    $at, $at, $v0           # mx ? -(f0 + e8) : f0
        addiu   $t5, $t5, -0x40
        addu    $t5, $t5, $at           # X
        srl     $t3, $t7, 6
        bne     $v1, $zero, ymir        # mirrored y: out of line
        andi    $t3, $t3, 1             # fy
        lhu     $t6, 0x10($a0)
        lhu     $at, 0xf2($a1)
        addiu   $t6, $t6, -8
        addu    $t6, $t6, $at           # Y
yret:   lbu     $v0, 0x28($a0)
        sb      $t2, 0x6c($a2)
        sb      $t3, 0x6d($a2)
        beq     $v0, $zero, 1f
        nop
        sll     $v0, $v0, 24
        sra     $v0, $v0, 26
        sll     $v0, $v0, 2
        lui     $at, 0x8004
        addu    $at, $at, $v0
        lw      $v0, -0x15b4($at)       # 0x8003ea4c [(s8)o->28 >> 2]
        nop
        lw      $at, 0x14($v0)          # p->14 | p->16 << 16
        sw      $v0, 0x58($a2)
        srl     $v1, $at, 16
        subu    $t5, $t5, $at
        subu    $t6, $t6, $v1
1:      sh      $t5, 0x5c($a2)          # X (bits 16.. of t5 / t6 are junk until masked)
        sh      $t6, 0x5e($a2)          # Y
        lb      $v1, 0x4e($a0)          # palette
        sll     $v0, $t4, 24
        bltz    $v0, pal50              # o->50 < 0: out of line
        andi    $t7, $t7, 0x1f
        bgez    $v1, palret
        andi    $at, $v1, 0x7f
        or      $t7, $at, $zero
palret: lw      $v0, 0x94($a1)          # c94
        sh      $t7, 0x6e($a2)
        lbu     $at, 5($a1)
        lhu     $t8, 0x1a($v0)
        lhu     $t9, 0x1c($v0)
        lbu     $v1, 6($a1)
        addu    $t8, $t8, $at
        andi    $t8, $t8, 0xffff        # x68
        addu    $t9, $t9, $v1
        andi    $t9, $t9, 0xffff        # x6a
        sh      $t8, 0x68($a2)
        sh      $t9, 0x6a($a2)
        lbu     $at, 0x6c($a0)
        sw      $zero, 0x78($a2)        # 0x78, 0x7a
        addiu   $at, $at, -0x2c
        sltiu   $at, $at, 0xb
        bne     $at, $zero, spchk       # codes 0x2c..0x36
        srl     $t4, $t4, 8             # o51 in the low byte
spret:  lbu     $at, 0xc($v0)           # U / V: table 0x8005c604 [c94->0c]
        lui     $v1, 0x8006
        sll     $at, $at, 2
        addu    $v1, $v1, $at
        lw      $at, -0x39fc($v1)       # 0x8005c604 | 0x8005c606 << 16
        lw      $v0, 0x58($a1)          # offset stream
        andi    $v1, $at, 0xffff
        srl     $at, $at, 16
        subu    $a0, $t8, $v1
        sll     $a0, $a0, 2             # U
        subu    $t4, $t9, $at           # V
        sw      $a0, 0($a2)
        sw      $t4, 4($a2)
        bne     $v0, $zero, stream      # out of line
        sb      $zero, 0x8e($a2)
strret: addiu   $at, $a3, -1            # packet: typ 0/2 -> next of the buffer, else w->34
        beq     $at, $zero, typ1
        andi    $at, $a3, 0xfd
        bne     $at, $zero, typ1
        lui     $v1, 0x8006
        lh      $v0, -0x3a04($v1)       # n (0x8005c5fc)
        lui     $at, 0x8007
        lhu     $at, -0x6584($at)       # limit (0x80069a7c)
        nop
        addiu   $at, $at, -1
        slt     $at, $v0, $at
        beq     $at, $zero, wrap
        lw      $a3, -0x2650($v1)       # base (0x8005d9b0)
alloc2: addiu   $at, $v0, 1
        sh      $at, -0x3a04($v1)
        sll     $at, $v0, 2
        addu    $at, $at, $v0
        sll     $at, $at, 3             # n * 40
        addu    $a3, $a3, $at
        sw      $a3, 0x34($a2)
pkok:   lbu     $at, 0x8e($a2)
        sw      $a3, 0x30($a2)
        addiu   $v0, $a3, 0x20
        bne     $at, $zero, offv
        sw      $v0, 0x50($a2)
        addiu   $v0, $a3, 0x2c          # ---- plain part (no vertex offsets)
        sw      $v0, 0x94($a2)
        sw      $v0, 0xa8($a2)
        beq     $t2, $zero, 5f          # x flipped: u0 - 1, at 0 the width shrinks
        addiu   $v0, $a0, -1
        bgez    $v0, 5f
        or      $a0, $v0, $zero
        or      $a0, $zero, $zero
        addiu   $t0, $t0, -1
        andi    $t0, $t0, 0xff
        sb      $t0, 0xe8($a1)
5:      beq     $t3, $zero, 6f          # y flipped
        addiu   $v0, $t4, -1
        bgez    $v0, 6f
        or      $t4, $v0, $zero
        or      $t4, $zero, $zero
        addiu   $t1, $t1, -1
        andi    $t1, $t1, 0xff
        sb      $t1, 0xe9($a1)
6:      sw      $a0, 0($a2)
        sw      $t4, 4($a2)
        subu    $v0, $zero, $t2
        and     $v0, $v0, $t0           # ex = fx ? e8 : 0
        addu    $at, $t5, $t0
        addu    $v1, $t5, $v0           # xa
        subu    $at, $at, $v0           # xb
        andi    $v1, $v1, 0xffff
        andi    $at, $at, 0xffff
        subu    $v0, $zero, $t3
        and     $v0, $v0, $t1           # ey
        addu    $t5, $t6, $t1
        addu    $t6, $t6, $v0           # ya
        subu    $t5, $t5, $v0           # yc
        sll     $t6, $t6, 16
        sll     $t5, $t5, 16
        or      $v0, $v1, $t6
        sw      $v0, 8($a3)
        or      $v0, $at, $t6
        sw      $v0, 16($a3)
        or      $v0, $v1, $t5
        sw      $v0, 24($a3)
        or      $v0, $at, $t5
        sw      $v0, 32($a3)
        or      $t2, $zero, $zero       # m78
        or      $t3, $zero, $zero       # m7a
uvtail: addu    $v0, $t0, $a0           # ---- u/v, clut, tpage (a0 = U, t4 = V, t2/t3 = m78/m7a)
        subu    $v0, $v0, $t2
        andi    $v0, $v0, 0xff          # ub
        andi    $v1, $a0, 0xff          # ua
        addu    $at, $t1, $t4
        subu    $at, $at, $t3
        andi    $at, $at, 0xff
        sll     $at, $at, 8             # vb
        andi    $t4, $t4, 0xff
        sll     $t4, $t4, 8             # va
        sll     $t7, $t7, 1
        lui     $t2, 0x8006
        addu    $t2, $t2, $t7
        lhu     $t7, -0x2b60($t2)       # clut (0x8005d4a0[pal])
        or      $t2, $v1, $at
        sh      $t2, 0x1c($a3)
        or      $t3, $v0, $at
        sh      $t3, 0x24($a3)
        srl     $t8, $t8, 6
        andi    $t9, $t9, 0x100
        srl     $t9, $t9, 4
        addu    $t8, $t8, $t9
        sll     $t8, $t8, 16            # tpage << 16
        or      $v0, $v0, $t4
        or      $v0, $v0, $t8
        sw      $v0, 0x14($a3)
        sll     $t7, $t7, 16
        or      $v1, $v1, $t4
        or      $v1, $v1, $t7
        sw      $v1, 0xc($a3)
link:   lbu     $at, 3($a1)             # ---- link packet a3 after the previous one
        lui     $v1, 0x8006
        addiu   $t0, $v1, -0x3090       # prev 0x8005cf70
        addiu   $at, $at, -1
        bne     $at, $zero, 7f
        addiu   $t1, $v1, -0x38a8       # head 0x8005c758
        lui     $v1, 0x8007
        addiu   $t0, $v1, -0x5cb8       # prev 0x8006a348
        addiu   $t1, $v1, -0x6228       # head 0x80069dd8
7:      lw      $v0, 0($t0)
        sll     $t2, $a3, 8
        beq     $v0, $zero, 8f
        srl     $t2, $t2, 8             # pk & 0xffffff
        lw      $t1, 0($v0)
        lui     $v1, 0xff00
        and     $t1, $t1, $v1
        or      $t1, $t1, $t2
        b       9f
        sw      $t1, 0($v0)
8:      sw      $a3, 0($t1)
9:      sw      $a3, 0($t0)
        lw      $v0, 0x70($a1)
        nop
        addiu   $v0, $v0, -0xb4
        jr      $ra
        sw      $v0, 0x70($a1)

/* ---- out of line ---- */
typ1a:  lw      $v0, 0x164($a1)
        nop
        addiu   $v0, $v0, 8
        b       t1back
        sw      $v0, 0x34($a2)

typ1:   b       pkok
        lw      $a3, 0x34($a2)

ymir:                                   # mirrored y (o->51 & 2); t1 = e9
        lh      $t6, 0x10($a0)          # y44
        lh      $v1, 0x96($a0)          # y40
        lhu     $at, 0xf2($a1)          # f2
        xori    $t3, $t3, 1
        bgez    $v1, 1f
        nop
        andi    $v1, $v1, 0xfff
        subu    $t6, $t6, $v1
1:      sw      $v1, 0x40($a2)
        sw      $t6, 0x44($a2)
        addu    $at, $at, $t1           # e9 + f2
        subu    $t6, $t6, $at
        b       yret
        addiu   $t6, $t6, -8

pal50:  addu    $t7, $t7, $v1           # o->50 < 0: palette += o->4e
        b       palret
        andi    $t7, $t7, 0xffff

spchk:  andi    $at, $t4, 0xff          # sprite packet when o51, fx and fy are all 0
        or      $at, $at, $t2
        or      $at, $at, $t3
        beq     $at, $zero, sprt
        nop
        b       spret
        nop

stream: lbu     $at, 0($v0)             # v0 = stream pointer
        addiu   $v0, $v0, 1
        bne     $at, $zero, offs
        sb      $at, 0x114($a1)
strend: sw      $v0, 0x58($a1)
        b       strret
        sw      $v0, 0x118($a1)

offs:                                   # offsets: at = flags, v0 = data; keep a0 (U), t4 (V)
        ori     $v1, $zero, 1
        sb      $v1, 0x8e($a2)
        lhu     $t8, 0x4c($a2)
        lhu     $t9, 0x4e($a2)
        subu    $t8, $zero, $t8         # mx mask
        srl     $t9, $t9, 1
        subu    $t9, $zero, $t9         # my mask
        andi    $v1, $at, 0x10
        beq     $v1, $zero, 1f
        nop
        lb      $v1, 0($v0)
        lb      $t7, 1($v0)
        xor     $v1, $v1, $t8
        subu    $v1, $v1, $t8
        xor     $t7, $t7, $t9
        subu    $t7, $t7, $t9
        addu    $t5, $t5, $v1
        addu    $t6, $t6, $t7
        andi    $t5, $t5, 0xffff
        sll     $v1, $t6, 16
        or      $v1, $v1, $t5
        sw      $v1, 0x5c($a2)
        addiu   $v0, $v0, 2
1:      addiu   $t2, $a2, 0x70          # 4 vertices: bit i -> 2 bytes (negated when mirrored), else 0
        ori     $t7, $zero, 1
2:      and     $v1, $at, $t7
        beq     $v1, $zero, 3f
        sh      $zero, 0($t2)
        lbu     $v1, 0($v0)
        lbu     $t3, 1($v0)
        xor     $v1, $v1, $t8
        subu    $v1, $v1, $t8
        xor     $t3, $t3, $t9
        subu    $t3, $t3, $t9
        sb      $v1, 0($t2)
        sb      $t3, 1($t2)
        addiu   $v0, $v0, 2
3:      sll     $t7, $t7, 1
        sltiu   $v1, $t7, 0x10
        bne     $v1, $zero, 2b
        addiu   $t2, $t2, 2
        ori     $v1, $zero, 4
        sh      $v1, 0x4a($a2)
        lw      $v1, 0x70($a2)
        lw      $t2, 0x74($a2)
        lui     $t9, 0x00ff
        or      $v1, $v1, $t2
        ori     $t9, $t9, 0x00ff
        and     $t2, $v1, $t9
        sltu    $t2, $zero, $t2         # m78
        srl     $v1, $v1, 8
        and     $v1, $v1, $t9
        sltu    $v1, $zero, $v1         # m7a
        sll     $v1, $v1, 16
        or      $v1, $v1, $t2
        sw      $v1, 0x78($a2)
        lbu     $t2, 0x6c($a2)          # restore fx, fy, palette, x68, x6a
        lbu     $t3, 0x6d($a2)
        lhu     $t7, 0x6e($a2)
        lhu     $t8, 0x68($a2)
        b       strend
        lhu     $t9, 0x6a($a2)

offv:                                   # ---- vertex offsets (a0 = U, t4 = V)
        lhu     $v0, 0x78($a2)          # m78
        lhu     $v1, 0x7a($a2)          # m7a
        bne     $v0, $zero, 1f
        nop
        beq     $t2, $zero, 1f
        addiu   $at, $a0, -1
        bgez    $at, 1f
        or      $a0, $at, $zero
        or      $a0, $zero, $zero
        addiu   $t0, $t0, -1
        andi    $t0, $t0, 0xff
        sb      $t0, 0xe8($a1)
1:      bne     $v1, $zero, 2f
        nop
        beq     $t3, $zero, 2f
        addiu   $at, $t4, -1
        bgez    $at, 2f
        or      $t4, $at, $zero
        or      $t4, $zero, $zero
        addiu   $t1, $t1, -1
        andi    $t1, $t1, 0xff
        sb      $t1, 0xe9($a1)
2:      sw      $a0, 0($a2)
        sw      $t4, 4($a2)
        subu    $t5, $t5, $v0           # xl = X - m78
        addu    $at, $t0, $v0           # D = e8 + m78
        subu    $t2, $zero, $t2
        and     $t2, $t2, $at           # ex
        addu    $at, $t5, $at
        addu    $t5, $t5, $t2           # xa
        subu    $t2, $at, $t2           # xb
        subu    $t6, $t6, $v1           # yt = Y - m7a
        addu    $at, $t1, $v1
        subu    $t3, $zero, $t3
        and     $t3, $t3, $at
        addu    $at, $t6, $at
        addu    $t6, $t6, $t3           # ya
        subu    $t3, $at, $t3           # yc
        .irp    k, 0, 1, 2, 3
        lb      $at, 0x70+2*\k($a2)
        lb      $v0, 0x71+2*\k($a2)
        .if     \k == 0 || \k == 2
        addu    $at, $at, $t5
        .else
        addu    $at, $at, $t2
        .endif
        .if     \k < 2
        addu    $v0, $v0, $t6
        .else
        addu    $v0, $v0, $t3
        .endif
        andi    $at, $at, 0xffff
        sll     $v0, $v0, 16
        or      $at, $at, $v0
        sw      $at, 8+8*\k($a3)
        .endr
        lhu     $t2, 0x78($a2)
        b       uvtail
        lhu     $t3, 0x7a($a2)

wrap:                                   # packet buffer full: swap buffers (original 0x800569c8..0x80056a98); v1 = 0x80060000
        addiu   $sp, $sp, -24
        sw      $ra, 16($sp)
        sw      $a2, 20($sp)
        lbu     $v0, -0x26a8($v1)       # 0x8005d958
        nop
        addiu   $v0, $v0, 1
        andi    $v0, $v0, 0xff
        sltiu   $at, $v0, 2
        bne     $at, $zero, 2f
        sb      $v0, -0x26a8($v1)
1:      jal     DrawSync
        ori     $a0, $zero, 1
        bne     $v0, $zero, 1b
        lui     $v1, 0x8006
        sb      $zero, -0x26a8($v1)
2:      lui     $v1, 0x8006
        lw      $a0, -0x3090($v1)       # 0x8005cf70
        nop
        beq     $a0, $zero, 3f
        nop
        jal     f15a68
        nop
        lui     $v1, 0x8006
        b       4f
        lw      $a0, -0x38a8($v1)       # 0x8005c758
3:      lw      $a0, -0x38a8($v1)
        nop
        beq     $a0, $zero, 5f
        nop
4:      jal     f16a54
        nop
5:      lui     $v1, 0x8006
        lbu     $v0, 0xa98($v1)         # 0x80060a98
        nop
        sltiu   $v0, $v0, 1
        sll     $at, $v0, 2
        addu    $at, $at, $v1
        lw      $a3, -0x36d8($at)       # 0x8005c928[k]
        sw      $zero, -0x38a8($v1)
        sw      $zero, -0x3090($v1)
        sh      $zero, -0x3a04($v1)
        sb      $v0, 0xa98($v1)
        sw      $a3, -0x2650($v1)
        lw      $ra, 16($sp)
        lw      $a2, 20($sp)
        addiu   $sp, $sp, 24
        lui     $a1, 0x8007
        lw      $a1, -0x5cc0($a1)
        lw      $a0, 0($a2)
        lw      $t4, 4($a2)
        lbu     $t0, 0xe8($a1)
        lbu     $t1, 0xe9($a1)
        lbu     $t2, 0x6c($a2)
        lbu     $t3, 0x6d($a2)
        lhu     $t5, 0x5c($a2)
        lhu     $t6, 0x5e($a2)
        lhu     $t7, 0x6e($a2)
        lhu     $t8, 0x68($a2)
        lhu     $t9, 0x6a($a2)
        or      $v0, $zero, $zero
        b       alloc2
        lui     $v1, 0x8006

sprt:                                   # ---- former 0x80055c34: 32-byte sprite packet; v0 = c94
        lui     $v1, 0x8006
        lh      $a0, -0x3a02($v1)       # 0x8005c5fe
        lui     $at, 0x8007
        lhu     $at, -0x5cb0($at)       # 0x8006a350
        nop
        addiu   $at, $at, -1
        slt     $at, $a0, $at
        beq     $at, $zero, swrap
        addiu   $at, $a0, 1
        sh      $at, -0x3a02($v1)
        lui     $at, 0x8007
        lw      $a3, -0x6128($at)       # 0x80069ed8
        sll     $a0, $a0, 5
        addu    $a3, $a3, $a0
spk:    lbu     $at, 0xc($v0)
        sw      $a3, 0x38($a2)
        lui     $v1, 0x8006
        sll     $at, $at, 2
        addu    $v1, $v1, $at
        lw      $at, -0x39fc($v1)       # bytes 0 and 2: 0x8005c604 / 0x8005c606
        andi    $t5, $t5, 0xffff
        sll     $v1, $t6, 16
        or      $v1, $v1, $t5
        sw      $v1, 0x14($a3)
        subu    $v1, $t8, $at
        sll     $v1, $v1, 2
        sb      $v1, 0x18($a3)
        srl     $at, $at, 16
        subu    $v1, $t9, $at
        sb      $v1, 0x19($a3)
        sll     $at, $t1, 16
        or      $at, $at, $t0
        sw      $at, 0x1c($a3)
        srl     $at, $t8, 6
        lui     $v1, 0xe100
        addu    $at, $at, $v1
        sltiu   $v1, $t9, 0x100
        bne     $v1, $zero, 1f
        sll     $t7, $t7, 1
        addiu   $at, $at, 0x10
1:      sw      $at, 4($a3)
        lui     $v1, 0x8006
        addu    $v1, $v1, $t7
        lhu     $at, -0x2b60($v1)
        b       link
        sh      $at, 0x1a($a3)

swrap:  addiu   $sp, $sp, -24
        sw      $ra, 16($sp)
        sw      $a2, 20($sp)
1:      jal     DrawSync
        ori     $a0, $zero, 1
        bne     $v0, $zero, 1b
        nop
        lw      $ra, 16($sp)
        lw      $a2, 20($sp)
        addiu   $sp, $sp, 24
        lui     $v1, 0x8006
        ori     $at, $zero, 1
        sh      $at, -0x3a02($v1)
        lui     $at, 0x8007
        lw      $a3, -0x6128($at)
        lui     $a1, 0x8007
        lw      $a1, -0x5cc0($a1)
        lhu     $t5, 0x5c($a2)
        lhu     $t6, 0x5e($a2)
        lhu     $t7, 0x6e($a2)
        lhu     $t8, 0x68($a2)
        lhu     $t9, 0x6a($a2)
        lbu     $t0, 0xe8($a1)
        lbu     $t1, 0xe9($a1)
        lw      $v0, 0x94($a1)
        b       spk
        nop
        .end    quad_part

/* ------------------------------------------------------------------------------------------------------------------ */
        .section .text.sec0_parse,"ax",@progbits
        .globl  sec0_parse
        .ent    sec0_parse
sec0_parse:
        lui     $v1, 0x8007
        lw      $v1, -0x5cc0($v1)       # ctx
        nop
        lw      $a0, 0x54($v1)          # s
        lw      $a1, 0x70($v1)          # a
        andi    $at, $a0, 3
        bne     $at, $zero, 1f
        nop
        lw      $t0, 0($a0)             # aligned: 8 bytes, word copies
        lw      $t1, 4($a0)
        addiu   $at, $a1, 0x18
        sw      $at, 0x20($a1)
        addiu   $at, $a0, 4
        sw      $at, 0x24($a1)
        sw      $t0, 0x14($a1)
        b       2f
        sw      $t1, 0x18($a1)
1:      lwr     $t0, 0($a0)             # unaligned: 7 bytes
        lwl     $t0, 3($a0)
        lwr     $t1, 4($a0)
        lwl     $t1, 7($a0)
        addiu   $at, $a1, 0x1b
        sw      $at, 0x2c($a1)
        sw      $at, 0x34($a1)
        addiu   $at, $a0, 7
        sw      $at, 0x30($a1)
        sw      $t0, 0x14($a1)
        sh      $t1, 0x18($a1)
        srl     $at, $t1, 16
        sb      $at, 0x1a($a1)
2:      andi    $at, $t0, 0xff
        sh      $at, 0xf6($v1)
        srl     $t2, $t0, 8
        andi    $at, $t2, 0xfff
        sh      $at, 0xf4($v1)          # (b1 | b2 << 8) & 0xfff
        srl     $t3, $t0, 16
        andi    $t3, $t3, 0xff          # b2
        srl     $t4, $t0, 24            # b3
        andi    $t5, $t1, 0xff          # b4
        srl     $t6, $t1, 8
        andi    $t6, $t6, 0xff          # b5
        srl     $a2, $t3, 4
        andi    $a2, $a2, 3             # m1
        srl     $t3, $t3, 6             # m2
        sh      $a2, 0x1c($a1)
        sh      $t3, 0x1e($a1)
        addiu   $a3, $a1, 0x14
        sw      $a3, 0($a1)
        ori     $at, $zero, 3
        bne     $a2, $at, 5f
        sll     $t7, $t5, 8
        or      $t7, $t7, $t4
        bne     $t3, $at, 3f
        sh      $t7, 0xf0($v1)          # m1 3: f0 = b3 | b4 << 8
        sw      $a3, 0x10($a1)          # m1 3, m2 3: f2 = b5 | b6 << 8
        srl     $t1, $t1, 16
        andi    $t1, $t1, 0xff
        sll     $t1, $t1, 8
        or      $t1, $t1, $t6
        sh      $t1, 0xf2($v1)
        jr      $ra
        ori     $v0, $zero, 7
3:      sw      $a3, 8($a1)             # m1 3: f2 = mode(m2, b5)
        ori     $at, $zero, 2
        beq     $t3, $at, 4f
        subu    $at, $zero, $t6
        or      $at, $t6, $zero
        bne     $t3, $zero, 4f
        sll     $t6, $t6, 24
        sra     $at, $t6, 24
4:      sh      $at, 0xf2($v1)
        jr      $ra
        ori     $v0, $zero, 6
5:      bne     $t3, $at, 6f
        ori     $at, $zero, 2
        sw      $a3, 0xc($a1)           # m2 3: f0 = m1 == 2 ? -b3 : b3, f2 = b4 | b5 << 8
        bne     $a2, $at, 7f
        or      $t7, $t4, $zero
        subu    $t7, $zero, $t4
7:      sh      $t7, 0xf0($v1)
        sll     $t6, $t6, 8
        or      $t6, $t6, $t5
        sh      $t6, 0xf2($v1)
        jr      $ra
        ori     $v0, $zero, 6
6:      sw      $a3, 4($a1)             # f0 = mode(m1, b3), f2 = mode(m2, b4)
        beq     $a2, $at, 8f
        subu    $t7, $zero, $t4
        or      $t7, $t4, $zero
        bne     $a2, $zero, 8f
        sll     $t4, $t4, 24
        sra     $t7, $t4, 24
8:      sh      $t7, 0xf0($v1)
        beq     $t3, $at, 9f
        subu    $t7, $zero, $t5
        or      $t7, $t5, $zero
        bne     $t3, $zero, 9f
        sll     $t5, $t5, 24
        sra     $t7, $t5, 24
9:      sh      $t7, 0xf2($v1)
        jr      $ra
        ori     $v0, $zero, 5
        .end    sec0_parse

/* ------------------------------------------------------------------------------------------------------------------ */
        .section .text.sec1_parse,"ax",@progbits
        .globl  sec1_parse
        .ent    sec1_parse
sec1_parse:
        lui     $a0, 0x8007
        lw      $a0, -0x5cc0($a0)       # ctx
        nop
        lw      $a1, 0x70($a0)          # w
        lw      $a2, 0x88($a0)          # tile header
        addiu   $at, $a1, 8
        lw      $t0, 0($a2)
        sw      $at, 0($a1)
        sw      $a2, 4($a1)
        sw      $t0, 8($a1)
        lui     $at, 0x3f
        ori     $at, $at, 0xffff
        and     $at, $t0, $at
        sw      $at, 0xe4($a0)
        srl     $t1, $t0, 24
        andi    $t2, $t1, 0xf
        addiu   $t2, $t2, 1
        sll     $t2, $t2, 3             # e8 = ((b3 & 15) + 1) * 8
        andi    $t3, $t1, 0xf0
        addiu   $t3, $t3, 0x10
        andi    $t3, $t3, 0xff
        sll     $t3, $t3, 8             # e9 = (b3 & 0xf0) + 16
        srl     $v0, $t0, 8
        andi    $v0, $v0, 0x8000        # ea = (b2 << 8) & 0x8000
        or      $t2, $t2, $t3
        sll     $at, $v0, 16
        or      $t2, $t2, $at
        jr      $ra
        sw      $t2, 0xe8($a0)
        .end    sec1_parse
