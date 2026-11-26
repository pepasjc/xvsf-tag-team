"""MSHvSF copy (mshspeed, 2026-11-20) of the MvC L2-G runtime (games/mvc/tools/l2/g2get.py, fx worker).  MSHvSF changes:
  * image header: word 0 = magic 0x47324d53 (the EXE gate tests its upper half 'G2'), +4 entry (v1 bit 31 set = return
    the group pointer + 6, the part headers: the gate6 sites), then g2get;
  * a hit whose pool entry lies in the next DANGER bytes of the ring (the next unpacks overwrite it first) is unpacked
    again at the write position: a returned group stays intact for >= POOL - DANGER bytes of later unpacks;
  * a miss never overwrites the part headers still to be read by a live decode-ahead cursor (scratchpad
    0x1f800128 + 32 k, k < 12: +0 block != 0, +4 next header, +16 parts left, +20 tiles left): the write range moves
    behind them (bounded; NCONF counts the give-ups, must stay 0).
--- original description ---
L2-G runtime (fx worker): g2get, the MIPS side of the G2 frame-group format (games/mvc/tools/l2/g2pack.py).

Called from the per-object draw: 0x8008f694 (`nop` before `addu v0, v0, v1`) -> `jal g2get`; the delay slot still
forms v0 = sec1 base + offset, v1 = offset.  Returns v0 = pointer to the group in STOCK layout:
  * section not packed (first word != 'G2PK'): v0 unchanged (stock / effect / stage DSPs, unpacked tiers)
  * packed: per-object memo (16 slots, hash of the drawing object s1 -> tag; a hint, the key is compared) -> hit;
    else a scan of the 16 fully associative tags (key = section + offset = the stock pointer; LRU stamps) -> hit;
    else unpack: anchor binary search + span walk, decode into a 2 KB ring pool (tags overlapped by the new range are
    dropped), the LRU tag takes it.
Preserves every register except v0 / v1.  Position independent (installed 128-aligned); RAM block G2RAM right after
the code (zeroed by the installer = empty):  +0x000 16 tags x 12 B (u32 key, u16 pos, u16 end, u32 stamp)
  +0x0C0 memo 16 x 8 B (u32 key, u32 tag)  +0x140 write pos  +0x144 stamp  +0x148 misses (diagnostic)  +0x150 pool
Cost (Beetle cycle model, tools/speed/decode/cost.py): memo hit 93 cycles, miss 1.2-1.6 hblank lines (~210 / part).

    code, sym = build(org, g2ram)          python g2get.py test [ids]   (Unicorn vs g2pack, every group, all tiers)
"""
import os, sys, struct, random, re
HERE = os.path.dirname(os.path.abspath(__file__)); GAME = os.path.abspath(os.path.join(HERE, "..", "..", "..", "mvc"))   # (MvC paths for the original test)
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "speed", "frame"), os.path.join(ROOT, "tools", "speed", "decode"), HERE,
                os.path.join(ROOT, "common", "dsp")]
POOL = 2048
MEMO, WPOS, STAMP, NMISS, NCONF, LAST, LASTI, POOLAT = 0xC0, 0x140, 0x144, 0x148, 0x14C, 0x150, 0x160, 0x170
DANGER = 640                      # > largest MSHvSF group (558 B)
MAGIC = 0x47324d53
EMERG = 576                                             # emergency area behind the pool (> largest group 558 B)
RAMSIZE = POOLAT + POOL + EMERG
TABA, TABD, TABB, TABX, TABY = 16, 30, 44, 75, 106      # table offsets in the section (g2pack: A, DT, B3, X, Y)


def inline(text):
    """`jal getb / li a0, N` -> inline read of N bits at bit position t2: from the register window t3 (>= 25 valid bits
    starting at bit position a0); reload with an unaligned word (lwl / lwr) only when the field is outside it"""
    k = [0]
    def rep(m):
        lab, n = m.group(1) or "", int(m.group(2)); k[0] += 1; g = "G%d" % k[0]
        body = [f"{lab}subu  $t7, $t2, $a0", f"addiu $v1, $t7, {n}", "sltiu $v1, $v1, 26", f"bnez  $v1, {g}",
                "srl   $v1, $t2, 3", "addu  $v1, $v1, $t1", "lwl   $t3, 3($v1)", "lwr   $t3, 0($v1)",
                "andi  $t7, $t2, 7", "srlv  $t3, $t3, $t7", "move  $a0, $t2", "move  $t7, $zero",
                f"{g}:     srlv  $v1, $t3, $t7", f"andi  $v1, $v1, {(1 << n) - 1}", f"addiu $t2, $t2, {n}"]
        return "\n        ".join(body)
    return re.sub(r"(\w+:\s+)?jal   getb\n        li    \$a0, (\d+)", rep, text)


def getv(tab, l):
    """5-bit index into a byte table at section + tab (31 = escape + 8 bits) -> v1"""
    return f"""
        jal   getb
        li    $a0, 5
        li    $t7, 31
        bne   $v1, $t7, {l}a
        addu  $t7, $t0, $v1
        jal   getb
        li    $a0, 8
        b     {l}b
        nop
{l}a:   lbu   $v1, {tab}($t7)
        nop
{l}b:
"""


def coord(tab, l, mreg):
    """x or y: mode 3 -> 16 bits raw (2 bytes), else a table value (1 byte); written at t4"""
    return f"""
        li    $t7, 3
        bne   {mreg}, $t7, {l}n
        nop
        jal   getb
        li    $a0, 16
        sb    $v1, 0($t4)
        srl   $v1, $v1, 8
        sb    $v1, 1($t4)
        b     {l}d
        addiu $t4, $t4, 2
{l}n:""" + getv(tab, l + "v") + f"""
        sb    $v1, 0($t4)
        addiu $t4, $t4, 1
{l}d:
"""


def src():
    return inline(r"""
        .word MAGIC
g2ent:  bltz  $v1, g2e6                     # +4: the entry the EXE gate jumps to
        nop
        b     g2get
        nop
g2e6:   addiu $sp, $sp, -8                  # gate6: group pointer + 6 (first part header)
        sw    $ra, 0($sp)
        addiu $v0, $v0, -6                  # (the gate added 6 for its stock path)
        sll   $v1, $v1, 1
        bal   g2get
        srl   $v1, $v1, 1
        lw    $ra, 0($sp)
        addiu $v0, $v0, 6
        jr    $ra
        addiu $sp, $sp, 8
g2get:  addiu $sp, $sp, -96
        sw    $t0, 20($sp)
        sw    $t1, 24($sp)
        subu  $t0, $v0, $v1                 # section (stock sections may be unaligned: lwl / lwr)
        lwl   $t1, 3($t0)
        lwr   $t1, 0($t0)
        lui   $t0, 0x4b50
        ori   $t0, $t0, 0x3247              # 'G2PK'
        bne   $t0, $t1, g2stock
        nop
        sw    $ra, 0($sp)
        bal   g2pc                          # position independent: the RAM block follows the code
        sw    $v1, 68($sp)                  # offset
g2pc:   addiu $t1, $ra, G2RAM - g2pc        # RAM block
        lw    $ra, 0($sp)
        srl   $t0, $s1, 4                   # memo slot: hash of the drawing object (s1); a hint only, the tag
        srl   $v1, $s1, 10                  # key is compared
        xor   $t0, $t0, $v1
        andi  $t0, $t0, 15
        sll   $t0, $t0, 3
        addu  $t0, $t0, $t1
        sw    $t0, 64($sp)
        lw    $v1, MEMO($t0)                # memo key
        nop
        bne   $v1, $v0, g2scan
        lw    $v1, MEMO + 4($t0)            # memo -> tag
        nop
        lw    $t0, 0($v1)
        nop
        bne   $t0, $v0, g2scan
        lhu   $t0, 4($v1)
        nop
        addu  $t0, $t0, $t1
        lw    $t0, POOLAT - 4($t0)          # the entry's key in the pool
        nop
        bne   $t0, $v0, g2dangk             # pool overwritten (by anything): unpack again
        lhu   $t0, 4($v1)                   # danger zone: the next unpacks write here first
        lw    $v1, WPOS($t1)
        nop
        subu  $t0, $t0, $v1
        andi  $t0, $t0, POOL - 1
        sltiu $v1, $t0, DANGER
        lw    $t0, 64($sp)
        bnez  $v1, g2dang                   # (v1 = danger flag)
        nop
        lw    $v1, MEMO + 4($t0)
        lw    $t0, STAMP($t1)
        nop
        addiu $t0, $t0, 1
        sw    $t0, STAMP($t1)
        sw    $t0, 8($v1)                   # LRU stamp
        lw    $t0, 4($v1)                   # pos | end << 16: recorded as a recent return
        lw    $v1, LASTI($t1)
        nop
        addiu $v1, $v1, 4
        andi  $v1, $v1, 12
        sw    $v1, LASTI($t1)
        addu  $v1, $v1, $t1
        sw    $t0, LAST($v1)
        andi  $t0, $t0, 0xffff
        addu  $v0, $t1, $t0
        addiu $v0, $v0, POOLAT
        lw    $t0, 20($sp)
        lw    $t1, 24($sp)
        jr    $ra
        addiu $sp, $sp, 96
g2dangk: lw   $t0, 64($sp)
        nop
g2dang: lw    $v1, MEMO + 4($t0)            # drop the tag: the scan misses and unpacks it again
        nop
        sw    $zero, 0($v1)
        sw    $zero, 4($v1)
g2scan: sw    $ra, 0($sp)                   # ---- full tag scan (16, LRU victim = smallest stamp)
        sw    $a0, 4($sp)
        sw    $a1, 8($sp)
        sw    $a2, 12($sp)
        sw    $a3, 16($sp)
        sw    $t2, 28($sp)
        sw    $t3, 32($sp)
        sw    $t4, 36($sp)
        sw    $t5, 40($sp)
        sw    $t6, 44($sp)
        sw    $t7, 48($sp)
        sw    $t8, 52($sp)
        sw    $t9, 56($sp)
        move  $a1, $t1                      # RAM block
        move  $a3, $v0                      # key
        lw    $a2, 68($sp)                  # offset
        move  $t4, $a1
        addiu $t5, $a1, 16 * 12
        li    $t6, -1                       # smallest stamp so far
        move  $t3, $a1                      # victim
1:      lw    $t7, 0($t4)
        lw    $t8, 8($t4)
        beq   $t7, $a3, g2found
        sltu  $t2, $t8, $t6
        beqz  $t2, 2f
        nop
        move  $t6, $t8
        move  $t3, $t4
2:      addiu $t4, $t4, 12
        bne   $t4, $t5, 1b
        nop
        sw    $t3, 72($sp)                  # victim tag
        lw    $t7, NMISS($a1)
        nop
        addiu $t7, $t7, 1
        sw    $t7, NMISS($a1)
        subu  $t0, $a3, $a2                 # section
        b     g2miss
        nop
g2found: lhu  $t2, 4($t4)                    # key check + danger zone (as in the memo path)
        nop
        addu  $t7, $t2, $a1
        lw    $t7, POOLAT - 4($t7)
        nop
        bne   $t7, $a3, 1f
        lw    $t7, WPOS($a1)
        nop
        subu  $t2, $t2, $t7
        andi  $t2, $t2, POOL - 1
        sltiu $t2, $t2, DANGER
        beqz  $t2, g2fnd2
        nop
1:
        sw    $zero, 0($t4)
        sw    $zero, 4($t4)
        sw    $t4, 72($sp)                  # victim = this tag
        subu  $t0, $a3, $a2
        b     g2miss
        nop
g2fnd2: lw    $t7, STAMP($a1)               # scan hit: stamp, memo, return
        lw    $t5, 64($sp)
        addiu $t7, $t7, 1
        sw    $t7, STAMP($a1)
        sw    $t7, 8($t4)
        sw    $a3, MEMO($t5)
        sw    $t4, MEMO + 4($t5)
        lhu   $t2, 4($t4)
        lw    $t6, 4($t4)                   # (recorded at g2out)
        addiu $v0, $a1, POOLAT
        b     g2out
        addu  $v0, $v0, $t2
g2miss:
        # ---- miss: anchor binary search (t5 lo, t6 hi)
        lhu   $t6, 6($t0)                   # groups
        lhu   $t2, 8($t0)
        addiu $t6, $t6, 15
        srl   $t6, $t6, 4
        addiu $t6, $t6, -1
        addu  $t2, $t2, $t0                 # anchors
        move  $t5, $zero
2:      slt   $t7, $t5, $t6
        beqz  $t7, 3f
        addu  $t8, $t5, $t6
        addiu $t8, $t8, 1
        srl   $t8, $t8, 1
        sll   $t9, $t8, 2
        addu  $t9, $t9, $t2
        lhu   $t9, 0($t9)
        nop
        sltu  $t7, $a2, $t9                 # off < anchor -> hi = m - 1, else lo = m
        beqz  $t7, 21f
        nop
        b     2b
        addiu $t6, $t8, -1
21:     b     2b
        move  $t5, $t8
3:      sll   $t9, $t5, 2
        addu  $t9, $t9, $t2
        lhu   $t5, 0($t9)                   # stock offset
        lhu   $t9, 2($t9)                   # stream offset
        lhu   $t1, 10($t0)
        nop
        addu  $t1, $t1, $t9
        addu  $t1, $t1, $t0                 # record pointer
4:      bal   g2rec                         # -> t1 body, t8 length, t9 span
        nop
        sltu  $t7, $t5, $a2
        beqz  $t7, 5f
        addu  $t5, $t5, $t9
        b     4b
        addu  $t1, $t1, $t8
5:      # ---- t1 = body: n, header, bits.  Allocate need = 6 + 8 n in the pool
        lbu   $t6, 0($t1)
        li    $t7, 127
        bne   $t6, $t7, 6f
        addiu $t1, $t1, 1
        lbu   $t6, 0($t1)
        addiu $t1, $t1, 1
6:      lw    $t2, WPOS($a1)                # write pos
        sll   $t3, $t6, 3
        addiu $t3, $t3, 10                  # + the 4-byte key before the group
        addu  $t3, $t3, $t2
        sltiu $t7, $t3, POOL + 1
        bnez  $t7, 7f
        nop
        move  $t2, $zero
        sll   $t3, $t6, 3
        addiu $t3, $t3, 10                  # + the 4-byte key before the group
7:      li    $a0, 48                       # ---- keep the last 4 returned groups and live decode-ahead
70:     addiu $t4, $a1, LAST                #      cursors' part headers (<= 48 moves)
        addiu $t9, $t4, 16
75:     lw    $t5, 0($t4)                   # returned group: pos | end << 16 (pool positions, key at pos - 4)
        nop
        beqz  $t5, 76f
        srl   $t7, $t5, 16                  # end
        andi  $t5, $t5, 0xffff
        addiu $t5, $t5, -4
        sltu  $t8, $t5, $t3
        sltu  $v1, $t2, $t7
        and   $t8, $t8, $v1
        bnez  $t8, 77f
        nop
76:     addiu $t4, $t4, 4
        bne   $t4, $t9, 75b
        nop
        lui   $t4, 0x1f80
        addiu $t4, $t4, 0x128
        addiu $t9, $t4, 12 * 32
71:     lw    $t5, 0($t4)                   # cursor in use
        lhu   $t7, 20($t4)                  # tiles left
        beqz  $t5, 73f
        lw    $t5, 4($t4)                   # next part header
        beqz  $t7, 73f
        subu  $t5, $t5, $a1
        addiu $t5, $t5, -POOLAT             # pool position
        sltiu $t8, $t5, POOL
        beqz  $t8, 73f
        lhu   $t7, 16($t4)                  # parts left
        nop
        sll   $t7, $t7, 3
        addu  $t7, $t7, $t5
        addiu $t7, $t7, 8                   # end of its headers (conservative)
        sltu  $t8, $t5, $t3
        sltu  $v1, $t2, $t7
        and   $t8, $t8, $v1
        beqz  $t8, 73f
        nop
77:     subu  $v1, $t3, $t2                 # overlap: move behind it
        addiu $t7, $t7, 3
        li    $t8, -4
        and   $t2, $t7, $t8
        addu  $t3, $t2, $v1
        sltiu $t8, $t3, POOL + 1
        bnez  $t8, 72f
        nop
        move  $t2, $zero                    # wrap
        move  $t3, $v1
72:     addiu $a0, $a0, -1
        bgtz  $a0, 70b
        nop
        lw    $t7, NCONF($a1)               # gave up: the emergency area behind the pool (counted)
        subu  $v1, $t3, $t2
        addiu $t7, $t7, 1
        sw    $t7, NCONF($a1)
        li    $t2, POOL
        b     74f
        addu  $t3, $t2, $v1
73:     addiu $t4, $t4, 32
        bne   $t4, $t9, 71b
        nop
74:     move  $t4, $a1                      # evict tags overlapping [t2, t3)
8:      lw    $t8, 4($t4)                   # pos | end << 16
        nop
        andi  $t7, $t8, 0xffff
        srl   $t8, $t8, 16
        sltu  $t7, $t7, $t3
        sltu  $t8, $t2, $t8
        and   $t7, $t7, $t8
        beqz  $t7, 9f
        nop
        sw    $zero, 0($t4)
        sw    $zero, 4($t4)
9:      addiu $t4, $t4, 12
        addiu $t7, $a1, 16 * 12
        bne   $t4, $t7, 8b
        nop
        addiu $t4, $a1, POOLAT
        addu  $t4, $t4, $t2
        sw    $a3, 0($t4)                   # entry: key, then the group (a hit checks the key: pool overwritten)
        addiu $t4, $t4, 4                   # out
        addiu $t2, $t2, 4
        sw    $t2, 60($sp)                  # pos
        sb    $t6, 0($t4)
        sb    $zero, 1($t4)
        lbu   $t7, 0($t1)
        lbu   $t8, 1($t1)
        sb    $t7, 2($t4)
        sb    $t8, 3($t4)
        lbu   $t7, 2($t1)
        lbu   $t8, 3($t1)
        sb    $t7, 4($t4)
        sb    $t8, 5($t4)
        addiu $t4, $t4, 6
        addiu $t1, $t1, 4                   # bit stream
        move  $t2, $zero                    # bit position
        lui   $a0, 0x7fff                   # window start: none yet
        move  $t5, $t6                      # parts left
        move  $t6, $zero                    # previous tile
        beqz  $t5, g2done
        nop
g2part: jal   getb
        li    $a0, 3
        li    $t7, 7
        beq   $v1, $t7, 10f
        sll   $t7, $v1, 1
        addu  $t7, $t7, $t0
        lbu   $a2, TABA($t7)                # flags
        lbu   $t8, TABA + 1($t7)            # modes xm | ym << 2
        b     11f
        nop
10:     jal   getb
        li    $a0, 8
        move  $a2, $v1
        jal   getb
        li    $a0, 4
        move  $t8, $v1
11:     jal   getb
        li    $a0, 1
        bnez  $v1, 12f
        nop
        b     14f
        addiu $t6, $t6, 1
12:     jal   getb
        li    $a0, 3
        li    $t7, 7
        beq   $v1, $t7, 13f
        sll   $t7, $v1, 1
        addu  $t7, $t7, $t0
        lh    $t7, TABD($t7)
        b     14f
        addu  $t6, $t6, $t7
13:     jal   getb
        li    $a0, 12
        move  $t6, $v1
14:     andi  $t6, $t6, 0xfff
        sb    $a2, 0($t4)                   # record: flags, tile | xm << 12 | ym << 14, b3, x, y
        sb    $t6, 1($t4)
        srl   $t7, $t6, 8
        sll   $t9, $t8, 4
        or    $t7, $t7, $t9
        sb    $t7, 2($t4)
""" + getv("TABB", "bb") + r"""
        sb    $v1, 3($t4)
        addiu $t4, $t4, 4
        andi  $t9, $t8, 3
""" + coord("TABX", "xx", "$t9") + r"""
        srl   $t9, $t8, 2
""" + coord("TABY", "yy", "$t9") + r"""
        addiu $t5, $t5, -1
        bnez  $t5, g2part
        nop
g2done: lw    $t2, 60($sp)                  # ---- victim tag: key, pos, end, stamp; memo; write pos = end aligned
        addiu $t3, $a1, POOLAT
        subu  $t3, $t4, $t3                 # end
        lw    $t8, 72($sp)                  # victim
        lw    $t7, STAMP($a1)
        lw    $t5, 64($sp)                  # memo slot
        addiu $t7, $t7, 1
        sw    $t7, STAMP($a1)
        sw    $a3, 0($t8)
        sh    $t2, 4($t8)
        sh    $t3, 6($t8)
        sw    $t7, 8($t8)
        sw    $a3, MEMO($t5)
        sw    $t8, MEMO + 4($t5)
        lw    $t6, 4($t8)                   # (recorded at g2out)
        addiu $t3, $t3, 3
        li    $t7, -4
        and   $t3, $t3, $t7
        sw    $t3, WPOS($a1)
        addiu $v0, $a1, POOLAT
        b     g2out
        addu  $v0, $v0, $t2
g2out:  lw    $t7, LASTI($a1)               # recent return: pos | end << 16
        nop
        addiu $t7, $t7, 4
        andi  $t7, $t7, 12
        sw    $t7, LASTI($a1)
        addu  $t7, $t7, $a1
        sw    $t6, LAST($t7)
        lw    $ra, 0($sp)
        lw    $a0, 4($sp)
        lw    $a1, 8($sp)
        lw    $a2, 12($sp)
        lw    $a3, 16($sp)
        lw    $t2, 28($sp)
        lw    $t3, 32($sp)
        lw    $t4, 36($sp)
        lw    $t5, 40($sp)
        lw    $t6, 44($sp)
        lw    $t7, 48($sp)
        lw    $t8, 52($sp)
        lw    $t9, 56($sp)
g2stock: lw   $t0, 20($sp)
        lw    $t1, 24($sp)
        jr    $ra
        addiu $sp, $sp, 96
# ---- group record at t1 -> t1 = body, t8 = body length, t9 = stock span  (uses t7)
g2rec:  lbu   $t8, 0($t1)
        li    $t7, 255
        bne   $t8, $t7, 1f
        addiu $t1, $t1, 1
        lbu   $t8, 0($t1)
        lbu   $t7, 1($t1)
        addiu $t1, $t1, 2
        sll   $t7, $t7, 8
        or    $t8, $t8, $t7
1:      lbu   $t9, 0($t1)
        li    $t7, 255
        bne   $t9, $t7, 2f
        addiu $t1, $t1, 1
        lbu   $t9, 0($t1)
        lbu   $t7, 1($t1)
        addiu $t1, $t1, 2
        sll   $t7, $t7, 8
        jr    $ra
        or    $t9, $t9, $t7
2:      jr    $ra
        addiu $t9, $t9, 6
g2endm: .word MAGIC                         # last code word: the gate checks it too
        .align 7
G2RAM:
""")


def build(org):
    """-> (code bytes up to the RAM block, symbols); the RAM block (RAMSIZE bytes, zeroed by the installer) starts at
    sym["G2RAM"] = org + len(code) (128-aligned).  Position independent: relocate by copying."""
    from gas import gas
    s = src()
    for k, v in dict(TABA=TABA, TABD=TABD, TABB=TABB, TABX=TABX, TABY=TABY, POOLAT=POOLAT, POOL=POOL, MEMO=MEMO, WPOS=WPOS, STAMP=STAMP, NMISS=NMISS, NCONF=NCONF, LASTI=LASTI, LAST=LAST, DANGER=DANGER, MAGIC=MAGIC).items():
        s = s.replace(k, str(v))
    code, sym = gas(s, org, {})
    import dlib
    bad = dlib.hazards(code, org)
    assert not bad, bad
    code = code[:sym["G2RAM"] - org]
    return code, sym


# ------------------------------------------------------------------------------------------------ Unicorn test
ORG, SECT, STACK = 0x80010000, 0x80040000, 0x801ff000


class UC:
    def __init__(self):
        import unicorn as U, unicorn.mips_const as M
        self.U, self.M = U, M
        self.mu = U.Uc(U.UC_ARCH_MIPS, U.UC_MODE_MIPS32 | U.UC_MODE_LITTLE_ENDIAN)
        self.mu.mem_map(0, 0x200000)
        self.mu.mem_map(0x1f800000, 0x1000)                    # scratchpad (decode-ahead cursors)
        self.code, self.sym = build(ORG); self.ram = self.sym["G2RAM"]
        self.mu.mem_write(ORG & 0x1fffff, self.code)
        self.R = {n: getattr(M, "UC_MIPS_REG_" + n.upper()) for n in
                  "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split()}
        self.instr = 0
        self.mu.hook_add(U.UC_HOOK_BLOCK, lambda uc, a, sz, ud: setattr(self, "instr", self.instr + sz // 4))

    def section(self, data, at=SECT):
        self.mu.mem_write(at & 0x1fffff, data); self.mu.mem_write(self.ram & 0x1fffff, bytes(RAMSIZE))
        return at

    def call(self, base, off):
        mu, R = self.mu, self.R
        keep = {r: 0x1000 + i for i, r in enumerate("a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 t8 t9 s0 s1 s2 s3 s4 s5 s6 s7 fp gp".split())}
        for r, v in keep.items(): mu.reg_write(R[r], v)
        mu.reg_write(R["v0"], base + (off & 0x7fffffff) + (6 if off >> 31 else 0)); mu.reg_write(R["v1"], off)
        mu.reg_write(R["sp"], STACK); mu.reg_write(R["ra"], 0x80001000)
        i0 = self.instr
        mu.emu_start(self.sym[getattr(self, "entry", "g2get")], 0x80001000, count=5_000_000)
        assert mu.reg_read(self.M.UC_MIPS_REG_PC) == 0x80001000, "g2get did not return"
        for r, v in keep.items(): assert mu.reg_read(R[r]) == v, "clobbered " + r
        assert mu.reg_read(R["sp"]) == STACK
        return mu.reg_read(R["v0"]), self.instr - i0

    def read(self, a, n): return bytes(self.mu.mem_read(a & 0x1fffff, n))


def test(ids=None):
    import dsp as D, g2pack as G
    u = UC(); print("g2get code %d bytes" % len(u.code))
    td = os.path.join(GAME, "work", "stfx", "rc2tree", "games", "mvc", "work", "dsp")
    tiers = sorted(d for d in os.listdir(td) if os.path.isdir(os.path.join(td, d)) and not d.startswith(("files", "hot", "cut")))
    tot_i = tot_g = 0; worst = 0
    for c in ids or D.char_ids("mvc"):
        data, base, label = D.char_dsp("mvc", c); stock = D.DSP(data, base, label).sec[1]
        starts = [o for o, n, h, p in G.split(stock)[0]]
        for t in [None] + tiers:
            if t:
                f = os.path.join(td, t, "PL%02X_10.DSP" % c)
                if not os.path.exists(f): continue
                s = D.DSP(open(f, "rb").read(), 0).sec[1]
            else: s = stock
            pk = G.pack(s, starts); sec = u.section(pk + bytes(16))
            rnd = random.Random(c); order = starts + rnd.sample(starts, min(len(starts), 64)) * 2   # cold, then repeats (hits / evictions)
            for o in order:
                p, n = u.call(sec, o)
                g = u.read(p, 6 + 8 * 255)
                n_parts = g[0]; ln = 6; q = 6
                for k in range(n_parts): q += D.parse_part(g, q).size
                assert g[:q] == s[o:o + q], (c, t, hex(o))
                tot_i += n; tot_g += 1; worst = max(worst, n)
            if t is None:                          # stock-pointer passthrough for an unpacked section
                u.section(s); p, n = u.call(sec, starts[1]); assert p == sec + starts[1]
        print("%02x ok (%d tiers)" % (c, len(tiers)), flush=True)
    print("calls %d, avg %.0f instructions per call (cold + hits), worst %d" % (tot_g, tot_i / tot_g, worst))



def cost(ids=(1, 0xc, 6, 0x10)):
    """Beetle R3000 cycle model (tools/speed/decode/cost.py) per hit / per miss (every group once, cold) / per part"""
    import dsp as D, g2pack as G, cost as CM
    u = UC(); mu = u.mu
    rd = lambda a: struct.unpack("<I", bytes(mu.mem_read(a & 0x1fffff, 4)))[0]
    m = CM.Model()
    def hook(uc, addr, size, ud):
        info = CM.decode_at(rd, addr); sc = False
        m.step(addr, info, sc)
    mu.hook_add(u.U.UC_HOOK_CODE, hook, begin=ORG, end=ORG + len(u.code))
    for c in ids:
        data, base, label = D.char_dsp("mvc", c); s = D.DSP(data, base, label).sec[1]
        gs, _ = G.split(s); starts = [o for o, n, h, p in gs]
        pk = G.pack(s, starts); sec = u.section(pk + bytes(16))
        miss = []; parts = 0
        for o, n, h, p in gs:
            c0 = m.cyc; u.call(sec, o); miss.append(m.cyc - c0); parts += n
        c0 = m.cyc; u.call(sec, gs[-1][0]); hit = m.cyc - c0
        mm = sum(miss) / len(miss)
        print("%02x miss avg %5.0f cycles (%.2f lines) max %6d | per part %.0f | hit %d cycles" % (
            c, mm, mm / 2153, max(miss), (sum(miss) - len(miss) * 600) / parts, hit))


if __name__ == "__main__":
    if sys.argv[1:2] == ["test"]: test([int(x, 16) for x in sys.argv[2:]] or None)
    if sys.argv[1:2] == ["cost"]: cost()



MAXLIVE = int(os.environ.get("MAXLIVE", "12"))
def test_msh(ids=None, tiers=None):
    """MSHvSF: every group of every character, stock file + every tier file (packed with the stock group starts),
    through the image entry (plain and the +6 form), cold then repeated hits / danger re-unpacks; plus live cursors
    in the scratchpad: their header bytes in the pool must survive every later unpack (NCONF must stay 0)."""
    import dsp as D, g2pack as G
    MG = os.path.abspath(os.path.join(HERE, "..", ".."))
    W = os.path.join(MG, "work", "dsp")
    u = UC(); u.entry = "g2ent"; print("image %d bytes, RAM %d" % (len(u.code), RAMSIZE))
    tiers = tiers or ["dsh_cut", "dsh", "dsh_hot4", "dsh_hot8", "dsh_hot16", "dsh_hot32", "dsm", "dsm_hot16", "dsm_hot32", "dsm_hot64"]
    rd = lambda a, n: bytes(u.mu.mem_read(a & 0x1fffff if a >> 24 == 0x80 else a, n))
    tot = 0; worst = 0; tot_i = 0; emerg = [0]
    for c in ids or range(0x17):
        stock = D.DSP(open(os.path.join(W, "files", "SP_PL%02X.DSP" % c), "rb").read(), 0).sec[1]
        starts = [o for o, n, h, p in G.split(stock)[0]]
        for t in [None] + tiers:
            f = os.path.join(W, t, "SP_PL%02X.DSP" % c) if t else None
            if f and not os.path.exists(f): continue
            s = D.DSP(open(f, "rb").read(), 0).sec[1] if f else stock
            pk = G.pack(s, starts); sec = u.section(pk + bytes(16))
            u.mu.mem_write(0x1f800000, bytes(0x400))
            rnd = random.Random(c * 31 + len(tiers))
            order = starts + rnd.sample(starts, min(len(starts), 96)) * 3
            live = []                                # (cursor slot, pool addr, bytes)
            recent = []                              # the last 3 returned groups must survive the next call
            for i, o in enumerate(order):
                six = rnd.random() < 0.3
                p, n = u.call(sec, o | (0x80000000 if six else 0))
                if six: p -= 6
                g = rd(p, 6 + 8 * 255); q = 6
                for k in range(g[0] | g[1] << 8): q += D.parse_part(g, q).size
                assert g[:q] == s[o:o + q], (c, t, hex(o))
                for pp, bb in recent: assert rd(pp, len(bb)) == bb, ("recent return overwritten", c, t)
                recent = (recent + [(p, g[:q])])[-3:]
                for slot, a, b in live:
                    if rd(a, len(b)) != b:
                        nconf = struct.unpack("<I", u.read(u.ram + NCONF, 4))[0]
                        raise AssertionError(("cursor bytes overwritten", c, t, slot, "NCONF", nconf, "live", [(x[0], hex(x[1]), len(x[2])) for x in live]))
                # make / drop cursors: a cursor reads the part headers of the group just returned
                if rnd.random() < 0.15 and q > 6 and len(live) < MAXLIVE:
                    free = [k for k in range(12) if k not in [x[0] for x in live]]
                    if free:
                        k = rnd.choice(free); np_ = g[0] | g[1] << 8; skip = rnd.randrange(np_)
                        hp = p + 6; left = np_
                        for j in range(skip): hp += D.parse_part(g, hp - p).size; left -= 1
                        cur = 0x1f800128 + 32 * k
                        u.mu.mem_write(cur, struct.pack("<II", 0x80100000, hp) + bytes(8) + struct.pack("<HHH", left, 0, 1))
                        live.append((k, hp, rd(hp, p + q - hp)))
                if live and rnd.random() < 0.1:
                    k, a, b = live.pop(rnd.randrange(len(live))); u.mu.mem_write(0x1f800128 + 32 * k, bytes(32))
                if not live and rnd.random() < 0.02:   # something else writes over part of the pool (post-battle loads)
                    o2 = rnd.randrange(POOL); L2 = rnd.randrange(1, 400)
                    u.mu.mem_write((u.ram + POOLAT + o2) & 0x1fffff, bytes(rnd.randrange(256) for _ in range(min(L2, POOL - o2)))); recent = []
                tot += 1; worst = max(worst, n); tot_i += n
            nconf = struct.unpack("<I", u.read(u.ram + NCONF, 4))[0]
            emerg[0] += nconf
            if t is None:
                u.section(s); p, n = u.call(sec, starts[1]); assert p == sec + starts[1]
                p, n = u.call(sec, starts[1] | 0x80000000); assert p == sec + starts[1] + 6
        print("%02x ok" % c, flush=True)
    print("calls %d, avg %.0f instructions, worst %d, emergency-area unpacks %d (stress: up to %d live cursors)" % (tot, tot_i / tot, worst, emerg[0], MAXLIVE))


if __name__ == "__main__" and sys.argv[1:2] == ["testmsh"]:
    test_msh([int(x, 16) for x in sys.argv[2:]] or None)
