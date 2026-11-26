/* Resident part of the MvC tag loader.  Code space (games/mvc/docs/CODESPACE.md, tools/tagload/fnscan.py):
 *   .g1  0x8002547c-0x80025540   blob read + word sum
 *   .g2  0x8001780c-0x800178b4   retry, call, decline
 *   .res 0x8001b454-0x8001b4fc   flushcache, heapcap, blobent, tl_dbg
 *
 * Hook in the stock versus loader 0x8002b7a4 (slot loop 0x8002b950..0x8002b9b0):
 *     8002b950  jal   glue                (was move s0,zero)
 *     8002b954  addiu a0, sp, 0x10        (was addiu s2,sp,0x10)      a0 = &list
 *     8002b958  bnez  v0, 0x8002b9b4      (was move s1,v0)            handled: skip the stock slot loop
 *     8002b95c  nop                       (was addu a1,s2,s0)
 * glue reads the loader blob (tagload.c) into the tile decode arena, checks its word sum, flushes the I-cache and
 * calls it.  When the blob is bad or declines (0), glue sets s0 / s1 / s2 / a1 the way the stock loop expects
 * them and returns to it (stock loading: cut-down partners, stock rules).
 * The file-table entry SPARE (CAPMOV.BIN, not read in battle) is borrowed for the read and restored.
 */
        .set noreorder
        .set noat
        .globl glue, flushcache, tl_dbg, blobent, heapcap, tl_entry, hcguard, hg_end, post_end

#define FTAB_SPARE  (0x800255e4 + 8 * 0x1ab)
#define ARENA       0x80092c40
#define RD          0x80024800
#define LOADER_FULL 0x800858ac   /* tag state bytes in a dead EXE span (zeroed by mktag): +0 LOADER_FULL, +1 RESTORE;
                                     the old 0x8007b6eb / 0x8007b6ee are live game bytes (0x8007b6eb toggles every second) */
#define POOLCAP     30000           /* GPU primitive pool cap: peak 709 entries = 28,360 B measured (cold study, work/cold) */

        .section .g1, "ax"
glue:
        addiu   $sp, $sp, -0x30
        sw      $ra, 0x18($sp)
        sw      $s0, 0x14($sp)
        sw      $a0, 0x10($sp)
        li      $s0, 3                  /* tries (tl_dbg[0] and LOADER_FULL were cleared by heapcap) */
gl_try: la      $t3, FTAB_SPARE
        lw      $t4, 0($t3)
        lw      $t5, 4($t3)
        la      $t0, blobent
        sw      $t4, 0x20($sp)
        sw      $t5, 0x24($sp)
        lw      $t1, 0($t0)
        lw      $t2, 4($t0)
        sw      $t1, 0($t3)
        beqz    $t2, 1f                 /* no blob on this disc */
        sw      $t2, 4($t3)
        li      $a1, ARENA
        jal     RD
        li      $a0, 0x1ab
1:      la      $t3, FTAB_SPARE
        lw      $t4, 0x20($sp)
        lw      $t5, 0x24($sp)
        sw      $t4, 0($t3)
        sw      $t5, 4($t3)
        la      $t0, blobent
        lw      $t2, 4($t0)             /* bytes, multiple of 4 */
        li      $t0, ARENA
        beqz    $t2, gl_nob
        addu    $t2, $t2, $t0
        move    $t1, $zero
2:      lw      $t3, 0($t0)
        addiu   $t0, $t0, 4
        bne     $t0, $t2, 2b
        addu    $t1, $t1, $t3
        j       gl_sum
        nop
g1_end:

        .section .g2, "ax"
gl_sum: beqz    $t1, 3f
        addiu   $s0, $s0, -1
        bnez    $s0, gl_try
        nop
        b       gl_fail
        li      $t0, 0xfb
3:      jal     flushcache
        nop
        la      $t0, tl_entry           /* blob entry: ARENA (tl_main) or ARENA + 8 (tl_restore) */
        lw      $t0, 0($t0)
        nop
        jalr    $t0
        lw      $a0, 0x10($sp)
        bnez    $v0, gl_ret
        nop
        b       gl_dec
        nop
gl_nob: li      $t0, 0xfa
gl_fail:
        la      $t1, tl_dbg
        lbu     $t2, 0($t1)
        nop
        bnez    $t2, gl_dec             /* blob ran and declined: keep its reason */
        nop
        sb      $t0, 0($t1)
gl_dec: move    $v0, $zero
gl_ret: lw      $ra, 0x18($sp)
        lw      $s0, 0x14($sp)
        lw      $a0, 0x10($sp)
        bnez    $v0, 1f
        addiu   $sp, $sp, 0x30
        move    $s0, $zero              /* registers of the stock slot loop */
        move    $s2, $a0
        lui     $s1, 0x8008
        addiu   $s1, $s1, -0x4918
        move    $a1, $s2
1:      jr      $ra
        nop
g2_end:

        .section .hg, "ax"
/* 0x800858b0 (dead span 0x800858ac-0x800858cc; +0 LOADER_FULL, +1 RESTORE before it).  LOADER_FULL is NOT cleared
 * per battle load any more: an ARCADE continue / rematch with the same team reloads only the stage and re-inits the
 * battle without the character loader (our four full characters stay in RAM) -> the tag rules must stay on
 * (build 02 bug: "only the first match is 2v2").  The loader clears / sets it whenever it runs.  Cleared here only
 * when the new pool end lies above the previous one (the stage grew into the character region: data not intact). */
hcguard:
        sltu    $t5, $t5, $t1
        beqz    $t5, 1f
        lui     $t2, 0x8008
        sb      $zero, 0x58ac($t2)
1:      j       0x800219cc
        nop
hg_end:

        .section .res, "ax"
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

/* GPU primitive pool cap.  0x8002b498 (end of the stage load) inits the pool with all the space from the end of the
 * stage data to 0x800c4fd8 (~64 KB).  Hook: 8002b528 `jal 0x800219cc` -> `jal heapcap` (delay slot move a1,s0):
 * caps the size, records the pool end for the loader, clears tl_dbg[0] (LOADER_FULL: see hcguard) (runs once per battle load,
 * before the loader; also for an ARCADE challenger battle, which skips the battle-scene init where tagmode.py hooks),
 * puts the versus flag back if a tag battle left it at 0, tail-calls the pool init. */
heapcap:
        sltiu   $t0, $a1, POOLCAP + 1
        bnez    $t0, 1f
        nop
        li      $a1, POOLCAP
1:      addu    $t1, $a0, $a1
        la      $t2, tl_dbg
        lw      $t5, 8($t2)             /* the previous battle's pool end (its region start) */
        sw      $t1, 8($t2)
        sb      $zero, 0($t2)
        lui     $t2, 0x8008
        lb      $t3, 0x58ad($t2)        /* RESTORE 0x800858ad: a tag battle ended without its post-battle phase */
        ori     $t4, $zero, 1           /* (ARCADE challenger): versus flag back to 1 before this battle */
        beqz    $t3, 2f
        nop
        sb      $t4, -0x48a3($t2)       /* versus flag 0x8007b75d */
        sb      $zero, 0x58ad($t2)
2:      j       hcguard
        nop

        .balign 4
blobent: .word 0, 0                     /* MSF + size of the blob (disc builder) */
tl_entry: .word ARENA                   /* entry glue calls (the restore hook sets ARENA + 8 around its call) */
tl_dbg:  .space 16                      /* see tagload.c */
        .globl dshptr, dsaptr
dshptr:  .word 0                        /* DSH1 / DSA1 decoder addresses for the dispatch (common/dsp/dsmdec.S) */
dsaptr:  .word 0
        .globl tl_pend
tl_pend: .word 0                        /* fragments to restore (rhook -> tl_restore) */
res_end:

/* Restore hook (.rh 0x80014774-0x800147dc): entry of the file loader 0x80024800 (`addiu sp,-0x20; sw s0,0x10(sp)` ->
 * `j rhook; nop`).  A tag battle that put data into battle-cold EXE ranges leaves their mask in tl_dbg[12..15]; the first
 * file load after the battle restores them (glue with tl_entry = blob entry 2 = tl_restore re-reads the EXE sectors)
 * before the load itself.  The mask moves to tl_pend first, so the blob read inside does not recurse. */
        .section .rh, "ax"
        .globl rhook
rhook:  lui     $t0, %hi(tl_dbg)
        lw      $t1, %lo(tl_dbg + 12)($t0)
        lui     $t2, 0x8009
        bnez    $t1, 1f
        ori     $t2, $t2, 0x2c48        /* ARENA + 8: blob entry 2 = tl_restore */
0:      addiu   $sp, $sp, -0x20
        j       0x80024808
        sw      $s0, 0x10($sp)
1:      sw      $zero, %lo(tl_dbg + 12)($t0)
        sw      $t1, %lo(tl_pend)($t0)
        addiu   $sp, $sp, -0x20
        sw      $ra, 0x18($sp)
        sw      $a0, 0x10($sp)
        sw      $a1, 0x14($sp)
        jal     glue
        sw      $t2, %lo(tl_entry)($t0)
        lui     $t0, %hi(tl_entry)
        lui     $t2, 0x8009
        ori     $t2, $t2, 0x2c40        /* ARENA */
        sw      $t2, %lo(tl_entry)($t0)
        lw      $ra, 0x18($sp)
        lw      $a0, 0x10($sp)
        lw      $a1, 0x14($sp)
        b       0b
        addiu   $sp, $sp, 0x20
rh_end:

        .section .entry, "ax"
        j       tl_wrap
        nop
        j       tl_restore
        nop
/* tl_main, then (post VC, tagload.c) a tail call into the post routine that sits in the strong payload outside the
 * blob: it reads files over the blob's RAM and returns straight to glue with v0 = 1 */
tl_wrap:
        addiu   $sp, $sp, -24
        sw      $ra, 16($sp)
        jal     tl_main
        nop
        lw      $ra, 16($sp)
        addiu   $sp, $sp, 24
        beqz    $v0, 1f
        nop
        la      $t0, tl_postfn
        lw      $t0, 0($t0)
        la      $a0, tl_postarg
        beqz    $t0, 1f
        lw      $a0, 0($a0)
        jr      $t0
        nop
1:      jr      $ra
        nop

/* post routine (position-independent but for the absolute jal into the EXE), copied after the RAM decoders:
 * a0 = list {n, (file index, RAM address, sprite set) x n}: RD(index, address), then REG(set, address, 0) */
        .section .post, "ax"
        .globl  post, post_list
post:   addiu   $sp, $sp, -32
        sw      $ra, 24($sp)
        sw      $s0, 20($sp)
        sw      $s1, 16($sp)
        move    $s0, $a0
        lw      $s1, 0($s0)
        addiu   $s0, $s0, 4
1:      beqz    $s1, 2f
        nop
        lw      $a0, 0($s0)
        jal     0x80024800              /* RD */
        lw      $a1, 4($s0)
        lw      $a0, 8($s0)
        lw      $a1, 4($s0)
        jal     0x80091e74              /* REG (mode 0: RAM set) */
        move    $a2, $zero
        addiu   $s0, $s0, 12
        b       1b
        addiu   $s1, $s1, -1
2:      lw      $ra, 24($sp)
        lw      $s0, 20($sp)
        lw      $s1, 16($sp)
        li      $v0, 1
        jr      $ra
        addiu   $sp, $sp, 32
post_list:
        .space  28
post_end:
