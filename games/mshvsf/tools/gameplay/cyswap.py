"""Post-boss scene fix (mktag.py --cyswap; mshfeat 2026-11-21; source cyswap.S, description there).
Bug (1.0, user report "freeze after fighting Cyber-Akuma"): the stock post-boss scene is written for the assist rules
(P1's main always on point): it loads the FIXED partner object's character into the P2 slot at the stock addresses
0x801448e0.. and then shows the BENCH member (match +0xa4 / id +0x7c) as P2 and switches the partner objects off.  With
the tag rules the partner can be on point at the KO: then the bench member is the main -> P2 copy of the main without
its P2-slot data (crash in the sprite part parser 0x800824ec) while the on-point partner, whose data the tag layout may
put into the load window, is still drawn (crash in the VRAM allocator 0x8008108c).  Fix: before the handler runs, make
the winning side's main the one on point (shown at the partner's place) and bench + switch off the partner: the scene
then plays exactly as when the main won on point.  2 MB, 8 MB and the 8 MB disc's 2 MB fallback (EXE only).

    patches()  -> [(addr, bytes)]: the rewritten 0x8002d43c-0x8002d534 region (rest = break), the 4 callers (jal setp +
               the side in the delay slot), the phase-table word
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "speed"))
SRC = os.path.join(HERE, "cyswap.S")
LO, HI = 0x8002d43c, 0x8002d534
CALLS = {0x8002d060: (0x0c00b50f, 0x00002021),       # jal 0x8002d43c (P1); delay slot (nop) -> move a0, zero
         0x8002d12c: (0x0c00b529, 0x34040001),       # jal 0x8002d4a4 (P2)                  -> ori a0, zero, 1
         0x8002cf70: (0x0c00b543, 0x34040003),       # jal 0x8002d50c (both)                -> ori a0, zero, 3
         0x8002d1a4: (0x0c00b543, 0x34040003)}
TABLE, TABLE_ORIG = 0x8006afac, 0x80056c94


def build():
    import slib, tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.S"); open(p, "w").write("#@C\n" + open(SRC).read())
        out, syms = slib.chunks(p, {"C": (LO, HI)}, {})
    return out["C"], syms


def patches(word=None):
    """word(addr) -> u32 of the EXE as built so far (checks the stock words)"""
    code, syms = build()
    if word:
        for a, (o, d) in CALLS.items(): assert (word(a), word(a + 4)) == (o, 0), ("cyswap caller", hex(a), hex(word(a)))
        assert word(TABLE) == TABLE_ORIG, "cyswap table word"
    jal = lambda t: struct.pack("<I", 0x0C000000 | (t >> 2 & 0x3ffffff))
    p = [(LO, code + struct.pack("<I", 0x0000000d) * ((HI - LO - len(code)) // 4))]
    p += [(a, jal(syms["setp"]) + struct.pack("<I", d)) for a, (o, d) in CALLS.items()]
    p.append((TABLE, struct.pack("<I", syms["cyhook"])))
    return p


if __name__ == "__main__":
    code, syms = build()
    print(len(code), "of", HI - LO, {k: hex(v) for k, v in syms.items()})
