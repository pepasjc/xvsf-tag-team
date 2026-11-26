"""MSHvSF ARCADE BALANCE (mktag.py --arcbal, needs --exopt): EX OPTIONS row "ARCADE BALANCE" OFF / ON, default OFF
(user 2026-11-22: stock PS1 values at power-on; was default ON).

Study: games/mshvsf/work/arcbal/MSH_REPORT.md (PS1 tag build vs FBNeo mshvsfu1d at matched speed).  The tag battles
already run the arcade's flag-0 rule set; what is left are unconditional port changes, all EXE words:

  M1 normal-attack meter table 0x80068634: 02 04 06 06 -> 02 06 08 08 (start / hit / victim / whiff of L / M / H normals)
  M2 block meter 0x80047c5c..0x80047c98: the hit-data flag tests in the arcade order (bit 6 -> 8, bit 4 -> 10, else the
     move's start value; specials: their meter byte), work/arcbal/blkfix.py
  M3 counter-hit bonus x34/32 tests 0x8004762c / 0x8004763c (the PS1 gave it to almost every grounded hit)
  M4 victim life-scaling (defence) per character: the PS1 has two lists (Ryu 0x80068bd8, everyone else 0x80068bc8);
     the arcade has one per character (68k 0x13ac2a, read once for this study; the values are below, no arcade data is
     read at build time).  The selector + bracket loop 0x80047874..0x800478b4 is rewritten in place (same registers out:
     v1 = factor, a2 = life, t0 scratch; the stock tail 0x800478b4.. multiplies), the data (26 B character index + 5 x 4 B
     factor rows) is a piece of the EX OPTIONS EXE pack (exopt.RANGES).
  (M5 Cyber-Akuma victim x1.5 stays: he is playable in the hack.  M6 game speed: the stock OPTION TURBO SPEED 1 already
  is the arcade's factory TURBO 7/6 - nothing here.)

Mechanism: the EXE keeps the stock words, so a cold boot is OFF (the option byte OPTB+6 is 0 at power-on, like
every EX OPTIONS byte: kept until power-off).  Changing the row on the EX OPTIONS screen (exopt.S abapply, OPE.ARC slack)
writes the ON or the stock words (runs table below, both sets) and flushes the I-cache.  No per-frame or per-hit cost.
"""
import struct

OPT = 6                                  # OPTB + 6 (0 OFF = default, 1 ON); exopt zeroes OPTB+1..+11 at build time

# ---- M4 data: per-character factor rows (life < 16, < 32, < 96, else; /32), the arcade's 0x13ac2a lists
ROWS = [(16, 20, 30, 34),                # 0 everyone (= PS1 0x80068bc8)
        (20, 26, 32, 34),                # 1 Ryu (= PS1 0x80068bd8)
        (16, 20, 30, 33),                # 2 top x33 (char id 0x00)
        (16, 20, 30, 32),                # 3 top x32 (ids 0x06, 0x0c, 0x10, 0x30)
        (16, 24, 30, 34)]                # 4 < 32 bracket x24 (ids 0x26, 0x2c)
ARC_ROW = {0x00: 2, 0x06: 3, 0x0c: 3, 0x10: 3, 0x30: 3, 0x12: 1, 0x26: 4, 0x2c: 4}   # victim obj+0x4e (= char * 2)
NCHAR = 26
STOCK_ROW = {0x12: 1}                    # the PS1 rule (for the OFF-equivalence check of the table)


def index(rowmap):
    return bytes(4 * rowmap.get(2 * c, 0) for c in range(NCHAR))


def pieces():
    """two opts.S-style pieces for exopt's EXE pack (placed independently: M4 loads each with its own lui)"""
    idx, rows = index(ARC_ROW), b"".join(bytes(r) for r in ROWS)
    def bl(d): return "".join("        .byte   %s\n" % ", ".join(str(b) for b in d[i:i + 16]) for i in range(0, len(d), 16))
    hd = "# ---------------------------------------------------------------- ARCADE BALANCE M4 (arcbal.py): "
    return (hd + "character index (row * 4 per victim obj+0x4e / 2)\n        .align  2\nabidx:\n" + bl(idx) +
            "        .align  2\n" + hd + "factor rows (life < 16, < 32, < 96, else)\n        .align  2\nabrow:\n" +
            bl(rows) + "        .align  2\n")


# Round 2 (2026-11-22) tried a per-frame RNG tick (the arcade's vblank handler 68k 0x6ca calls rand 0x192c every frame):
# present's `jal VSync` 0x800208dc -> stub {VSync(0); rand}.  Dropped: with the same seed poked before every move, ON +
# tick matched the arcade's damage LESS often (exact 2373 vs 2443 of 3036), and the only space left for its 20-24 B was a
# static-dead span 0x8002e550 that Blackheart's fights use (OFF differed from m11_c4 only in 8v9 / 9v8).  The residual
# +-1 damage is the RNG phase (every victim, both directions), not a per-character factor.


# ---- words
def _I(op, rs, rt, imm): return op << 26 | rs << 21 | rt << 16 | (imm & 0xffff)
def _R(rs, rt, rd, sa, fn): return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn
V0, V1, A0, A1, A2, T0, S1, S4, ZERO = 2, 3, 4, 5, 6, 8, 17, 20, 0

M1_AT, M1_STOCK, M1_ARC = 0x80068634, bytes.fromhex("02040606"), bytes.fromhex("02060808")
M3 = {0x8004762c: (0x14620005, 0x14620009),      # bne v1,v0 -> 0x80047644 (bonus)  => bne -> 0x80047654 (no bonus)
      0x8004763c: (0x14400005, 0x10400005)}      # bnez v0 -> 0x80047654           => beqz v0 -> 0x80047654
M2_AT = 0x80047c5c
SK = 0x5ec7a11d                              # stock words stored masked (no game words in the sources)
M2_STOCK = [w ^ SK for w in (0xcea5a10d, 0xd243a1a1, 0x4a87a111, 0x7ac55e62, 0x5ec2b09f, 0x6e85a11c, 0x4a87a11e, 0x5ec2b01f, 0x56c6be38, 0x7ac2a115, 0x6e85a11c, 0x4e87a11f, 0x7ac2a117, 0xde42a344, 0x7ac55e62, 0x5e658939)]
M4_AT = 0x80047874
M4_STOCK = [w ^ SK for w in (0xd844a153, 0xd841a349, 0x4aa5a119, 0x62c5211a, 0x62c5211a, 0x56c6bf38, 0x7a842ac5, 0x7a842ad5, 0xdaa5a11d, 0x5ec7a11d, 0x5e05b137, 0x4a87a11e, 0x5ec7a11d, 0x56c6bf38, 0x7aa4a119, 0xdaa4a11f)]


def m2_arc():
    """block-meter words in the arcade order (= work/arcbal/blkfix.py)"""
    def bnez(pc, rs, tgt): return _I(5, rs, 0, (tgt - pc - 4) >> 2)
    T = 0x80047c94
    return [_I(0x24, V1, V0, 0x10), _I(0x23, A0, A0, 0xbc), bnez(0x80047c64, V0, T), _R(0, A1, V1, 6, 2),
            _I(0xc, V1, V1, 1), bnez(0x80047c70, V1, T), _I(9, ZERO, V0, 8), _R(0, A1, V1, 4, 2),
            _I(0xc, V1, V1, 1), bnez(0x80047c80, V1, T), _I(9, ZERO, V0, 10), _I(0x20, A0, V0, 0x259),
            0, 0, _I(0xc, V0, A1, 0x7f), 0]


def _hilo(a):
    hi = (a + 0x8000) >> 16 & 0xffff
    return hi, a - (hi << 16)


def m4_arc(idx, rows):
    """0x80047874..0x800478b0: v1 = char*2 (obj+0x4e), a2 = life (obj+0x254); row = IDX[char]; factor =
    ROWS[row + (life >= 16) + (life >= 32) + (life >= 96)] (= the stock loop's bracket walk over 16 / 32 / 96 / 999)"""
    hi1, lo1 = _hilo(idx)
    hi2, lo2 = _hilo(rows + 3)
    assert -0x8000 <= lo1 and lo1 + NCHAR < 0x8000 and -0x8000 <= lo2 - 3 and lo2 + 16 < 0x8000
    return [0x8683004e,                          # 74 lh   v1,0x4e(s4)        (stock)
            0x86860254,                          # 78 lh   a2,0x254(s4)       (stock)
            _I(0xf, 0, V0, hi1),                 # 7c lui  v0,%hi(abidx)
            _R(0, V1, V1, 1, 2),                 # 80 srl  v1,v1,1            char
            _R(V1, V0, V1, 0, 0x21),             # 84 addu v1,v1,v0
            _I(0x24, V1, V1, lo1),               # 88 lbu  v1,%lo(abidx)(v1)  row * 4
            _I(0xf, 0, V0, hi2),                 # 8c lui  v0,%hi(abrow+3)
            _I(0xa, A2, T0, 16),                 # 90 slti t0,a2,16
            _R(V1, V0, V1, 0, 0x21),             # 94 addu v1,v1,v0
            _R(V1, T0, V1, 0, 0x23),             # 98 subu v1,v1,t0
            _I(0xa, A2, T0, 32),                 # 9c slti t0,a2,32
            _R(V1, T0, V1, 0, 0x23),             # a0 subu v1,v1,t0
            _I(0xa, A2, T0, 96),                 # a4 slti t0,a2,96
            _R(V1, T0, V1, 0, 0x23),             # a8 subu v1,v1,t0
            _I(0x24, V1, V1, lo2),               # ac lbu  v1,%lo(abrow+3)(v1)  factor
            0]                                   # b0 nop; b4.. stock: lw v0,(s1); nop; mult v0,v1; mflo; sra 5; sw


def words(sy):
    """{addr: (stock word, arcade word)} for every word ARCADE BALANCE changes"""
    w = {M1_AT: (struct.unpack("<I", M1_STOCK)[0], struct.unpack("<I", M1_ARC)[0])}
    w.update(M3)
    for base, st, ar in ((M2_AT, M2_STOCK, m2_arc()), (M4_AT, M4_STOCK, m4_arc(sy["abidx"], sy["abrow"]))):
        for i, (s, a) in enumerate(zip(st, ar)):
            if s != a: w[base + 4 * i] = (s, a)
    return w


def runs(sy):
    """[(addr, [stock], [arcade])] contiguous runs of changed words"""
    out = []
    W = words(sy)
    for a in sorted(W):
        s, r = W[a]
        if out and out[-1][0] + 4 * len(out[-1][1]) == a: out[-1][1].append(s); out[-1][2].append(r)
        else: out.append((a, [s], [r]))
    return out


def exe_patches(word, sy):
    """ON words for the EXE image; word(addr) = the EXE word as built so far (must be stock).  Since the default-OFF
    change exopt only calls it for the stock check and does not apply the result (cold boot = stock words)."""
    p = []
    for a, s, r in runs(sy):
        for i, x in enumerate(s):
            assert word(a + 4 * i) == x, "ARCADE BALANCE site %08x not stock: %08x" % (a + 4 * i, word(a + 4 * i))
        p.append((a, struct.pack("<%dI" % len(r), *r)))
    return p


def runtab(sy):
    """assembly for the EX OPTIONS screen's swap table: per run .word addr, n, arcade words, stock words; .word 0"""
    t = "ABRUNS:\n"
    for a, s, r in runs(sy):
        t += "        .word   0x%08x, %d\n" % (a, len(s))
        t += "        .word   %s\n" % ", ".join("0x%08x" % x for x in r)
        t += "        .word   %s\n" % ", ".join("0x%08x" % x for x in s)
    return t + "        .word   0\n"


def model(life, char2, rowmap):
    """the factor the M4 code picks (host model)"""
    r = ROWS[rowmap.get(char2, 0)]
    return r[(life >= 16) + (life >= 32) + (life >= 96)]


if __name__ == "__main__":
    # OFF-equivalence of the table itself: the stock lists through the stock walk = model with STOCK_ROW
    st = {0: [(16, 16), (32, 20), (96, 30), (999, 34)], 1: [(16, 20), (32, 26), (96, 32), (999, 34)]}
    def walk(lst, life):
        i = 0
        while life >= lst[i][0]: i += 1
        return lst[i][1]
    for c in range(NCHAR):
        for life in range(-5, 200):
            assert model(life, 2 * c, STOCK_ROW) == walk(st[1 if 2 * c == 0x12 else 0], life)
    print("table model = stock walk for the stock row map: OK")
    sy = dict(abidx=0x80022264, abrow=0x8003b7f0)
    for a, s, r in runs(sy):
        print("%08x %2d" % (a, len(s)))
    print("runs %d words" % sum(len(s) for a, s, r in runs(sy)))


CALL = """        jal     abapply                         # ARCADE BALANCE: the EXE words of the row's value (any row: cheap)
        nop
"""
CODE = r"""# ARCADE BALANCE (arcbal.py): OPTB+6 (0 OFF, 1 ON) -> copy the arcade or the stock words of every run of ABRUNS
# {addr, n, arcade words[n], stock words[n]} into the EXE, then BIOS FlushCache inside a critical section (as glue.S
# flushcache: the changed code may sit in the I-cache from the last fight).  Menu only; nothing runs per frame.
abapply: addiu  $sp, $sp, -24
        sw      $ra, 16($sp)
        lui     $t0, %hi(OPTB)
        lbu     $t1, %lo(OPTB)+6($t0)
        lui     $t2, %hi(ABRUNS)
        addiu   $t2, $t2, %lo(ABRUNS)
1:      lw      $t3, 0($t2)                     # addr (0 = end)
        lw      $t4, 4($t2)                     # n
        beqz    $t3, 4f
        sll     $t5, $t4, 2                     # bytes of one set
        addiu   $t2, $t2, 8
        move    $t6, $t2                        # the arcade set
        bnez    $t1, 2f                         # 1 = ON
        addu    $t7, $t2, $t5
        move    $t6, $t7                        # 0 = OFF (default): the stock set
2:      lw      $t8, 0($t6)
        addiu   $t6, $t6, 4
        addiu   $t4, $t4, -1
        sw      $t8, 0($t3)
        bnez    $t4, 2b
        addiu   $t3, $t3, 4
        b       1b
        addu    $t2, $t7, $t5                   # next run
4:      ori     $a0, $zero, 1
        syscall                                 # EnterCriticalSection
        ori     $t2, $zero, 0xa0
        jalr    $t2
        ori     $t1, $zero, 0x44                # A0 0x44 FlushCache
        ori     $a0, $zero, 2
        syscall                                 # ExitCriticalSection
        lw      $ra, 16($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 24
        .align  2
ABRUNS_TAB
"""
