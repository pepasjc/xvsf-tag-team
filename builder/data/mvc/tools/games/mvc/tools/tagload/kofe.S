/* kofe.S = fecache.S with a 2048-slot index (ring at +0x4220), for the free-on-KO cache (kocache.py, 2026-11-18): the
 * KO'd character's sprite file becomes the ring.  Original header follows.
 * Decoded-tile cache in front of the RAM decoders (DSH1/DSX and DSA1 routes of the dispatch, common/dsp/dsmdec.S).
 * Copied by the loader (tagload.c) to the start of the per-battle cache area B = STRONG - CACHE; position-independent.
 *   B + 0x000  this code (<= 0x200 bytes)
 *   B + 0x200  control: +0 A (bytes written, absolute)  +4 R (ring size, power of 2)  +8 saved ra  +12 src  +16 dst
 *              +20 n  +24 DSA1 decoder  +28 DSH1 decoder
 *   B + 0x220  index: 2048 x { src, A at the entry }   (slot = ((src >> 2) ^ (src >> 11)) & 2047)
 *   B + 0x4220 ring: entries { src, n, data rounded up to 4 }, an entry that would cross the ring end starts the next lap
 * Hit: src in its slot, the entry not yet overwritten (A - pos <= R) and its header = (src, n): the cached bytes are
 * copied to dst (n rounded up to 4; the decoders write up to 15 bytes past n anyway).  Miss: the decoder runs, then
 * its output is stored.  Keys are tile stream addresses: fixed for a battle; the loader clears the index per load.
 * Entered like the decoders: a0 src  a1 dst  a2 n (> 0)  a3 section; only caller-saved registers, no stack. */
        .set    noreorder
        .set    noat
        .text
        .globl  fe_dsh, fe_dsa, fe_end
#define CTL     0x200
#define IDX     0x220
#define RING    0x4220

fe_dsh: move    $t8, $ra
        bal     fe0
        ori     $v1, $zero, 4           /* DSH1 route: decoder word at CTL + 28 */
fe_dsa: move    $t8, $ra
        bal     fe0
        move    $v1, $zero              /* DSA1 route: CTL + 24 */
fe0:    move    $t7, $ra                /* t7 = fe_dsa + 12 (DSA) or fe_dsa (DSH): normalise */
        bnez    $v1, 1f
        move    $ra, $t8
        addiu   $t7, $t7, -12
1:      addiu   $t6, $t7, CTL - (fe_dsa - fe_dsh)   /* control block (fe_dsh = code start) */
        addu    $at, $t6, $v1
        lw      $t9, 24($at)            /* the real decoder */
        sltiu   $at, $a2, 4097
        beqz    $at, go                 /* big decodes (0x80045a90: 0x7080 bytes) are not cached */
        srl     $t0, $a0, 2
        srl     $t1, $a0, 11
        xor     $t0, $t0, $t1
        andi    $t0, $t0, 2047
        sll     $t0, $t0, 3
        addu    $t0, $t0, $t6
        lw      $t1, IDX-CTL($t0)       /* key */
        lw      $t2, IDX-CTL+4($t0)     /* pos */
        bne     $t1, $a0, miss
        lw      $t3, 0($t6)             /* A */
        lw      $t4, 4($t6)             /* R */
        subu    $t3, $t3, $t2
        sltu    $at, $t4, $t3
        bnez    $at, miss               /* overwritten since */
        addiu   $t4, $t4, -1
        and     $t2, $t2, $t4
        addu    $t2, $t2, $t6
        lw      $t1, RING-CTL($t2)      /* entry src */
        lw      $t5, RING-CTL+4($t2)    /* entry n */
        bne     $t1, $a0, miss
        addiu   $t3, $a2, 3
        bne     $t5, $a2, miss
        srl     $t3, $t3, 2             /* words */
        addiu   $t2, $t2, RING-CTL+8
2:      lw      $t1, 0($t2)             /* hit: copy (dst any alignment) */
        addiu   $t3, $t3, -1
        swl     $t1, 3($a1)
        swr     $t1, 0($a1)
        addiu   $t2, $t2, 4
        bnez    $t3, 2b
        addiu   $a1, $a1, 4
        jr      $ra
        nop
go:     jr      $t9
        nop

miss:   sw      $ra, 8($t6)
        sw      $a0, 12($t6)
        sw      $a1, 16($t6)
        jalr    $t9
        sw      $a2, 20($t6)
        bal     3f
        nop
3:      addiu   $t6, $ra, CTL - (3b - fe_dsh)
        lw      $a0, 12($t6)
        lw      $a1, 16($t6)
        lw      $a2, 20($t6)
        lw      $t3, 0($t6)             /* A */
        lw      $t4, 4($t6)             /* R */
        addiu   $t5, $a2, 11
        srl     $t5, $t5, 2
        sll     $t5, $t5, 2             /* L = 8 + n rounded up to 4 */
        addiu   $t1, $t4, -1
        and     $t0, $t3, $t1           /* ring offset */
        addu    $t2, $t0, $t5
        sltu    $at, $t4, $t2
        beqz    $at, 4f
        srl     $t2, $a0, 2
        or      $t3, $t3, $t1           /* would cross the end: next lap */
        addiu   $t3, $t3, 1
        move    $t0, $zero
4:      srl     $t7, $a0, 11
        xor     $t2, $t2, $t7
        andi    $t2, $t2, 2047
        sll     $t2, $t2, 3
        addu    $t2, $t2, $t6
        sw      $a0, IDX-CTL($t2)
        sw      $t3, IDX-CTL+4($t2)
        addu    $t0, $t0, $t6
        sw      $a0, RING-CTL($t0)
        sw      $a2, RING-CTL+4($t0)
        addu    $t3, $t3, $t5
        sw      $t3, 0($t6)             /* A += L */
        addiu   $t0, $t0, RING-CTL+8
        addiu   $t5, $t5, -8
5:      lwl     $t1, 3($a1)             /* store the decoder's output (dst any alignment) */
        lwr     $t1, 0($a1)
        addiu   $t5, $t5, -4
        sw      $t1, 0($t0)
        addiu   $a1, $a1, 4
        bnez    $t5, 5b
        addiu   $t0, $t0, 4
        lw      $ra, 8($t6)
        nop
        jr      $ra
        nop
fe_end:
