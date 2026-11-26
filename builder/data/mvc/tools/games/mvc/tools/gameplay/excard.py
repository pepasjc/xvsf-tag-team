"""EX OPTIONS rows saved on the memory card inside MvC's own save (mktag.py --excard; user rule 2026-11-24: every EX
OPTIONS row is saved with the game's save and restored on load; stock / older saves load and give the defaults).

Stock save (OPDEMO.ARC, OPTION -> MEMORY CARD): file "BASLUS-01059" of 0x500 bytes, game data 0x100 .. 0x4fb (options +
key config 0x100 .., ranking 0x1a0 .. 0x21c, zero padding after), XOR of those bytes at 0x4fc (setter 0x8009f510,
checker 0x8009f570).  Ours at file 0x4f0: 'X' 'O' 1, STAGE ANIM, INTRO, ARCADE FRAMES, ACHIEVEMENT POPUP, ASSISTS,
ARCADE BALANCE, INFINITE SUPER METER (one layout for 2 MB and 8 MB).  Code: excard.S in the EXE dead spans of the
2026-11-17 8 MB menu (CODESPACE.md; stock bytes in every final, asserted here) + two `jal` words in OPDEMO.ARC.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "mshvsf", "tools", "speed")))
SRC = os.path.join(HERE, "excard.S")
OPD, OPD_BASE = "OPDEMO.ARC", 0x8009dfe4
SV_SITE, SV_STOCK = 0x8009ec28, 0x0C000000 | (0x8009f510 >> 2 & 0x3FFFFFF)
LD_SITE, LD_STOCK = 0x8009edb8, 0x0C000000 | (0x8009f570 >> 2 & 0x3FFFFFF)
SPANS = {"A": (0x8003cf60, 0x8003cfa4), "D": (0x80030d14, 0x80030d54), "F": (0x8005f87c, 0x8005f8bc),
         "B": (0x8003ca3c, 0x8003ca78), "E": (0x8001a9e4, 0x8001aa1c), "G": (0x80049c70, 0x80049ca8),
         "H": (0x80049d84, 0x80049dbc), "C": (0x8005f808, 0x8005f83c)}
HOOKA, HOOKW = 0x8001d110, 0x081F7F80        # 8 MB: mvcver's resident stub word 2 -> j 0x807dfe00 (mkap8.boot8_fr)


def build(argv):
    import slib
    indef = 1 if "--introsimple" in argv else 0
    out, syms = slib.chunks(SRC, SPANS, dict(HOOKA=HOOKA, HOOKW=HOOKW, INDEF=indef))
    return out, syms


def patches(argv, rexe, ropd):
    """rexe(addr, n) / ropd(addr, n) read the image being built -> ([(exe addr, bytes)], [(OPD offset, bytes)])"""
    out, syms = build(argv)
    exe = []
    for k, (lo, hi) in SPANS.items():
        assert rexe(lo, hi - lo) != bytes(hi - lo) or True
        exe.append((lo, out[k]))
    for a, w in ((SV_SITE, SV_STOCK), (LD_SITE, LD_STOCK)):
        assert struct.unpack("<I", ropd(a, 4))[0] == w, "--excard: OPDEMO call %08x not stock" % a
    opd = [(SV_SITE - OPD_BASE, struct.pack("<I", 0x0C000000 | (syms["svhook"] >> 2 & 0x3FFFFFF))),
           (LD_SITE - OPD_BASE, struct.pack("<I", 0x0C000000 | (syms["ldhook"] >> 2 & 0x3FFFFFF)))]
    return exe, opd, syms


if __name__ == "__main__":
    out, syms = build(sys.argv)
    for k, v in sorted(out.items()): print(k, hex(SPANS[k][0]), len(v), "of", SPANS[k][1] - SPANS[k][0])
    print({k: hex(v) for k, v in syms.items()})
