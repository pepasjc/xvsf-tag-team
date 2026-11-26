"""dsadx.S (DSA1 decoder + 1-entry leaf cache) as a position-independent binary for mktag.py --dxdsa."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "decode"))
import dlib


def binary(at=0x801fd808):
    src = os.path.join(HERE, "dsadx.S"); od = os.path.join(ROOT, "work", "dsp_obj")
    c, sym = dlib.assemble(src, at, outdir=od)
    c2, _ = dlib.assemble(src, at ^ 0x00100000, outdir=od)
    assert c == c2, "dsadx.S not position-independent"
    assert not dlib.hazards(c, at), "dsadx.S load-delay hazards"
    assert (sym["dsa_dec"] & 0xffffffff) == at
    return c
