# OPTION MODE rows after the stock ones (games/mvc/tools/gameplay/optrows.py, fs05, fx worker 2026-11-19).
# Linked into OPDEMO.ARC's last-sector slack (loaded with the file, untouched in OPTION MODE: tools/speed5/slackchk.py).
# Row r (cursor 15 + r): value byte 0x800858c9 + r (dead-span bytes after ASSIST_GATE, never cleared -> the choice
# survives matches / menu / attract / continue until power-off).  The stock LEFT / RIGHT +-1 is redirected there by
# rbase; optrows wraps the value, draws label (x 0x90) + value (x 0x120) at y Y0 + 8 r, bright when the cursor is on it.

#@O
optrows:                                        # from OPDEMO 0x800a29c4 (was jal 0x800a1e24); s0 = 0x8007b6e8
        addiu   $sp, $sp, -48
        sw      $ra, 40($sp)
        sw      $s1, 36($sp)
        sw      $s2, 32($sp)
        sw      $s3, 28($sp)
        jal     0x800a1e24                      # stock lines
        nop
        lui     $s3, %hi(ROWS)
        addiu   $s3, $s3, %lo(ROWS)             # records: label, nvals, value strings x 4
        move    $s1, $zero
1:      lui     $t0, 0x8008
        addu    $t0, $t0, $s1
        lb      $t1, 0x58c9($t0)
        lw      $t3, 4($s3)
        bgez    $t1, 2f
        slt     $t2, $t1, $t3
        addiu   $t1, $t3, -1                    # -1 -> last
        li      $t2, 1
2:      bnez    $t2, 3f
        nop
        move    $t1, $zero                      # past the last -> first
3:      sb      $t1, 0x58c9($t0)
        sll     $t1, $t1, 2
        addu    $t1, $s3, $t1
        lw      $s2, 8($t1)                     # value string
        lb      $t2, 0xd($s0)                   # cursor
        addiu   $t4, $s1, 15
        lui     $a2, 0x0823
        bne     $t2, $t4, 4f
        ori     $a2, $a2, 1
        lui     $a2, 0x0820                     # our row selected: bright
        ori     $a2, $a2, 1
4:      sw      $a2, 16($sp)
        sll     $t5, $s1, 3
        addiu   $t5, $t5, Y0
        sw      $t5, 20($sp)
        lui     $a1, 0x90
        or      $a1, $a1, $t5
        jal     FONT                            # label
        lw      $a0, 0($s3)
        lw      $t5, 20($sp)
        lui     $a1, 0x120
        or      $a1, $a1, $t5
        lw      $a2, 16($sp)
        jal     FONT                            # value
        move    $a0, $s2
        addiu   $s1, $s1, 1
        slti    $t0, $s1, NROWS
        bnez    $t0, 1b
        addiu   $s3, $s3, 24
        lw      $ra, 40($sp)
        lw      $s1, 36($sp)
        lw      $s2, 32($sp)
        lw      $s3, 28($sp)
        jr      $ra
        addiu   $sp, $sp, 48

rbase:                                          # from OPDEMO 0x800a263c / 0x800a266c (LEFT / RIGHT), v1 = cursor
        sltiu   $t0, $v1, 15                    # cursor < 15: stock v1 = s0 + cursor (value block[0x11 + cursor])
        addiu   $t0, $t0, -1                    # cursor >= 15: v1 + 0x11 = 0x800858c9 + cursor - 15
        andi    $t0, $t0, 0xa1c1                # 0x800858c9 - 0x8007b708
        addu    $v1, $v1, $t0
        jr      $ra
        addu    $v1, $s0, $v1

        .align  2
ROWS:   ROWTAB
