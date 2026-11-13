"""Stage BG tile layers (P/P4/STAGEn.BIN, loaded at 0x80098000): the two compiled templates that draw a 25x16 map of
16x16 SPRT prims ("7010": always rebuilds, "8306": skips the rebuild when the camera has not moved), matched in
every stage file, their per-instance constants extracted, and a register-allocated rewrite emitted in place.

    instances()                 -> [(stage, file, addr, kind, params)]
    ovl_patches()               -> {file: [(ram_addr, bytes)]}
    python bgtile.py            list the matched instances
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
P4 = os.path.join(ROOT, "disc", "files", "P", "P4")
OVL = 0x80098000
REF = {"7010": ("STAGEA.BIN", 0x80098df4, 712), "8306": ("STAGEA.BIN", 0x800990bc, 796), "6318": ("STAGE2.BIN", 0x80098a0c, 812),
       "7010c": ("STAGE6.BIN", 0x8009a700, 728)}
KINDS = ("7010", "8306", "6318", "7010c")

# parameter positions in the reference listings: (name, index of lui, index of the lo instruction) or (name, index) for a 16-bit immediate
PAR = {
    "7010": dict(addr=[("CY", 1, 2), ("WID", 3, 4), ("PREV", 10, 11), ("CX", 16, 17), ("PBASE", 18, 19), ("HEAD", 20, 21), ("MBASE", 22, 23),
                       ("MAPPTR", 34, 35), ("PBASE", 75, 76), ("PREV", 106, 107), ("PREV", 136, 137), ("PREV", 163, 164), ("HEAD", 170, 171)],
                 imm=[("CLUTOR", 116), ("RSKIP", 155)]),
    "8306": dict(addr=[("CX", 1, 2), ("CY", 3, 4), ("CXC", 5, 6), ("CYC", 14, 15), ("PREV", 19, 20), ("WID", 27, 28), ("PREV", 34, 35), ("PBASE", 39, 40),
                       ("HEAD", 41, 42), ("MBASE", 43, 44), ("CXC", 45, 46), ("CYC", 47, 48), ("MAPPTR", 55, 56), ("PBASE", 96, 97), ("PREV", 127, 128),
                       ("PREV", 157, 158), ("PREV", 184, 185), ("HEAD", 191, 192)],
                 imm=[("CLUTOR", 137), ("RSKIP", 176)]),
    # 7010 that also stores the camera into a cache (no early out)
    "7010c": dict(addr=[("CY", 1, 2), ("WID", 3, 4), ("PREV", 7, 8), ("CX", 16, 17), ("PBASE", 18, 19), ("HEAD", 20, 21), ("MBASE", 22, 23),
                        ("CYC", 26, 27), ("CXC", 30, 31), ("MAPPTR", 38, 39), ("PBASE", 79, 80), ("PREV", 110, 111), ("PREV", 140, 141),
                        ("PREV", 167, 168), ("HEAD", 174, 175)],
                  imm=[("CLUTOR", 120), ("RSKIP", 159)]),
    # 8306 with the camera fractions kept in scratchpad +0xe / +0x10
    "6318": dict(addr=[("CX", 1, 2), ("CY", 3, 4), ("CXC", 5, 6), ("CYC", 14, 15), ("PREV", 19, 20), ("PBASE", 27, 28), ("HEAD", 29, 30),
                       ("WID", 32, 33), ("PREV", 44, 45), ("CXC", 47, 48), ("CYC", 49, 50), ("MBASE", 55, 56), ("MAPPTR", 61, 62),
                       ("PBASE", 102, 103), ("PREV", 131, 132), ("PREV", 161, 162), ("PREV", 188, 189), ("HEAD", 195, 196)],
                 imm=[("CLUTOR", 141), ("RSKIP", 180)]),
}


def _w(d, a): return struct.unpack_from("<I", d, a - OVL)[0]


def _lo(w):
    v = w & 0xffff
    return v - 0x10000 if v & 0x8000 else v


def match(d, addr, kind):
    """-> params dict if the function at addr is an instance of the template, else None"""
    rf, ra, n = REF[kind]
    ref = open(os.path.join(P4, rf), "rb").read()
    if addr - OVL + n > len(d): return None
    par = {}; pos = set()
    for nm, i, j in PAR[kind]["addr"]:
        wi, wj = _w(d, addr + 4 * i), _w(d, addr + 4 * j)
        if wi >> 16 != _w(ref, ra + 4 * i) >> 16 or wj >> 16 != _w(ref, ra + 4 * j) >> 16: return None
        v = ((wi & 0xffff) << 16) + _lo(wj) & 0xffffffff
        if par.setdefault(nm, v) != v: return None
        pos |= {i, j}
    for nm, i in PAR[kind]["imm"]:
        w = _w(d, addr + 4 * i)
        if w >> 16 != _w(ref, ra + 4 * i) >> 16: return None
        par[nm] = w & 0xffff; pos.add(i)
    for k in range(n // 4):
        if k in pos: continue
        w, r = _w(d, addr + 4 * k), _w(ref, ra + 4 * k)
        if w == r: continue
        if w >> 26 == 2 and r >> 26 == 2 and (w & 0x3ffffff) - (r & 0x3ffffff) == (addr - ra) >> 2: continue    # j inside the function
        return None
    return par


def instances():
    out = []
    for st in range(11):
        f = "STAGE%X.BIN" % st
        d = open(os.path.join(P4, f), "rb").read()
        for a in range(OVL, OVL + len(d) - 8, 4):
            if _w(d, a) != 0x27bdffe8: continue
            for kind in KINDS:
                p = match(d, a, kind)
                if p: out.append((st, f, a, kind, p))
    return out


TEMPLATE = r"""
# fast tile layer, kind {kind}: same reads, same final memory (prims, links, PREV/HEAD/MAPPTR, scratchpad 0..0xd{cache}), same calls
f:
    addiu $sp, $sp, -0x18
    sw    $ra, 0x10($sp)
    lui   $t9, %hi(CX)
    lhu   $t2, %lo(CX)($t9)             # camx
    lui   $t9, %hi(CY)
    lhu   $t3, %lo(CY)($t9)             # camy
    lui   $t8, 0x1f80
    sh    $t2, 0xa($t8)
    sh    $t3, 0xc($t8)
{early}    lui   $t9, %hi(WID)
    lhu   $v0, %lo(WID)($t9)
    srl   $v1, $t3, 4
    srl   $v0, $v0, 1
    mult  $v1, $v0
{cachewr}{scrwr}    srl   $a0, $t2, 4
    sll   $a0, $a0, 1
    mflo  $t0
    addu  $a0, $a0, $t0
    sll   $a0, $a0, 1
    lui   $t9, %hi(MBASE)
    addiu $t9, $t9, %lo(MBASE)
    addu  $a0, $a0, $t9                 # a0 = map pointer
    lui   $a1, %hi(PBASE)
    addiu $a1, $a1, %lo(PBASE)          # a1 = prim of index i
    move  $a2, $zero                    # a2 = previous prim
    move  $t1, $zero                    # t1 = i
    move  $t0, $zero                    # t0 = row
    andi  $v0, $t2, 15
    subu  $t2, $zero, $v0               # t2 = -(camx & 15)
    andi  $t3, $t3, 15
    subu  $t3, $zero, $t3               # t3 = row * 16 - (camy & 15)
    lui   $t4, 0xe100
    lui   $t5, 0x00ff
    ori   $t5, $t5, 0xffff
    lui   $t6, 0xff00
    lui   $t9, CLUTOR
row:
    move  $a3, $zero                    # a3 = column (u16)
col:
    lw    $t7, 0($a0)
    nop
    andi  $v0, $t7, 0x3ff
    xori  $v1, $v0, 0x80
    bnez  $v1, emit
    srl   $t8, $t7, 16                  # run length / u | v << 8
    ori   $v1, $zero, 0x19
    sll   $v0, $a3, 16
    sra   $v0, $v0, 16
    subu  $v1, $v1, $v0                 # rest of the row
    sltu  $v0, $v1, $t8
    beqz  $v0, 1f
    sll   $v1, $v1, 2
    b     rowend
    addu  $a0, $a0, $v1
1:  addu  $a3, $a3, $t8
    andi  $a3, $a3, 0xffff
    sll   $v1, $t8, 2
    b     colchk
    addu  $a0, $a0, $v1
emit:
    sll   $v1, $v0, 22
    or    $v1, $v1, $t9
    or    $v1, $v1, $t8
    sw    $v1, 0x18($a1)                # u, v, clut
    sll   $v0, $a3, 4
    addu  $v0, $v0, $t2
    andi  $v0, $v0, 0xffff
    sll   $v1, $t3, 16
    or    $v0, $v0, $v1
    sw    $v0, 0x14($a1)                # x, y
    srl   $v0, $t7, 10
    andi  $v0, $v0, 0x3f
    addu  $v0, $v0, $t4
    sw    $v0, 4($a1)                   # tpage
    beqz  $a2, 2f
    and   $v1, $a1, $t5
    lw    $v0, 0($a2)
    nop
    and   $v0, $v0, $t6
    or    $v0, $v0, $v1
    sw    $v0, 0($a2)                   # link
2:  move  $a2, $a1
    addiu $a1, $a1, 28
    addiu $t1, $t1, 1
    addiu $a3, $a3, 1
    addiu $a0, $a0, 4
colchk:
    sll   $v0, $a3, 16
    sra   $v0, $v0, 16
    slti  $v0, $v0, 0x19
    bnez  $v0, col
    nop
rowend:
    addiu $t0, $t0, 1
    addiu $a0, $a0, RSKIP
    slti  $v0, $t0, 0x10
    bnez  $v0, row
    addiu $t3, $t3, 16
    lui   $t9, %hi(MAPPTR)
    sw    $a0, %lo(MAPPTR)($t9)
    lui   $t9, %hi(PREV)
    sw    $a2, %lo(PREV)($t9)
    lui   $v1, %hi(PBASE)
    addiu $v1, $v1, %lo(PBASE)
    lui   $t9, %hi(HEAD)
    sw    $v1, %lo(HEAD)($t9)
    lui   $t8, 0x1f80
    sh    $t1, 4($t8)
    sh    $a3, 6($t8)
    sh    $t0, 8($t8)
    beqz  $a2, done
    nop
    sw    $a2, 0($t8)
    jal   0x80015a68                    # TermPrim(PREV)
    move  $a0, $a2
draw:
    lui   $t9, %hi(HEAD)
    lw    $a0, %lo(HEAD)($t9)
    jal   0x80016a54                    # DrawOTag(HEAD)
    nop
done:
    lw    $ra, 0x10($sp)
    addiu $sp, $sp, 0x18
    jr    $ra
    nop
"""
EARLY = r"""    lui   $t9, %hi(CXC)
    lhu   $v0, %lo(CXC)($t9)
    lui   $t9, %hi(CYC)
    bne   $t2, $v0, 3f
    lhu   $v1, %lo(CYC)($t9)
    nop
    bne   $t3, $v1, 3f
    nop
    lui   $t9, %hi(PREV)
    lw    $v0, %lo(PREV)($t9)
    nop
    beqz  $v0, done
    nop
    b     draw
    nop
3:
"""
CACHEWR = r"""    lui   $t9, %hi(CXC)
    sh    $t2, %lo(CXC)($t9)
    lui   $t9, %hi(CYC)
    sh    $t3, %lo(CYC)($t9)
"""


SCRWR = r"""    andi  $v0, $t2, 15
    sh    $v0, 0xe($t8)
    andi  $v0, $t3, 15
    sh    $v0, 0x10($t8)
"""


def build(addr, kind, par):
    sys.path.insert(0, HERE)
    from gas import gas
    src = TEMPLATE.replace("{kind}", kind).replace("{cache}", ", camera cache" if kind != "7010" else "")
    early = kind in ("8306", "6318")
    src = src.replace("{early}", EARLY if early else "").replace("{cachewr}", CACHEWR if early or kind == "7010c" else "")
    src = src.replace("{scrwr}", SCRWR if kind == "6318" else "")
    src = src.replace("CLUTOR", "0x%x" % par["CLUTOR"]).replace("RSKIP", "0x%x" % par["RSKIP"])
    defs = {k: v for k, v in par.items() if k not in ("CLUTOR", "RSKIP")}
    code, sy = gas(src, addr, defs)
    n = REF[kind][2]
    assert len(code) <= n, "%s at %08x: %d > %d" % (kind, addr, len(code), n)
    return code


def ovl_patches():
    out = {}
    for st, f, a, kind, p in instances():
        out.setdefault("P/P4/" + f, []).append((a, build(a, kind, p)))
    return out


if __name__ == "__main__":
    for st, f, a, kind, p in instances():
        print(st, f, "%08x" % a, kind, " ".join("%s=%x" % kv for kv in sorted(p.items())), len(build(a, kind, p)))
