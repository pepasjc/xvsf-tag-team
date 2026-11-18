"""XvSF speed 1.1, part "quad": the per-sprite-part primitive builder and the two part-header parsers, rewritten in place.

    0x80056340  quad_part   one sprite part -> POLY_FT4 (or the 32-byte sprite packet of 0x80055c34, folded in), linked
    0x80057be4  sec0_parse  part header (returns 5/6/7)
    0x80057f48  sec1_parse  tile header
Sources: tools/speed/quad/quad.S (hand-written R3000 code; quad.c = the same in C, reference / fallback).
Prebuilt bytes: tools/speed/quad/quad_<addr>.bin (rebuild: python tools/speed/quad.py build [c]).
Tests: tools/speed/quad/qtest.py (unicorn differential over the captured corpus), qcap.py (capture).

patches() -> [(ram_addr, bytes)] for the US EXE (RAM addresses).  RANGES = every RAM range written (inside SPANS,
the original function bodies); FREED = ranges this patch leaves dead.
"""
import os, sys, struct, subprocess

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quad")
# (start, end of the original function) - the new code of each function stays inside its own original body
FUNCS = [("quad_part", 0x80056340, 0x800577c8), ("sec0_parse", 0x80057be4, 0x80057f48), ("sec1_parse", 0x80057f48, 0x80058000)]
SPANS = [(lo, hi) for _, lo, hi in FUNCS]                       # the original functions
_size = lambda lo: os.path.getsize(os.path.join(HERE, "quad_%08x.bin" % lo)) if os.path.exists(os.path.join(HERE, "quad_%08x.bin" % lo)) else 0
RANGES = [(lo, lo + _size(lo)) for _, lo, hi in FUNCS]           # exactly what patches() writes
# dead after this patch (no reference left in the executable or any overlay; free for other parts, by agreement):
# the folded 0x80055c34 and the unused tails of the three replaced functions
FREED = [(0x80055c34, 0x80055ebc)] + [(lo + _size(lo), hi) for _, lo, hi in FUNCS]
SYMS = {"DrawSync": 0x80016454, "f15a68": 0x80015a68, "f16a54": 0x80016a54}


def _bin(lo):
    return os.path.join(HERE, "quad_%08x.bin" % lo)


def patches():
    out = []
    for name, lo, hi in FUNCS:
        b = open(_bin(lo), "rb").read()
        assert lo + len(b) <= hi, name
        out.append((lo, b))
    return out


def build(src="quad.S", outdir=HERE, tag=""):
    """compile + link at the fixed addresses; writes quad_<addr>.bin (or <tag>_<addr>.bin) into outdir"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from toolenv import mips_prefix
    G = mips_prefix()
    obj = os.path.join(outdir, "obj"); os.makedirs(obj, exist_ok=True)
    cf = ["-march=r3000", "-mabi=32", "-mno-abicalls", "-fno-pic", "-G0", "-msoft-float"]
    o = os.path.join(obj, "quad.o")
    if src.endswith(".c"):
        subprocess.check_call([G + "gcc", "-O2", "-ffreestanding", "-fno-builtin", "-ffunction-sections", *cf, "-c", os.path.join(HERE, src), "-o", o])
    else:
        subprocess.check_call([G + "gcc", *cf, "-c", os.path.join(HERE, src), "-o", o])
    ld = "SECTIONS {\n"
    for name, lo, hi in FUNCS:
        extra = " *(.text.quad_sprt)" if name == "quad_part" else ""
        ld += "  .t%08x 0x%08x : { *(.text.%s)%s }\n" % (lo, lo, name, extra)
    ld += "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }\n}\n"
    open(os.path.join(obj, "quad.ld"), "w").write(ld)
    elf = os.path.join(obj, "quad.elf")
    subprocess.check_call([G + "ld", "-T", os.path.join(obj, "quad.ld"), *["--defsym=%s=0x%08x" % kv for kv in SYMS.items()], o, "-o", elf])
    res = {}
    for name, lo, hi in FUNCS:
        b = os.path.join(outdir, "%s_%08x.bin" % (tag or "quad", lo))
        subprocess.check_call([G + "objcopy", "-O", "binary", "-j", ".t%08x" % lo, elf, b])
        data = open(b, "rb").read()
        assert lo + len(data) <= hi, "%s too big: %d > %d" % (name, len(data), hi - lo)
        res[lo] = data
        print("%-11s %08x  %4d bytes (original %4d)" % (name, lo, len(data), hi - lo))
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build("quad.c" if len(sys.argv) > 2 and sys.argv[2] == "c" else "quad.S")
    else:
        for a, b in patches(): print("%08x %d bytes" % (a, len(b)))
