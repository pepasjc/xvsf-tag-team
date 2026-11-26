/* SUPERSEDED 2026-11-24 by the 1.0-line 8 MB module (mkap8.py, entry8.S, ap8m.c, s8/): kept for reference, not built. */
# Resident main-menu part of the MvC 8 MB build (tools/ap8/mkap8.py): the 8 MB probe at the first main-menu frame and
# "8MB" left of the version line.  Pieces are packed by games/mshvsf/tools/speed/slib.pack into small dead EXE spans
# (mkap8.MRANGES; only j / jal / la between pieces; unused bytes = break).
#
# Hook: DAT/OPDEMO.ARC entry 0, 0x800a2b2c (end of the main-menu text routine 0x800a2a50: `jr ra`, delay slot
# `addiu sp, sp, 0x30`) -> `j ap8menu`.  ra = the routine's caller, sp restored: ap8menu returns with `jr ra`.
#
# State: byte STATE = 0x800858ae (dead EXE word 0x800858ac, zeroed in the image by mktag.py: +0 LOADER_FULL, +1 RESTORE,
# +2 probe 0 not yet / 1 no 8 MB / 2 8 MB, +3 cache valid this boot (ap8.c)).  The loader blob (ap8.c) probes the same
# way if the menu never ran (it never probes twice).
#
# Probe (real hardware, see XvSF 1.0.1): RAM_SIZE = 0xb88 (what the BIOS writes); then a test that writes nothing: 32
# words of game code (0x80024810, file loader) against the same address + 2 MB: all equal = mirrored = 2 MB, nothing
# above 2 MB is ever written.  Else write / read back at +2, +4, +6 MB of the word 0x800858ac with a BIOS-ROM read in
# between (drains the CPU write buffer), the low word must stay unchanged; everything restored.

# ---------------------------------------------------------------- main-menu hook
ap8menu:
        lui     $t0, 0x8008
        lbu     $t1, 0x58ae($t0)
        nop
        beqz    $t1, 1f
        addiu   $t1, $t1, -2
        bnez    $t1, 2f
        nop
        j       ap8mark
        nop
1:      j       ap8probe
        nop
2:      jr      $ra
        nop

# ---------------------------------------------------------------- read-only mirror test
ap8probe:
        lui     $t2, 0x1f80
        ori     $t3, $zero, 0xb88
        sw      $t3, 0x1060($t2)
        lui     $t4, 0x8002
        ori     $t4, $t4, 0x4810
        lui     $t5, 0x0020
        addu    $t5, $t4, $t5
        j       ap8mir
        ori     $t6, $zero, 32

# ---------------------------------------------------------------- mirror loop: 32 words equal at +2 MB = 2 MB console
ap8mir:
3:      lw      $t7, 0($t4)
        lw      $t8, 0($t5)
        addiu   $t4, $t4, 4
        bne     $t7, $t8, 4f
        addiu   $t5, $t5, 4
        addiu   $t6, $t6, -1
        bnez    $t6, 3b
        nop
        move    $t6, $zero
        j       ap8set
        ori     $v1, $zero, 1
4:      j       ap8wr0
        nop

# ---------------------------------------------------------------- write / read-back at +2, +4, +6 MB: setup
ap8wr0:
        lui     $t0, 0x8008
        addiu   $t0, $t0, 0x58ac
        lw      $t1, 0($t0)                     # low word (restored after every test)
        ori     $v1, $zero, 2
        lui     $t8, 0x0020                     # step 2 MB
        nor     $t9, $t1, $zero                 # pattern
        lui     $a3, 0xbfc0                     # BIOS ROM
        lui     $a2, 0x0060                     # last offset
        j       ap8wr
        lui     $t2, 0x0020

# ---------------------------------------------------------------- write / read-back loop (t2 = offset)
ap8wr:
        addu    $t3, $t0, $t2
        lw      $t4, 0($t3)
        sw      $t9, 0($t3)
        lw      $t5, 0($a3)                     # BIOS-ROM read: the write above has left the write buffer
        lw      $t6, 0($t3)
        lw      $t7, 0($t0)
        sw      $t1, 0($t0)
        sw      $t4, 0($t3)
        xor     $t6, $t6, $t9
        xor     $t7, $t7, $t1
        or      $t6, $t6, $t7
        bnez    $t6, 6f
        nop
        bne     $t2, $a2, ap8wr
        addu    $t2, $t2, $t8
6:      j       ap8set
        sltu    $t6, $zero, $t6

# ---------------------------------------------------------------- store the result (v1 - t6: 1 or 2)
ap8set:
        subu    $v1, $v1, $t6
        lui     $t0, 0x8008
        j       ap8menu
        sb      $v1, 0x58ae($t0)

# ---------------------------------------------------------------- "8MB" left of the version line
ap8mark:
        addiu   $sp, $sp, -0x18
        sw      $ra, 0x10($sp)
        la      $a0, ap8txt
        lui     $a1, MARKX
        ori     $a1, $a1, MARKY
        lui     $a2, 0x1027
        jal     0x80020f10
        ori     $a2, $a2, 0x2001
        lw      $ra, 0x10($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 0x18

# ---------------------------------------------------------------- text
ap8txt:
        .asciz  "8MB"
        .align  2
