"""MSHvSF L2 (mshspeed, 2026-11-20): packed frame-group sections ("G2", format of games/mvc/tools/l2) in the tag
loader's tier files, unpacked on demand by g2get (tools/l2/g2get.py, MSHvSF copy) - `mktag.py --l2g`.

RAM: the g2get image + its RAM block at G2AT (top of the loader region, right below STRONG_AT 0x801fe200), copied by
tl_main after the last CD read (tagload.c -DL2G); the planner's REGION_END is G2AT (the packed files are ~30 % smaller
in sec1: 5.7 KB per character on average, the image costs ~5.6 KB per battle).

EXE (every --l2g build; stock behaviour whenever the image is not valid):
  gate  0x80011bd4-0x80011c28 (84 B; dead EXE span, the 8 MB menu's in ap8 builds: --l2g is 2 MB only)
        g2gate (v0 = group pointer, v1 = offset): the image runs when its first word (G2AT) and its last code word
        both have 'G2' in the upper half (heapcap clears the first at every battle load, whatever loader runs; tl_main
        writes it last after the copy), else returns v0 (= the stock pointer).
        g2gate6: the same + 6 (pointer to the first part header).  No stack frame; uses $at; the image keeps every
        register except v0 / v1 (and returns with v1 bit 31 set from gate6 - v1 is dead at both gate6 sites).
  sites (every sec1 reader: the only code that reads the slot table 0x80092bd0 besides the registration):
        0x80081738 per-object draw (ctx + 0xc)            nop -> jal g2gate (delay slot: the stock addu)
        0x800847a0-0x800847bc predecode queue (nparts)     leaf: ra kept in t9 around jal g2gate (block rewritten)
        0x80084b30-0x80084b48 pre-decode 0x80084ab8         block rewritten: jal g2gate, + 6 after
        0x80013378-0x80013398 decode-ahead ah_mk (cursor)   jal g2gate6 (tools/speed/ahead.py chunk B, words checked)
    python l2.py        prints image / gate sizes
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "speed", "frame"), os.path.join(ROOT, "common", "dsp")]
import g2get as GG, g2pack as GP

STRONG_AT = 0x801fe200
GATE = (0x80011bd4, 0x80011c28)
MAGIC_HI = GG.MAGIC >> 16                       # 'G2'


def image_size():
    code, sym = GG.build(0x801f0000)
    return len(code), GG.RAMSIZE


def g2at():
    n, r = image_size()
    return (STRONG_AT - n - r) & ~127


def image():
    """(G2AT, code bytes, RAM block size)"""
    at = g2at()
    code, sym = GG.build(at)
    assert sym["g2ent"] == at + 4 and code[:4] == struct.pack("<I", GG.MAGIC)
    assert at + len(code) + GG.RAMSIZE <= STRONG_AT
    return at, code, GG.RAMSIZE


GATE_SRC = r"""
g2gate6: lui  $at, 0x8000
        or    $v1, $v1, $at
        addiu $v0, $v0, 6                   # gate6: +6 now (the image takes it off again)
g2gate:
g2c:    lui   $at, %hi(G2AT)
        lw    $at, %lo(G2AT)($at)           # first word of the image
        nop
        srl   $at, $at, 16
        xori  $at, $at, MAGIC_HI
        bnez  $at, 1f
        lui   $at, %hi(G2END)
        lw    $at, %lo(G2END)($at)          # last code word of the image: a load into the middle shows here
        nop
        srl   $at, $at, 16
        xori  $at, $at, MAGIC_HI
        bnez  $at, 1f
        nop
        j     G2ENT
        nop
1:      jr    $ra
        nop
"""


def gate(at):
    from gas import gas
    code, sym = gas(GATE_SRC, GATE[0], {"G2AT": at, "G2ENT": at + 4, "G2END": GG.build(at)[1]["g2endm"], "MAGIC_HI": MAGIC_HI})
    assert GATE[0] + len(code) <= GATE[1], len(code)
    return code, sym


def _asm(src, org, defs):
    from gas import gas
    return gas(src, org, defs)[0]


# stock words of the rewritten blocks (checked before patching)
STOCK = {0x80081738: "00000000",
         0x800847a0: "73008280" "d02b6324" "80100200" "21104300" "1000a394" "0000428c" "00000000" "21104300",
         0x80084b30: "00000000" "1300a012" "0980043c" "10008296" "981e8424" "2110a200" "06004224"}


def exe_patches(at, read):
    """[(addr, bytes)]: gate + the three EXE sites (stock words asserted with read(addr, n))"""
    gcode, gsym = gate(at)
    G, G6 = gsym["g2gate"], gsym["g2gate6"]
    for a, h in STOCK.items():
        assert read(a, len(h) // 2).hex() == h, "L2 site %08x not stock: %s" % (a, read(a, len(h) // 2).hex())
    out = [(GATE[0], gcode)]
    out.append((0x80081738, _asm("jal G\n", 0x80081738, {"G": G})))
    out.append((0x800847a0, _asm("""
        sll   $v0, $v0, 2
        addu  $v1, $v1, $v0
        lw    $v0, 0x2bd0($v1)
        lhu   $v1, 0x10($a1)
        move  $t9, $ra
        jal   G
        addu  $v0, $v0, $v1
        move  $ra, $t9
""", 0x800847a0, {"G": G})))
    out.append((0x80084b30, _asm("""
        lhu   $v1, 0x10($s4)
        .word 0x12a00013                  # beqz s5, 0x80084b84 (stock word)
        lui   $a0, 0x8009
        addiu $a0, $a0, 0x1e98
        jal   G
        addu  $v0, $a1, $v1
        addiu $v0, $v0, 6
""", 0x80084b30, {"G": G})))
    for a, b in out[1:]:
        assert len(b) == len(STOCK[a]) // 2, hex(a)
    return out, gsym


AH_AT = 0x80013378
AH_STOCK = "09800e3c" "2170cd01" "d02bce8d" "10000f96" "0880183c" "21c00d03" "2170cf01" "0600ce25" "04008ead"


def ahead_patch(chunks, gsym):
    """rewrite ah_mk's first-part-header pointer (ahead chunk B) to come from g2gate6; chunks = [(addr, bytes)]"""
    new = _asm("""
        lui   $t6, 0x8009
        addu  $t6, $t6, $t5
        lw    $v0, 0x2bd0($t6)
        lhu   $v1, 0x10($s0)
        lui   $t8, 0x8008
        jal   G6
        addu  $v0, $v0, $v1
        addu  $t8, $t8, $t5
        sw    $v0, 4($t4)
""", AH_AT, {"G6": gsym["g2gate6"]})
    out = []; done = False
    for a, b in chunks:
        if a <= AH_AT < a + len(b):
            o = AH_AT - a
            assert b[o:o + len(new)].hex() == AH_STOCK, "ahead ah_mk words changed: %s" % b[o:o + len(new)].hex()
            b = b[:o] + new + b[o + len(new):]; done = True
        out.append((a, b))
    assert done, "ahead chunk B not found"
    return out


def pack_tier(data, stock):
    """a tier file (DSP) with sec1 packed (group starts from the character's stock file)"""
    return GP.pack_dsp(data, stock)


if __name__ == "__main__":
    at, code, ram = image()
    g, s = gate(at)
    print("G2AT %08x image %d B + RAM %d B (%d B below STRONG_AT), gate %d B" % (at, len(code), ram, STRONG_AT - at, len(g)))
