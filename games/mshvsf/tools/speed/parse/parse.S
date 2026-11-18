# MSHvSF speed, part "parse": the two sprite-part header parsers of the sprite engine, rewritten in place
# (the XvSF 1.1 quad.S sec0_parse / sec1_parse analogues).  ctx = *(u32 *)0x80092160 (the scratchpad context
# 0x1f800000 set by the per-object sprite draw 0x8008113c).
#
#   sec0  0x80082d9c-0x80083034  part header: copies 8 bytes ctx->8 (src, any alignment) -> ctx->4 (aligned buffer),
#         sets ctx+0x3c (b0 << 16 | 12-bit field), ctx+0x40/0x41 (b3 nibbles), ctx+0x38 (offset pair, 4 formats by
#         the two 2-bit modes in bits 12-15 of b1|b2<<8), returns the header length 8 / 7 / 6.
#   sec1  0x80083034-0x800830c4  tile header: copies the word at a0 -> ctx->4, sets ctx+0x30 (22-bit offset),
#         ctx+0x34 / 0x35 (width bytes, rows), ctx+0x36 (flag), returns the flag.
# Same final memory, same v0 as stock; callers read nothing else (checked: every call site reloads a0-a3 / v1).

#@SEC0
sec0:
    lui   $t0, 0x8009
    lw    $t0, 0x2160($t0)
    nop
    lw    $a0, 8($t0)                   # src
    lw    $a1, 4($t0)                   # 8-byte buffer (aligned)
    andi  $v0, $a0, 3
    bnez  $v0, 1f
    nop
    lw    $v0, 0($a0)
    lw    $v1, 4($a0)
    b     2f
    nop
1:  lwr   $v0, 0($a0)
    lwl   $v0, 3($a0)
    lwr   $v1, 4($a0)
    lwl   $v1, 7($a0)
2:  sw    $v0, 0($a1)
    sw    $v1, 4($a1)
    srl   $t1, $v0, 8                   # b1 | b2 << 8 | b3 << 16
    andi  $t2, $t1, 0xfff
    andi  $t3, $v0, 0xff
    sll   $t3, $t3, 16
    or    $t3, $t3, $t2
    sw    $t3, 0x3c($t0)
    srl   $t3, $v0, 24                  # b3
    andi  $t2, $t3, 0xf
    sb    $t2, 0x40($t0)
    srl   $t3, $t3, 4
    sb    $t3, 0x41($t0)
    andi  $t1, $t1, 0xffff
    srl   $a3, $t1, 14                  # x mode
    srl   $t1, $t1, 12
    andi  $t1, $t1, 3                   # y mode
    ori   $t2, $zero, 3
    bne   $t1, $t2, ny3
    ori   $t3, $zero, 2
# y mode 3
    beq   $a3, $t2, r8                  # x mode 3: word = bytes 4..7
    andi  $t4, $v1, 0xffff              # b4 | b5 << 8
    srl   $t5, $v1, 16
    beq   $a3, $t3, y3x2
    andi  $t5, $t5, 0xff                # b6
    bnez  $a3, w7                       # x mode 1: b6
    sll   $t5, $t5, 16
    sll   $t5, $t5, 8                   # x mode 0: (s8)b6 << 16
    b     w7
    sra   $t5, $t5, 8
y3x2:
    negu  $t5, $t5                      # x mode 2: -b6 << 16
    sll   $t5, $t5, 16
w7: or    $t5, $t5, $t4
    sw    $t5, 0x38($t0)
    jr    $ra
    ori   $v0, $zero, 7
r8: sw    $v1, 0x38($t0)
    jr    $ra
    ori   $v0, $zero, 8
ny3:
    bne   $a3, $t2, h2
    andi  $t4, $v1, 0xff                # b4
# y mode 0..2, x mode 3: (b5 | b6 << 8) << 16 | (y 2: -b4 & 0xffff, else b4)
    srl   $t5, $v1, 8
    andi  $t5, $t5, 0xffff
    bne   $t1, $t3, 3f
    sll   $t5, $t5, 16
    negu  $t4, $t4
    andi  $t4, $t4, 0xffff
3:  or    $t5, $t5, $t4
    sw    $t5, 0x38($t0)
    jr    $ra
    ori   $v0, $zero, 7
h2: # two halves: +0x38 from b4 by y mode, +0x3a from b5 by x mode (0: signed byte, 1: byte, 2: -byte)
    beq   $t1, $t3, 4f
    sll   $t6, $t4, 24
    bnez  $t1, 5f
    nop
    b     5f
    sra   $t4, $t6, 24
4:  negu  $t4, $t4
5:  sh    $t4, 0x38($t0)
    srl   $t4, $v1, 8
    andi  $t4, $t4, 0xff                # b5
    beq   $a3, $t3, 6f
    sll   $t6, $t4, 24
    bnez  $a3, 7f
    nop
    b     7f
    sra   $t4, $t6, 24
6:  negu  $t4, $t4
7:  sh    $t4, 0x3a($t0)
    jr    $ra
    ori   $v0, $zero, 6

#@SEC1
sec1:
    lui   $a2, 0x8009
    lw    $a1, 0x2160($a2)              # ctx
    lw    $v0, 0($a0)                   # tile header word
    lw    $v1, 4($a1)                   # buffer
    lui   $a3, 0x3f
    ori   $a3, $a3, 0xffff
    sw    $v0, 0($v1)
    and   $t0, $v0, $a3
    sw    $t0, 0x30($a1)
    srl   $t0, $v0, 24                  # b3
    andi  $t1, $t0, 0xf
    addiu $t1, $t1, 1
    sll   $t1, $t1, 3
    sb    $t1, 0x34($a1)
    andi  $t1, $t0, 0xf0
    addiu $t1, $t1, 0x10
    sb    $t1, 0x35($a1)
    srl   $v0, $v0, 8
    andi  $v0, $v0, 0x8000
    jr    $ra
    sh    $v0, 0x36($a1)
