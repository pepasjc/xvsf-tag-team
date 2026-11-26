/* Second boot card (fan-patch notice) - tools/card2patch.py.
 *
 * Entered from the first card's wipe routine (tools/logo/logo.S, its `la $t7, ENTRY` is pointed here): the GPU is
 * set up (320x240 NTSC 15-bit, display on, start (0,0)), the VRAM fill to black has been issued, timer 1 mode is 0.
 * Bare metal like the first card: no BIOS call, no stack, interrupt state untouched, only t0-t9 used, so the game's
 * entry code still gets every other register as the BIOS passed it.
 *
 *   1. once the GPU is idle (the first card's fill of the whole VRAM takes a while; a transfer queued behind it
 *      loses words), the picture (IMG_AT, 15-bit, 320 x 240) -> VRAM (0,256) by CPU writes to GP0 while the screen shows the
 *      black (0,0) buffer, then display start (0,256): no tearing.
 *   2. hold HOLD_FRAMES frames of LINES h-blanks on timer 1 (clock = h-blank; the mode write resets the count; the
 *      pad is read right after it, inside the frame).
 *      From frame SKIP_AFTER on, pad 1 is read once per frame through the SIO port (01 42 00 00 00, no ACK
 *      interrupt): START (byte 3 bit 3) or X (byte 4 bit 6), active low, ends the hold.  No pad / no answer reads
 *      as 0xff (nothing pressed); every wait has a bound.  Before each byte JOY_DATA is read once: mednafen-based
 *      emulators (Beetle) only receive after a data read (checked: Beetle and SwanStation both see 41 5a + buttons).
 *   3. VRAM black, display start (0,0), timer 1 mode 0, pad port deselected (JOY_CTRL 0).
 *   4. the wipe routine is copied below the stack top and zeroes IMG_AT..card2_end (the executable's zero area
 *      is all zeros again), then jumps to ENTRY.
 * ENTRY, IMG_AT, IMG_WORDS, HOLD_FRAMES, SKIP_AFTER, LINES come from the builder (-D).
 */
        .set noreorder
        .set noat
        .section .card2, "ax"
        .globl card2_start
card2_start:
        lui     $t0, 0x1f80
        lui     $t1, 0x1400
1:      lw      $t9, 0x1814($t0)                /* GPUSTAT bits 26 + 28: idle and ready - the first card's fill of */
        nop                                     /* the whole VRAM is done (the transfer must not start behind it) */
        and     $t9, $t9, $t1
        bne     $t9, $t1, 1b
        nop
        lui     $t1, 0xa000                     /* GP0(A0): CPU -> VRAM, (0,256), 320 x 240 */
        sw      $t1, 0x1810($t0)
        lui     $t1, 256
        sw      $t1, 0x1810($t0)
        lui     $t1, 240
        ori     $t1, $t1, 320
        sw      $t1, 0x1810($t0)
        li      $t2, IMG_AT
        li      $t3, IMG_AT + IMG_WORDS * 4
2:      lw      $t4, 0($t2)                     /* one word = two pixels; the loop is about as slow per word */
        addiu   $t2, $t2, 4                     /* as the first card's (a CPU store cannot outrun the transfer) */
        nop
        nop
        nop
        nop
        sw      $t4, 0x1810($t0)
        bne     $t2, $t3, 2b
        nop
3:      lw      $t9, 0x1814($t0)                /* the transfer is through: ready for a command */
        nop
        srl     $t9, $t9, 28
        andi    $t9, $t9, 1
        beqz    $t9, 3b
        nop
        lui     $t1, 0x0504                     /* GP1(05): display start (0,256) */
        sw      $t1, 0x1814($t0)

        move    $t8, $zero                      /* frames shown */
4:      ori     $t1, $zero, 0x0100              /* timer 1: clock = h-blank (the write resets the count); the pad */
        sw      $t1, 0x1114($t0)                /* is read inside the frame, then the rest of the frame is waited */
        addiu   $t8, $t8, 1
        sltiu   $t9, $t8, SKIP_AFTER
        bnez    $t9, 9f
        nop
        /* pad 1: 01 42 00 00 00; t5 = byte index, t6 = byte 3, t7 = byte 4 */
        ori     $t1, $zero, 0x000d              /* JOY_MODE: baud factor 1, 8 bits */
        sh      $t1, 0x1048($t0)
        ori     $t1, $zero, 0x0088              /* JOY_BAUD: 250 kHz */
        sh      $t1, 0x104e($t0)
        ori     $t1, $zero, 0x0013              /* JOY_CTRL: TX enable, /JOY1 low, acknowledge */
        sh      $t1, 0x104a($t0)
        ori     $t9, $zero, 0x0400              /* select -> first byte */
6:      addiu   $t9, $t9, -1
        bnez    $t9, 6b
        nop
        ori     $t6, $zero, 0xff
        ori     $t7, $zero, 0xff
        move    $t5, $zero
7:      ori     $t4, $zero, 16
70:     lhu     $t9, 0x1044($t0)                /* drain the receive FIFO (at most 16 bytes) */
        addiu   $t4, $t4, -1
        andi    $t9, $t9, 2
        beqz    $t9, 71f
        nop
        lbu     $t9, 0x1040($t0)
        bnez    $t4, 70b
        nop
71:     lbu     $t9, 0x1040($t0)                /* one read more: Beetle (mednafen) receives only after a data read */
        ori     $t1, $zero, 0x01                /* byte to send: 01, 42, 00, 00, 00 */
        beqz    $t5, 72f
        nop
        ori     $t1, $zero, 0x42
        ori     $t9, $zero, 1
        beq     $t5, $t9, 72f
        nop
        move    $t1, $zero
72:     ori     $t9, $zero, 0x0400              /* TX ready (JOY_STAT bit 0), bounded */
73:     lhu     $t4, 0x1044($t0)
        addiu   $t9, $t9, -1
        andi    $t4, $t4, 1
        bnez    $t4, 74f
        nop
        bnez    $t9, 73b
        nop
74:     sw      $t1, 0x1040($t0)
        ori     $t9, $zero, 0x1000              /* answer byte (JOY_STAT bit 1), bounded; none = 0xff */
        ori     $t3, $zero, 0xff
75:     lhu     $t4, 0x1044($t0)
        addiu   $t9, $t9, -1
        andi    $t4, $t4, 2
        bnez    $t4, 76f
        nop
        bnez    $t9, 75b
        nop
        b       77f
        nop
76:     lbu     $t3, 0x1040($t0)
77:
        ori     $t9, $zero, 3
        bne     $t5, $t9, 78f
        nop
        move    $t6, $t3
78:     ori     $t9, $zero, 4
        bne     $t5, $t9, 79f
        nop
        move    $t7, $t3
79:     ori     $t9, $zero, 0x0400              /* the pad's acknowledge comes after the byte: wait it out */
791:    addiu   $t9, $t9, -1
        bnez    $t9, 791b
        nop
        addiu   $t5, $t5, 1
        sltiu   $t9, $t5, 5
        bnez    $t9, 7b
        nop
        sh      $zero, 0x104a($t0)              /* deselect */
        andi    $t6, $t6, 0x08                  /* START pressed (0) */
        beqz    $t6, 10f
        nop
        andi    $t7, $t7, 0x40                  /* X pressed (0) */
        beqz    $t7, 10f
        nop
9:      lhu     $t9, 0x1110($t0)
        nop
        sltiu   $t9, $t9, LINES
        bnez    $t9, 9b
        nop
        sltiu   $t9, $t8, HOLD_FRAMES
        bnez    $t9, 4b
        nop

10:     lui     $t1, 0x1400
101:    lw      $t9, 0x1814($t0)                /* idle and ready */
        nop
        and     $t9, $t9, $t1
        bne     $t9, $t1, 101b
        nop
        lui     $t1, 0x0200                     /* GP0(02): fill black, (0,0) 1008 x 511 */
        sw      $t1, 0x1810($t0)
        sw      $zero, 0x1810($t0)
        lui     $t1, 0x01ff
        ori     $t1, $t1, 0x03f0
        sw      $t1, 0x1810($t0)
        lui     $t1, 0x0500                     /* GP1(05): display start (0,0) */
        sw      $t1, 0x1814($t0)
        sw      $zero, 0x1114($t0)              /* timer 1 mode as after reset */
        sh      $zero, 0x104a($t0)              /* pad port: nothing selected */
        /* the wipe routine runs from below the stack top (the first card's copy there is done with) */
        la      $t2, wipe
        la      $t3, wipe_end
        lui     $t4, 0x801f
        ori     $t4, $t4, 0xf000
        move    $t5, $t4
11:     lw      $t6, 0($t2)
        addiu   $t2, $t2, 4
        sw      $t6, 0($t4)
        bne     $t2, $t3, 11b
        addiu   $t4, $t4, 4
        li      $t2, IMG_AT
        la      $t3, card2_end
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
card2_end:
