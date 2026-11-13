/* Sprite tile decoders for X-Men vs. Street Fighter (SLUS-00627), speed version (tools/speed/decode.py).
 *   XVM1 (tools/nsp_mid.py)  xvm_dec   rewritten: row above kept in a scratchpad ring, loads scheduled
 *   XVH1 (tools/nsp_huff.py) nsp_dec   as tools/nspdec/nspdec.S
 * Entered by `j dec_entry` over the first instruction of the game's RLE tile decoder 0x8001b5b0(a0=src,
 * a1=dst, a2=nbytes).  Uses only caller-saved registers plus s0/s1 (saved, XVH1 only), no $gp, no calls.
 * Every load-delay slot is respected (R3000).  Scratchpad 0x1f800300-0x1f80037f = XVM1 row buffer
 * (clobbered on every XVM1 call; the game itself uses 0x1f800000-0x1f800207).
 *
 * Code areas (as tools/nsppatch.py, S shortened): S 0x80010440-0x800104c8 (roundpatch.py: 0x800104c8-0x80010508), Z 0x800158f4-0x80015a68,
 * X 0x80015bac-0x80015d9c, Y 0x80015dd4-0x80015f94.
 */
        .set    noreorder
        .set    noat
        .text
        .globl  nsp_dec, xvm_dec, dec_entry, rle, ahcb, cS_end, cZ, cZ_end, cX, cX_end, cY, cY_end, cR, cR_end

#define FRAME 16                /* XVH1: s0, s1, s2 */
#define RBH 0x0280              /* XVH1 row buffer rb[0..259]: scratchpad offset */
#define RB 0x0300               /* XVM1 row buffer: scratchpad offset */

/* ================================================================ chunk S (0x80010440-0x80010508) */
/* XVM1 (format: tools/nsp_mid.py)
 * a0 src   a1 dst   a3 model   a2 model + fallback-record offset   t5 end of output
 * t0 bit buffer (MSB first)   t1 bits available - 16
 * t2 x = &rb[column]   t6 &rb[W]   rb[column] = byte above (ring: written in place as the row is decoded)
 * t3 model + ((P >> 4) << 8)   t4 P = previous output byte   t7 current table */
xvm_dec:                                /* the dispatch has loaded v0 = src[0], t9 = src[3], v1 = src[1] */
        lbu     $t8, 2($a0)             /* first 32 stream bits, big endian */
        sll     $v0, $v0, 24
        sll     $v1, $v1, 16
        sll     $t8, $t8, 8
        or      $v0, $v0, $v1
        or      $t8, $t8, $t9
        or      $t0, $v0, $t8
        lhu     $t9, 8($a3)             /* fallback records */
        srl     $t3, $t0, 28
        addiu   $t3, $t3, 1
        sll     $t3, $t3, 3             /* W bytes */
        sll     $t0, $t0, 4
        addiu   $a0, $a0, 4
        addu    $t5, $a1, $a2           /* end of output */
        addu    $a2, $t9, $a3
        lui     $t2, 0x1f80
        ori     $t2, $t2, RB
        addu    $t6, $t2, $t3           /* &rb[W] */
        addiu   $v0, $zero, -1
        move    $t8, $t2
1:      sw      $v0, 0($t8)             /* row 0: the row above is all 0xff */
        sw      $v0, 4($t8)
        addiu   $t8, $t8, 8
        bne     $t8, $t6, 1b
        nop
        ori     $t1, $zero, 12
        ori     $t4, $zero, 0xff
        b       msym
        addiu   $t3, $a3, 0xf00
mesc:   srl     $v0, $t0, 24            /* escape: 8 raw bits, then the literal path with length 0 */
        sll     $t0, $t0, 8
        addiu   $t1, $t1, -8
        b       mgot + 4
        sll     $v0, $v0, 4
cS_end:
        .org    0x800158f4 - 0x80010440
/* ================================================================ chunk Z (0x800158f4-0x80015a68) */
cZ:
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
        or      $t3, $t3, $v0           /* P in all four bytes (repeat) */
/* one segment = the part of the run inside the current row */
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
/* XVH1 (moved here for space) */
even:   move    $t5, $v0                /* keep the low nibble; never a row or tile end */
        b       sym
        move    $t4, $t8
rowend: move    $t1, $s2
        ori     $t3, $zero, 0xf00
        b       next
        ori     $t4, $zero, 15
cZ_end:
        .org    0x80015bac - 0x80010440
/* ================================================================ chunk X (0x80015bac-0x80015d9c) */
cX:
/* XVH1 (format: tools/nsp_huff.py), unchanged from tools/nspdec/nspdec.S
 * a0 src, a1 dst, a2 nbytes (>0), a3 model (sec2 start)
 * t0 bit buffer (left aligned, sentinel bit below the data)   t1 &rb[x]   t2 &rb[W]
 * t3 L<<8   t4 UL   t5 pending low nibble   t6 map2   t7 tabofs
 * rb[x] = pixel above x (the previous row, overwritten as the row is decoded); rb[W] = 15 */
nsp_dec:
        addiu   $sp, $sp, -FRAME
        sw      $s0, 0($sp)
        sw      $s1, 4($sp)
        sw      $s2, 8($sp)
        lui     $s2, 0x1f80
        ori     $s2, $s2, RBH           /* s2 = rb (scratchpad) */
        lbu     $t0, 0($a0)             /* first byte: width code in the high nibble */
        addiu   $a0, $a0, 1
        addu    $a2, $a1, $a2           /* a2 = end of output */
        srl     $t2, $t0, 4
        addiu   $t2, $t2, 1
        sll     $t2, $t2, 4             /* W pixels */
        sll     $t0, $t0, 28
        lui     $v0, 0x0800
        or      $t0, $t0, $v0           /* 4 data bits + sentinel */
        lui     $v0, 0x0f0f
        ori     $v0, $v0, 0x0f0f
        addu    $t2, $s2, $t2           /* &rb[W] */
        move    $t1, $s2
1:      sw      $v0, 0($t1)             /* rb[0..W+3] = 15 */
        sltu    $v1, $t1, $t2
        bnez    $v1, 1b
        addiu   $t1, $t1, 4
        lhu     $t6, 8($a3)
        lhu     $t7, 10($a3)
        move    $t1, $s2
        addu    $t6, $a3, $t6
        addu    $t7, $a3, $t7
        ori     $t3, $zero, 0xf00
        ori     $t4, $zero, 15

sym:    lbu     $t8, 0($t1)             /* U */
        lbu     $t9, 1($t1)             /* UR */
        sll     $v0, $t8, 4
        or      $v0, $v0, $t3
        or      $v0, $v0, $t4
        addu    $v0, $v0, $a3
        lbu     $v0, 12($v0)            /* class = map1[L<<8 | U<<4 | UL] */
        move    $v1, $zero              /* d = 0 */
        sll     $v0, $v0, 4
        or      $v0, $v0, $t9
        addu    $v0, $v0, $t6
        lbu     $v0, 0($v0)             /* table = map2[class<<4 | UR] */
        nop
        sll     $v0, $v0, 1
        addu    $v0, $v0, $t7
        lhu     $v0, 0($v0)             /* record offset */
        nop
        addu    $s0, $a3, $v0           /* s0 -> cnt[len] */
        addiu   $s1, $s0, 12            /* s1 -> symbols of the current length */

bit:    sll     $t9, $t0, 1
        beqz    $t9, refill             /* only the sentinel left */
        srl     $v0, $t0, 31            /* next bit */
gotbit: lbu     $at, 0($s0)             /* number of codes of this length */
        sll     $v1, $v1, 1
        addu    $v1, $v1, $v0           /* d = d*2 + bit */
        sltu    $v0, $v1, $at
        bnez    $v0, found
        move    $t0, $t9
        subu    $v1, $v1, $at
        addiu   $s0, $s0, 1
        b       bit
        addu    $s1, $s1, $at

refill: lbu     $t0, 0($a0)
        lui     $v0, 0x0080
        addiu   $a0, $a0, 1
        sll     $t0, $t0, 24
        or      $t0, $t0, $v0
        sll     $t9, $t0, 1
        b       gotbit
        srl     $v0, $t0, 31

found:  addu    $v0, $s1, $v1
        lbu     $v0, 0($v0)             /* symbol */
        andi    $v1, $t1, 1             /* x odd?  (rb is at an even address) */
        sltiu   $t9, $v0, 16
        beqz    $t9, isrun
        sll     $t3, $v0, 8             /* L = p<<8 (recomputed after a run) */
        sb      $v0, 0($t1)             /* literal pixel: rb[x] = p */
        beqz    $v1, even
        addiu   $t1, $t1, 1
        sll     $v0, $v0, 4
        or      $v0, $v0, $t5
        sb      $v0, 0($a1)             /* byte = low | p<<4 */
        addiu   $a1, $a1, 1
        beq     $t1, $t2, rowend
        move    $t4, $t8                /* UL = U */
next:   sltu    $v0, $a1, $a2
        bnez    $v0, sym
        nop
        lw      $s0, 0($sp)
        lw      $s1, 4($sp)
        lw      $s2, 8($sp)
        jr      $ra
        addiu   $sp, $sp, FRAME

/* XVM1: codes longer than 6 bits - canonical walk over the table's fallback record
 * (per length 7..12: u16 limit left-justified to 12 bits, s16 entry-list adjust; one lw reads both;
 * lengths 7 and 8 loaded back to back) */
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
cX_end:
        .org    0x80015dd4 - 0x80010440
/* ================================================================ chunk Y (0x80015dd4-0x80015f94) */
cY:
/* XVH1: copy `run` pixels from the row above (rb is left unchanged).  v0 = symbol, v1 = x&1 */
isrun:  sltiu   $at, $v0, 32            /* run length in pixels from the symbol (no table) */
        bnez    $at, 3f
        addiu   $t9, $v0, -15           /* symbols 16..31: 1..16 */
        addiu   $v0, $v0, -32           /* j = 0..13: 24, 32, 48, 64, 96, ... 1024, 2048, 4096 */
        sltiu   $t8, $v0, 12
        beqz    $t8, 2f
        srl     $t8, $v0, 1
        andi    $t9, $v0, 1
        addiu   $t9, $t9, 3
        addiu   $t8, $t8, 3
        b       3f
        sllv    $t9, $t9, $t8           /* (3 or 4) << (3 + j / 2) */
2:      ori     $t9, $zero, 1
        addiu   $t8, $v0, -1
        sllv    $t9, $t9, $t8           /* j = 12, 13: 1 << (j - 1) */
3:      beqz    $v1, 4f
        nop
        lbu     $v0, 0($t1)             /* x odd: complete the pending byte */
        addiu   $t1, $t1, 1
        addiu   $t9, $t9, -1
        sll     $v0, $v0, 4
        or      $v0, $v0, $t5
        sb      $v0, 0($a1)
        bne     $t1, $t2, 4f
        addiu   $a1, $a1, 1
        move    $t1, $s2
4:      sltiu   $v0, $t9, 2
        bnez    $v0, 6f
        nop
5:      lbu     $v0, 0($t1)             /* whole bytes (x even) */
        lbu     $v1, 1($t1)
        addiu   $t1, $t1, 2
        addiu   $t9, $t9, -2
        sll     $v1, $v1, 4
        or      $v0, $v0, $v1
        sb      $v0, 0($a1)
        bne     $t1, $t2, 55f
        addiu   $a1, $a1, 1
        move    $t1, $s2
55:     sltiu   $v0, $t9, 2
        beqz    $v0, 5b
        nop
6:      beqz    $t9, 7f
        nop
        lbu     $t5, 0($t1)             /* one pixel left: x even, cannot wrap */
        addiu   $t1, $t1, 1
7:      beq     $t1, $s2, 8f            /* context for the next symbol */
        ori     $t4, $zero, 15          /* row start: L = UL = 15 */
        lbu     $t4, -1($t1)            /* else L = UL = rb[x-1] */
        nop
8:      j       next
        sll     $t3, $t4, 8

/* XVM1 run, repeat segment: P to rb and dst */
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
/* RLE literal: L = t9 + 1 raw bytes, copied in whole (unaligned) words while the over-write stays
 * inside the tile (later ops overwrite the extra bytes) */
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

/* RLE literal close to the end of the tile: byte by byte, exactly what the original writes - it copies
 * the bytes in pairs, so an odd-length literal also copies the next stream byte (L rounded up to even) */
rlitb:  andi    $t6, $t9, 1
        addu    $t6, $t6, $t8
1:      lbu     $v1, 0($a0)
        addiu   $a0, $a0, 1
        addiu   $a1, $a1, 1
        bne     $a1, $t6, 1b
        sb      $v1, -1($a1)
        b       rlitd
        nop
rlitd:  lbu     $v0, 0($t0)
        move    $a1, $t8
        b       rnext
        addiu   $a0, $t0, 1
cY_end:
        .org    0x8001b5b0 - 0x80010440
/* ================================================================ chunk R (0x8001b5b0-0x8001b710): the game's RLE decoder */
cR:
/* dispatch: is a0 inside the sec2 of a loaded XVH1/XVM1 file?  (file ids 0..0x12 and set 0x26; the
 * section pointer table 0x8005c830 is written by the NSP loader 0x80053f78).  Among matches the highest
 * sec2 start wins (guards against a stale pointer whose header is still intact).  Same rule as 1.0.1. */
dec_entry:
        j       0f                      /* a jump first, as on 1.0.1, for harnesses that hook this entry */
        lui     $t1, 0x8006             /* (they run `j target; nop`: redone below) */
0:      blez    $a2, dret
        lui     $t1, 0x8006
        addiu   $t1, $t1, -0x37d0 + 0x27*4      /* round 1: entry 0x26 */
        addiu   $t2, $t1, -4
        lui     $t4, 0x3148
        ori     $t4, $t4, 0x5658        /* 'XVH1' */
        lui     $t6, 0x0005             /* 'XVH1' ^ 'XVM1' */
        move    $a3, $zero
1:      lw      $v0, -4($t1)
        addiu   $t1, $t1, -4
        beqz    $v0, 2f
        sltu    $v1, $a0, $v0           /* src below this sec2? */
        bnez    $v1, 2f
        sltu    $v1, $v0, $a3           /* below the best match so far? */
        bnez    $v1, 2f
        nop
        lw      $v1, 0($v0)             /* magic */
        lw      $t3, 4($v0)             /* sec2 size */
        xor     $v1, $v1, $t4
        beqz    $v1, 4f
        addu    $t3, $v0, $t3
        bne     $v1, $t6, 2f
4:      sltu    $v1, $a0, $t3
        beqz    $v1, 2f
        nop
        move    $a3, $v0
2:      bne     $t1, $t2, 1b
        lui     $v1, 0x8006
        addiu   $v1, $v1, -0x37d0       /* &entry 0 */
        beq     $t2, $v1, 3f
        addiu   $t1, $v1, 0x13*4        /* round 2: entries 0x12..0 */
        b       1b
        move    $t2, $v1
3:      beqz    $a3, rle
        lw      $v1, 0($a3)             /* a3 = model: which codec?  (a3 = 0: reads RAM 0, harmless) */
        lbu     $v0, 0($a0)             /* xvm_dec's first loads (harmless for XVH1) */
        beq     $v1, $t4, nsp_dec
        lbu     $t9, 3($a0)
        b       xvm_dec
        lbu     $v1, 1($a0)
/* the game's byte RLE (format: tools/nsp.py rle_decode): control byte c; c >= 0x10: (c>>4)+1 bytes of
 * (c&15)*0x11; else (c&15)+1 raw bytes.  Every byte the original writes is written with the same value
 * (including the run overrun past n); literal over-writes stay inside [dst, dst+n) and are overwritten. */
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

/* idle-hook callback (the frame worker's EBV+12 points here; a0 = hblank deadline, a1 = vblanks passed): the
 * decode-ahead predictor is read with the directory sector each battle (tools/speed/decode/ahead_sector.py, at
 * 0x801fe804); run it only when its magic is there (boss / stock path / failed read / outside battle: no-op). */
ahcb:   lui     $t0, 0x8020
        lw      $t1, -0x17fc($t0)       /* 0x801fe804 */
        lui     $t2, 0x5041
        bne     $t1, $t2, dret
        addiu   $t0, $t0, -0x17e8       /* 0x801fe818 = ah_entry */
        jr      $t0
        nop
cR_end:
        .org    0x8001b710 - 0x80010440
