"""STAGE ANIM option (mktag.py --stageanim; source stageanim.S): OPTION MODE line FULL / REDUCED / OFF (default FULL,
session RAM like the speed meter flag) that holds the animation timers of the stage's own objects.

    exe_patches()      -> [(addr, bytes)]   dead-span chunks + the two object-walker call sites
    overlay_patches()  -> [(file, offset, bytes)]   OPDEMO.ARC: cursor wrap 0..15, draw hook, label + "FULL" strings
    ram_part()         -> bytes linked at SA (0x801fdf40, after the meter's RAM part; copied with it every battle)
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "mshvsf", "tools", "speed")))
SRC = os.path.join(HERE, "stageanim.S")
SA, SA_END = 0x801fdf28, 0x801fe000
CHUNKS = {"A": (0x80032964, 0x80032998), "B": (0x80032830, 0x80032864), "C": (0x8003c310, 0x8003c340),
          "D": (0x8002f780, 0x8002f7b0), "S": (0x80024d5c, 0x80024d94), "R": (SA, SA_END)}
OPD, OPD_BASE = "OPDEMO.ARC", 0x8009dfe4
LBL, STR_FULL, STR_OFF = 0x800b5b82, 0x800b5b8d, 0x8009e174          # label slot 15 of the option table; "OFF" stock
WALK = (0x8004f060, 0x8004f15c)                                     # jalr v0 in the two object walkers
SITES = {0x800a2704: (0x2842000f, 0x28420010),                       # slti v0,v0,0xf -> 0x10 (cursor 0..15)
         0x800a2708: (0x2402000e, 0x2402000f)}                       # li v0,0xe -> 0xf (wrap up to 15)
DRAW_AT, DRAW_ORIG = 0x800a29cc, 0x9202000d                         # lbu v0,0xd(s0) after the stock draw call


# OFF: per-stage words held at a fixed value (stage, address, value): BG-layer animation state set by stage objects
HOLDS = [(4, 0x800a1594, 0)]          # stage 4 (council): monitor-layer selector (0 = screens dark, a stock state)


def build():
    import slib, tempfile
    defs = dict(FONT=0x80020f10, LBL=LBL, STR_FULL=STR_FULL, STR_OFF=STR_OFF, SAMAGIC=0x4d494e41, SPAWN=0x8006edf0, FS05=int("--fs05" in sys.argv))
    tab = "".join("        .half   %d, %d\n        .word   0x%08x\n" % (st, v, a) for st, a, v in HOLDS)
    tab += "        .half   0xffff, 0\n        .word   0\n"
    src = open(SRC).read().replace("HOLDS:  HOLDTAB", "HOLDS:\n" + tab)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "stageanim.S"); open(p, "w").write(src)
        out, syms = slib.chunks(p, CHUNKS, defs)
    assert syms["SA"] == SA
    return out, syms


def exe_patches():
    out, syms = build()
    p = [(CHUNKS[k][0], out[k]) for k in ("S" if "--fs05" in sys.argv else "ABCDS")]   # fs05: OPTION line = optrows
    jal = struct.pack("<I", 0x0C000000 | (syms["sa_stub"] >> 2 & 0x3ffffff))
    return p + [(a, jal) for a in WALK]


def overlay_patches():
    if "--fs05" in sys.argv: return []                              # fs05: optrows.py draws the line (OPDEMO slack)
    out, syms = build()
    p = [(a, struct.pack("<I", n)) for a, (o, n) in SITES.items()]
    p += [(DRAW_AT, struct.pack("<I", 0x0C000000 | (syms["optdraw"] >> 2 & 0x3ffffff)))]
    p += [(LBL, b"STAGE ANIM\0"), (STR_FULL, b"FULL\0")]
    return [(OPD, a - OPD_BASE, d) for a, d in p]


def check(exe_word, opd):
    """exe_word(addr) -> u32 of the stock EXE; opd = OPDEMO.ARC bytes (stock)"""
    for a in WALK: assert exe_word(a) == 0x0040f809, "walker site %08x not jalr v0" % a
    for a, (o, n) in SITES.items(): assert struct.unpack_from("<I", opd, a - OPD_BASE)[0] == o, "OPDEMO %08x" % a
    assert struct.unpack_from("<I", opd, DRAW_AT - OPD_BASE)[0] == DRAW_ORIG
    assert opd[LBL - OPD_BASE:STR_FULL - OPD_BASE + 5] == bytes(16), "label slot 15 not free"
    assert opd[STR_OFF - OPD_BASE:STR_OFF - OPD_BASE + 4] == b"OFF\0"


def ram_part():
    out, syms = build()
    return out["R"]


if __name__ == "__main__":
    out, syms = build()
    for k in "ABCDSR": print(k, hex(CHUNKS[k][0]), len(out[k]), "of", CHUNKS[k][1] - CHUNKS[k][0])
    print({k: hex(syms[k]) for k in ("optdraw", "sa_stub", "SA", "VSTR")})
