        .set noreorder
/* EXE side: the two hook entries (the battle loader's frame holds the character list at sp+0x38) */
        .section .chunkj_head, "ax"
#ifndef MODULE
        .globl glue8, effglue8, modent
glue8:  j       hook8
        addiu   $a1, $sp, 0x38
effglue8:
        j       effhook8
        addiu   $a2, $sp, 0x38
        .section .chunki_data, "aw"
        .balign 8
        .space 4                        /* file entries must sit at 4 mod 8 (same residue as the game file table) */
modent: .space 8                        /* MSF + size of the module (disc builder) */

#else
/* module side: vectors at MOD+0 (eff), MOD+8 (hook), MOD+16 (sel), MOD+24 (menu), then the file tables at MOD+0x24 (4 mod 8) */
        .section .modhead, "ax"
        .globl T
        j       mod_eff
        nop
        j       mod_hook
        nop
        j       mod_sel
        nop
        j       mod_menu
        nop
        .word   0
T:      .space  (19 * 5 + 7) * 8 + 19 * 4 + 39 * 4 + 20 * 2 + 7 * 4 + 4 + 8 + 8

/* LOADFILE (0x8002de3c) without the file cache: its two first instructions (replaced by `j mod_loadfile`), then the rest */
        .text
        .globl  orig_loadfile
orig_loadfile:
        addiu   $sp, $sp, -0x20
        j       0x8002de44
        sw      $s0, 0x10($sp)
#endif
