/* "PEPA SOFT HOUSE" boot card for X-Men vs. Street Fighter (SLUS-00627) - tools/logopatch.py.
 *
 * Lives in the zero-filled part of the game's own executable image (0x80099000-0x800f0000 is all zeros
 * in the file and is only heap at run time); the PS-EXE header's entry point is redirected here.
 * Bare metal, like the card of the user's other hacks: no BIOS call, no interrupt state touched, no stack,
 * only t0-t9 / at are used, so the game's entry code gets every register exactly as the BIOS passed it.
 *
 *   1. GPU reset, 320x240 NTSC 15-bit; the card (1 bit per pixel, 1 = ink) is expanded into one
 *      CPU->VRAM transfer at (0,0); display on.
 *   2. hold: ROUNDS x HBLANKS h-blanks on free-running timer 1 (mode: clock = h-blank), no pad, no vsync.
 *   3. the whole VRAM filled black (the display stays on and shows black, as some emulators keep the last
 *      picture while the display is off), timer 1 mode back to 0.
 *   4. a 7-instruction routine is copied below the stack top and run from there: it zeroes this stub and
 *      the bitmap (the image region is all zeros again, as in the original executable) and jumps to the
 *      game's entry point.
 * ENTRY, DATA_LEN, HBLANKS, ROUNDS come from the builder (-D).
 */
        .set noreorder
        .set noat
        .section .logo, "ax"
        .globl logo_start, logo_bits
logo_start:
        lui     $t0, 0x1f80
        sw      $zero, 0x1814($t0)              /* GP1(00): reset */
        lui     $t1, 0x0800
        ori     $t1, $t1, 0x0001                /* GP1(08): 320x240, NTSC, 15-bit */
        sw      $t1, 0x1814($t0)
        lui     $t1, 0x0500                     /* GP1(05): display start (0,0) */
        sw      $t1, 0x1814($t0)
        lui     $t1, 0x06c6
        ori     $t1, $t1, 0x0260                /* GP1(06): horizontal range */
        sw      $t1, 0x1814($t0)
        lui     $t1, 0x0704
        ori     $t1, $t1, 0x0010                /* GP1(07): vertical range */
        sw      $t1, 0x1814($t0)
1:      lw      $t9, 0x1814($t0)                /* GPUSTAT bit 28: ready for a command */
        nop
        srl     $t9, $t9, 28
        andi    $t9, $t9, 1
        beqz    $t9, 1b
        nop
        lui     $t1, 0xa000                     /* GP0(A0): CPU -> VRAM, (0,0), 320 x 240 */
        sw      $t1, 0x1810($t0)
        sw      $zero, 0x1810($t0)
        lui     $t1, 240
        ori     $t1, $t1, 320
        sw      $t1, 0x1810($t0)
        la      $t2, logo_bits
        addiu   $t3, $t2, DATA_LEN
2:      lbu     $t4, 0($t2)
        ori     $t5, $zero, 4                   /* four words (eight pixels) per byte */
3:      andi    $t6, $t4, 0x80                  /* ink -> 0x0000, paper -> 0x7fff */
        sltiu   $t6, $t6, 1
        sll     $t7, $t6, 15
        subu    $t6, $t7, $t6
        andi    $t7, $t4, 0x40
        sltiu   $t7, $t7, 1
        sll     $t8, $t7, 15
        subu    $t7, $t8, $t7
        sll     $t7, $t7, 16
        or      $t6, $t6, $t7
        sw      $t6, 0x1810($t0)
        sll     $t4, $t4, 2
        addiu   $t5, $t5, -1
        bnez    $t5, 3b
        nop
        addiu   $t2, $t2, 1
        bne     $t2, $t3, 2b
        nop
        lui     $t1, 0x0300                     /* GP1(03): display on */
        sw      $t1, 0x1814($t0)
        ori     $t8, $zero, ROUNDS
4:      ori     $t1, $zero, 0x0100              /* timer 1: clock = h-blank, free running (the write resets the count) */
        sw      $t1, 0x1114($t0)
5:      lhu     $t9, 0x1110($t0)
        nop
        sltiu   $t9, $t9, HBLANKS
        bnez    $t9, 5b
        nop
        addiu   $t8, $t8, -1
        bnez    $t8, 4b
        nop
6:      lw      $t9, 0x1814($t0)
        nop
        srl     $t9, $t9, 28                    /* GPUSTAT bit 28 again (the bit the upload waited for) */
        andi    $t9, $t9, 1
        beqz    $t9, 6b
        nop
        lui     $t1, 0x0200                     /* GP0(02): fill black, (0,0) 1008 x 511 */
        sw      $t1, 0x1810($t0)
        sw      $zero, 0x1810($t0)
        lui     $t1, 0x01ff
        ori     $t1, $t1, 0x03f0
        sw      $t1, 0x1810($t0)
        sw      $zero, 0x1114($t0)              /* timer 1 mode as after reset */
        /* the wipe routine runs from below the stack top (free memory; the game's entry sets its own stack) */
        la      $t2, wipe
        la      $t3, wipe_end
        lui     $t4, 0x801f
        ori     $t4, $t4, 0xf000
        move    $t5, $t4
7:      lw      $t6, 0($t2)
        addiu   $t2, $t2, 4
        sw      $t6, 0($t4)
        bne     $t2, $t3, 7b
        addiu   $t4, $t4, 4
        la      $t2, logo_start
        la      $t3, logo_end
        la      $t7, ENTRY
        jr      $t5
        nop
wipe:   sw      $zero, 0($t2)                   /* position independent */
        addiu   $t2, $t2, 4
        bne     $t2, $t3, wipe
        nop
        jr      $t7
        nop
wipe_end:
        .balign 4
logo_bits:
        .incbin "card.bin"
        .balign 4
logo_end:
