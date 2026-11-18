"""MSHvSF speed, part "parse": sprite part-header parser 0x80082d9c (sec0) and tile-header parser 0x80083034 (sec1)
rewritten in place (XvSF 1.1 quad.S sec0_parse / sec1_parse analogues; same calling interface, same memory writes,
same v0).  Called 6-57 times per logic frame (per sprite part); stock ~250 / ~140 cycles per call.

    patches(); RANGES (inside the stock function bodies); FREED (unused tails); apply_ram(e); python parse.py build
Tests: parse/ptest.py (unicorn differential: random fuzz + real captured inputs).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "parse", "parse.S")
BIN = os.path.join(HERE, "parse", "bin")
CHUNKS = {"SEC0": (0x80082d9c, 0x80083034), "SEC1": (0x80083034, 0x800830c4)}
EXPECT = {0x80082d9c: 0x3c028009, 0x80083034: 0x3c068009}


def build():
    sys.path.insert(0, HERE)
    import slib
    out, syms = slib.chunks(SRC, CHUNKS)
    os.makedirs(BIN, exist_ok=True)
    for k in CHUNKS: open(os.path.join(BIN, k + ".bin"), "wb").write(out[k])
    print("; ".join("%s %d/%d" % (k, len(out[k]), hi - lo) for k, (lo, hi) in CHUNKS.items()))


def patches():
    return [(lo, open(os.path.join(BIN, k + ".bin"), "rb").read()) for k, (lo, hi) in CHUNKS.items()]


RANGES = [(a, a + len(d)) for a, d in patches()] if os.path.exists(os.path.join(BIN, "SEC0.bin")) else list(CHUNKS.values())
FREED = [(a + len(d), CHUNKS[k][1]) for (a, d), k in zip(patches(), CHUNKS)] if os.path.exists(os.path.join(BIN, "SEC0.bin")) else []


def apply_ram(e):
    """poke into a running game (tests only; a disc build is exact).  Leaf functions, whole bodies poked between two
    vblanks; checked in game by vcheck.py (identical state)."""
    for a, w in EXPECT.items(): assert e.u32(a) == w, "%08x not stock" % a
    for a, d in patches(): e.poke(a, d)


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]: build()
    for a, d in patches(): print("%08x %d bytes" % (a, len(d)))
    print("FREED", ["%08x-%08x" % r for r in FREED])
