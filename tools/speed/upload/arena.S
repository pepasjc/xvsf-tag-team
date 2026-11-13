# Arena block allocator, replaces 0x80058d04 in place (entry address unchanged).
#
# Same algorithm and the same results as the original: first fit in the list of arena blocks sorted by
# start offset (head 0x8006a34c, tail 0x80069a80, pool of free block structs 0x8006a344, capacity u16
# 0x8005d95a, request = byte(S+0xe8) * byte(S+0xe9) + 16, S = *(0x8006a340) = scratchpad).
# Block struct (16 bytes): +0 prev, +4 next, +8 u8 flag, +0xa s16 start, +0xc u16 size (rounded up to 4).
#
# Speed: a hint (HINT) remembers the last block P of the list prefix in which every gap before a block is
# <= 144 bytes.  A request is at least 8*16+16 = 144 bytes (sec1 tile sizes are multiples of 16x16 pixels at
# 4 bpp) and needs a gap > request, so no request of >= 144 bytes can ever be placed before P: the scan
# starts after P.  Allocations only shrink gaps, so the hint stays valid; every place that unlinks a block
# clears HINT (sweep 0x80058f84, single frees in 0x80058424 / 0x80059e60, patched), and an empty list
# (battle init, arena flush) resets it.  Requests below 144 bytes (none seen) scan from the head.
# The original's locals in the scratchpad stack frame are not written (dead after return).

        .equ HEAD, 0x8006a34c
        .equ POOL, 0x8006a344
        .equ TAIL, 0x80069a80

        .globl alloc
alloc:                                     # entry of the original (used by the pre-decode in 0x80059e60): no waiting
        move    $t8, $zero
        nop                                # (keeps branch targets off the first two words: profiler wrappers move them)
common:
        lui     $t0, 0x8007
        lw      $t1, -0x5cc0($t0)          # S
        lw      $a1, -0x5cb4($t0)          # head
        lbu     $v0, 0xe8($t1)
        lbu     $v1, 0xe9($t1)
        lui     $t9, %hi(HINT)
        mult    $v0, $v1
        lw      $a0, %lo(HINT)($t9)        # P (0 = none)
        lui     $t1, 0x8006
        lhu     $t7, -0x26a6($t1)          # capacity (0x8005d95a)
        .if VCRES
        nop                                # (load delay)
        addiu   $t7, $t7, -VCRES           # the VRAM tile cache keeps its tables at the end of the arena
        .endif
        move    $t5, $zero                 # Q = previous block (0 = none)
        move    $t2, $zero                 # cur = end of Q
        move    $t6, $zero                 # newP = 0
        mflo    $t3
        beqz    $a1, notfound              # empty list: insert at offset 0 (hint reset below: newP = 0 = Q)
        addiu   $t3, $t3, 0x10             # need
        sltiu   $at, $t3, 144
        bnez    $at, scan                  # small request: scan from the head
        move    $t4, $a1                   # B = head
        beqz    $a0, scan
        nop
        # start after P
        lh      $v0, 0xa($a0)
        lhu     $v1, 0xc($a0)
        lw      $t4, 4($a0)                # B = P.next
        move    $t5, $a0                   # Q = P
        move    $t6, $a0                   # newP = P
        beqz    $t4, notfound
        addu    $t2, $v0, $v1              # cur = P.end

scan:   # t4 = B, t2 = cur, t5 = Q (previous visited), t6 = newP; t9 bit0: still in the small-gap prefix
        ori     $t9, $zero, 1
loop:
        lh      $v0, 0xa($t4)              # B.start
        lhu     $v1, 0xc($t4)
        subu    $at, $v0, $t2              # gap = B.start - cur
        slt     $a2, $t3, $at              # need < gap ?
        bnez    $a2, found
        slti    $a2, $at, 145
        and     $t9, $t9, $a2              # prefix continues while gap <= 144
        beqz    $t9, 1f
        lw      $a3, 4($t4)                # B.next
        move    $t6, $t4                   # newP = B
1:      move    $t5, $t4                   # Q = B
        addu    $t2, $v0, $v1              # cur = B.end
        bnez    $a3, loop
        move    $t4, $a3

notfound:                                  # append after Q (last block) if cap - cur > need
        subu    $at, $t7, $t2
        slt     $at, $t3, $at
        bnez    $at, take
        nop
        b       fail
        nop

found:  lw      $t5, 0($t4)                # Q = B.prev (as the original)

take:   # pop a block struct from the pool
        lui     $t0, 0x8007
        lw      $v0, -0x5cbc($t0)          # pool head
        nop
        beqz    $v0, fail
        nop
        lw      $v1, 4($v0)
        nop
        sw      $v1, -0x5cbc($t0)
        sw      $zero, 0($v1)              # new pool head .prev = 0 (writes address 0 when the pool is now empty, as the original)
        sw      $zero, 0($v0)
        beqz    $t5, athead
        sw      $zero, 4($v0)
        lw      $v1, 4($t5)                # insert after Q
        sw      $t5, 0($v0)
        beqz    $v1, 2f
        sw      $v1, 4($v0)
        sw      $v0, 0($v1)
2:      b       linked
        sw      $v0, 4($t5)
athead: lw      $v1, -0x5cb4($t0)          # head
        nop
        beqz    $v1, 3f
        sw      $v0, -0x5cb4($t0)          # head = N
        sw      $v0, 0($v1)                # old head.prev = N
        b       linked
        sw      $v1, 4($v0)                # N.next = old head
3:      sw      $zero, 0($v0)
        sw      $zero, 4($v0)
linked: lw      $v1, 4($v0)
        ori     $at, $zero, 1
        bnez    $v1, 4f
        sb      $at, 8($v0)                # flag = 1
        lui     $at, 0x8007
        sw      $v0, -0x6580($at)          # tail = N
4:      addiu   $v1, $t3, 3
        andi    $v1, $v1, 0xfffc
        sh      $t2, 0xa($v0)              # start = cur
        sh      $v1, 0xc($v0)              # size = need rounded up to 4
        bne     $t6, $t5, 5f               # newP == Q: the new block (gap 0) extends the prefix
        lui     $t9, %hi(HINT)
        move    $t6, $v0
5:      jr      $ra
        sw      $t6, %lo(HINT)($t9)

fail:   lui     $t9, %hi(HINT)
        sw      $t6, %lo(HINT)($t9)
        # Before failing (which makes the caller wait for the GPU and drop every cached tile): if blocks that were
        # already uploaded (flag 0) exist and no GPU transfer is pending any more, give them back now and retry once.
        andi    $at, $t8, 2
        bnez    $at, nogo                  # already retried
        lui     $t0, 0x8007
        lw      $a0, -0x5cb4($t0)          # any flag-0 block?
        nop                                # (load delay)
6:      beqz    $a0, nogo
        nop
        lbu     $at, 8($a0)
        nop
        beqz    $at, 8f                    # a flag-0 block
        nop
        lw      $a0, 4($a0)
        b       6b
        nop
8:
        andi    $at, $t8, 1
        beqz    $at, nogo                  # no-wait entry (pre-decode): fail as the original (IDLE_RECLAIM: try when idle)
        nop
        addiu   $sp, $sp, -24              # wait entry: while (DrawSync(1)) ;  as the caller would do next
        sw      $ra, 16($sp)
7:      jal     0x80016454
        ori     $a0, $zero, 1
        bnez    $v0, 7b
        nop
        lw      $ra, 16($sp)
        addiu   $sp, $sp, 24
        b       reclaim_retry
        ori     $t8, $zero, 3
idle:   lui     $t0, 0x8002                # same test as DrawSync(1) == 0, without calling it: queue empty,
        lw      $at, 0x2628($t0)           # GPU DMA idle, GPU ready for commands
        lw      $a0, 0x262c($t0)
        lw      $a1, 0x2604($t0)
        bne     $at, $a0, nogo
        lw      $a2, 0x25f8($t0)
        lw      $a1, 0($a1)                # D2_CHCR
        lw      $a2, 0($a2)                # GPUSTAT
        lui     $at, 0x0100
        and     $a1, $a1, $at
        bnez    $a1, nogo
        lui     $at, 0x0400
        and     $a2, $a2, $at
        beqz    $a2, nogo
        ori     $t8, $zero, 2
reclaim_retry:
        move    $t7, $ra
        jal     reclaim                    # leaf, t-registers only (keeps t7, t8)
        nop
        b       common
        move    $ra, $t7
nogo:   jr      $ra
        addiu   $v0, $zero, -1

        .globl alloc_w
alloc_w:                                   # entry for 0x80059564 / 0x80059930: may wait for the GPU queue (they do after a failure anyway)
        b       common
        ori     $t8, $zero, 1

        .align 2
        .globl HINT
HINT:   .word   0

# ---------------------------------------------------------------------------------------------- 0x80058f84
# End-of-frame sweep (called from 0x80057ad8), replaces the original in place: every block whose flag is 0 is
# unlinked and pushed onto the pool exactly as the original (same pointer writes and results), and the same
# scratchpad words are left: *(0x8006a340) = 0x1f800000, S+0x70 = S+0x190, S+0x178 = cursor (ends 0),
# S+0x180 = next of the last freed block (unchanged when nothing is freed).
        .org    0x280
        .globl sweep
sweep:
        lui     $t0, 0x8007
        lui     $t1, 0x1f80
        sw      $t1, -0x5cc0($t0)          # *(0x8006a340) = S
        ori     $v0, $t1, 0x190
        sw      $v0, 0x70($t1)             # scratch stack pointer = S+0x190 (as the original)
        move    $t8, $ra
        jal     reclaim
        sw      $zero, 0x178($t1)          # cursor ends 0
        beqz    $v1, 1f
        lui     $t1, 0x1f80
        sw      $v0, 0x180($t1)
1:      jr      $t8
        nop

# reclaim: unlink every flag-0 block from the list and push it on the pool (the sweep's list work), clear HINT.
# Leaf; uses at, v0, v1, a0-a3, t0-t6, t9 (keeps t7, t8).
        .globl reclaim
reclaim:
        lui     $t0, 0x8007
        lw      $a1, -0x5cb4($t0)          # head
        lui     $t9, %hi(HINT)
        sw      $zero, %lo(HINT)($t9)
        beqz    $a1, rdone
        lw      $t2, -0x6580($t0)          # tail
        lw      $t3, -0x5cbc($t0)          # pool head
        move    $t4, $a1                   # head (in a register, written back at the end)
        move    $t5, $zero                 # next of the last freed block (returned in v0)
        move    $t6, $zero                 # any freed (returned in v1)
rloop:  lbu     $v0, 8($a1)
        lw      $v1, 4($a1)                # next
        bnez    $v0, rnext
        lw      $a0, 0($a1)                # prev
        move    $t5, $v1
        ori     $t6, $zero, 1
        bne     $t2, $a1, 1f
        nop
        move    $t2, $a0                   # tail = prev
1:      bnez    $a0, 2f
        nop
        move    $t4, $v1                   # head = next
        beqz    $v1, 3f
        nop
        b       3f
        sw      $zero, 0($v1)              # next.prev = 0
2:      beqz    $v1, 4f
        nop
        sw      $a0, 0($v1)                # next.prev = prev
4:      sw      $v1, 4($a0)                # prev.next = next
3:      sw      $zero, 0($a1)              # push on the pool
        beqz    $t3, 5f
        sw      $zero, 4($a1)
        sw      $a1, 0($t3)                # pool.prev = block
        sw      $t3, 4($a1)
5:      move    $t3, $a1
rnext:  bnez    $v1, rloop
        move    $a1, $v1
        sw      $t4, -0x5cb4($t0)
        sw      $t2, -0x6580($t0)
        sw      $t3, -0x5cbc($t0)
rdone:  move    $v0, $t5
        jr      $ra
        move    $v1, $t6

