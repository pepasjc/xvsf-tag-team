# EX OPTIONS rows on the memory card inside MSHvSF's own save (exopt.py --excard; user rule 2026-11-24: every EX
# OPTIONS row is saved with the game's save and restored on load; stock / older saves load and give the defaults).
# The game's save (OPE.ARC / OPDEMO, OPTION -> MEMORY CARD): file "BASLUS-00793-MSHVSSF", 0x500 bytes written / read in
# one call from the image at 0x800b86d0; game data at file 0x100 .. 0x1c1 (option block, ranking, names), then unused
# bytes; XOR of file 0x100 .. 0x4fb at 0x4fc (setter 0x80099098 a0 = image, checker 0x800990f8 a0 = image + 0x100,
# 0 = valid).  Ours at file 0x4f0, inside the XOR range (the game's checksum covers it): 'X' 'O' 1, then the option bytes
# STAGE ANIM (OPTB+2), ACHIEVEMENT POPUP (+3), ARCADE BALANCE (+6), INFINITE SUPER METER (+7), ARCADE FRAMES (+9, 8 MB
# discs; 0 on 2 MB).  One layout for 2 MB and 8 MB.  Defaults = 0 for every row.
#   svhook: OPE.ARC 0x80098808 `jal 0x80099098` (delay slot a0 = image) -> stamp, then the stock setter
#   ldhook: OPE.ARC 0x80098998 `jal 0x800990f8` (a0 = image + 0x100, s2 = image; after the read) -> stock check; valid
#           + ours -> bytes back; valid without ours -> defaults; invalid -> nothing restored (the game reports it).
#           Then ARCADE BALANCE's words follow the restored byte (abapply, EX OPTIONS screen code in the OPE.ARC slack:
#           resident while OPTION runs).  v0 = the check result for the caller.

# ---------------------------------------------------------------- card save: stamp + rows, then the stock XOR setter
svhook: lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)+2($t0)
        lbu     $t2, %lo(OPTB)+3($t0)
        lbu     $t3, %lo(OPTB)+6($t0)
        lbu     $t4, %lo(OPTB)+7($t0)
        lbu     $t5, %lo(OPTB)+9($t0)
        ori     $t6, $zero, 0x58                # 'X'
        sb      $t6, 0x4f0($a0)
        ori     $t6, $zero, 0x4f                # 'O'
        sb      $t6, 0x4f1($a0)
        ori     $t6, $zero, 1                   # layout version
        sb      $t6, 0x4f2($a0)
        sb      $t1, 0x4f3($a0)
        sb      $t2, 0x4f4($a0)
        sb      $t3, 0x4f5($a0)
        sb      $t4, 0x4f6($a0)
        sb      $t5, 0x4f7($a0)
        j       SVSET                           # the stock checksum (ra = the save routine)
        nop

# ---------------------------------------------------------------- card load: the stock check, then our block
ldhook: addiu   $sp, $sp, -24
        sw      $ra, 16($sp)
        jal     LDCHK                           # stock XOR check (a0 = image + 0x100): 0 = valid
        nop
        bnez    $v0, 9f                         # invalid: the game reports it, nothing restored
        lbu     $t0, 0x4f0($s2)
        lbu     $t1, 0x4f1($s2)
        lbu     $t2, 0x4f2($s2)
        xori    $t0, $t0, 0x58
        xori    $t1, $t1, 0x4f
        xori    $t2, $t2, 1
        or      $t0, $t0, $t1
        or      $t0, $t0, $t2
        bnez    $t0, 8f                         # stock / older save: defaults
        lui     $t9, %hi(OPTB)
        j       ldset
        nop
8:      j       ldz
        nop
9:      lw      $ra, 16($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24

# ---------------------------------------------------------------- card load: ours present -> the bytes back (t9 = %hi(OPTB))
ldset:  lbu     $t1, 0x4f3($s2)
        lbu     $t2, 0x4f4($s2)
        lbu     $t3, 0x4f5($s2)
        lbu     $t4, 0x4f6($s2)
        lbu     $t5, 0x4f7($s2)
        sb      $t1, %lo(OPTB)+2($t9)
        sb      $t2, %lo(OPTB)+3($t9)
        sb      $t3, %lo(OPTB)+6($t9)
        sb      $t4, %lo(OPTB)+7($t9)
        j       ldfin
        sb      $t5, %lo(OPTB)+9($t9)

# ---------------------------------------------------------------- card load: no block of ours -> defaults (all 0)
ldz:    sb      $zero, %lo(OPTB)+2($t9)
        sb      $zero, %lo(OPTB)+3($t9)
        sb      $zero, %lo(OPTB)+6($t9)
        sb      $zero, %lo(OPTB)+7($t9)
        j       ldfin
        sb      $zero, %lo(OPTB)+9($t9)

# ---------------------------------------------------------------- card load: ARCADE BALANCE words, return valid
ldfin:
.if ABCARD
        jal     ABAPPLY                         # the arcade or the stock words for the restored byte (+ FlushCache)
        nop
.endif
        move    $v0, $zero
        lw      $ra, 16($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24
