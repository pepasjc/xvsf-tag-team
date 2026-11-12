        .set noreorder
        .section .chunka_head, "ax"
        .globl glue, effglue, flushcache, dirent, tl_dbg
glue:   j       hook
        addiu   $a1, $sp, 0x38          /* a1 = &list in the battle loader frame */
effglue:
        j       effhook
        addiu   $a2, $sp, 0x38          /* a2 = &list */
/* BIOS FlushCache inside a critical section.  FlushCache isolates the cache; an interrupt taken in
 * that window (the CD drive finishing a read) runs the exception handler from the isolated cache
 * and never comes back.  EnterCriticalSection / ExitCriticalSection = syscall with a0 = 1 / 2. */
flushcache:
        addiu   $sp, $sp, -0x18
        sw      $ra, 0x10($sp)
        li      $a0, 1
        syscall
        li      $t2, 0xa0
        jalr    $t2
        li      $t1, 0x44               /* BIOS A(0x44) FlushCache */
        li      $a0, 2
        syscall
        lw      $ra, 0x10($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 0x18
        .section .chunkf_data, "aw"
        .balign 8
        .space 4                        /* directory entries must sit at 4 mod 8 (same residue as the game file table) */
        .globl bossdirent, bk
dirent: .space 8                        /* MSF + size of the directory sector (disc builder) */
bossdirent: .space 8                    /* MSF + size of the boss directory sector (disc builder) */
bk:     .space 16                       /* two exchanged file-table entries */
        .byte 0xff, 0xff, 0, 0          /* characters they belong to: none */
        .section .dbg, "aw"
tl_dbg: .space 12
