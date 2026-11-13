"""Speed version of the sprite tile decoders (XvSF tag hack 1.1 speed project, "decode" part).

Replaces the whole tile-decode path of the 2 MB build: the game's RLE decoder 0x8001b5b0 and the hack's
XVM1 / XVH1 decoders (tools/nsppatch.py + tools/nspdec/nspdec.S).  Same file formats, byte-identical output.
Source: tools/speed/decode/nspdec.S (one blob linked at 0x80010440, holes = untouched game code/data).

    0x80010440-0x800104c8   S  XVM1 set-up, escape                  } the code areas of tools/nsppatch.py
    0x800158f4-0x80015a68   Z  XVM1 main loop, copy-from-above runs  } (uncalled libgpu helper / debug-dump; S stops at roundpatch.py 0x800104c8
    0x80015bac-0x80015d9c   X  XVH1 main loop, XVM1 long codes       }  functions; holes between them are
    0x80015dd4-0x80015f94   Y  XVH1 runs, XVM1 repeat runs, RLE lit. }  live and untouched)
    0x8001b5b0-0x8001b710   R  dispatch (now AT the decoder entry: no hook jump) + RLE decoder
Scratchpad 0x1f800300-0x1f80037f: XVM1 row buffer (the game uses 0x1f800000-0x1f800207 only).

    python tools/speed/decode.py build      reassemble (MIPS toolchain, tools/toolenv.py)
    python tools/speed/decode.py            list the patch ranges
patches() -> [(ram address, bytes)]; RANGES = the ranges they write; apply_ram(emu).
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "decode")
sys.path.insert(0, D)
ORG = 0x80010440
CHUNKS = [("S", 0x80010440, 0x800104c8, None, "cS_end"), ("Z", 0x800158f4, 0x80015a68, "cZ", "cZ_end"),
          ("X", 0x80015bac, 0x80015d9c, "cX", "cX_end"), ("Y", 0x80015dd4, 0x80015f94, "cY", "cY_end"),
          ("R", 0x8001b5b0, 0x8001b710, "cR", "cR_end")]
BIN, SYM = os.path.join(D, "nspdec.bin"), os.path.join(D, "nspdec.sym")
SCRATCH = (0x1f800300, 0x1f800380)


def build():
    import dlib
    code, s = dlib.assemble(os.path.join(D, "nspdec.S"), ORG)
    open(BIN, "wb").write(code)
    open(SYM, "w").write("".join("%08x %s\n" % (v, k) for k, v in sorted(s.items(), key=lambda x: x[1])))
    bad = dlib.hazards(code, ORG, [(lo, hi) for n, lo, hi, a, b in CHUNKS])
    assert not bad, "load-delay hazards:\n" + "\n".join(bad)


def symbols():
    s = {}
    for l in open(SYM):
        a, n = l.split(); s[n] = int(a, 16)
    return s


def patches():
    b = open(BIN, "rb").read(); s = symbols()
    assert s["xvm_dec"] == ORG and s["dec_entry"] == 0x8001b5b0 and len(b) % 4 == 0
    out = []
    for i, (name, lo, hi, a, e) in enumerate(CHUNKS):
        assert (a is None or s[a] == lo) and lo < s[e] <= hi, f"chunk {name} overflows: ends at {s[e]:08x} > {hi:08x}"
        out.append((lo, b[lo - ORG:s[e] - ORG]))
        if i + 1 < len(CHUNKS):            # the hole up to the next chunk must be empty in the blob
            nlo = CHUNKS[i + 1][1]
            assert not any(b[s[e] - ORG:nlo - ORG]), f"code in the hole after chunk {name}"
    assert ORG + len(b) == CHUNKS[-1][2] or ORG + len(b) == s[CHUNKS[-1][4]]
    return out


RANGES = None


def _ranges():
    return [(a, a + len(d)) for a, d in patches()]


def apply_ram(emu):
    for addr, data in patches():
        emu.poke(addr, data)


try:
    RANGES = _ranges()
except Exception:                          # not built yet
    RANGES = [(lo, hi) for n, lo, hi, a, e in CHUNKS]

if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
        RANGES = _ranges()
    for addr, data in patches():
        print(f"{addr:08x}-{addr + len(data):08x} {len(data):4d} bytes")
