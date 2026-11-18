# MSHvSF speed: RAM versions of the BIOS A0 memcpy (0x2a) and bzero (0x28), port of XvSF 1.1 tools/speed/frame
# (splist.S / layers.S, tested there against scph1001/5501/7001).  Entered from the game's stubs (0x800144a8 memcpy,
# 0x80014498 bzero), rewritten as
#     sltiu t2, n, 0x400 ; bnez t2, f_xxx ; addiu t1, zero, N ; j a0bios
# (n >= 1 KB keeps the BIOS routine = stock timing; see XvSF frame REPORT round 5, attract-demo race).
# Results, final a0..a2 / v0 / v1 / t6 and the A0 dispatcher's t0 (= A0 table entry), t1 (= N*4), t2 (= 0xa0)
# are exactly those of the BIOS routines (byte loops, forward).
# The code is split over statically and dynamically dead ranges (deadcode.py / deadtest.py), one chunk each:
#   C1 0x80010a38-0x80010aec  copy core + a0bios
#   C2 0x8001117c-0x800111d8  fill loops
#   C3 0x80013a38-0x80013a9c  bzero entry, fill tail, common return
#   C4 0x80013acc-0x80013afc  memcpy entry
# Each chunk is assembled at its own address (build.py); labels of the other chunks come in as absolute symbols,
# so every cross-chunk transfer is a `j`.

#@C1
copy:                                   # a0 src, a1 dst, a2 n > 0, v0 = (dst - src < 4); temps v0, t0, t6
    bnez  $v0, cbyte                    # dst - src in 0..3: forward byte copy (overlap semantics of word moves)
    andi  $v0, $a1, 3
    beqz  $v0, calig
    lbu   $t6, 0($a0)                   # (head byte; harmless extra read when the branch is taken)
chead:
    addiu $a0, $a0, 1
    addiu $a2, $a2, -1
    sb    $t6, 0($a1)
    beqz  $a2, cend
    addiu $a1, $a1, 1
    andi  $v0, $a1, 3
    bnez  $v0, chead
    lbu   $t6, 0($a0)                   # next head byte (harmless extra read on exit)
calig:
    sltiu $v0, $a2, 4
    bnez  $v0, cbyte4
    andi  $v0, $a0, 3
    bnez  $v0, cunal1
    lwr   $t6, 0($a0)                   # first unaligned word (overwritten by cword's lw when not taken)
cword:                                  # both aligned
    lw    $t6, 0($a0)
    addiu $a2, $a2, -4
    addiu $a0, $a0, 4
    sw    $t6, 0($a1)
    sltiu $v0, $a2, 4
    beqz  $v0, cword
    addiu $a1, $a1, 4
    b     cbyte4
    nop
cunal:                                  # dst aligned, src not
    lwr   $t6, 0($a0)
cunal1:
    lwl   $t6, 3($a0)
    addiu $a2, $a2, -4
    addiu $a0, $a0, 4
    sw    $t6, 0($a1)
    sltiu $v0, $a2, 4
    beqz  $v0, cunal
    addiu $a1, $a1, 4
cbyte4:
    beqz  $a2, cend
    nop
cbyte:
    lbu   $t6, 0($a0)
    addiu $a0, $a0, 1
    addiu $a2, $a2, -1
    sb    $t6, 0($a1)
    bnez  $a2, cbyte
    addiu $a1, $a1, 1
cend:
    j     cend5
    lbu   $t6, -1($a1)                  # BIOS leaves the last byte in t6

#@C4
cend5:
    move  $t0, $a0                      # memcpy: swap back (a0 = dst end, a1 = src end)
    move  $a0, $a1
    j     mdone
    move  $a1, $t0

fbyte4:
    beqz  $t2, 1f
    nop
fbyte:
    sb    $t0, 0($a0)
    addiu $t2, $t2, -1
    bnez  $t2, fbyte
    addiu $a0, $a0, 1
1:  j     fend
    move  $a1, $zero                    # bzero: a1 = 0 (the only fill user here)

#@C2
fill:                                   # a0 dst, t0 pattern, t2 n > 0; temp v0
    andi  $v0, $a0, 3
    beqz  $v0, falig
    nop
    sb    $t0, 0($a0)
    addiu $t2, $t2, -1
    bnez  $t2, fill
    addiu $a0, $a0, 1
falig:                                  # (also reached with t2 = 0 from the head loop)
    sltiu $v0, $t2, 16
    beqz  $v0, fword
    nop
    j     fbyte4
    nop
fword:
    sw    $t0, 0($a0)
    sw    $t0, 4($a0)
    sw    $t0, 8($a0)
    sw    $t0, 12($a0)
    addiu $t2, $t2, -16
    sltiu $v0, $t2, 16
    beqz  $v0, fword
    addiu $a0, $a0, 16
    j     fbyte4
    nop

#@C3
f_bzero:                                # bzero(dst a0, n a1) -> dst
    beqz  $a0, mret0
    nop
    blez  $a1, mret0
    nop
    move  $v1, $a0
    move  $t2, $a1
    j     fill
    move  $t0, $zero
fend:
mdone:
    move  $v0, $v1
mret:                                   # A0 dispatcher registers as the BIOS path leaves them
    sll   $t1, $t1, 2
    lw    $t0, 0x200($t1)
    jr    $ra
    ori   $t2, $zero, 0xa0
mret0:
    b     mret
    move  $v0, $zero
f_memcpy:                               # memcpy(dst a0, src a1, n a2) -> dst
    beqz  $a0, mret0
    nop
    j     memcpy2
    nop
a0bios:                                 # n >= 1 KB: the BIOS routine through the A0 dispatcher (t1 = N set by the stub)
    ori   $t2, $zero, 0xa0
    jr    $t2
    nop

#@C5
memcpy2:                                # (from f_memcpy: a0 != 0)
    blez  $a2, 2f
    move  $v1, $a0
    move  $t0, $a0                      # swap: the core copies a0 -> a1
    move  $a0, $a1
    move  $a1, $t0
    subu  $v0, $a1, $a0
    j     copy
    sltiu $v0, $v0, 4
2:  j     mdone
    nop
