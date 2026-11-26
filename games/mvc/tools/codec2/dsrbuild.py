"""dsrdec.S (DSR1 decoder) as a position-independent binary for mktag.py --dsr (checked: same bytes at two addresses,
no load-delay hazards, no $sp / $s* / $gp / jal)."""
import os, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "decode"))
import dlib


def binary(at=0x801fd808):
    src = os.path.join(HERE, "dsrdec.S"); od = os.path.join(ROOT, "work", "dsp_obj")
    c, sym = dlib.assemble(src, at, outdir=od)
    c2, _ = dlib.assemble(src, at ^ 0x00100000, outdir=od)
    assert c == c2, "dsrdec.S not position-independent"
    assert not dlib.hazards(c, at), "dsrdec.S load-delay hazards"
    assert (sym["dsr_dec"] & 0xffffffff) == at
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    for i in md.disasm(c, at):
        t = i.mnemonic + " " + i.op_str
        assert not re.search(r"[$](sp|s[0-8]|fp|gp|k[01])\b|^jal ", t), t
    return c
