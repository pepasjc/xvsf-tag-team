"""Assemble GNU-as MIPS source at a fixed address: gas(src, org) -> (bytes, {symbol: address})."""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from toolenv import mips_prefix


def gas(src, org, defs=None):
    P = mips_prefix()
    with tempfile.TemporaryDirectory() as d:
        s, o, e, b = (os.path.join(d, n) for n in ("a.S", "a.o", "a.elf", "a.bin"))
        hdr = "".join(".set %s, 0x%x\n" % (k, v) for k, v in (defs or {}).items())
        open(s, "w").write(".set noreorder\n.set noat\n.text\n" + hdr + src + "\n")
        subprocess.check_call([P + "as", "-EL", "-march=r3000", "-mabi=32", "-no-mips16", "-o", o, s])
        subprocess.check_call([P + "ld", "-EL", "-Ttext=0x%x" % org, "-e", "0x%x" % org, "-o", e, o])
        subprocess.check_call([P + "objcopy", "-O", "binary", "-j", ".text", e, b])
        syms = {}
        for l in subprocess.check_output([P + "nm", e]).decode().split("\n"):
            p = l.split()
            if len(p) == 3: syms[p[2]] = int(p[0], 16) & 0xffffffff
        return open(b, "rb").read(), syms
