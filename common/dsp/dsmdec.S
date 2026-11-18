/* DSP tile decoders for MSHvSF (SLUS-00793) and MvC (SLUS-01059): DSM1 (common/dsp/dsm.py) + the game's byte RLE.
 * With -DDSH=addr (MSHvSF; MvC optional): a tile inside a 'DSH1' section (common/dsp/dsh.py) jumps to the DSH1 decoder at addr
 * (common/dsp/dshdec.S, copied there by the battle loader) with a0-a2 unchanged and a3 = the section.
 * With -DDSHPTR=addr [-DDSAPTR=addr] (MvC): the same routes for 'DSH1' (and 'DSA1', common/dsp/dsa.py + dsadec.S),
 * but the decoder address is read from the RAM word at DSHPTR / DSAPTR (the loader places the decoders per battle).
 * Port of the XvSF 1.1 speed decoders (tools/speed/decode/nspdec.S: XVM1 = DSM1 except the width byte, RLE).
 * Replaces the game's RLE tile decoder (MSHvSF 0x8001bd68, MvC 0x8001bd48; a0 = src, a1 = dst, a2 = nbytes):
 * unit .u_entry is linked AT that address (dispatch + RLE runs fit the original 352 bytes), the other units go
 * to the free ranges given by the per-game linker script (common/dsp/dsmpatch.py).  Units never fall through
 * into each other; conditional branches between units need them within +-128 KB.
 * Uses only caller-saved registers, no stack, no $gp.  Every load-delay slot is respected (R3000).
 * Scratchpad 0x1f800300-0x1f8003ff: DSM1 row ring (clobbered per call; the games use 0x000-0x0ff in battle).
 * TAB = the game's per-slot pixel-section pointer table (MSHvSF 0x80087d40, MvC 0x80092b30), NSLOT entries. */
        .set    noreorder
        .set    noat
        .globl  dec_entry, dsm_dec, rle, dret

#define RB 0x0300
#ifndef NSLOT
#define NSLOT 16
#endif

/* ================================================================ dispatch: is a0 inside a loaded DSM1 part? */
        .section .u_entry, "ax"
dec_entry:
        blez    $a2, dret
        lui     $t1, %hi(TAB)
        addiu   $t1, $t1, %lo(TAB)
        addiu   $t2, $t1, NSLOT*4
        lui     $t4, 0x314d
        ori     $t4, $t4, 0x5344        /* 'DSM1' */
#if defined(DSH) || defined(DSHPTR)
#define ROUTES
        lui     $t6, 0x0005             /* 'DSH1' ^ 'DSM1' */
#endif
#ifdef DSAPTR
        lui     $t5, 0x000c             /* 'DSA1' ^ 'DSM1' */
#endif
        move    $a3, $zero
1:      lw      $v0, 0($t1)
        addiu   $t1, $t1, 4
        bgez    $v0, 2f                 /* not a KSEG0 pointer (stream position, 0) */
        sltu    $v1, $a0, $v0           /* src below this section? */
        bnez    $v1, 2f
        sltu    $v1, $v0, $a3           /* below the best match so far? */
        bnez    $v1, 2f
        nop
        lw      $v1, 0($v0)             /* magic */
        lw      $t3, 4($v0)             /* size of the DSM1 / DSH1 part */
#ifdef ROUTES
        xor     $v1, $v1, $t4
        beqz    $v1, 4f                 /* 'DSM1' */
        addu    $t3, $v0, $t3
#ifdef DSAPTR
        beq     $v1, $t6, 4f            /* 'DSH1' */
        nop
        bne     $v1, $t5, 2f            /* not 'DSA1' either */
#else
        bne     $v1, $t6, 2f            /* not 'DSH1' either */
#endif
        nop
4:
#else
        bne     $v1, $t4, 2f
        addu    $t3, $v0, $t3
#endif
        sltu    $v1, $a0, $t3
        beqz    $v1, 2f
        nop
        move    $a3, $v0
2:      bne     $t1, $t2, 1b
        nop
#if defined(DSH)
        beqz    $a3, rle
        nop
        lw      $v1, 0($a3)             /* which codec? */
        nop
        beq     $v1, $t4, dsm_dec
        nop
        j       DSH                     /* DSH1 (common/dsp/dshdec.S, loaded at DSH by the battle loader) */
        nop
#elif defined(DSHPTR)
        beqz    $a3, rle
        nop
        lw      $v1, 0($a3)             /* which codec? */
        lui     $t9, %hi(DSHPTR)
        xor     $v1, $v1, $t4
        beqz    $v1, dsm_dec
#ifdef DSAPTR
        lui     $t8, %hi(DSAPTR)        /* (dsm_dec writes t8 before reading it) */
        bne     $v1, $t6, 5f            /* not DSH1: DSA1 */
#else
        nop
#endif
        lw      $t9, %lo(DSHPTR)($t9)   /* DSH1 decoder address (word owned by the battle loader) */
        nop
        jr      $t9
        nop
#ifdef DSAPTR
5:      lw      $t8, %lo(DSAPTR)($t8)   /* DSA1 decoder address */
        nop
        jr      $t8
        nop
#endif
#else
        bnez    $a3, dsm_dec
        nop
#endif
/* the game's byte RLE: control byte c; c >= 0x10: (c>>4)+1 bytes of (c&15)*0x11; else (c&15)+1 raw bytes.
 * Every byte the original writes is written with the same value (incl. the run overrun past n). */
rle:    addu    $t5, $a1, $a2           /* end */
        lui     $t7, %hi(sb0)
        addiu   $t7, $t7, %lo(sb0)
        lbu     $v0, 0($a0)
        addiu   $a0, $a0, 1
rl:     andi    $v1, $v0, 0xf0
        beqz    $v1, rlit
        andi    $t9, $v0, 15
        lbu     $v0, 0($a0)             /* next control byte */
        srl     $t0, $v1, 4             /* h: the run is h+1 bytes */
        srl     $v1, $v1, 2
        subu    $t8, $t7, $v1
        sll     $v1, $t9, 4
        or      $t9, $t9, $v1           /* (c & 15) * 0x11 */
        jr      $t8
        addiu   $a0, $a0, 1
        sb      $t9, 15($a1)
        sb      $t9, 14($a1)
        sb      $t9, 13($a1)
        sb      $t9, 12($a1)
        sb      $t9, 11($a1)
        sb      $t9, 10($a1)
        sb      $t9, 9($a1)
        sb      $t9, 8($a1)
        sb      $t9, 7($a1)
        sb      $t9, 6($a1)
        sb      $t9, 5($a1)
        sb      $t9, 4($a1)
        sb      $t9, 3($a1)
        sb      $t9, 2($a1)
        sb      $t9, 1($a1)
sb0:    sb      $t9, 0($a1)
        addiu   $a1, $a1, 1
        addu    $a1, $a1, $t0
rnext:  sltu    $at, $a1, $t5
        bnez    $at, rl
        nop
dret:   jr      $ra
        nop
        .section .u_rlit, "ax"
/* RLE literal */
/* L = t9 + 1 raw bytes, copied in whole (unaligned) words while the over-write stays inside the tile */
rlit:   addiu   $t9, $t9, 1             /* L */
        addu    $t8, $a1, $t9           /* end of the literal in dst */
        addu    $t0, $a0, $t9           /* next control byte */
        addiu   $at, $t8, 3
        sltu    $at, $t5, $at
        bnez    $at, rlitb
1:      lwl     $v1, 3($a0)             /* (also the delay slot: harmless on the way to rlitb) */
        lwr     $v1, 0($a0)
        addiu   $a0, $a0, 4
        addiu   $a1, $a1, 4
        sltu    $at, $a1, $t8
        swl     $v1, -1($a1)
        bnez    $at, 1b
        swr     $v1, -4($a1)
        b       rlitd
        nop
/* close to the end of the tile: byte by byte, exactly what the original writes - it copies the bytes in
 * pairs, so an odd-length literal also copies the next stream byte (L rounded up to even) */
rlitb:  andi    $t6, $t9, 1
        addu    $t6, $t6, $t8
1:      lbu     $v1, 0($a0)
        addiu   $a0, $a0, 1
        addiu   $a1, $a1, 1
        bne     $a1, $t6, 1b
        sb      $v1, -1($a1)
rlitd:  lbu     $v0, 0($t0)
        move    $a1, $t8
        b       rnext
        addiu   $a0, $t0, 1

/* ================================================================ DSM1 set-up
 * a0 src   a1 dst   a3 model   a2 model + fallback-record offset   t5 end of output
 * t0 bit buffer (MSB first)   t1 bits available - 16
 * t2 x = &rb[column]   t6 &rb[W]   rb[column] = byte above (ring: written in place as the row is decoded)
 * t3 model + ((P >> 4) << 8)   t4 P = previous output byte   t7 current table */
        .section .u_setup, "ax"
dsm_dec:
        lbu     $t3, 0($a0)             /* W bytes */
        lbu     $v0, 1($a0)             /* first 32 stream bits, big endian */
        lbu     $v1, 2($a0)
        lbu     $t8, 3($a0)
        lbu     $t9, 4($a0)
        sll     $v0, $v0, 24
        sll     $v1, $v1, 16
        sll     $t8, $t8, 8
        or      $v0, $v0, $v1
        or      $t8, $t8, $t9
        lhu     $t9, 8($a3)             /* fallback records */
        or      $t0, $v0, $t8
        addiu   $a0, $a0, 5
        addu    $t5, $a1, $a2           /* end of output */
        addu    $a2, $t9, $a3
        lui     $t2, 0x1f80
        ori     $t2, $t2, RB
        addu    $t6, $t2, $t3           /* &rb[W] */
        addiu   $v0, $zero, -1
        move    $t8, $t2
1:      sw      $v0, 0($t8)             /* row 0: the row above is all 0xff */
        addiu   $t8, $t8, 4
        sltu    $at, $t8, $t6
        bnez    $at, 1b
        nop
        ori     $t1, $zero, 16
        ori     $t4, $zero, 0xff
        b       msym
        addiu   $t3, $a3, 0xf00
mesc:   srl     $v0, $t0, 24            /* escape: 8 raw bits, then the literal path with length 0 */
        sll     $t0, $t0, 8
        addiu   $t1, $t1, -8
        b       mgot + 4
        sll     $v0, $v0, 4

/* ================================================================ DSM1 main loop */
        .section .u_loop, "ax"
msym:   lbu     $v0, 0($t2)             /* U = byte above (scratchpad) */
msym1:  srl     $t8, $t0, 25
        addu    $v0, $v0, $t3
        lbu     $t7, 76($v0)            /* table = map[(P>>4)<<8 | U] */
        andi    $t8, $t8, 0x7e          /* next 6 bits * 2 */
        addu    $t8, $t8, $a3
        addiu   $a1, $a1, 1
        sll     $v0, $t7, 7
        addu    $v0, $v0, $t8
        lh      $v0, 4172($v0)          /* LUT entry */
        addiu   $t2, $t2, 1
mgot:   bltz    $v0, mspecial
        andi    $v1, $v0, 15            /* code length */
        srl     $t4, $v0, 4             /* literal byte */
        sllv    $t0, $t0, $v1
        subu    $t1, $t1, $v1
        andi    $t3, $v0, 0xf00
        sb      $t4, -1($a1)
        sb      $t4, -1($t2)
        bltz    $t1, mrefill
        addu    $t3, $t3, $a3
mchk:   bne     $t2, $t6, msym1
        lbu     $v0, 0($t2)
mrow:   lui     $t2, 0x1f80             /* end of a row */
        bne     $a1, $t5, msym
        ori     $t2, $t2, RB
        jr      $ra
        nop
mrefill:
        lbu     $v0, 0($a0)             /* 16 more bits */
        lbu     $v1, 1($a0)
        subu    $t9, $zero, $t1
        sll     $v0, $v0, 8
        or      $v0, $v0, $v1
        sllv    $v0, $v0, $t9
        or      $t0, $t0, $v0
        addiu   $a0, $a0, 2
        bne     $t2, $t6, msym
        addiu   $t1, $t1, 16
        b       mrow
        nop
mspecial:
        sll     $t9, $v0, 17
        bltz    $t9, mlong              /* bit 14: code longer than 6 bits */
        sll     $t9, $v0, 19
        sllv    $t0, $t0, $v1
        bltz    $t9, mesc               /* bit 12: escape */
        subu    $t1, $t1, $v1
        srl     $t8, $v0, 3
        andi    $t8, $t8, 0x3e
        addu    $t8, $t8, $a3
        lhu     $t8, 12($t8)            /* run length */
        addiu   $a1, $a1, -1            /* undo the literal pre-increments */
        addiu   $t2, $t2, -1
        andi    $at, $v0, 0x2000        /* at: 0 copy from the row above, else repeat P */
        sll     $t3, $t4, 8
        or      $t3, $t3, $t4
        sll     $v0, $t3, 16
        b       mseg
        or      $t3, $t3, $v0           /* P in all four bytes (repeat) */

/* ================================================================ DSM1 runs: one segment = the part of the run in this row */
        .section .u_run, "ax"
mseg:   subu    $v1, $t6, $t2           /* room left in this row */
        sltu    $v0, $t8, $v1
        beqz    $v0, 1f
        subu    $t9, $t8, $v1           /* left for the next row */
        move    $v1, $t8
        move    $t9, $zero
1:      addu    $t7, $t2, $v1           /* end of this segment in rb */
        srl     $v0, $v1, 2
        sll     $v0, $v0, 2
        bnez    $at, mfill
        addu    $v0, $t2, $v0           /* end of the whole words */
        beq     $t2, $v0, 3f
        nop
2:      lwl     $t8, 3($t2)             /* copy from the row above: rb -> dst, rb unchanged */
        lwr     $t8, 0($t2)
        addiu   $t2, $t2, 4
        swl     $t8, 3($a1)
        swr     $t8, 0($a1)
        bne     $t2, $v0, 2b
        addiu   $a1, $a1, 4
3:      beq     $t2, $t7, 5f
        nop
4:      lbu     $t8, 0($t2)
        addiu   $t2, $t2, 1
        sb      $t8, 0($a1)
        bne     $t2, $t7, 4b
        addiu   $a1, $a1, 1
5:      b       mwrap
        lbu     $t4, -1($t2)            /* P = last byte copied */

        .section .u_fill, "ax"
/* repeat segment: P to rb and dst */
mfill:  beq     $t2, $v0, 3f
        nop
2:      swl     $t3, 3($t2)
        swr     $t3, 0($t2)
        addiu   $t2, $t2, 4
        swl     $t3, 3($a1)
        swr     $t3, 0($a1)
        bne     $t2, $v0, 2b
        addiu   $a1, $a1, 4
3:      beq     $t2, $t7, mwrap
        nop
4:      sb      $t4, 0($t2)
        addiu   $t2, $t2, 1
        sb      $t4, 0($a1)
        bne     $t2, $t7, 4b
        addiu   $a1, $a1, 1
mwrap:  bne     $t2, $t6, 6f            /* end of the segment: row end? */
        move    $t8, $t9
        lui     $t2, 0x1f80
        beq     $a1, $t5, dret          /* (a run never passes the tile end) */
        ori     $t2, $t2, RB
6:      bnez    $t8, mseg
        nop
        andi    $t3, $t4, 0xf0          /* context from P */
        sll     $t3, $t3, 4
        bltz    $t1, mrefill
        addu    $t3, $t3, $a3
        b       msym
        nop

/* ================================================================ DSM1 codes longer than 6 bits: canonical walk over
 * the table's fallback record (per length 7..12: u16 limit left-justified to 12 bits, s16 entry-list adjust) */
        .section .u_long, "ax"
mlong:  sll     $t9, $t7, 5
        addu    $t9, $t9, $a2
        lw      $v0, 0($t9)             /* length 7: lim | adj << 16 */
        lw      $v1, 4($t9)             /* length 8 */
        srl     $t8, $t0, 20            /* next 12 bits */
        andi    $at, $v0, 0xffff
        sltu    $at, $t8, $at
        bnez    $at, mlf
        ori     $t7, $zero, 5           /* t7 = 12 - length */
        andi    $at, $v1, 0xffff
        sltu    $at, $t8, $at
        move    $v0, $v1
        bnez    $at, mlf
        ori     $t7, $zero, 4
1:      lw      $v0, 8($t9)             /* lengths 9..12 */
        addiu   $t9, $t9, 4
        andi    $at, $v0, 0xffff
        sltu    $at, $t8, $at
        beqz    $at, 1b
        addiu   $t7, $t7, -1
mlf:    sra     $v0, $v0, 16
        srlv    $t8, $t8, $t7
        sll     $t8, $t8, 1
        addu    $v0, $v0, $t8
        addu    $v0, $v0, $a3
        lh      $v0, 0($v0)             /* entry (its length field is the full code length) */
        b       mgot
        nop
