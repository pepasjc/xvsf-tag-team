"""XvSF speed meter for hardware speed tests (TEST BUILDS ONLY, never in a release): tools/meter/meter.S.

    python tools/meterpatch.py IN.bin OUT.bin      a copy of a built US disc image with the meter (also the shipped 1.2)
    mktagdisc.py NAME ... --meter                  the same, applied last in the build

apply(exe_read, exe_write): the meter code / data images go into the EXE's zero area at COPY_AT with a boot copy
stub chained in front of pc0 (copies them to kernel RAM, FlushCache, jumps to the previous pc0); present's
`jal PutDispEnv` becomes `jal mstub`.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "games", "mshvsf", "tools", "speed")]
from mipsasm import Asm, REG
REG.setdefault("$s6", 22); REG.setdefault("$s7", 23)
SRC = os.path.join(HERE, "meter", "meter.S")
CHUNKS = {"C": (0x80009AA0, 0x80009CF0), "D": (0x80009410, 0x800094F0)}
COPY_AT, COPY_END = 0x800bf000, 0x800bf800          # zero in the EXE image (skip's copy 0x800bf800, ach's 0x800a0000)
PRESENT = (0x80028b58, 0x80028d60)
PUTDISPENV = 0x80016d20
EXE_BASE, EXE_HDR = 0x80010000, 0x800
MY = 48                                             # y of the readout (top left, under P1's bars)
AUTOKO = 2400                                       # arcade test runs: the CPU team is KO'd 40 s into each fight
jal = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)


def build():
    import slib
    out, syms = slib.chunks(SRC, CHUNKS, dict(MY=MY, AUTOKO=AUTOKO))
    return out, syms


def copy_stub(prev_pc0, parts):
    a = Asm(COPY_AT)
    for i, (dst, d) in enumerate(parts):
        a._i(lambda pc, L, i=i: 0x3C080000 | (L["d%d" % i] >> 16))                    # lui t0, hi(src)
        a._i(lambda pc, L, i=i: 0x35080000 | (L["d%d" % i] & 0xFFFF))                 # ori t0, t0, lo(src)
        a.lui("$t1", dst >> 16); a.ori("$t1", "$t1", dst & 0xffff)
        e = dst + len(d)
        a.lui("$t2", e >> 16); a.ori("$t2", "$t2", e & 0xffff)
        a.label("c%d" % i)
        a.lw("$t3", 0, "$t0")
        a.addiu("$t0", "$t0", 4)
        a.sw("$t3", 0, "$t1")
        a.addiu("$t1", "$t1", 4)
        a.bne("$t1", "$t2", "c%d" % i)
        a.nop()
    a.addu("$s7", "$a0", "$zero"); a.addu("$s6", "$a1", "$zero")
    a.addiu("$t2", "$zero", 0xa0)                    # FlushCache
    a.jalr("$t2")
    a.addiu("$t1", "$zero", 0x44)
    a.addu("$a0", "$s7", "$zero"); a.addu("$a1", "$s6", "$zero")
    a.addu("$s7", "$zero", "$zero"); a.addu("$s6", "$zero", "$zero")
    a.j(prev_pc0)
    a.nop()
    for i, (dst, d) in enumerate(parts):
        a.label("d%d" % i)
        a.blob(d + bytes(-len(d) % 4))
    return a.assemble()


def apply(exe_read, exe_write, quiet=False):
    out, syms = build()
    u32 = lambda a: struct.unpack("<I", exe_read(a, 4))[0]
    sites = [a for a in range(PRESENT[0], PRESENT[1], 4) if u32(a) == jal(PUTDISPENV)]
    assert len(sites) == 1, "present: jal PutDispEnv not found once: %s" % [hex(x) for x in sites]
    prev_pc0 = u32(EXE_BASE - EXE_HDR + 0x10)
    parts = [(CHUNKS[k][0], out[k]) for k in ("C", "D")]
    cp = copy_stub(prev_pc0, parts)
    assert COPY_AT + len(cp) <= COPY_END and exe_read(COPY_AT, len(cp)) == bytes(len(cp)), "meter copy area not zero"
    exe_write(COPY_AT, cp)
    exe_write(sites[0], struct.pack("<I", jal(syms["mstub"])))
    exe_write(EXE_BASE - EXE_HDR + 0x10, struct.pack("<I", COPY_AT))
    if not quiet:
        print("speed meter (TEST BUILD): code %08x (%d bytes), data %08x (%d bytes), hook %08x, copy %08x (%d bytes), pc0 -> %08x (was %08x)" % (
            CHUNKS["C"][0], len(out["C"]), CHUNKS["D"][0], len(out["D"]), sites[0], COPY_AT, len(cp), COPY_AT, prev_pc0))
    return syms


def main():
    import json, shutil
    sys.path.insert(0, HERE)
    import region
    from mkdisc import fix_sector
    src, dst = sys.argv[1], sys.argv[2]
    shutil.copyfile(src, dst)
    lmap = json.load(open(region.LMAP))
    exe_lba, exe_size = lmap[region.EXE]
    touched = set()
    with open(dst, "r+b") as f:
        def exe_read(addr, n):
            b = bytearray()
            for i in range(n):
                o = addr - EXE_BASE + EXE_HDR + i
                f.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048); b += f.read(1)
            return bytes(b)
        def exe_write(addr, data):
            for i in range(len(data)):
                o = addr - EXE_BASE + EXE_HDR + i
                assert 0 <= o < exe_size
                sec = exe_lba + o // 2048
                f.seek(sec * 2352 + 24 + o % 2048); f.write(data[i:i + 1]); touched.add(sec)
        apply(exe_read, exe_write)
        for sec in sorted(touched):
            f.seek(sec * 2352); raw = bytearray(f.read(2352)); fix_sector(raw)
            f.seek(sec * 2352); f.write(raw)
    cue = os.path.splitext(dst)[0] + ".cue"
    open(cue, "w").write('FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n' % os.path.basename(dst))
    print("->", dst, cue)


if __name__ == "__main__":
    main()
