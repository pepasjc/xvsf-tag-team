# MSHvSF (SLUS-00793) - playable Cyber-Akuma (hold SELECT + confirm on Akuma) + secret characters unlocked.  Built by cyber.py.
#
# Two in-place rewrites (no new code space):
#   .sel  SELECT.BIN (overlay at 0x80094800) 0x80097698-0x800977b4: the per-frame "code counter" of the select
#         screen (stock: 0x80097698 + its helper 0x800976fc, called from the main-pick state 0x80096be8 and the
#         partner-pick state 0x80096f60 only).
#   .exe  SLUS_007.93 0x8004f82c-0x8004f8c4: the tail of the SHORT CUT (text list) select's input reader 0x8004f64c.
#
# Stock behaviour kept: on Akuma, every new SELECT press counts (+0x24 of the select struct, max 10; a hold is one
# press); the pick routine turns Akuma into Cyber-Akuma when the count is 5 and into Apocalypse (char 0) when it is 6;
# holding SELECT while confirming Blackheart / Hulk / Dhalsim / Bison / Omega Red / Spider-Man gives Mech-Zangief /
# Dark Sakura / Shadow / U.S. Agent / Mephisto / Armored Spider-Man.  New, the same pattern for Cyber-Akuma: SELECT
# held while confirming Akuma, before this player has picked anything, sets the count to 5 in that frame (unless it
# is 6: the Apocalypse code with its last tap still held) -> Cyber-Akuma (solo: the stock select skips the partner
# pick for him).  START does nothing on the select screens (stock).
# The unlock checks of the save flag 0x80025076 (bit 1 Cyber-Akuma, bit 0 Apocalypse) are patched to "on" by
# cyber.py (one word each), and the stock counter no longer waits for the flag.

        .set noreorder
        .set noat

# ------------------------------------------------------------------------------------------------- SELECT.BIN
# a0 = select struct (0x80071af4 P1 / 0x80071b20 P2): +1 side, +2 picks made, +0xa cursor char id * 2,
#      +0x24 code count.  Raw pad: 0x80027d60[side] held, 0x80027db8[side] previous frame.
#      Mapped pad (pressed this frame) read by the caller right after us: 0x80071ad8[+1].
        .section .sel, "ax"
sel_tick:
        lui     $t0, 0x8002
        lb      $v0, 0x50ac($t0)        # menu mode
        li      $v1, 3
        beq     $v0, $v1, 9f            # CROSS OVER: stock does nothing here either
        lh      $v1, 10($a0)
        li      $t2, 0x1e               # Akuma
        bne     $v1, $t2, 8f
        lb      $a1, 1($a0)             # side
        li      $t2, 2                  # TRAINING with two pads: stock side swap
        bne     $v0, $t2, 1f
        lui     $t3, 0x8007
        lbu     $t3, 0x0a91($t3)        # human bits
        li      $t2, 3
        bne     $t3, $t2, 1f
        nop
        lb      $t3, 0x504d($t0)
        nop
        srav    $t3, $t3, $a1
        andi    $t3, $t3, 1
        bnez    $t3, 1f
        nop
        xori    $a1, $a1, 1
1:      sll     $a1, $a1, 1
        addu    $a1, $a1, $t0
        lhu     $t1, 0x7d60($a1)        # held
        lhu     $t2, 0x7db8($a1)        # previous
        nop
        nor     $t2, $t2, $zero
        and     $t2, $t1, $t2           # new presses
        andi    $v0, $t2, 0x100         # SELECT: stock code counter (a hold is one press)
        beqz    $v0, 2f
        lb      $v0, 0x24($a0)
        nop
        slti    $v1, $v0, 10
        beqz    $v1, 2f
        addiu   $v0, $v0, 1
        sb      $v0, 0x24($a0)
2:      andi    $v0, $t1, 0x100         # SELECT held ...
        beqz    $v0, 9f
        lb      $v0, 2($a0)             # ... nothing picked yet ...
        lb      $v1, 1($a0)
        bgtz    $v0, 9f
        lui     $t0, 0x8007
        sll     $v1, $v1, 1
        addu    $t0, $t0, $v1
        lhu     $v0, 0x1ad8($t0)        # ... and a confirm button pressed this frame (the stock code reads it after us)
        nop
        andi    $v0, $v0, 0x770
        beqz    $v0, 9f
        lb      $v0, 0x24($a0)
        li      $v1, 6
        beq     $v0, $v1, 9f            # 6th tap still held: Apocalypse stays Apocalypse
        li      $v0, 5
        jr      $ra
        sb      $v0, 0x24($a0)          # count 5 = Cyber-Akuma in the stock pick
8:      sb      $zero, 0x24($a0)        # not on Akuma: count back to 0
9:      jr      $ra
        nop
sel_end:

# ------------------------------------------------------------------------------------------------- EXE (SHORT CUT)
# In 0x8004f64c: s1 / s0 mapped pad now / before, s2 result bits (0x02 0x04 0x08 0x10 confirm buttons, 0x20 SELECT
# held), s3 select struct (+4 state: 2 = main pick, +0xa list position, +0x24 code count), s4 pad index.
# Entry 0x8004f82c (and 0x8004f830 from the branch at 0x8004f820 with v0 = 0x80020000 set in its delay slot).
        .section .exe, "ax"
exe_tail:
        lui     $v0, 0x8002
        sll     $v1, $s4, 1             # 0x8004f830
        addu    $v1, $v1, $v0
        lhu     $t0, 0x7d60($v1)        # raw held
        lhu     $t1, 0x7db8($v1)        # raw previous
        andi    $v0, $t0, 0x100
        beqz    $v0, 1f
        nor     $t1, $t1, $zero
        ori     $s2, $s2, 0x20          # SELECT held (hidden variants)
1:      and     $t1, $t0, $t1           # new presses
        lui     $v0, 0x8007
        lh      $v1, 10($s3)            # cursor (list position)
        lb      $t2, -21501($v0)        # list position of Akuma (0x8006abf4[0x0f])
        lbu     $t3, 0x24($s3)          # code count
        bne     $v1, $t2, 9f
        andi    $v0, $t1, 0x100
        beqz    $v0, 2f                 # new SELECT on Akuma: stock code counter (a hold is one press)
        addiu   $t3, $t3, 1
        slti    $v0, $t3, 7
        bnez    $v0, 3f
        nop
        li      $t3, 10
3:      sb      $t3, 0x24($s3)
2:      andi    $v0, $t0, 0x100         # SELECT held + confirm on Akuma in the main pick (state 2):
        beqz    $v0, 9f
        andi    $v0, $s2, 0x1e
        beqz    $v0, 9f
        lh      $v1, 4($s3)
        li      $v0, 2
        bne     $v1, $v0, 9f
        lbu     $v0, 0x24($s3)
        li      $t1, 6
        beq     $v0, $t1, 9f            # 6th tap still held: Apocalypse
        li      $v0, 5
        sb      $v0, 0x24($s3)          # count 5, and drop the SELECT bit (the stock Cyber-Akuma check wants it clear)
        xori    $s2, $s2, 0x20
9:      move    $v0, $s2                # must end at 0x8004f8c0 (epilogue at 0x8004f8c4)
exe_end:
