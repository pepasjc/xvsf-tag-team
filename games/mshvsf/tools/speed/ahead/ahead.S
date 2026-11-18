# MSHvSF speed, part "ahead": deferred pre-decode (decode-ahead in the idle time of the frame).
#
# The engine already pre-decodes the predicted next animation frame of every drawn object (queue 0x80087e08,
# 0x8008555c -> 0x80084cd4 -> 0x80084ab8, called once per logic frame before present), but it does it all at once,
# on the critical path of the frame where the prediction was made.  With the slow sprite tiers (DSM1 ~30, DSH1 ~80
# cycles per byte) that pre-decode alone pushes frames past the vblank.
#
# Here the stock pre-decode still runs at the stock time and does everything it did (block allocation, arena block
# size, node states, scratchpad writes are bit-identical), except that its tile decoder calls are only RECORDED
# (D1).  When 0x80084ab8 succeeds, the LAST tile of the block is decoded at once (its RLE / DSH1 overrun is the only
# write outside the block: it happens at the stock time), and a cursor for the other tiles is kept (D2).  The
# cursors are worked off tile by tile:
#   - in the idle time of every frame, right after the stock pre-decode (FR), while the next tile fits before the
#     next vblank (hblank counter 1, free running: the main loop's ResetRCnt(1) is dropped; the game never reads
#     the counter);
#   - completely, when the block is about to be used: after the pre-decode check 0x80084984 said "use the
#     pre-decoded frame" (CK), and at an arena flush for nodes whose entry the flush keeps (FLUSH).
# A block freed before use (0x80083704: node release, or the per-frame free of unused blocks) cancels its cursor:
# nothing reads a freed block.  Deferred tiles of a block are decoded in the stock order; the tile before the
# (already decoded) last one would overwrite the head of the last tile with its overrun: those 16 bytes are saved
# and restored around it.  So every block holds exactly the stock bytes before anything reads it.
# Deferral only in the fight phase (0x80070778 == 8) and after an arena init (INIT clears everything).
#
# RAM block ahd (in the EXE, zero at load): +0 mode (1 = inside a deferred 0x80084ab8)  +4 tiles seen  +8/+0xc/+0x10
#   last tile src/dst/n  +0x14 cursors in use  +0x18 initialised (set by INIT)
# Scratchpad (the game uses 0x000-0x0ff, the DSM1/DSH1 decoders 0x300-0x3ff; undefined until INIT):
#   0x118-0x127 16-byte save   0x128 + 32 * k (k < NK): cursor slot k (free: +0 == 0)
#   cursor: +0 arena block  +4 next part header  +8 sec1 table  +12 pixel section  +16 u16 parts left
#           +18 u16 offset in block  +20 u16 tiles left  +22 u16 rate (cycles/byte)  +24 VRAM node  +28 node block
#   0x2e0.. statistics (words, wrap): +0 blocks deferred, +4 tiles deferred, +8 tiles in slices, +0xc tiles forced
#   (use), +0x10 cursors cancelled (free), +0x14 tiles finished at a flush, +0x18 dropped (validation)
# (constants: ahead.py DEFS)

# ---------------------------------------------------------------- next deferred tile of cursor a0, if it fits in
# a1 lines: v0 = lines charged (>= 0) or -1 (does not fit, nothing done).  A broken cursor is dropped (tiles = 0).
ah_next:
        addiu   $sp, $sp, -40
        sw      $ra, 36($sp)
        sw      $s0, 32($sp)
        sw      $s1, 28($sp)
        sw      $s2, 24($sp)
        sw      $s3, 20($sp)
        move    $s0, $a0
        lw      $t0, 0($s0)                     # validation: node -> node block -> arena block, allocated
        lw      $t1, 24($s0)
        lw      $t2, 28($s0)
        lw      $t1, 0x1c($t1)
        lbu     $t3, 8($t0)
        bne     $t1, $t2, ah_nbad
        lw      $t2, 8($t2)
        xori    $t3, $t3, 1
        bne     $t2, $t0, ah_nbad
        nop
        bnez    $t3, ah_nbad
        nop
1:      lhu     $t1, 16($s0)                    # parts left
        lw      $t0, 4($s0)                     # part header
        beqz    $t1, ah_nbad
        nop
        lbu     $t3, 1($t0)
        lbu     $t4, 2($t0)
        lbu     $t2, 0($t0)                     # b0 (0x80: no tile)
        sll     $t4, $t4, 8
        or      $t3, $t3, $t4                   # b1 | b2 << 8
        srl     $t4, $t3, 12
        andi    $t4, $t4, 3                     # y mode
        srl     $t5, $t3, 14                    # x mode
        xori    $t4, $t4, 3
        sltiu   $t4, $t4, 1
        xori    $t5, $t5, 3
        sltiu   $t5, $t5, 1
        addu    $t4, $t4, $t5
        addiu   $t4, $t4, 6                     # header length 6 / 7 / 8
        andi    $t2, $t2, 0x80
        beqz    $t2, 2f
        addu    $s1, $t0, $t4                   # next header
        sw      $s1, 4($s0)
        addiu   $t1, $t1, -1
        b       1b
        sh      $t1, 16($s0)
2:      andi    $t3, $t3, 0xfff                 # tile index
        lw      $t5, 8($s0)
        sll     $t3, $t3, 2
        addu    $t5, $t5, $t3
        lw      $t5, 0($t5)                     # tile header
        lw      $t7, 12($s0)                    # pixel section
        srl     $t8, $t5, 24
        andi    $t9, $t8, 15
        addiu   $t9, $t9, 1
        sll     $t9, $t9, 3                     # bytes per row
        andi    $t8, $t8, 0xf0
        addiu   $t8, $t8, 0x10
        andi    $t8, $t8, 0xff                  # rows (u8, as the stock parser stores it)
        multu   $t9, $t8
        sll     $t5, $t5, 10
        srl     $t5, $t5, 10
        lhu     $t6, 22($s0)                    # rate
        addu    $s2, $t7, $t5                   # src
        mflo    $s3                             # n
        j       ah_tile                         # (chunk E)
        nop
ah_nbad:
        j       ah_bad
        nop

# ---------------------------------------------------------------- ah_next, part 2: s0 cursor, s1 next header,
# s2 src, s3 n, t6 rate, a1 budget
ah_tile:
        multu   $s3, $t6
        lhu     $t8, 18($s0)                    # offset in the block
        lw      $t9, 0($s0)
        mflo    $t6
        srl     $t6, $t6, 11
        addiu   $t6, $t6, 1                     # lines (2048 cycles each, conservative)
        slt     $t5, $a1, $t6
        bnez    $t5, 80f                        # does not fit
        lhu     $t5, 0x10($t9)                  # block size
        addu    $t4, $t8, $s3
        sltu    $t5, $t5, $t4
        bnez    $t5, ah_bad                     # would leave the block: broken cursor
        sw      $t6, 16($sp)
        lw      $t9, 0xc($t9)                   # block offset in the arena
        lhu     $t2, 20($s0)
        sw      $s1, 4($s0)                     # commit the part
        sh      $t4, 18($s0)
        lhu     $t1, 16($s0)
        addiu   $t2, $t2, -1
        sh      $t2, 20($s0)
        addiu   $t1, $t1, -1
        sh      $t1, 16($s0)
        lui     $a1, 0x8008
        addiu   $a1, $a1, 0x7e10
        addu    $a1, $a1, $t9
        addu    $a1, $a1, $t8                   # dst
        move    $a0, $s2
        move    $a2, $s3
        bnez    $t2, 5f                         # the tile before the decoded last one: keep its head
        addu    $s1, $a1, $s3
        lw      $t0, 0($s1)
        lw      $t1, 4($s1)
        lw      $t2, 8($s1)
        lw      $t3, 12($s1)
        lui     $t4, 0x1f80
        sw      $t0, 0x118($t4)
        sw      $t1, 0x11c($t4)
        sw      $t2, 0x120($t4)
        jal     DEC
        sw      $t3, 0x124($t4)
        lui     $t4, 0x1f80
        lw      $t0, 0x118($t4)
        lw      $t1, 0x11c($t4)
        lw      $t2, 0x120($t4)
        lw      $t3, 0x124($t4)
        sw      $t0, 0($s1)
        sw      $t1, 4($s1)
        sw      $t2, 8($s1)
        b       6f
        sw      $t3, 12($s1)
5:      jal     DEC
        nop
6:      b       ah_ret
        lw      $v0, 16($sp)
80:     b       ah_ret
        addiu   $v0, $zero, -1
ah_bad: sh      $zero, 20($s0)                  # broken: drop the rest
        move    $v0, $zero
        .if STATS
        lui     $t0, 0x1f80
        lw      $t1, ST+0x18($t0)
        nop
        addiu   $t1, $t1, 1
        sw      $t1, ST+0x18($t0)
        .endif
ah_ret: lw      $ra, 36($sp)
        lw      $s0, 32($sp)
        lw      $s1, 28($sp)
        lw      $s2, 24($sp)
        lw      $s3, 20($sp)
        jr      $ra
        addiu   $sp, $sp, 40
# ---------------------------------------------------------------- remove cursor a0
ah_rm:
        la      $t9, ahd
        lw      $t1, 0x14($t9)
        sw      $zero, 0($a0)
        addiu   $t1, $t1, -1
        jr      $ra
        sw      $t1, 0x14($t9)

# ---------------------------------------------------------------- make a cursor (tail of ah_d2: t1 = tiles left,
# s0 = queue entry; frame of ah_d2 on the stack)
ah_mk:
        lui     $t0, 0x1f80
        addiu   $t4, $t0, CUR
1:      lw      $t2, 0($t4)                     # free slot (there is one: fewer than NK in use)
        addiu   $t4, $t4, 32
        bnez    $t2, 1b
        nop
        addiu   $t4, $t4, -32
        la      $t9, ahd
        lw      $t2, 0x14($t9)
        sh      $zero, 18($t4)
        addiu   $t2, $t2, 1
        sw      $t2, 0x14($t9)
        .if STATS
        lw      $t3, ST+0($t0)
        nop
        addiu   $t3, $t3, 1
        sw      $t3, ST+0($t0)
        lw      $t3, ST+4($t0)
        nop
        addu    $t3, $t3, $t1
        sw      $t3, ST+4($t0)
        .endif
        sh      $t1, 20($t4)
        lhu     $t2, 0xc($s0)                   # parts
        lbu     $t5, 0xa($s0)                   # set
        sh      $t2, 16($t4)
        sll     $t5, $t5, 2
        lui     $t6, 0x8009
        addu    $t6, $t6, $t5
        lw      $t6, 0x2bd0($t6)                # frame data of the set
        lhu     $t7, 0x10($s0)                  # predicted frame
        lui     $t8, 0x8008
        addu    $t8, $t8, $t5
        addu    $t6, $t6, $t7
        addiu   $t6, $t6, 6
        sw      $t6, 4($t4)                     # first part header
        lw      $t6, 0x7da0($t8)                # sec1 table
        lw      $t7, 0x7d40($t8)                # pixel section
        sw      $t6, 8($t4)
        sw      $t7, 12($t4)
        lw      $t2, 0($t7)                     # codec -> rate (cycles per byte, conservative)
        li      $t3, 0x31485344                 # 'DSH1'
        beq     $t2, $t3, 2f
        ori     $t6, $zero, 96
        li      $t3, 0x314d5344                 # 'DSM1'
        beq     $t2, $t3, 2f
        ori     $t6, $zero, 36
        ori     $t6, $zero, 14                  # RLE
2:      lw      $t2, 4($s0)                     # object
        sh      $t6, 22($t4)
        lw      $t2, 0x64($t2)                  # VRAM node
        nop
        lw      $t7, 0x1c($t2)                  # node block of this pre-decode
        sw      $t2, 24($t4)
        lw      $t8, 8($t7)                     # arena block
        sw      $t7, 28($t4)
        j       ah_d2_ok
        sw      $t8, 0($t4)

# ---------------------------------------------------------------- D2: call of 0x80084ab8 in 0x80084cd4 (0x80084d5c)
# a0 = queue entry (VRAM node + 0x30): +4 object, +0xa set, +0xc parts, +0x10 predicted frame offset
ah_d2:
        la      $t0, ahd
        lw      $t1, 0x14($t0)
        lw      $t4, 0x18($t0)                  # initialised
        lui     $t3, 0x8007
        lbu     $t3, 0x778($t3)                 # battle phase: 8 = fighting
        sltiu   $t2, $t1, NK
        and     $t2, $t2, $t4
        xori    $t3, $t3, 8
        sltiu   $t3, $t3, 1
        and     $t2, $t2, $t3
        beqz    $t2, 7f                         # no free cursor / not fighting: stock
        ori     $t1, $zero, 1
        addiu   $sp, $sp, -32
        sw      $ra, 28($sp)
        sw      $s0, 24($sp)
        move    $s0, $a0
        sw      $t1, 0($t0)
        jal     AB8
        sw      $zero, 4($t0)
        la      $t0, ahd
        lw      $t1, 4($t0)
        bnez    $v0, 9f                         # failed: stock frees the block (nothing was decoded)
        sw      $zero, 0($t0)
        beqz    $t1, 8f
        lw      $a0, 8($t0)                     # the last tile now (its overrun leaves the block: stock time)
        lw      $a1, 0xc($t0)
        lw      $a2, 0x10($t0)
        jal     DEC
        nop
        la      $t0, ahd
        lw      $t1, 4($t0)
        nop
        addiu   $t1, $t1, -1
        beqz    $t1, 8f
        nop
        j       ah_mk                           # returns to ah_d2_ok
        nop
7:      j       AB8
        nop
8:
ah_d2_ok:
        move    $v0, $zero
9:      lw      $ra, 28($sp)
        lw      $s0, 24($sp)
        jr      $ra
        addiu   $sp, $sp, 32

# ---------------------------------------------------------------- FR: replaces jal 0x8008555c in the main loop
ah_frame:
        addiu   $sp, $sp, -24
        sw      $ra, 20($sp)
        sw      $s1, 12($sp)
        sw      $s0, 16($sp)
        lui     $s0, 0x1f80                     # the stock 0x8008555c (inlined, its range is reused):
        ori     $a0, $s0, 0x60                  #   ctx = scratchpad, ctx->4 = 0x1f800060,
        lui     $v0, 0x8009                     #   pre-decode queue entries while 0x80084cd4 returns 1
        sw      $s0, 0x2160($v0)
        sw      $a0, 4($s0)
1:      jal     0x80084cd4
        nop
        andi    $v0, $v0, 0xff                  # (s8)v0 == 1
        addiu   $v0, $v0, -1
        beqz    $v0, 1b
        nop
2:      la      $t0, ahd
        lw      $t0, 0x14($t0)
        addiu   $s1, $s0, CUR                   # first cursor in use
        beqz    $t0, 9f
        nop
3:      lw      $t0, 0($s1)
        addiu   $s1, $s1, 32
        beqz    $t0, 3b
        nop
        jal     ah_budget
        addiu   $s1, $s1, -32
        blez    $v0, 9f
        move    $a1, $v0
        jal     ah_next
        move    $a0, $s1
        bltz    $v0, 9f                         # the next tile does not fit
        nop
        .if STATS
        lw      $t0, ST+8($s0)
        nop
        addiu   $t0, $t0, 1
        sw      $t0, ST+8($s0)
        .endif
        lhu     $t1, 20($s1)
        nop
        bnez    $t1, 2b
        nop
        jal     ah_rm
        move    $a0, $s1
        b       2b
        nop
9:      lw      $ra, 20($sp)
        lw      $s0, 16($sp)
        lw      $s1, 12($sp)
        jr      $ra
        addiu   $sp, $sp, 24

# ---------------------------------------------------------------- CK: replaces jal 0x80084984 in 0x8008113c
ah_chk:
        addiu   $sp, $sp, -24
        sw      $ra, 20($sp)
        jal     CHECK
        nop
        lui     $t0, 0x8009
        lw      $t0, 0x2160($t0)                # ctx
        la      $t3, ahd
        lb      $t1, 0x49($t0)                  # 1 = use the pre-decoded frame
        lw      $t2, 0x14($t3)
        addiu   $t1, $t1, -1
        bnez    $t1, 9f
        lw      $t1, 0x44($t0)                  # VRAM node
        beqz    $t2, 9f
        nop
        lw      $t1, 0x18($t1)                  # node block in use
        nop
        beqz    $t1, 9f
        nop
        lw      $a0, 8($t1)
        jal     ah_find
        nop
        beqz    $v0, 9f
        nop
        jal     ah_fin
        move    $a0, $v0
        .if STATS
        lui     $t0, 0x1f80
        lw      $t1, ST+0xc($t0)
        nop
        addu    $t1, $t1, $v0
        sw      $t1, ST+0xc($t0)
        .endif
9:      lw      $ra, 20($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24

# ---------------------------------------------------------------- RAM state (zero in the EXE)
ahd:    .word   0, 0, 0, 0, 0, 0, 0


# ---------------------------------------------------------------- FLUSH: entry of the arena flush 0x80083a2c
# The flush frees every arena block and resets the pre-decode entries of every node in use: drop all cursors.
ah_flush:
        la      $t0, ahd
        sw      $zero, 0x14($t0)
        lui     $t0, 0x1f80
        addiu   $t1, $t0, 32 * NK
1:      addiu   $t1, $t1, -32
        bne     $t1, $t0, 1b
        sw      $zero, CUR($t1)
        addiu   $sp, $sp, -0x18                 # the stock first word (the second ran in the hook's delay slot)
        j       0x80083a34
        lui     $v1, 0x8008

# ---------------------------------------------------------------- FREE: entry of the arena block free 0x80083704
# (a0 used list, a1 free list, a2 block; leaf).  Nothing reads a freed block: cancel its cursor.
ah_free:
        la      $t0, ahd
        lw      $t1, 0x14($t0)
        lui     $t0, 0x1f80
        beqz    $t1, 9f
        addiu   $t3, $t0, CUR + 32 * NK
        beqz    $a2, 9f
        addiu   $t0, $t0, CUR
1:      lw      $t2, 0($t0)
        addiu   $t0, $t0, 32
        beq     $t2, $a2, 2f
        nop
        bne     $t0, $t3, 1b
        nop
        b       9f
        nop
2:      sw      $zero, -32($t0)
        la      $t9, ahd
        addiu   $t1, $t1, -1
        sw      $t1, 0x14($t9)
        .if STATS
        lui     $t0, 0x1f80
        lw      $t1, ST+0x10($t0)
        nop
        addiu   $t1, $t1, 1
        sw      $t1, ST+0x10($t0)
        .endif
9:      beqz    $a2, 1f                         # the two stock words (lui v1 ran in the hook's delay slot)
        lui     $v1, 0x8009
        j       0x8008370c
        nop
1:      j       0x800837b0
        nop

# ---------------------------------------------------------------- finish cursor a0 (all its tiles) and remove it
# v0 = tiles decoded.  Clobbers caller-saved registers.
ah_fin:
        addiu   $sp, $sp, -24
        sw      $ra, 20($sp)
        sw      $s0, 16($sp)
        sw      $s1, 12($sp)
        move    $s0, $a0
        move    $s1, $zero
1:      lhu     $t0, 20($s0)
        nop
        beqz    $t0, 2f
        nop
        ori     $a1, $zero, 0x7fff
        jal     ah_next
        move    $a0, $s0
        b       1b
        addiu   $s1, $s1, 1
2:      jal     ah_rm
        move    $a0, $s0
        move    $v0, $s1
        lw      $ra, 20($sp)
        lw      $s0, 16($sp)
        lw      $s1, 12($sp)
        jr      $ra
        addiu   $sp, $sp, 24
# ---------------------------------------------------------------- find the cursor of arena block a0 -> v0 (0: none)
ah_find:
        beqz    $a0, 4f
        lui     $v0, 0x1f80
        addiu   $t1, $v0, CUR + 32 * NK
        addiu   $v0, $v0, CUR
1:      lw      $t2, 0($v0)
        nop
        beq     $t2, $a0, 3f
        addiu   $v0, $v0, 32
        bne     $v0, $t1, 1b
        nop
        jr      $ra
        move    $v0, $zero
3:      jr      $ra
        addiu   $v0, $v0, -32
4:      jr      $ra
        move    $v0, $zero

# ---------------------------------------------------------------- INIT: entry of the arena init 0x80080298
ah_init:
        la      $t0, ahd
        sw      $zero, 0($t0)
        sw      $zero, 0x14($t0)
        ori     $t1, $zero, 1
        sw      $t1, 0x18($t0)
        lui     $t0, 0x1f80
        addiu   $t1, $t0, 32 * NK
1:      addiu   $t1, $t1, -32
        bne     $t1, $t0, 1b
        sw      $zero, CUR($t1)
        addiu   $sp, $sp, -0x20
        j       0x800802a0
        sw      $s1, 0x14($sp)

# ---------------------------------------------------------------- D1: decoder call inside 0x80084ab8 (0x80084c40)
ah_d1:
        la      $t0, ahd
        lw      $t1, 0($t0)
        lw      $t2, 4($t0)
        beqz    $t1, 1f
        addiu   $t2, $t2, 1
        sw      $t2, 4($t0)
        sw      $a0, 8($t0)
        sw      $a1, 0xc($t0)
        jr      $ra
        sw      $a2, 0x10($t0)
1:      j       DEC
        nop

# ---------------------------------------------------------------- v0 = hblank lines left before the deadline
ah_budget:
        lui     $t1, 0x1f80
        lhu     $t1, 0x1110($t1)                # hblank counter 1 (free running)
        lui     $t2, 0x8002
        lw      $t2, -0x2dcc($t2)               # its value at the last VSync(0) return (libetc)
        nop
        subu    $t1, $t1, $t2
        andi    $t1, $t1, 0xffff
4:      sltiu   $t3, $t1, LINES
        beqz    $t3, 4b
        addiu   $t1, $t1, -LINES
        addiu   $v0, $t1, MARGIN                # t1 = position in the frame - 263
        jr      $ra
        subu    $v0, $zero, $v0

# ---------------------------------------------------------------- PRED1: the engine's next-frame predictor for
# script type 1 (stock 0x800845cc + step 0x80084528; called from 0x80084a64).  Stock gives up at a jump record (loop
# points: the first two frames after every loop of an animation were never pre-decoded); this one follows jumps as
# the animation step 0x80049c2c does, bounded to 24 records.  a0 = object; v0 = next frame id != the current one, or -1.  Leaf.
ah_pred1:
        lw      $t0, 0x34($a0)                  # next record
        lw      $t1, 0x60($a0)                  # animation data
        lhu     $t9, 0x3c($a0)                  # frame now
        lw      $t2, 8($t1)
        lw      $t3, 4($t1)
        addu    $t2, $t2, $t1                   # frame table
        addu    $t3, $t3, $t1                   # jump base
        ori     $t8, $zero, 24
1:      lhu     $a1, 0($t0)
        lhu     $a2, 2($t0)
        addiu   $t8, $t8, -1
        bltz    $t8, 9f
        andi    $v1, $a1, 0xff
        andi    $v0, $a2, 0x7000
        srl     $v0, $v0, 4
        or      $v1, $v1, $v0
        sll     $v1, $v1, 2
        addu    $v1, $v1, $t2
        lwl     $v0, 3($v1)                     # frame id of this record (u32, any alignment)
        lwr     $v0, 0($v1)
        srl     $a1, $a1, 8                     # duration
        andi    $t7, $a2, 0x8000
        beqz    $t7, 2f
        addiu   $t0, $t0, 4
        lwl     $t4, 3($t0)                     # jump: next record = jump base + u32
        lwr     $t4, 0($t0)
        nop
        addu    $t0, $t3, $t4
2:      beqz    $a1, 1b                         # duration 0: the next record follows at once
        andi    $t4, $v0, 0xffff
        beq     $t4, $t9, 1b                    # same frame as now: look further
        nop
        jr      $ra
        nop
9:      jr      $ra
        addiu   $v0, $zero, -1

# ---------------------------------------------------------------- PRED2: the stock type-2 predictor (0x800846cc +
# step 0x80084660, 8-byte records), same result, compact (its range is reused).  Called from 0x80084a7c.
ah_pred2:
        lw      $t0, 0x30($a0)
        lhu     $t9, 0x3c($a0)
        lhu     $t1, 2($t0)
        lw      $t0, 0x34($a0)
        andi    $t1, $t1, 0x8000
        bnez    $t1, 9f
        nop
1:      lhu     $t1, 2($t0)
        lwl     $v0, 7($t0)                     # frame id = u32 at record + 4
        lwr     $v0, 4($t0)
        andi    $t1, $t1, 0x8000
        bnez    $t1, 9f
        addiu   $t0, $t0, 8
        andi    $t2, $v0, 0xffff
        beq     $t2, $t9, 1b
        nop
        jr      $ra
        nop
9:      jr      $ra
        addiu   $v0, $zero, -1

