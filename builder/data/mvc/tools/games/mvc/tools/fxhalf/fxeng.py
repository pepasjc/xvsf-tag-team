"""Engine side of option B (half-resolution effect tiles drawn 2x scaled), MvC SLUS-01059.

Sprite tile pipeline (per tile of a frame group, ctx = *(0x8009c4d0) = scratchpad 0x1f800000):
  0x8008cac8  kind-8 tile-entry parser: 5 bytes -> *(ctx+4), offset & 0x3fffff -> ctx+0x30, width bytes -> ctx+0x34,
              rows -> ctx+0x35  (kind-6 entries: 0x8008ca50; group cells: 0x8008fca4 / 0x8008fe0c)
  0x8008c45c  per tile: RECT = (cell x + ctx+0x40, cell y + ctx+0x41, ctx+0x34 / 2 halfwords, ctx+0x35 rows), decode
              ctx+0x34 * ctx+0x35 bytes (0x8008c318 -> 0x8001bd48) into the staging buffer, LoadImage, draw 0x8008cb60
  0x8008cb60  draw: s6 = 2 * ctx+0x34 = width px -> ctx+0x34, s5 = rows; positions (0x8008da08 / da48 / dab4 / db18,
              flip-dependent, read ctx+0x34/0x35); UV extents from s6 / s5; corners by the vertex writers
              0x8008d2b0 / d37c / c194 / c258 (FT4 0x2d, quad builder 0x8008ced8), path 2: 0x8008d440 (SPRT16 0x7d /
              SPRT 0x65 when unscaled, else FT4 via 0x8008d68c / d704 / d750 / d79c, builder 0x8008d130 / 0x8008d6b8);
              camera zoom 0x8008d848 gets the size as arguments.
  So: texture size (VRAM rect, decode size, UV extent) = the entry's size; screen size = ctx+0x34/0x35 after the
  doubling at 0x8008cbd0.  Hitboxes are separate data (never tile sizes).

Patches
  P1 0x8008cac8 (38 words, rewritten): width byte bit 7 = half flag (masked off for everything downstream),
     rows bit 7 = narrow (only when flagged, masked off too); FLAG = flag | (flag + narrow) << 2
  P2 0x8008cbc0 -> jal S1: s6 = UV width = 2 * bytes - pad (pad = FLAG >> 1: 0, or 2 / 4 px of repeated edge),
     s5 = UV rows = rows - flag (the repeated bottom row), ctx+0x34 = s6 << flag, ctx+0x35 = s5 << flag,
     FLAG cleared (group-cell draws without a tile parse see 0)
  P3 0x8008cd88-0x8008cda0: the zoom call gets ctx+0x34 / ctx+0x35 (screen size) instead of s6 / s5 (same values unflagged)
  P4 0x8008d564 -> jal S2: a flagged tile never takes the unscaled SPRT path (screen size != UV size) -> FT4 path
  S1 0x80012670 (60 B), S2 + FLAG 0x800125c0 (44 B): dead spans of games/mvc/tools/tagload/fnscan.py
Unflagged tiles: identical results (the same values written, the same primitives).
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mipsasm
from mipsasm import Asm
for _i in range(4, 8): mipsasm.REG.setdefault("$s%d" % _i, 16 + _i)

S1_AT, S1_END = 0x80012670, 0x800126b0
S2_AT, S2_END = 0x800125c0, 0x800125f0
PARSE, PARSE_END = 0x8008cac8, 0x8008cb60
CTXP = 0x8009c4d0

R = {n: i for i, n in enumerate("zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split())}


def rv(op, rd, rt, rs):                       # sllv / srlv rd, rt, rs
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | {"sllv": 4, "srlv": 6}[op]


def hi(a): return ((a + 0x8000) >> 16) & 0xFFFF
def lo(a): return a - (hi(a) << 16) if a - (hi(a) << 16) < 0x8000 else a - (hi(a) << 16) - 0x10000


def s2():
    a = Asm(S2_AT)
    a.label("s2")
    a.lw("$t0", 0x30, "$sp")                  # 0x8008d440's frame: the caller's s6 (UV width)
    a.lbu("$t1", 0x34, "$s0")                 # screen width
    a.andi("$v1", "$s6", 0xFF)                # the replaced instructions
    a.andi("$t0", "$t0", 0xFF)
    a.bne("$t0", "$t1", "scaled")
    a.addiu("$v0", "$zero", 0x10)
    a.jr("$ra")
    a.nop()
    a.label("scaled")
    a.j(0x8008d65c)                           # epilogue of 0x8008d440 with v0 = 1 -> the FT4 path
    a.addiu("$v0", "$zero", 1)
    a.label("flag")
    a.word(0)
    return a


def build():
    b = s2(); c2 = b.assemble(); L = dict(b.labels()); FLAG = L["flag"]
    assert S2_AT + len(c2) <= S2_END
    a = Asm(S1_AT)
    a.label("s1")
    a.lbu("$v0", 0x34, "$s0")                 # texture width bytes
    a.lbu("$s5", 0x35, "$s0")                 # rows
    a.lui("$t0", hi(FLAG))
    a.lbu("$t1", lo(FLAG), "$t0")
    a.sll("$v0", "$v0", 1)
    a.andi("$t2", "$t1", 1)                   # half flag
    a.srl("$t3", "$t1", 1)                    # pad columns (0 / 2 / 4)
    a.subu("$s6", "$v0", "$t3")               # UV width px
    a.subu("$s5", "$s5", "$t2")               # UV rows: minus the pad row
    a.word(rv("sllv", "v0", "s6", "t2"))      # screen width
    a.sb("$v0", 0x34, "$s0")
    a.word(rv("sllv", "t3", "s5", "t2"))      # screen rows
    a.sb("$t3", 0x35, "$s0")
    a.jr("$ra")
    a.sb("$zero", lo(FLAG), "$t0")
    c1 = a.assemble(); assert S1_AT + len(c1) <= S1_END
    p = Asm(PARSE)
    p.lui("$a2", 0x800A)
    p.lw("$v1", -0x3B30, "$a2")               # ctx
    p.lbu("$t0", 0, "$a0")
    p.lw("$a1", 4, "$v1")                     # entry copy buffer
    p.lbu("$t1", 1, "$a0")
    p.lbu("$t2", 2, "$a0")
    p.lbu("$t3", 3, "$a0")
    p.lbu("$t4", 4, "$a0")
    p.sb("$t0", 0, "$a1")
    p.sb("$t1", 1, "$a1")
    p.sb("$t2", 2, "$a1")
    p.srl("$t5", "$t3", 7)                    # half flag
    p.andi("$t3", "$t3", 0x7F)
    p.sb("$t3", 3, "$a1")
    p.sb("$t3", 0x34, "$v1")
    p.srl("$t6", "$t4", 7)
    p.and_("$t6", "$t6", "$t5")               # narrow (rows bit 7 counts only for flagged tiles)
    p.addiu("$t7", "$zero", 0xFF)
    p.word(rv("srlv", "t7", "t7", "t5"))      # 0x7f when flagged
    p.and_("$t4", "$t4", "$t7")
    p.sb("$t4", 4, "$a1")
    p.sb("$t4", 0x35, "$v1")
    p.sll("$t1", "$t1", 8)
    p.or_("$t0", "$t0", "$t1")
    p.andi("$t2", "$t2", 0x3F)
    p.sll("$t2", "$t2", 16)
    p.or_("$t0", "$t0", "$t2")
    p.sw("$t0", 0x30, "$v1")
    p.addu("$t6", "$t6", "$t5")
    p.sll("$t6", "$t6", 2)                    # (flag + narrow) << 2 = 2 * UV width reduction (2 or 4 px)
    p.or_("$t5", "$t5", "$t6")
    p.lui("$t7", hi(FLAG))
    p.sb("$t5", lo(FLAG), "$t7")
    p.jr("$ra")
    p.or_("$v0", "$zero", "$zero")
    cp = p.assemble(); assert PARSE + len(cp) <= PARSE_END
    cp += struct.pack("<I", 0) * ((PARSE_END - PARSE - len(cp)) // 4)
    jal = lambda t: struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))
    nop = struct.pack("<I", 0)
    p3 = struct.pack("<7I", 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~)
    return [(PARSE, cp), (0x8008cbc0, jal(S1_AT) + nop * 4), (0x8008cd88, p3), (0x8008d564, jal(S2_AT) + nop),
            (S1_AT, c1), (S2_AT, c2)], FLAG


ORIG = {0x8008cbc0: [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~],
        0x~~~~~~~~: [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~],
        0x~~~~~~~~: [0x~~~~~~~~, 0x~~~~~~~~],
        0x~~~~~~~~: [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~]}


def patches():
    return build()[0]


def check_orig(read32):
    for a, ws in ORIG.items():
        for i, w in enumerate(ws):
            assert read32(a + 4 * i) == w, f"unexpected code at {a + 4 * i:08x}: {read32(a + 4 * i):08x}"


if __name__ == "__main__":
    exe = open(os.path.join(ROOT, "games", "mvc", "disc", "SLUS_010.59"), "rb").read()
    r32 = lambda a: struct.unpack_from("<I", exe, a - 0x80010000 + 0x800)[0]
    check_orig(r32)
    ps, flag = build()
    print("FLAG %08x" % flag)
    for a, d in ps:
        print("%08x %3d %s" % (a, len(d), d.hex()))
