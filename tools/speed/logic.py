"""XvSF speed 1.1, part "logic": game-logic / per-frame functions rewritten in place (see FUNCS).

Source: tools/speed/logic/logic.S, one section .text.f<addr> per replaced function, assembled to its own address;
each must fit in the original body (SPANS).  Prebuilt bytes: tools/speed/logic/logic_<addr>.bin
(rebuild: python tools/speed/logic.py build).  Tests: tools/speed/logic/ltest.py (unicorn differential over calls
captured with lcap.py), hazard check tools/speed/quad/hazard.py style (logic/lhazard.py).

patches() -> [(ram_addr, bytes)] for the US EXE (RAM addresses).  RANGES = every RAM range written.
"""
import os, sys, subprocess

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logic")
# (name, start, end of the original function)
FUNCS = [
    ("drawlist_add", 0x800303f0, 0x80030530),      # insert an object into the priority-sorted draw list
    ("cmd_match", 0x8007d100, 0x8007d168),         # command matcher of the move parser: frameless early out
    ("cmd_tail", 0x8006b6a4, 0x8006b71c),          # its fast-path tail, statically dead range
    ("cmd_slow", 0x8006cdec, 0x8006ce74),          # its prologue + CPU branch, moved to a statically dead range (tools/deadcode.py)
]
SPANS = [(lo, hi) for _, lo, hi in FUNCS]
SYMS = {}


def _bin(lo, bindir=None, tag="logic"):
    return os.path.join(bindir or HERE, "%s_%08x.bin" % (tag, lo))


def patches(bindir=None, tag="logic"):
    out = []
    for name, lo, hi in FUNCS:
        p = _bin(lo, bindir, tag)
        if not os.path.exists(p): continue
        b = open(p, "rb").read()
        assert lo + len(b) <= hi, name
        out.append((lo, b))
    return out


RANGES = [(lo, lo + len(b)) for lo, b in patches()]


def build(src="logic.S", outdir=HERE, tag="logic"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from toolenv import mips_prefix
    G = mips_prefix()
    obj = os.path.join(outdir, "obj"); os.makedirs(obj, exist_ok=True)
    cf = ["-march=r3000", "-mabi=32", "-mno-abicalls", "-fno-pic", "-G0", "-msoft-float"]
    o = os.path.join(obj, "logic.o")
    subprocess.check_call([G + "gcc", *cf, "-c", os.path.join(HERE, src), "-o", o])
    ld = "SECTIONS {\n" + "".join("  .t%08x 0x%08x : { *(.text.f%08x) }\n" % (lo, lo, lo) for _, lo, hi in FUNCS)
    ld += "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }\n}\n"
    open(os.path.join(obj, "logic.ld"), "w").write(ld)
    elf = os.path.join(obj, "logic.elf")
    subprocess.check_call([G + "ld", "-T", os.path.join(obj, "logic.ld"), *["--defsym=%s=0x%08x" % kv for kv in SYMS.items()], o, "-o", elf])
    for name, lo, hi in FUNCS:
        b = _bin(lo, outdir, tag)
        subprocess.check_call([G + "objcopy", "-O", "binary", "-j", ".t%08x" % lo, elf, b])
        n = os.path.getsize(b)
        if n == 0: os.remove(b); continue
        assert lo + n <= hi, "%s too big: %d > %d" % (name, n, hi - lo)
        print("%-14s %08x  %4d bytes (original %4d)" % (name, lo, n, hi - lo))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build": build()
    else:
        for a, b in patches(): print("%08x %d bytes" % (a, len(b)))
