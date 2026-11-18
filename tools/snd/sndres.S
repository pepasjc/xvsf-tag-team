# XvSF tag hack 1.2: every loaded character gets its full own sound bank (partners too) - resident part, in the
# quad worker's FREED range 0x80055c34-0x80055ebc (tools/speed/quad.py FREED).  Assembled by tools/sndpatch.py with
# FLUSHCACHE (tools/tagload glue.S: BIOS FlushCache in a critical section) and the layout constants of snd.h.
#
#  snd_list   the battle loader 0x8002ac38 calls it instead of building its stock bank list and `jal 0x8004cb18`:
#             a0 = character list (sp+0x38, after the stock dedupe / boss rule), a1 = bank list buffer (sp+0x40).
#             Reads the sound directory (2 sectors to DIRBUF, word sum checked) and runs its code (snddir.c), which
#             picks the files and loads the banks.  Unreadable directory: the stock list (partners load their
#             HELP bank) with the stock stash place (SPU 0x68000).
#  vh_w/vb_w  the bank loader's two file reads (0x8004cd58 VH merge, 0x8004cdd0 VB load): while snd_on, the
#             chosen level's files (fake file indices into the directory's entry table).
#  stash_up   in place of `jal 0x80057b40` in the set-0x37 loader 0x80054428: SP_EFF2's pixel section to stashbase,
#             an SPU address, or main RAM when bit 31 is set (8 MB); returns it: the loader stores it as the set's
#             sec2 (0x8005c90c), where the tile fetch `cdtile` (tools/speed/upload/helpers.S) reads it.

        .equ    FTABLE, 0x8003d91c
        .equ    LOADFILE, 0x8002de3c
        .equ    BANKLOAD, 0x8004cb18
        .equ    MERGE, 0x8004ce34
        .equ    VBLOAD, 0x8004d418
        .equ    SPUADDR, 0x800116c8
        .equ    SPUWRITE, 0x80011668
        .equ    SPUWAIT, 0x80011720
        .equ    ENTK, DIRBUF + ENTOFF - FTABLE          # fake index * 8 of entry 0 (a multiple of 8)

        .globl  snd_list, vh_w, vb_w, stash_up, stashbase, snd_on, snd_xl, snd_cl, ap8fn, sndent
snd_list:
        addiu   $sp, $sp, -32
        sw      $ra, 28($sp)
        sw      $s0, 24($sp)
        sw      $s1, 20($sp)
        move    $s0, $a0
        move    $s1, $a1
        lh      $t0, 0($a0)                # bk = [0x26, ch[0..3]]
        lh      $t1, 2($a0)
        lh      $t2, 4($a0)
        lh      $t3, 6($a0)
        ori     $v0, $zero, 0x26
        sh      $v0, 0($a1)
        sh      $t0, 2($a1)
        sh      $t1, 4($a1)
        sh      $t2, 6($a1)
        sh      $t3, 8($a1)
        lui     $at, %hi(snd_on)
        sb      $zero, %lo(snd_on)($at)
        lui     $v0, 6
        ori     $v0, $v0, 0x8000
        lui     $at, %hi(stashbase)
        sw      $v0, %lo(stashbase)($at)   # stock stash place until the directory says otherwise
        lui     $a0, %hi(sndent)
        addiu   $a0, $a0, %lo(sndent)
        lui     $at, %hi(FTABLE)
        addiu   $at, $at, %lo(FTABLE)
        subu    $a0, $a0, $at
        sra     $a0, $a0, 3                # fake file index of sndent
        jal     LOADFILE
        lui     $a1, %hi(DIRBUF)
        lui     $t0, %hi(sndent)
        lw      $t1, %lo(sndent + 4)($t0)  # its size
        lui     $a1, %hi(DIRBUF)
        bne     $v0, $t1, 8f
        lw      $t2, 0($a1)                # magic
        lui     $t3, %hi(MAGIC)
        ori     $t3, $t3, %lo(MAGIC)
        bne     $t2, $t3, 8f
        lw      $t4, 8($a1)                # nwords
        nop
        sltiu   $t5, $t4, DIRSIZE / 4 - 1
        beqz    $t5, 8f
        addiu   $t6, $a1, 8
        move    $t7, $zero
1:      lw      $t8, 0($t6)                # sum of nwords words from &nwords on
        addiu   $t4, $t4, -1
        addu    $t7, $t7, $t8
        bnez    $t4, 1b
        addiu   $t6, $t6, 4
        lw      $t2, 4($a1)
        nop
        bne     $t2, $t7, 8f
        nop
        jal     FLUSHCACHE                 # the directory's code was just read
        nop
        move    $a0, $s0
        move    $a1, $s1
        lui     $t9, %hi(DIRBUF + CODEOFF)
        addiu   $t9, $t9, %lo(DIRBUF + CODEOFF)
        jalr    $t9                        # snd_policy (snddir.c): the banks are loaded there
        nop
        b       9f
        nop
8:      lh      $v0, 4($s1)                # stock: partners (odd entries) load their HELP bank (+0x13)
        nop
        bltz    $v0, 2f
        addiu   $v0, $v0, 0x13
        sh      $v0, 4($s1)
2:      lh      $v0, 8($s1)
        nop
        bltz    $v0, 3f
        addiu   $v0, $v0, 0x13
        sh      $v0, 8($s1)
3:      jal     BANKLOAD
        move    $a0, $s1
9:      lw      $ra, 28($sp)
        lw      $s1, 20($sp)
        lw      $s0, 24($sp)
        jr      $ra
        addiu   $sp, $sp, 32

# a0 = bank (0..0x11 or 0x26 XS_MAIN), t1 = 0 (VH) / 8 (VB) -> a0 = fake file index of e[level][b][t1]; t2-t6
tr:     ori     $t2, $zero, 0x26
        lui     $t3, %hi(snd_xl)
        bne     $a0, $t2, 1f
        lbu     $t4, %lo(snd_cl)($t3)      # characters: snd_cl
        lbu     $t4, %lo(snd_xl)($t3)      # XS_MAIN: snd_xl, table bank 18
        ori     $a0, $zero, 18
1:      nop
        sll     $t5, $t4, 4
        sll     $t6, $t4, 1
        addu    $t5, $t5, $t6
        addu    $t5, $t5, $t4              # level * 19
        addu    $t5, $t5, $a0
        sll     $t5, $t5, 4                # * 16
        addu    $t5, $t5, $t1
        lui     $t6, %hi(ENTK)
        addiu   $t6, $t6, %lo(ENTK)
        addu    $t5, $t5, $t6
        jr      $ra
        srl     $a0, $t5, 3

vh_w:   lui     $t0, %hi(snd_on)
        lbu     $t0, %lo(snd_on)($t0)
        move    $t9, $ra
        beqz    $t0, 1f
        move    $t1, $zero
        bal     tr
        addiu   $a0, $a0, -0xb9
        move    $ra, $t9
1:      j       MERGE
        nop

vb_w:   lui     $t0, %hi(snd_on)
        lbu     $t0, %lo(snd_on)($t0)
        move    $t9, $ra
        beqz    $t0, 1f
        ori     $t1, $zero, 8
        bal     tr
        addiu   $a0, $a0, -0xe2
        move    $ra, $t9
1:      j       VBLOAD
        nop

stash_up:
        lui     $t0, %hi(stashbase)
        lw      $v0, %lo(stashbase)($t0)
        nop
        bgez    $v0, 2f
        move    $t1, $v0
1:      lbu     $t2, 0($a0)                # main RAM (8 MB)
        addiu   $a1, $a1, -1
        sb      $t2, 0($t1)
        addiu   $a0, $a0, 1
        bnez    $a1, 1b
        addiu   $t1, $t1, 1
        jr      $ra
        nop
2:      addiu   $sp, $sp, -32              # SPU, as 0x80057b40 does it
        sw      $ra, 28($sp)
        sw      $a0, 24($sp)
        sw      $a1, 20($sp)
        jal     SPUADDR
        move    $a0, $v0
        lw      $a0, 24($sp)
        lw      $a1, 20($sp)
        jal     SPUWRITE
        nop
        jal     SPUWAIT
        ori     $a0, $zero, 1
        lw      $ra, 28($sp)
        lui     $t0, %hi(stashbase)
        lw      $v0, %lo(stashbase)($t0)
        jr      $ra
        addiu   $sp, $sp, 32

        .org    0x25c                      # RES + 0x25c: sndent lands at 4 mod 8 (RES = 0x80055c34 is 4 mod 8 itself)
stashbase:
        .word   0x68000
ap8fn:  .word   0                          # 8 MB build: ap8ready() (tools/mkap8disc.py)
snd_on: .byte   0
snd_xl: .byte   0
snd_cl: .byte   0
        .byte   0
sndent: .word   0, 0                       # MSF + size of the sound directory (tools/mktagdisc.py), at 4 mod 8
