# Resident EXE stubs of the MvC sound module (dead spans, see games/mvc/docs/CODESPACE.md).  The play function's first
# two instructions (0x80086ae8: addiu sp,-0x88; andi a1,a1,0xff00) become `j sndstub; nop`.
#   sndstub (0x80022350, 68 B): tag rules running (versus flag 0x8007b75d == 0), LOADER_FULL (0x800858ac) == 3 and the
#       swap code's magic at 0x801fe800 -> swentry (RAM, swap.c); flag 1 -> sndrest; else the replaced instructions.
#   sndrest (0x800178ec, 72 B): the stock bank addresses 0x800884b8.. (banks 1-4) back if a tag battle changed them
#       (menus and every other battle load use them; the RAM code re-applies its own ones in the next tag battle).
        .set noreorder
        .set noat
        .section .stub, "ax"
        .globl sndstub
sndstub:
        lui     $t0, 0x8008
        lbu     $t1, -0x48a3($t0)
        lbu     $t2, 0x58ac($t0)
        bnez    $t1, sndrest
        addiu   $t2, $t2, -3
        bnez    $t2, 1f
        lui     $t4, 0x8020
        lw      $t5, -0x1800($t4)
        lui     $t6, %hi(MAGIC)
        ori     $t6, $t6, %lo(MAGIC)
        bne     $t5, $t6, 1f
        nop
        j       SWENTRY
        nop
1:      addiu   $sp, $sp, -0x88
        j       0x80086af0
        andi    $a1, $a1, 0xff00
        .globl stub_end
stub_end:
        .section .rest, "ax"
        .globl sndrest
sndrest:
        lui     $t0, 0x8009
        lw      $t1, -0x7b44($t0)
        lui     $t2, 0x0004
        ori     $t2, $t2, 0x90e0
        beq     $t1, $t2, 2f
        lui     $t3, 0x0003
        ori     $t3, $t3, 0x15b0
        sw      $t3, -0x7b48($t0)
        sw      $t2, -0x7b44($t0)
        lui     $t3, 0x0004
        ori     $t3, $t3, 0xcac0
        sw      $t3, -0x7b40($t0)
        lui     $t3, 0x0006
        ori     $t3, $t3, 0x45f0
        sw      $t3, -0x7b3c($t0)
2:      addiu   $sp, $sp, -0x88
        j       0x80086af0
        andi    $a1, $a1, 0xff00
        .globl rest_end
rest_end:
