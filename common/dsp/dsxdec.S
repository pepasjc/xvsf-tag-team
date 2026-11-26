/* DSH1 tile decoder, LUT variant (model records with a 4-bit lookup table: common/dsp/dsx.py).
 * Based on dshdec.S: for MSHvSF (SLUS-00793) and, with -DMVC, MvC (SLUS-01059; only the tile-width header code
 * differs: W/4 - 1 instead of W/16 - 1, MvC tiles have any even byte width).  Format: common/dsp/dsh.py.  Port of the XvSF XVH1 decoder
 * (tools/nspdec/nspdec.S, tools/speed/decode/nspdec.S) without stack or saved registers.
 * Linked at DSH (MSHvSF 0x801fe200, MvC default 0x801fd800) and copied there by the battle loader; entered from the dispatch at the game's tile
 * decoder entry 0x8001bd68 (common/dsp/dsmdec.S) with
 *     a0 = src (tile stream)   a1 = dst   a2 = nbytes (> 0)   a3 = DSH1 pixel section (model)
 * Writes nbytes + e bytes (e from the tile header = what the stock RLE decoder writes past nbytes).
 * Uses only caller-saved registers, no stack, no $gp, no calls.  Every load-delay slot is respected (R3000).
 * Scratchpad 0x1f800300-0x1f8003ff: rb[0..W+3] (row above, one pixel per byte; W <= 240) and the tail word at
 * 0x1f8003fc (clobbered per call).
 *
 * a0 src   a1 dst   a2 end of the nbytes   a3 model
 * t0 bit buffer (left aligned, a sentinel bit below the data)   t1 &rb[x]   t2 &rb[W]
 * t3 L<<8 | UL   t4 map1   t5 pending low nibble   t6 -> cnt[length]   t7 -> symbols of the current length   t8 U
 * rb[x] = pixel above x (the previous row, overwritten as the row is decoded); rb[W] = 15 */
        .set    noreorder
        .set    noat
        .text
        .globl  dsh_dec, dsh_end

#define RB      0x0300
#define EW      0x03fc
#define O_TOFS  12              /* u16 tofs[tables]; then map1 (t4), map2 = map1 + 4096 */

dsh_dec:
        lui     $t6, 0x1f80             /* s0 (callee-saved) is the format flag: kept at 0x1f8003f4 meanwhile */
        sw      $s0, 0x3f4($t6)
        lbu     $v0, 0($a0)             /* 16 bits: header (3..12 bits), then codes */
        lbu     $v1, 1($a0)
        addiu   $a0, $a0, 2
        sll     $v0, $v0, 24
        sll     $v1, $v1, 16
        or      $t0, $v0, $v1
        addu    $a2, $a1, $a2           /* end of output */
#ifdef MVC
        ori     $t2, $zero, 3           /* width code W/4 - 1: '0' 3 (16 px), '10' 7 (32 px), '11' + 6 bits */
        bgez    $t0, 1f
        ori     $t9, $zero, 1           /* t9 = header bits */
        sll     $v0, $t0, 1
        ori     $t2, $zero, 7
        bgez    $v0, 1f
        ori     $t9, $zero, 2
        srl     $t2, $t0, 24
        andi    $t2, $t2, 63
        ori     $t9, $zero, 8
#else
        move    $t2, $zero              /* width code: '0' 0, '10' 1, '11' + 4 bits */
        bgez    $t0, 1f
        ori     $t9, $zero, 1           /* t9 = header bits */
        sll     $v0, $t0, 1
        ori     $t2, $zero, 1
        bgez    $v0, 1f
        ori     $t9, $zero, 2
        srl     $t2, $t0, 26
        andi    $t2, $t2, 15
        ori     $t9, $zero, 6
#endif
1:      sllv    $v0, $t0, $t9           /* overrun: '0' + 4 bits rep, '10' none, '11' + 4 bits raw */
        bltz    $v0, 2f
        srl     $v1, $v0, 27
        ori     $v1, $v1, 0x100         /* rep: e copies of the last byte */
        b       3f
        addiu   $t9, $t9, 5
2:      sll     $v0, $v0, 1
        bltz    $v0, 4f
        srl     $v1, $v0, 27
        move    $v1, $zero              /* none */
        b       3f
        addiu   $t9, $t9, 2
4:      andi    $v1, $v1, 15            /* raw: e bytes at the end of the stream */
        addiu   $t9, $t9, 6
3:      sllv    $t0, $t0, $t9
        ori     $v0, $zero, 0x8000
        sllv    $v0, $v0, $t9
        or      $t0, $t0, $v0           /* sentinel below the 16 - t9 bits left */
        lui     $t1, 0x1f80
        ori     $t1, $t1, RB
        sw      $v1, EW-RB($t1)
        addiu   $t2, $t2, 1
#ifdef MVC
        sll     $t2, $t2, 2             /* W = (code + 1) * 4 pixels (MvC: any even byte width) */
#else
        sll     $t2, $t2, 4
#endif
        addu    $t2, $t1, $t2           /* &rb[W] */
        lui     $v0, 0x0f0f
        ori     $v0, $v0, 0x0f0f
        move    $t8, $t1
5:      sw      $v0, 0($t8)             /* rb[0..W+3] = 15 */
        sltu    $v1, $t8, $t2
        bnez    $v1, 5b
        addiu   $t8, $t8, 4
        lh      $s0, 8($a3)             /* classes; bit 15 set = LUT model (DSX), else plain DSH1 */
        lhu     $v0, 10($a3)            /* tables */
        ori     $t3, $zero, 0xf0f       /* L = UL = 15 */
        sll     $v1, $v0, 4
        bgez    $s0, 1f                 /* plain DSH1: map1 right after tofs */
        sll     $v0, $v0, 1
        addu    $v0, $v0, $v1           /* DSX: 18 * tables (tofs + LUT array) */
1:      addu    $t4, $a3, $v0
        addiu   $t4, $t4, O_TOFS        /* map1 (LUT of table t at map1 - 16 (t + 1)) */

sym:    lbu     $t8, 0($t1)             /* U */
sym1:   lbu     $t9, 1($t1)             /* UR */
        sll     $v0, $t8, 4
        or      $v0, $v0, $t3
        addu    $v0, $v0, $t4
        lbu     $v0, 0($v0)             /* class = map1[L<<8 | U<<4 | UL] */
        addu    $t9, $t9, $t4
        sll     $t6, $t0, 12            /* 11 bits or fewer before the sentinel: refill 16 */
        beqz    $t6, refill
        sll     $v0, $v0, 4
sym2:   addu    $v0, $v0, $t9
        lbu     $v0, 4096($v0)          /* table = map2[class<<4 | UR] */
        bgez    $s0, plain              /* plain DSH1 file: bit-serial from level 1 */
        srl     $v1, $t0, 28            /* the next 4 bits */
        sll     $at, $v0, 4
        subu    $at, $t4, $at
        addu    $at, $at, $v1
        lbu     $at, -16($at)           /* LUT entry: symbol | (length - 1) << 6, 0xff = longer than 4 bits */
        andi    $v1, $t1, 1             /* x odd?  (rb is at an aligned address) */
        sltiu   $t7, $at, 0xff
        beqz    $t7, esc
        srl     $t7, $at, 6
        addiu   $t7, $t7, 1
        sllv    $t0, $t0, $t7           /* consume the code */
        andi    $v0, $at, 63            /* symbol */
found:  sltiu   $at, $v0, 16            /* v0 = symbol, v1 = x & 1 */
        beqz    $at, isrun
        sll     $t3, $v0, 8
        or      $t3, $t3, $t8           /* L = p, UL = U */
        sb      $v0, 0($t1)             /* literal pixel: rb[x] = p */
        beqz    $v1, even
        addiu   $t1, $t1, 1
        sll     $v0, $v0, 4
        or      $v0, $v0, $t5
        sb      $v0, 0($a1)             /* byte = low | p<<4 */
        beq     $t1, $t2, rowend
        addiu   $a1, $a1, 1
next:   bne     $a1, $a2, sym1
        lbu     $t8, 0($t1)             /* U (harmless at the end) */
        b       tail
        nop
even:   b       sym
        move    $t5, $v0                /* keep the low nibble; never a row or tile end */
rowend: lui     $t1, 0x1f80
        ori     $t1, $t1, RB
        b       next
        ori     $t3, $zero, 0xf0f

/* code longer than 4 bits (v0 = table): canonical bit-serial decode from level 5; record: K4 S4 cnt[12]..cnt[1] symbols
   (tofs -> symbols), K4 = sum cnt[k] << (4 - k), S4 = sum cnt[k] (k <= 4) */
esc:    sll     $v0, $v0, 1
        addu    $v0, $v0, $a3
        lhu     $t6, O_TOFS($v0)
        srl     $v1, $t0, 28
        addu    $t6, $t6, $a3           /* symbols */
        lbu     $at, -14($t6)           /* K4 */
        lbu     $v0, -13($t6)           /* S4 */
        addiu   $t7, $t6, -5            /* -> cnt[5] */
        subu    $v1, $v1, $at           /* d = prefix - K4 */
        addu    $t6, $t6, $v0           /* sp */
        sll     $t0, $t0, 4
escl:   srl     $v0, $t0, 31
        lbu     $at, 0($t7)             /* cnt[l] */
        sll     $t0, $t0, 1
        sll     $v1, $v1, 1
        addu    $v1, $v1, $v0           /* d = d*2 + bit */
        addiu   $t7, $t7, -1
        sltu    $v0, $v1, $at
        bnez    $v0, 2f
        addu    $v0, $t6, $v1
        subu    $v1, $v1, $at
        b       escl
        addu    $t6, $t6, $at
2:      lbu     $v0, 0($v0)             /* symbol */
        b       found
        andi    $v1, $t1, 1

/* plain DSH1 record (cnt[maxlen]..cnt[1] symbols, tofs -> symbols): canonical bit-serial decode from level 1; the
   buffer holds >= 12 bits (the longest code), so no refill inside */
plain:  sll     $v0, $v0, 1
        addu    $v0, $v0, $a3
        lhu     $t6, O_TOFS($v0)
        move    $v1, $zero              /* d */
        addu    $t6, $t6, $a3           /* sp = symbols */
        b       escl
        addiu   $t7, $t6, -1            /* -> cnt[1] */

/* 16 more bits below the ones left: the old sentinel s (bit >= 20) -> data, new sentinel 16 bits lower */
refill: lbu     $t6, 0($a0)
        lbu     $t7, 1($a0)
        addiu   $a0, $a0, 2
        sll     $t6, $t6, 9
        sll     $t7, $t7, 1
        or      $t6, $t6, $t7
        ori     $t6, $t6, 1             /* 16 data bits + sentinel */
        subu    $t7, $zero, $t0
        and     $t7, $t7, $t0           /* s */
        xor     $t0, $t0, $t7
        srl     $t7, $t7, 16
        multu   $t6, $t7
        mflo    $t6
        or      $t0, $t0, $t6
        b       sym2
        nop


/* copy `run` pixels from the row above (rb is left unchanged).  v0 = symbol, v1 = x&1 */
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
        lui     $t1, 0x1f80
        ori     $t1, $t1, RB
4:      andi    $v0, $t1, 2             /* x even: align x to 4 with one byte */
        beqz    $v0, 42f
        sltiu   $v0, $t9, 2
        bnez    $v0, 6f                 /* < 2 pixels */
        nop
        lbu     $v0, 0($t1)
        lbu     $v1, 1($t1)
        addiu   $t1, $t1, 2
        addiu   $t9, $t9, -2
        sll     $v1, $v1, 4
        or      $v0, $v0, $v1
        sb      $v0, 0($a1)
        bne     $t1, $t2, 42f
        addiu   $a1, $a1, 1
        lui     $t1, 0x1f80
        ori     $t1, $t1, RB
42:     sltiu   $v0, $t9, 4
        bnez    $v0, 44f
        nop
        lw      $v0, 0($t1)             /* 4 pixels -> 2 bytes (x % 4 == 0 and W % 4 == 0: inside the row) */
        addiu   $t9, $t9, -4
        addiu   $t1, $t1, 4
        srl     $v1, $v0, 4
        or      $v0, $v0, $v1
        sb      $v0, 0($a1)
        srl     $v0, $v0, 16
        sb      $v0, 1($a1)
        bne     $t1, $t2, 42b
        addiu   $a1, $a1, 2
        lui     $t1, 0x1f80
        b       42b
        ori     $t1, $t1, RB
44:     sltiu   $v0, $t9, 2
        bnez    $v0, 6f
        nop
        lbu     $v0, 0($t1)             /* 2 or 3 pixels left: one byte */
        lbu     $v1, 1($t1)
        addiu   $t1, $t1, 2
        addiu   $t9, $t9, -2
        sll     $v1, $v1, 4
        or      $v0, $v0, $v1
        sb      $v0, 0($a1)
        bne     $t1, $t2, 6f
        addiu   $a1, $a1, 1
        lui     $t1, 0x1f80
        ori     $t1, $t1, RB
6:      beqz    $t9, 7f
        nop
        lbu     $t5, 0($t1)             /* one pixel left: x even, cannot wrap */
        addiu   $t1, $t1, 1
7:      andi    $v0, $t1, 0xff          /* context for the next symbol */
        beqz    $v0, 8f                 /* row start: L = UL = 15 */
        ori     $t3, $zero, 0xf0f
        lbu     $t3, -1($t1)            /* else L = UL = rb[x-1] */
        nop
        sll     $v0, $t3, 8
        or      $t3, $t3, $v0
8:      b       next
        nop

/* the overrun bytes past nbytes */
tail:   lui     $t1, 0x1f80
        lw      $s0, 0x3f4($t1)         /* the caller's s0 back (not used after here) */
        lw      $v1, EW($t1)
        nop
        beqz    $v1, dret
        andi    $t7, $v1, 15            /* e */
        andi    $v1, $v1, 0x100
        beqz    $v1, rawb
        nop
        lbu     $v0, -1($a1)            /* rep: the last byte e times */
        nop
1:      sb      $v0, 0($a1)
        addiu   $t7, $t7, -1
        bnez    $t7, 1b
        addiu   $a1, $a1, 1
dret:   jr      $ra
        nop
rawb:   move    $v0, $zero              /* raw: 8 bits per byte */
        ori     $t8, $zero, 8
2:      sll     $at, $t0, 1
        bnez    $at, 3f
        srl     $v1, $t0, 31
        lbu     $t0, 0($a0)
        addiu   $a0, $a0, 1
        sll     $t0, $t0, 24
        lui     $v1, 0x0080
        or      $t0, $t0, $v1
        sll     $at, $t0, 1
        srl     $v1, $t0, 31
3:      move    $t0, $at
        sll     $v0, $v0, 1
        addiu   $t8, $t8, -1
        bnez    $t8, 2b
        or      $v0, $v0, $v1
        sb      $v0, 0($a1)
        addiu   $t7, $t7, -1
        bnez    $t7, rawb
        addiu   $a1, $a1, 1
        jr      $ra
        nop
dsh_end:
