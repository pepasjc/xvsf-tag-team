/* Resident part of the MSHvSF tag loader (dead EXE range 0x80013580-0x80013748, see docs/CODESPACE.md).
 *
 * Hook in the stock battle loader 0x8002ac98 (slot loop at 0x8002af50):
 *     8002af50  jal   glue                (was move s0,zero)
 *     8002af54  addiu a0, sp, 0x18        (was move s2,v0)        a0 = &list
 *     8002af58  bnez  v0, 0x8002afe0      (was lui v0,0x8007)     handled: skip the stock slot loop
 *     8002af5c  nop                       (was addiu s1,v0,0x538)
 * glue reads the loader blob (tagload.c) into the sprite decode arena, checks its word sum, flushes the
 * I-cache and calls it.  When the blob is bad or declines (0), glue sets s0 / s1 / s2 the way the stock
 * loop expects them and returns to it (stock loading: cut-down partners).
 */
        .set noreorder
        .set noat
        .section .glue, "ax"
        .globl glue, flushcache, tl_dbg, blobent

#define FTAB_SPARE  (0x800247dc + 8 * 0x10f)
#define ARENA       0x80087e10
#define RD          0x80024554

glue:
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x18($sp)
        sw      $s0, 0x14($sp)
        sw      $a0, 0x10($sp)
        la      $t1, tl_dbg
        sb      $zero, 0($t1)
        li      $s0, 3                  /* tries */
1:      la      $t0, blobent
        lw      $t1, 0($t0)
        lw      $t2, 4($t0)
        la      $t3, FTAB_SPARE
        sw      $t1, 0($t3)
        sw      $t2, 4($t3)
        beqz    $t2, 8f                 /* no blob on this disc: stock */
        li      $t0, 0xfa
        li      $a1, ARENA
        jal     RD
        li      $a0, 0x10f
        la      $t0, blobent
        lw      $t2, 4($t0)             /* bytes, multiple of 4 */
        li      $t0, ARENA
        addu    $t2, $t2, $t0
        move    $t1, $zero
2:      lw      $t3, 0($t0)
        addiu   $t0, $t0, 4
        bne     $t0, $t2, 2b
        addu    $t1, $t1, $t3
        beqz    $t1, 3f
        addiu   $s0, $s0, -1
        bnez    $s0, 1b
        nop
        b       8f
        li      $t0, 0xfb
3:      jal     flushcache
        nop
        li      $t0, ARENA
        jalr    $t0
        lw      $a0, 0x10($sp)
        bnez    $v0, 9f
        nop
        b       8f
        nop
8:      la      $t1, tl_dbg             /* t0 = reason when the blob did not run */
        lbu     $t2, 0($t1)
        nop
        bnez    $t2, 7f                 /* blob ran and declined: keep its reason */
        nop
        sb      $t0, 0($t1)
7:      move    $v0, $zero
9:      lw      $ra, 0x18($sp)
        lw      $s0, 0x14($sp)
        beqz    $v0, 10f
        addiu   $sp, $sp, 0x20
        jr      $ra
        nop
10:     move    $s0, $zero              /* registers of the stock slot loop */
        lui     $s2, 0x8002
        addiu   $s2, $s2, 0x5040
        lui     $s1, 0x8007
        jr      $ra
        addiu   $s1, $s1, 0x538

/* BIOS FlushCache inside a critical section (an interrupt in the isolated-cache window hangs: XvSF tag14) */
flushcache:
        addiu   $sp, $sp, -0x18
        sw      $ra, 0x10($sp)
        li      $a0, 1
        syscall
        li      $t2, 0xa0
        jalr    $t2
        li      $t1, 0x44
        li      $a0, 2
        syscall
        lw      $ra, 0x10($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 0x18

        .balign 4
blobent: .word 0, 0                     /* MSF + size of the blob (disc builder) */
tl_dbg:  .space 16                      /* [0] 1 loaded / 0xfe no fit / 0xfc char 0 / 0xfd bad dir / 0xfb bad blob / 0xfa no blob / 0xf9 mode
                                           [1] tier of P1 main | P1 partner << 4  [2] same for P2
                                               (0 DSH1, 1 DSH1+hot32, 2 DSM1, 3-5 DSM1 + hot 16/32/64 KB RLE, 6 stock RLE)
                                           [4..7] end of the loaded data  [8..11] end of the GPU pool (heapcap) */

/* GPU primitive pool cap.  0x8002a9b4 (after the stage data) inits the pool with all the space up to
 * 0x800bbfd8: 16-54 KB by stage.  Hook: 8002aa38 `move a0,s1` -> `jal heapcap`, 8002aa3c `jal 0x80020fe4` -> nop;
 * heapcap caps the size (s0) at 16 KB (stage 8's stock pool is 16084 bytes), records the pool end for the loader,
 * and tail-calls the pool init (returns to 8002aa40, the old delay slot `move a1,s0`: harmless). */
        .section .heapcap, "ax"
        .globl heapcap
heapcap:
        sltiu   $t0, $s0, 16385
        bnez    $t0, 1f
        nop
        li      $s0, 16384
1:      addu    $t1, $s1, $s0
        la      $t2, tl_dbg
        sw      $t1, 8($t2)
        move    $a0, $s1
        j       0x80020fe4
        move    $a1, $s0

        .section .entry, "ax"
        j       tl_main
        nop
