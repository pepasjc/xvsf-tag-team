# 0x800590c4-0x80059d68: arena flush + the three per-part upload loops of the sprite draw 0x80059e60,
# rewritten in place with their entry addresses unchanged:
#   0x800590c4 flush      drop every object's pre-decoded tile chain (arena flush)
#   0x800592e8            (not patched: DrawSync loop + flush + block list reset, also called from 0x800577c8)
#   0x8005935c up_cached  frame fully pre-decoded: upload every part from its cached arena block
#   0x80059564 up_partial frame partly pre-decoded: cached parts, then decode the rest
#   0x80059930 up_stream  no pre-decoded data: decode each tile into a temporary block, upload it, free it
# Same calls with the same arguments in the same order (parsers 0x80057be4 / 0x80057f48, tile decoder 0x8001b5b0,
# quad 0x80056340, 0x80055ef8, allocator, DrawSync, CD calls of set 0x37) and the same memory writes as the
# originals (the scratchpad words the callees read included); LoadImage goes through fastload (below).
# S = scratchpad 0x1f800000 (= *0x8006a340).  Scratch words: 0x38 part index, 0x48 placement cursor, 0x4c last
# placement, 0x54 sec0 cursor, 0x58 modifier stream, 0x68 tile source, 0x88 sec1 entry, 0x8c sec1 table,
# 0x90 VRAM node, 0x94 rect descriptor, 0x98 tile node, 0xe4 sec2 offset, 0xe8/0xe9 tile bytes per row / rows,
# 0xf4 tile index, 0xf6 part flags (0x80 = last part), 0x11c-0x122 LoadImage rect, 5/6 placement x/y.

        .equ TFREE, 0x80069dd0
        .equ PARSE0, 0x80057be4
        .equ PARSE1, 0x80057f48
        .equ QUAD, 0x80056340
        .equ F55EF8, 0x80055ef8
        # DECODE: the tile decoder 0x8001b5b0, or the VRAM tile cache's vc_decode_lazy; LOADIMG: fastload, or the cache's vc_load (upload.py)
        .equ DRAWSYNC, 0x80016454
        .equ FLUSHALL, 0x800592e8

# ------------------------------------------------------------------------------------------ 0x800590c4 flush
# For the four player objects and the three object lists *0x80043830 *0x80042658 *0x80042654 (linked by +0x30):
# the VRAM node (+0x70) gets its tile-node chain moved onto the free list, +0x22 = 0, +0x1e = 0xffff.
# (The original's scratchpad locals, above the scratch stack pointer and never allocated, are not written.)
        .globl flush
flush:
        addiu   $sp, $sp, -8
        sw      $ra, 0($sp)
        lui     $a0, 0x8004
        jal     fnode
        addiu   $a0, $a0, 0x2a10
        lui     $a0, 0x8004
        jal     fnode
        addiu   $a0, $a0, 0x3178
        lui     $a0, 0x8004
        jal     fnode
        addiu   $a0, $a0, 0x2d58
        lui     $a0, 0x8004
        jal     fnode
        addiu   $a0, $a0, 0x34b8
        lui     $a1, 0x8004
        lw      $a0, 0x3830($a1)
        jal     flist
        nop
        lui     $a1, 0x8004
        lw      $a0, 0x2658($a1)
        jal     flist
        nop
        lui     $a1, 0x8004
        lw      $a0, 0x2654($a1)
        lw      $ra, 0($sp)
        addiu   $sp, $sp, 8
flist:  beqz    $a0, ret                   # a0 = first object of a list (may be 0)
        nop
        move    $t8, $ra
1:      jal     fnode                      # keeps a0, t8
        nop
        lw      $a0, 0x30($a0)
        nop
        bnez    $a0, 1b
        nop
        jr      $t8
        nop
fnode:  lw      $a1, 0x70($a0)             # a0 = object; uses v0, v1, a1, a2, at
        nop
        beqz    $a1, ret
        nop
        move    $a2, $ra
        bal     chainfree
        nop
        ori     $at, $zero, 0xffff
        sh      $zero, 0x22($a1)
        jr      $a2
        sh      $at, 0x1e($a1)

# chainfree(a1 = VRAM node): if it has a tile-node chain (+0x30 head, +0x34 tail), put the chain in front of the
# free list exactly as the original code does (free.prev = tail even when the free list is empty, i.e. a write
# to address 0; tail.next = free; +0x30 = +0x34 = 0; free list = head).  Uses v0, v1, at.
chainfree:
        lw      $v0, 0x30($a1)
        lui     $v1, %hi(TFREE)
        beqz    $v0, ret
        lw      $v1, %lo(TFREE)($v1)
        lw      $at, 0x34($a1)
        nop
        sw      $at, 0($v1)
        sw      $v1, 4($at)
        lui     $v1, %hi(TFREE)
        sw      $zero, 0x30($a1)
        sw      $v0, %lo(TFREE)($v1)
        sw      $zero, 0x34($a1)
ret:    jr      $ra
        nop

# skipmod: the part's modifier byte is 0xff (part hidden): S[0x58]++, S[0x48]++.  v0 = 1 when skipped.
# Called right after PARSE0 (S[0x54] already advanced).  Uses v0, v1, a0.
skipmod:
        lw      $a0, 0x58($s0)
        nop
        beqz    $a0, 1f
        move    $v0, $zero
        lbu     $v1, 0($a0)
        ori     $at, $zero, 0xff
        bne     $v1, $at, 1f
        lw      $v1, 0x48($s0)
        addiu   $a0, $a0, 1
        addiu   $v1, $v1, 1
        sw      $a0, 0x58($s0)
        sw      $v1, 0x48($s0)
        ori     $v0, $zero, 1
1:      jr      $ra
        nop

# parts: PARSE0, S[0x54] += result, modifier check, then (not skipped) S[0x88] = S[0x8c] + 4 * S[0xf4], PARSE1.
# Returns v0 = 1 when the part is hidden (PARSE1 not called).  Non-leaf (ra in s3).
parts:  move    $s3, $ra
        jal     PARSE0
        nop
        lw      $v1, 0x54($s0)
        nop
        addu    $v1, $v1, $v0
        bal     skipmod
        sw      $v1, 0x54($s0)
        bnez    $v0, 1f
        lhu     $v0, 0xf4($s0)
        lw      $v1, 0x8c($s0)
        sll     $v0, $v0, 2
        addu    $v1, $v1, $v0
        jal     PARSE1
        sw      $v1, 0x88($s0)
        move    $v0, $zero
1:      jr      $s3
        nop

# place: S[5] = (p & 15) * 4, S[0x4c] = S[0x48], S[0x48]++, S[6] = p & 0xf0 (p = placement byte), 0x80055ef8()
# when the VRAM node's +0xb is 1, then the quad builder for the object (s1).  Non-leaf (ra in s3).
place:  lw      $v0, 0x48($s0)
        move    $s3, $ra
        lbu     $v1, 0($v0)
        sw      $v0, 0x4c($s0)
        andi    $at, $v1, 0xf
        sll     $at, $at, 2
        sb      $at, 5($s0)
        andi    $v1, $v1, 0xf0
        sb      $v1, 6($s0)
        addiu   $v0, $v0, 1
        sw      $v0, 0x48($s0)
        lw      $v0, 0x90($s0)
        nop
        lbu     $v0, 0xb($v0)
        ori     $at, $zero, 1
        bne     $v0, $at, 1f
        nop
        jal     F55EF8
        nop
1:      jal     QUAD
        move    $a0, $s1
        jr      $s3
        nop

# ------------------------------------------------------------------------------------- 0x8005935c up_cached
        .org    0x8005935c - 0x800590c4
        .globl up_cached
up_cached:
        addiu   $sp, $sp, -0x28
        sw      $s0, 0x10($sp)
        lui     $s0, 0x8007
        lw      $s0, -0x5cc0($s0)
        sw      $ra, 0x18($sp)
        sw      $s1, 0x14($sp)
        sw      $s3, 0x1c($sp)
        sw      $s2, 0x20($sp)
        lw      $v0, 0x90($s0)
        move    $s1, $a0
        .if FC                             # frame cache hit for this node: quads only
        lui     $at, %hi(FCHITA)
        lw      $at, %lo(FCHITA)($at)
        lw      $v0, 0x90($s0)
        beqz    $at, 9f
        nop
        bne     $at, $v0, 9f
        nop
        bal     fc_quads
        nop
        b       fcx_c
        nop
9:
        .endif
        lw      $v0, 0x30($v0)             # first tile node of the chain
1:      bal     parts
        sw      $v0, 0x98($s0)
        bnez    $v0, 2f
        nop
        bal     rawchk
        nop
        beqz    $v1, 5f
        move    $s2, $zero
        addiu   $s2, $v0, 4                # RAW tile: DMA from the file
5:      bal     rect
        nop
        beqz    $s2, 6f
        nop
        move    $a1, $s2
6:      lw      $v0, 0x48($s0)
        lw      $v1, 0x4c($s0)
        nop
        beq     $v0, $v1, 3f
        nop
        jal     LOADIMG
        nop
3:      bal     place
        nop
2:
        .globl pr_cached
pr_cached:
        lw      $v0, 0x98($s0)             # block flag = 0 (uploaded); a RAW tile's node has no block
        nop
        lw      $v0, 8($v0)
        nop
        beqz    $v0, 7f
        nop
        sb      $zero, 8($v0)
7:
        lhu     $v0, 0xf6($s0)
        nop
        andi    $v0, $v0, 0x80
        bnez    $v0, 4f
        lw      $v0, 0x98($s0)
        nop
        b       1b
        lw      $v0, 4($v0)                # next tile node
4:      lw      $a1, 0x90($s0)
        bal     chainfree
        nop
        .if FC
fcx_c:  jal     FC_DONE                    # frame cache: the rect holds its frame
        nop
        .endif
        lw      $ra, 0x18($sp)
        lw      $s3, 0x1c($sp)
        lw      $s2, 0x20($sp)
        lw      $s1, 0x14($sp)
        lw      $s0, 0x10($sp)
        jr      $ra
        addiu   $sp, $sp, 0x28

# rect: S[0x11c] = desc.x + (p & 15) * 4, S[0x11e] = desc.y + (p & 0xf0), S[0x120] = S[0xe8] / 2, S[0x122] = S[0xe9]
# (desc = S[0x94], p = placement byte at S[0x48]); a0 = S + 0x11c, a1 = arena + start of the tile node's block.
# Leaf; v0, v1, a0, a1, at.
rect:   lw      $v0, 0x48($s0)
        lw      $a0, 0x94($s0)
        lbu     $v1, 0($v0)
        lhu     $a1, 0x1a($a0)
        andi    $at, $v1, 0xf
        sll     $at, $at, 2
        addu    $a1, $a1, $at
        sh      $a1, 0x11c($s0)
        lhu     $a1, 0x1c($a0)
        andi    $v1, $v1, 0xf0
        addu    $a1, $a1, $v1
        sh      $a1, 0x11e($s0)
        lbu     $v0, 0xe8($s0)
        lbu     $v1, 0xe9($s0)
        srl     $v0, $v0, 1
        sh      $v0, 0x120($s0)
        sh      $v1, 0x122($s0)
        lw      $v0, 0x98($s0)
        lui     $a1, 0x8006
        lw      $v0, 8($v0)
        lw      $a1, 0xaf0($a1)            # arena base
        lh      $v0, 0xa($v0)
        addiu   $a0, $s0, 0x11c
        jr      $ra
        addu    $a1, $a1, $v0

# decode the current tile (source S[0x68]) into the tile node's block: DECODE(S[0x68], arena + start, e8 * e9)
# Tail-called (keeps the caller's ra).
dectile:
        lbu     $v0, 0xe8($s0)
        lbu     $a2, 0xe9($s0)
        lw      $v1, 0x98($s0)
        mult    $v0, $a2
        lw      $v1, 8($v1)
        lui     $a1, 0x8006
        lw      $a1, 0xaf0($a1)
        lh      $v1, 0xa($v1)
        lw      $a0, 0x68($s0)
        mflo    $a2
        j       DECODE
        addu    $a1, $a1, $v1

# rawchk: v0 = sec2 of the node's set + S[0xe4] (the tile's data), v1 = 1 when it is a RAW tile (first word
# 'XRAW', the 4 bpp pixels follow: uploaded by DMA straight from the sprite file, never decoded).  RAW tiles only
# exist above 2 MB (the 8 MB build's pre-decoded tiles): below 0x80200000 the tag is not read.  Leaf; v0, v1, at.
        .equ RAWTAG, 0x57415258
rawchk: lw      $v0, 0x90($s0)
        nop
        lbu     $v0, 0x11($v0)
        lw      $v1, 0xe4($s0)
        sll     $v0, $v0, 2
        lui     $at, 0x8006
        addu    $at, $at, $v0
        lw      $v0, -0x37d0($at)          # 0x8005c830[set]
        nop
        addu    $v0, $v0, $v1
        lui     $at, 0x8020
        sltu    $at, $v0, $at
        bnez    $at, 1f                    # in the first 2 MB: not RAW
        andi    $at, $v0, 3                # RAW tiles are word aligned (RLE / XVM1 tiles need not be)
        bnez    $at, 1f
        nop
        lw      $at, 0($v0)
        lui     $v1, 0x5741
        ori     $v1, $v1, 0x5258
        xor     $v1, $v1, $at
        jr      $ra
        sltiu   $v1, $v1, 1
1:      jr      $ra
        move    $v1, $zero

# ------------------------------------------------------------------------------------ 0x80059564 up_partial
        .globl up_partial
up_partial:
        addiu   $sp, $sp, -0x28
        sw      $s0, 0x10($sp)
        lui     $s0, 0x8007
        lw      $s0, -0x5cc0($s0)
        sw      $ra, 0x18($sp)
        sw      $s1, 0x14($sp)
        sw      $s3, 0x1c($sp)
        sw      $s2, 0x20($sp)
        lw      $v0, 0x90($s0)
        sw      $zero, 0x38($s0)           # part index
        lw      $v0, 0x30($v0)
        move    $s1, $a0
        .if FC                             # frame cache hit for this node: quads only
        lui     $at, %hi(FCHITA)
        lw      $at, %lo(FCHITA)($at)
        lw      $v0, 0x90($s0)
        beqz    $at, 9f
        nop
        bne     $at, $v0, 9f
        nop
        bal     fc_quads
        nop
        b       fcx_p
        nop
9:      lw      $v0, 0x90($s0)             # (v0 = the chain head again)
        nop
        lw      $v0, 0x30($v0)
        .endif
pl_loop:                                   # v0 = tile node
        bal     parts
        sw      $v0, 0x98($s0)
        bnez    $v0, pl_next               # hidden part
        move    $s2, $zero
        bal     rawchk
        nop
        beqz    $v1, 1f
        nop
        addiu   $s2, $v0, 4                # RAW tile: DMA from the file, no block
        lw      $a0, 0x90($s0)
        lw      $at, 0x38($s0)
        lh      $v1, 0x22($a0)
        nop
        slt     $at, $at, $v1
        bnez    $at, pl_rect               # cached part: the tile node has no block
        lw      $v1, 0x98($s0)
        sw      $v0, 0x68($s0)             # fresh part: as the original's S[0x68]; the temporary node holds no block
        b       pl_rect
        sw      $zero, 8($v1)
1:      lw      $a0, 0x90($s0)
        lw      $v0, 0x38($s0)
        lh      $v1, 0x22($a0)             # parts pre-decoded
        nop
        slt     $v0, $v0, $v1
        bnez    $v0, pl_rect               # cached
        lbu     $v0, 0x11($a0)
        .globl pr_fresh
pr_fresh:
        lw      $v1, 0xe4($s0)
        sll     $v0, $v0, 2
        lui     $at, 0x8006
        addu    $at, $at, $v0
        lw      $v0, -0x37d0($at)          # sec2 of the set (0x8005c830[set])
        nop
        addu    $v0, $v0, $v1
        jal     ALLOC_W
        sw      $v0, 0x68($s0)
        lw      $v1, 0x98($s0)
        addiu   $at, $zero, -1
        bne     $v0, $at, pl_dec
        sw      $v0, 8($v1)
        jal     FLUSHALL                   # DrawSync loop, flush, block list reset (as the inline original)
        nop
        lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)
        jal     ALLOC_W
        sw      $v0, 0x98($s0)
        lw      $v1, 0x98($s0)
        addiu   $at, $zero, -1
        bne     $v0, $at, pl_dec
        sw      $v0, 8($v1)
        .if FCBAD
        lui     $at, %hi(FCBAD)            # (frame cache: this rect does not hold its frame complete)
        sb      $at, %lo(FCBAD)($at)
        .endif
        lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)
        nop
        sw      $v0, 0x98($s0)
        b       pl_next
        sw      $zero, 8($v0)
pl_dec: jal     dectile
        nop
pl_rect:
        .globl pr_rect
pr_rect:
        bal     rect
        nop
        beqz    $s2, 2f
        nop
        move    $a1, $s2
2:      lw      $v0, 0x48($s0)
        lw      $v1, 0x4c($s0)
        nop
        beq     $v0, $v1, pl_place
        nop
        jal     LOADIMG
        nop
pl_place:
        bal     place
        nop
pl_next:
        lw      $v0, 0x98($s0)             # block flag = 0 when there is a block
        nop
        lw      $v0, 8($v0)
        nop
        lhu     $v1, 0xf6($s0)
        beqz    $v0, 1f
        nop
        sb      $zero, 8($v0)
1:      andi    $v1, $v1, 0x80
        bnez    $v1, pl_last
        lw      $v1, 0x38($s0)
        lw      $a0, 0x90($s0)
        addiu   $v1, $v1, 1
        sw      $v1, 0x38($s0)
        lh      $v0, 0x22($a0)
        nop
        slt     $v1, $v1, $v0
        beqz    $v1, 2f
        lw      $v0, 0x98($s0)
        nop
        b       pl_loop
        lw      $v0, 4($v0)                # next cached tile node
2:      bal     chainfree                  # cached parts done: chain back to the free list
        move    $a1, $a0
        lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)
        nop
        bnez    $v0, pl_loop
        nop
        lui     $at, 0x8006
        b       pl_loop
        sw      $zero, -0x37d8($at)        # 0x8005c828 = 0
pl_last:
        lw      $a1, 0x90($s0)
        bal     chainfree
        nop
        .if FC
fcx_p:  jal     FC_DONE                    # frame cache: the rect holds its frame
        nop
        .endif
        lw      $ra, 0x18($sp)
        lw      $s3, 0x1c($sp)
        lw      $s2, 0x20($sp)
        lw      $s1, 0x14($sp)
        lw      $s0, 0x10($sp)
        jr      $ra
        addiu   $sp, $sp, 0x28

# fastload(rect, data): LoadImage(rect, data) without the libgpu call chain, for the direct case only.
# When the debug level is 0, the libgpu entry points are the stock ones and (async mode) the command queue is
# empty, GPU DMA is idle and 0x80022530 == 0, libgpu's _addque2 runs the transfer at once with interrupts
# masked; this does the same hardware writes in the same order and the same RAM writes (timeout 0x8002263c /
# 0x80022640 via 0x80018d80, saved mask 0x80022630, 0x8002252c = 1, rect w/h clipped in place, GP1/GP0
# command + header + the first n%16 words by the CPU, the rest by DMA in 16-word blocks, 0x80022618/1c/20 =
# transfer fn / rect / data, mask restored).  Otherwise: the original LoadImage.
        .globl fastload
fastload:
        lui     $t0, 0x8002
        lbu     $t1, 0x2526($t0)           # debug level
        lw      $t2, 0x251c($t0)           # libgpu vector table
        bnez    $t1, slow
        lw      $t3, 0x209c($t0)           # &I_MASK
        lw      $t4, 0x20($t2)             # transfer function
        lw      $t5, 8($t2)                # _addque2
        lui     $t6, 0x8001
        ori     $t6, $t6, 0x7f24
        bne     $t4, $t6, slow
        lui     $t6, 0x8001
        ori     $t6, $t6, 0x8510
        bne     $t5, $t6, slow
        lbu     $t1, 0x2525($t0)           # async mode
        lhu     $t7, 0($t3)                # SetIntrMask(0)
        sh      $zero, 0($t3)
        beqz    $t1, direct
        nop
        lw      $t1, 0x2628($t0)
        lw      $t2, 0x262c($t0)
        lw      $t5, 0x2604($t0)
        bne     $t1, $t2, unmask           # queue not empty
        lw      $t6, 0x2530($t0)
        lw      $t5, 0($t5)                # D2_CHCR
        bnez    $t6, unmask
        lui     $t1, 0x0100
        and     $t5, $t5, $t1
        beqz    $t5, direct
        nop
unmask: sh      $t7, 0($t3)
slow:   j       0x80016718
        nop
direct: addiu   $sp, $sp, -32
        sw      $ra, 16($sp)
        sw      $a0, 20($sp)
        sw      $a1, 24($sp)
        sw      $t4, 28($sp)
        jal     0x80018d80                 # timeout = VSync(-1) + 240 (masked: the value the original keeps)
        sw      $t7, 0x2630($t0)           # saved mask
        lw      $a0, 20($sp)
        lw      $a1, 24($sp)
        lui     $t0, 0x8002
        ori     $at, $zero, 1
        sw      $at, 0x252c($t0)
        lw      $t9, 0x25f8($t0)           # &GP1 (GPUSTAT)
        lui     $t8, 0x0400
3:      lw      $at, 0($t9)                # wait: ready for a command
        nop
        and     $at, $at, $t8
        beqz    $at, 3b
        nop
        lh      $v0, 4($a0)                # the transfer function 0x80017f24: clip w, h in place
        lh      $at, 0x2528($t0)
        bltz    $v0, 4f
        move    $v1, $zero
        slt     $v1, $at, $v0
        beqz    $v1, 4f
        move    $v1, $v0
        move    $v1, $at
4:      sh      $v1, 4($a0)
        lh      $v0, 6($a0)
        lh      $at, 0x252a($t0)
        bltz    $v0, 5f
        move    $a2, $zero
        slt     $a2, $at, $v0
        beqz    $a2, 5f
        move    $a2, $v0
        move    $a2, $at
5:      mult    $v1, $a2
        sh      $a2, 6($a0)
        lw      $t1, 0x25f4($t0)           # &GP0
        mflo    $v0
        addiu   $v0, $v0, 1
        srl     $at, $v0, 31
        addu    $v0, $v0, $at
        sra     $a2, $v0, 1                # words
        blez    $a2, done                  # (the transfer function returns -1, nothing sent)
        sra     $a3, $v0, 5                # 16-word blocks
        sll     $at, $a3, 4
        subu    $a2, $a2, $at              # words sent by the CPU
6:      lw      $at, 0($t9)                # the transfer function waits again
        nop
        and     $at, $at, $t8
        beqz    $at, 6b
        lui     $at, 0x0400
        sw      $at, 0($t9)                # GP1: DMA off
        lui     $at, 0x0100
        sw      $at, 0($t1)                # GP0: clear cache
        lui     $at, 0xa000
        sw      $at, 0($t1)                # GP0: copy CPU -> VRAM
        lw      $at, 0($a0)
        lw      $v0, 4($a0)
        sw      $at, 0($t1)
        sw      $v0, 0($t1)
        beqz    $a2, 8f                    # (no I/O store in a delay slot: unicorn's MMIO hooks fault there)
        nop
7:      lw      $at, 0($a1)
        addiu   $a2, $a2, -1
        sw      $at, 0($t1)
        bnez    $a2, 7b
        addiu   $a1, $a1, 4
8:      beqz    $a3, done
        lui     $at, 0x0400
        ori     $at, $at, 2
        sw      $at, 0($t9)                # GP1: DMA CPU -> GPU
        lw      $v0, 0x25fc($t0)
        lw      $v1, 0x2600($t0)
        sw      $a1, 0($v0)                # D2_MADR
        sll     $a3, $a3, 16
        ori     $a3, $a3, 0x10
        sw      $a3, 0($v1)                # D2_BCR
        lw      $v0, 0x2604($t0)
        lui     $at, 0x0100
        ori     $at, $at, 0x201
        sw      $at, 0($v0)                # D2_CHCR: start
done:   lw      $t4, 28($sp)
        lw      $a0, 20($sp)
        lw      $a1, 24($sp)
        sw      $t4, 0x2618($t0)
        sw      $a0, 0x261c($t0)
        sw      $a1, 0x2620($t0)
        lw      $v0, 0x209c($t0)
        lhu     $at, 0x2630($t0)           # SetIntrMask(saved)
        lw      $ra, 16($sp)
        sh      $at, 0($v0)
        addiu   $sp, $sp, 32
        jr      $ra
        move    $v0, $zero


# ------------------------------------------------------------------------------------- 0x80059930 up_stream
        .globl up_stream
up_stream:
        addiu   $sp, $sp, -0x28
        sw      $s0, 0x10($sp)
        lui     $s0, 0x8007
        lw      $s0, -0x5cc0($s0)
        sw      $s1, 0x14($sp)
        sw      $s2, 0x18($sp)
        sw      $s3, 0x1c($sp)
        sw      $s4, 0x20($sp)
        sw      $ra, 0x24($sp)
        move    $s1, $a0                   # object
        .if FC                             # frame cache hit for this node: quads only
        lui     $at, %hi(FCHITA)
        lw      $at, %lo(FCHITA)($at)
        lw      $v0, 0x90($s0)
        beqz    $at, 9f
        nop
        bne     $at, $v0, 9f
        nop
        bal     fc_quads
        nop
        b       fcx_s
        nop
9:
        .endif
        lw      $a0, 0x90($s0)
        nop
        lbu     $v1, 0xf($a0)
        ori     $at, $zero, 1
        bne     $v1, $at, 1f
        ori     $v1, $zero, 2
        sb      $v1, 0xf($a0)              # node +0xf: 1 -> 2, also in the rect descriptor
        lw      $v0, 0x94($s0)
        nop
        sb      $v1, 0xf($v0)
1:      lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)       # a free tile node serves as the temporary holder
        nop
        bnez    $v0, st_loop
        nop
        jal     FLUSHALL                   # none left: DrawSync loop, flush, block list reset
        nop
        lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)
        lui     $at, 0x8006
        sw      $zero, -0x37d8($at)        # 0x8005c828 = 0
st_loop:
        sw      $v0, 0x98($s0)
st_part:
        bal     parts
        nop
        bnez    $v0, st_next               # hidden part
        lw      $v1, 0x48($s0)
        lw      $v0, 0x4c($s0)
        nop
        beq     $v1, $v0, st_place         # same placement as the previous part: no upload
        lw      $v0, 0x90($s0)
        ori     $at, $zero, 0x37
        lbu     $v1, 0x11($v0)             # set
        nop
        bne     $v1, $at, 2f
        sll     $v0, $v1, 2
        bal     cdtile                     # set 0x37: tile bytes from the CD -> v0 = S[0x6c]
        nop
        b       3f
        nop
2:      bal     rawchk                     # v0 = 0x8005c830[set] + S[0xe4]
        nop
        beqz    $v1, 3f
        nop
        sw      $v0, 0x68($s0)             # RAW tile: no block, no decode; DMA from the file
        addiu   $s2, $v0, 4
        lw      $v0, 0x98($s0)
        nop
        bal     rect
        sw      $zero, 8($v0)              # tile node: no block (the original's final state; rect reads it)
        jal     fastload
        move    $a1, $s2
        b       st_place
        nop
3:      jal     ALLOC_W
        sw      $v0, 0x68($s0)
        lw      $v1, 0x98($s0)
        addiu   $at, $zero, -1
        bne     $v0, $at, 4f
        sw      $v0, 8($v1)
        jal     FLUSHALL
        nop
        lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)
        jal     ALLOC_W
        sw      $v0, 0x98($s0)
        lw      $v1, 0x98($s0)
        addiu   $at, $zero, -1
        bne     $v0, $at, 4f
        sw      $v0, 8($v1)
        .if FCBAD
        lui     $at, %hi(FCBAD)            # (frame cache: this rect does not hold its frame complete)
        sb      $at, %lo(FCBAD)($at)
        .endif
        lui     $v0, %hi(TFREE)
        lw      $v0, %lo(TFREE)($v0)       # no room even after the flush: the part is skipped (as the original)
        b       st_next
        sw      $v0, 0x98($s0)
4:      jal     dectile
        nop
        bal     rect
        nop
        jal     LOADIMG
        nop
        lw      $v0, 0x98($s0)
        nop
        lw      $v1, 8($v0)
        nop
        sb      $zero, 8($v1)              # block flag = 0 (uploaded)
        sw      $zero, 8($v0)              # tile node: no block
st_place:
        bal     place
        nop
st_next:
        lhu     $v0, 0xf6($s0)
        nop
        andi    $v0, $v0, 0x80
        beqz    $v0, st_part
        nop
        .if FC
fcx_s:  jal     FC_DONE                    # frame cache: the rect holds its frame
        nop
        .endif
        lw      $ra, 0x24($sp)
        lw      $s4, 0x20($sp)
        lw      $s3, 0x1c($sp)
        lw      $s2, 0x18($sp)
        lw      $s1, 0x14($sp)
        lw      $s0, 0x10($sp)
        jr      $ra
        addiu   $sp, $sp, 0x28

# cdtile (set 0x37, tiles streamed from the CD): S[0x28] = S[0xe4] rounded as the original, seek + read
# e8*e9 bytes to *0x8006a354, S[0x6c] = buffer + S[0xe4] - S[0x28], wait for the read; v0 = S[0x6c].
cdtile: move    $s4, $ra
        lw      $v1, 0xe4($s0)
        nop
        andi    $v0, $v1, 7
        beqz    $v0, 1f
        sw      $v1, 0x28($s0)
        srl     $v0, $v1, 3
        sll     $v0, $v0, 3
        addiu   $v0, $v0, -8
        sw      $v0, 0x28($s0)
1:      lbu     $v1, 0xe8($s0)
        lbu     $v0, 0xe9($s0)
        nop
        mult    $v1, $v0
        lw      $a0, 0x28($s0)
        lui     $s3, 0x8007
        lw      $s3, -0x5cac($s3)          # *0x8006a354
        lui     $v0, 6
        ori     $v0, $v0, 0x8000
        addu    $a0, $a0, $v0
        mflo    $s2
        jal     0x800116c8
        sw      $s3, 0x6c($s0)
        move    $a0, $s3
        jal     0x80010a74
        move    $a1, $s2
        jal     0x80011720
        ori     $a0, $zero, 1
        lui     $v0, 0x8007
        lw      $v0, -0x5cac($v0)
        lw      $v1, 0xe4($s0)
        lw      $a0, 0x28($s0)
        addu    $v0, $v0, $v1
        subu    $v0, $v0, $a0
        sw      $v0, 0x6c($s0)
2:      jal     0x80011720
        move    $a0, $zero
        ori     $at, $zero, 1
        bne     $v0, $at, 2b
        nop
        lw      $v0, 0x6c($s0)
        jr      $s4
        nop


# frame cache hit (tools/speed/upload/fcache.c): the node's rect already holds the frame.  Its pre-decoded tile chain
# is not needed: blocks flag 0 (the sweep frees them), chain onto the free list; then the quads of every visible part
# (parts / place as the upload loops).  s0 = S, s1 = object; uses s2, s3 (saved by the calling loop).
        .if FC
fc_quads:
        move    $s2, $ra
        lw      $a1, 0x90($s0)
        nop
        lw      $v0, 0x30($a1)
        nop
1:      beqz    $v0, 2f
        nop
        lw      $v1, 8($v0)
        nop
        beqz    $v1, 3f
        nop
        sb      $zero, 8($v1)
3:      lw      $v0, 4($v0)
        b       1b
        nop
2:      bal     chainfree
        nop
4:      bal     parts
        nop
        bnez    $v0, 5f
        nop
        bal     place
        nop
5:      lhu     $v0, 0xf6($s0)
        nop
        andi    $v0, $v0, 0x80
        beqz    $v0, 4b
        nop
        jr      $s2
        nop
        .endif
