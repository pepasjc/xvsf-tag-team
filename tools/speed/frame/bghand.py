"""Stage BG tile layers that are one-off compiled variants (not covered by the bgtile.py templates): stage 6 L1/L2/L4,
stage 7 L1/L3, stage 8 L2, the tile part of stage 0 L2.  Each rewrite keeps the stock prologue word for word (it computes the
camera, row range, caches, map pointer and stores them exactly as stock), then a bridge loads that state into
registers and a register-allocated tile loop does the rest with the same reads, the same final memory and the same
calls (TermPrim / DrawOTag with the same a0).

    HAND                      [(stage, addr, end, spec)]  end = first address not replaced
    ovl_patches()             {"P/P4/STAGEn.BIN": [(ram_addr, bytes)]}
    python bghand.py          build + sizes
"""
import os, sys, struct, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
P4 = os.path.join(ROOT, "disc", "files", "P", "P4")
OVL = 0x80098000
MAPPTR = 0x8002778c
TERMPRIM, DRAWOTAG = 0x80015a68, 0x80016a54

# spec keys:
#   k        stock words kept (prologue); repl {index: asm} replaces kept words (branches out of the prologue)
#   bridge   asm that sets t1 (prim index), t0 (first row), $at (row end), t2 = camx, t3 = camy
#            (raw values, only & 15 is used), may branch to norows itself; then the generic part follows
#   psize    16 (SPRT_16: xy +8, uv/clut +0xc) or 28 (DR_TPAGE + SPRT_16: tpage +4, xy +0x14, uv/clut +0x18)
#   pbase prev head init (PREV start value: 0 or the dummy prim) rskip clutor
#   scr      None or (size 'h'/'w', off_i, off_col, off_row): the scratchpad state words stock leaves
#   frame    True: own epilogue (whole function); else the address to continue at (a section inside a function)
SPECS = {
    # stage 6 L2: 28-byte prims, rows 0..n (n from the camera, scr+0xa), flag 0x8009e810 copies 0x80022c44 first
    (6, 0x8009a9d8): dict(n=211, k=60, repl={}, psize=28, pbase=0x8009ed84, prev=0x800aeb4c, head=0x800aeb5c, init=0,
                          rskip=0x5c, clutor=8, scr=("h", 4, 6, 8), frame=True,
                          bridge="""    lui   $t8, 0x1f80
    move  $t1, $zero
    move  $t0, $zero
    lh    $at, 0xa($t8)
    lhu   $t2, 0xc($t8)
    lhu   $t3, 0xe($t8)
"""),
    # stage 6 L4: rows r0 (scr+0xa) .. scr+0xc, prim index from 0xa0
    (6, 0x8009ad24): dict(n=220, k=62, repl={}, psize=28, pbase=0x8009ed84, prev=0x800aeb54, head=0x800aeb64, init=0,
                          rskip=0x5c, clutor=8, scr=("h", 4, 6, 8), frame=True,
                          bridge="""    lui   $t8, 0x1f80
    ori   $t1, $zero, 0xa0
    lh    $t0, 0xa($t8)
    lh    $at, 0xc($t8)
    lhu   $t2, 0xe($t8)
    lhu   $t3, 0x10($t8)
"""),
    # stage 6 L1: 16-byte prims after a dummy head, camera cache early out, rows scr+0xe .. scr+0x10
    (6, 0x8009a394): dict(n=219, k=77, repl={23: "beq $v1, $v0, done", 25: "j draw"}, psize=16, pbase=0x8009e884,
                          prev=0x800aeb48, head=0x800aeb58, init=0x800a3b64, rskip=0x5c, clutor=4, scr=("h", 4, 6, 8),
                          frame=True,
                          bridge="""    lui   $t8, 0x1f80
    move  $t1, $zero
    lh    $t0, 0xe($t8)
    lh    $at, 0x10($t8)
    lhu   $t2, 0xa($t8)
    lhu   $t3, 0xc($t8)
"""),
    # stage 7 L1: 16-byte prims after a dummy head, signed camera (+0x14), word scratch, rows 0..min(16, ..)
    (7, 0x800995a0): dict(n=192, k=68, repl={24: "beq $v1, $v0, done", 26: "j draw"}, psize=16, pbase=0x8009e124,
                          prev=0x800af59c, head=0x800af5a8, init=0x800a3d90, rskip=0x1c, clutor=4, scr=("w", 4, 8, 0xc),
                          frame=True,
                          bridge="""    lui   $t8, 0x1f80
    move  $t1, $zero
    move  $t0, $zero
    lw    $at, 0x18($t8)
    lw    $t2, 0x10($t8)
    lw    $t3, 0x14($t8)
"""),
    # stage 7 L3: 28-byte prims, word scratch, 16 rows, camera cache early out
    (7, 0x800998a0): dict(n=195, k=60, repl={25: "beqz $v0, done", 27: "j draw"}, psize=28, pbase=0x800a18ec,
                          prev=0x800af5a4, head=0x800af5b0, init=0, rskip=0x5c, clutor=0xc, scr=("w", 4, 8, 0xc),
                          frame=True,
                          bridge="""    lui   $t8, 0x1f80
    move  $t1, $zero
    move  $t0, $zero
    ori   $at, $zero, 16
    lw    $t2, 0x10($t8)
    lw    $t3, 0x14($t8)
"""),
    # stage 8 L2: 28-byte prims, 16 rows, camera window switching on 0x80041eb6 (prologue), map offset 0x800ae0d8
    (8, 0x800996d8): dict(n=286, k=144, repl={}, psize=28, pbase=0x8009f4d8, prev=0x800ae09c, head=0x800ae0a8, init=0,
                          rskip=0x11c, clutor=8, scr=("h", 4, 6, 8), frame=True,
                          bridge="""    lui   $t8, 0x1f80
    move  $t1, $zero
    move  $t0, $zero
    ori   $at, $zero, 16
    lhu   $t2, 0xa($t8)
    lhu   $t3, 0xc($t8)
"""),
    # stage 0 L2, the tile section 0x8009a5c4..0x8009a84c between the two object loops (no scratchpad; i in s1,
    # which the code after the section reassigns); camx = (0x80022c3c + 0x100) & 0x7ff in t3, camy in a0
    (0, 0x8009a5c4): dict(n=162, k=51, repl={19: "beqz $v0, done", 21: "j draw"}, psize=28, pbase=0x8009e114,
                          prev=0x800aefd0, head=0x800aefe0, init=0, rskip=0x9c, clutor=8, scr=None, frame=0x8009a84c,
                          bridge="""    move  $t2, $t3
    move  $t3, $a0
    move  $t1, $zero
    move  $t0, $zero
    ori   $at, $zero, 16
"""),
}
BODY = r"""
    # ---- generic part: a0 map, t1 i, t0 row, $at row end, t2 camx, t3 camy ----
    lui   $t9, %hi(MAPPTR)
    lw    $a0, %lo(MAPPTR)($t9)         # map pointer as the prologue left it
    lui   $t9, %hi(PREVA)
    lw    $a2, %lo(PREVA)($t9)          # PREV as the prologue left it (= INIT)
    slt   $v0, $t0, $at
    beqz  $v0, norows
{pidx}    andi  $v0, $t2, 15
    subu  $t2, $zero, $v0               # t2 = -(camx & 15)
    sll   $v1, $t0, 4
    andi  $t3, $t3, 15
    subu  $t3, $v1, $t3                 # t3 = row * 16 - (camy & 15)
    lui   $t4, 0xe100
    lui   $t5, 0x00ff
    ori   $t5, $t5, 0xffff
    lui   $t6, 0xff00
    lui   $t9, CLUTOR
row:
    move  $a3, $zero                    # a3 = column
col:
    lw    $t7, 0($a0)
    nop
    andi  $v0, $t7, 0x3ff
    xori  $v1, $v0, 0x80
    bnez  $v1, emit
    srl   $t8, $t7, 16                  # run length / u | v << 8
    ori   $v1, $zero, 0x19
    subu  $v1, $v1, $a3                 # rest of the row
    sltu  $v0, $v1, $t8
    beqz  $v0, 1f
    sll   $v1, $v1, 2
    b     rowend
    addu  $a0, $a0, $v1
1:  addu  $a3, $a3, $t8
    sll   $v1, $t8, 2
    b     colchk
    addu  $a0, $a0, $v1
emit:
    sll   $v1, $v0, 22
    or    $v1, $v1, $t9
    or    $v1, $v1, $t8
    sw    $v1, UVOFF($a1)               # u, v, clut
    sll   $v0, $a3, 4
    addu  $v0, $v0, $t2
    andi  $v0, $v0, 0xffff
    sll   $v1, $t3, 16
    or    $v0, $v0, $v1
    sw    $v0, XYOFF($a1)               # x, y
{tpage}    lw    $v0, 0($a2)
    and   $v1, $a1, $t5
    and   $v0, $v0, $t6
    or    $v0, $v0, $v1
{linkguard}    sw    $v0, 0($a2)                   # link
2:  move  $a2, $a1
    addiu $a1, $a1, PSIZE
    addiu $t1, $t1, 1
    addiu $a3, $a3, 1
    addiu $a0, $a0, 4
colchk:
    slti  $v0, $a3, 0x19
    bnez  $v0, col
    nop
rowend:
    addiu $t0, $t0, 1
    addiu $a0, $a0, RSKIP
    slt   $v0, $t0, $at
    bnez  $v0, row
    addiu $t3, $t3, 16
    lui   $t9, %hi(MAPPTR)
    sw    $a0, %lo(MAPPTR)($t9)
    lui   $t9, %hi(PREVA)
    sw    $a2, %lo(PREVA)($t9)
{scrall}{curst}    jal   TERMPRIM                      # TermPrim(PREV)
    move  $a0, $a2
draw:
    lui   $t9, %hi(HEADA)
    lw    $a0, %lo(HEADA)($t9)
    jal   DRAWOTAG                      # DrawOTag(HEAD)
    nop
done:
{epi}
norows:
{scrnorow}    b     done
    nop
"""


def _stock(st):
    return open(os.path.join(P4, "STAGE%X.BIN" % st), "rb").read()


def source(st, addr, sp):
    d = _stock(st)
    o = addr - OVL
    out = ".set noreorder\n"
    for i in range(sp["k"]):
        out += "    %s\n" % sp["repl"][i] if i in sp["repl"] else "    .word 0x%08x\n" % struct.unpack_from("<I", d, o + 4 * i)[0]
    out += sp["bridge"]
    S = sp["scr"]
    if S:
        st_ = "sh" if S[0] == "h" else "sw"
        scrall = "    lui   $t8, 0x1f80\n    %s $t1, 0x%x($t8)\n    %s $a3, 0x%x($t8)\n    %s $t0, 0x%x($t8)\n" % (st_, S[1], st_, S[2], st_, S[3])
        scrnorow = "    lui   $t8, 0x1f80\n    %s $t1, 0x%x($t8)\n    %s $t0, 0x%x($t8)\n" % (st_, S[1], st_, S[3])
        curst = "    sw    $a2, 0($t8)                   # scratch +0 = last prim\n"
    else:
        scrall = scrnorow = curst = ""
    if sp["init"]:
        guard = "    lui   $v0, %%hi(0x%x)\n    addiu $v0, $v0, %%lo(0x%x)\n    beq   $a2, $v0, done\n    nop\n" % (sp["init"], sp["init"])
    else:
        guard = "    beqz  $a2, done\n    nop\n"
    if sp["psize"] == 28:
        pidx = "    sll   $v0, $t1, 3\n    subu  $v0, $v0, $t1\n    sll   $v0, $v0, 2\n"
        tpage = "    srl   $v0, $t7, 10\n    andi  $v0, $v0, 0x3f\n    addu  $v0, $v0, $t4\n    sw    $v0, 4($a1)                   # tpage\n"
        xy, uv = 0x14, 0x18
    else:
        pidx = "    sll   $v0, $t1, 4\n"
        tpage = ""
        xy, uv = 8, 0xc
    pidx += "    lui   $a1, %%hi(0x%x)\n    addiu $a1, $a1, %%lo(0x%x)\n    addu  $a1, $a1, $v0             # a1 = prim of index i\n" % (sp["pbase"], sp["pbase"])
    if sp["init"]:
        linkguard = ""                 # PREV is never 0 (dummy head)
        tpage += ""
    else:
        linkguard = ""
        tpage += "    beqz  $a2, 2f\n    nop\n"
    if sp["frame"] is True:
        epi = "    lw    $ra, 0x10($sp)\n    addiu $sp, $sp, 0x18\n    jr    $ra\n    nop"
    else:
        epi = "    j     0x%x\n    nop" % sp["frame"]
    b = BODY.replace("{pidx}", pidx).replace("{tpage}", tpage).replace("{linkguard}", linkguard)
    b = b.replace("{scrall}", scrall + guard).replace("{curst}", curst if S else "").replace("{scrnorow}", scrnorow).replace("{epi}", epi)
    b = b.replace("CLUTOR", "0x%x" % sp["clutor"]).replace("RSKIP", "0x%x" % sp["rskip"]).replace("PSIZE", "%d" % sp["psize"])
    b = b.replace("UVOFF", "0x%x" % uv).replace("XYOFF", "0x%x" % xy)
    b = b.replace("PREVA", "0x%x" % sp["prev"]).replace("HEADA", "0x%x" % sp["head"]).replace("MAPPTR", "0x%x" % MAPPTR)
    b = b.replace("TERMPRIM", "0x%x" % TERMPRIM).replace("DRAWOTAG", "0x%x" % DRAWOTAG)
    return out + b


def build(st, addr, sp):
    sys.path.insert(0, HERE)
    from gas import gas
    code, sy = gas(source(st, addr, sp), addr)
    assert len(code) <= 4 * sp["n"], "stage %d %08x: %d > %d" % (st, addr, len(code), 4 * sp["n"])
    return code


def stock_ok(st, addr, sp):
    d = _stock(st)
    o = addr - OVL
    return d[o:o + 4 * sp["n"]]


def ovl_patches():
    out = {}
    for (st, a), sp in sorted(SPECS.items()):
        out.setdefault("P/P4/STAGE%X.BIN" % st, []).append((a, build(st, a, sp)))
    return out


if __name__ == "__main__":
    for (st, a), sp in sorted(SPECS.items()):
        c = build(st, a, sp)
        print("stage %d %08x: %d / %d bytes, stock sha1 %s" % (st, a, len(c), 4 * sp["n"], hashlib.sha1(stock_ok(st, a, sp)).hexdigest()[:12]))
