/* 8 MB build (tools/ap8): blob entry ap8_ent (blob word 0, patched by mkap8.py).  The blob has ~170 B left under
 * mktag's 31,800 B limit, so this stub is all there is:
 *   8 MB test: a word written to 0x806858ac reads back there and does not show at 0x800858ac (2 MB consoles mirror
 *   the 2 MB over the 8 MB window; SwanStation's 2 MB mode reads nothing up there).
 *   2 MB -> tl_wrap (glue.S, ARENA + 16): the 2 MB loader, unchanged.
 *   8 MB -> the module (tagload.c built again with AP8MOD + ap8m.c, linked at MOD) read from the disc to MOD every
 *   battle (fresh .data / .bss, as the blob gets by its own read; ~14 sectors), I-cache flushed, run.
 * Tail jumps with glue's ra (the post routine reads files over the blob's RAM and returns straight to glue). */
        .set noreorder
#define FTSP  0x633c                    /* file table entry SPARE 0x1ab: 0x800255e4 + 8 * 0x1ab = 0x8002633c */
        .text
        .globl ap8_ent
ap8_ent:
        lui     $t0, 0x8008             /* 8 MB test: ~l written to 0x806858ac must read back there and must not */
        lw      $t1, 0x58ac($t0)        /* show at 0x800858ac (2 MB: mirrored -> lo changes; SwanStation 2 MB: */
        lui     $t2, 0x8068             /* nothing up there -> no read-back) */
        nor     $t3, $t1, $zero
        sw      $t3, 0x58ac($t2)
#ifdef DRAIN8
        lw      $t5, 0x58ac($t0)        /* lo read first: drains the write buffer and puts lo (!= ~lo) on the bus, so */
        lw      $t4, 0x58ac($t2)        /* an unmapped hi (open bus) cannot echo ~lo (hardware 2 MB mode) */
#else
        lw      $t4, 0x58ac($t2)
        lw      $t5, 0x58ac($t0)
#endif
        sw      $t1, 0x58ac($t0)        /* lo back (LOADER_FULL / RESTORE / bytes) */
        bne     $t4, $t3, 2f
        lui     $t6, %hi(tl8_dir)
        bne     $t5, $t1, 2f
        nop
        addiu   $sp, $sp, -32
        sw      $ra, 28($sp)
        sw      $a0, 24($sp)
        lui     $t8, 0x8002
        lw      $t9, FTSP($t8)
        lw      $v1, FTSP + 4($t8)
        lw      $v0, %lo(tl8_dir)($t6)  /* module msf */
        lw      $t7, %lo(tl8_dir + 4)($t6)   /* module bytes */
        sw      $t9, 16($sp)
        sw      $v1, 20($sp)
        sw      $v0, FTSP($t8)
        sw      $t7, FTSP + 4($t8)
        lui     $a1, 0x8020
        jal     0x80024800              /* RD(SPARE, MOD) */
        li      $a0, 0x1ab
        lw      $t9, 16($sp)
        lw      $v1, 20($sp)
        lui     $t8, 0x8002
        sw      $t9, FTSP($t8)
        jal     flushcache
        sw      $v1, FTSP + 4($t8)
        lw      $ra, 28($sp)
        lw      $a0, 24($sp)
        lui     $t0, 0x8020
        jr      $t0
        addiu   $sp, $sp, 32
2:      j       0x80092c50              /* tl_wrap */
        nop

        .section .dir8, "aw"
        .globl tl8_dir
tl8_dir: .word 0, 0, 0                  /* module msf, bytes, sum fix (mkap8.py) */
