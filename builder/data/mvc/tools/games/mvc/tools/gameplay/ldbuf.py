"""rc4.10 `--ldbuf`: the post-battle loading screen's winner prim buffer (freeze / MiSTer / real-PS1 hang root cause).

Stock: scene 12 (post-battle NOW LOADING) handler 0x8002c960 takes the winner's object (0x8007b828 + 0xa0 / 0xa8) and
0x80090534(obj, buf, 0) renders it as a frozen sprite: one 40-B prim entry per part of its current frame group (tag
chain + 0x2d808080 SPRT), into a FIXED buffer buf = 0x801fce00 (`lui a1,0x801f` at 0x8002c9e4 (bne delay slot) /
0x8002c9f0, `ori a1,a1,0xce00` at 0x8002c9f4).  Up to 152 parts (Strider) -> 6,080 B -> 0x801fe5c0.  Free top RAM in
the stock game; in a tag battle that RAM holds g2get's tags + group pool, the vcache image, the strong payload (DSH1 /
DSA1 decoders 0x801fd400.., post routine, meter, STAGE ANIM RAM part).  Which one gets hit depends on the winner's frame
-> a timing-dependent hang (ARCADE P2-side regress freeze: g2get pool -> garbage part count 9844 for Cap's shield ->
prim alloc 0x80021b40 returns 0 -> prims at 0x80000000 -> chain into character data -> AdEL in 0x8008ced4).

Fix: the sites read the buffer address from the word LDBUF_W (EX OPTIONS block 0x8001175c.., +8), written by mktag
= tagload.c ldbuf_at: a FIXED 4 KB buffer right below the lowest possible top-resident block (vcache + g2get + L1b +
cut-in reservations); the planner region (TOP0 battles) always ends below it, so no stage load, character load or
resident copy ever writes it and the frozen winner survives the whole next load (as 0x801fce00 does in the stock game).
Win / stand / move frames have <= 51 parts (2 KB); 4 KB = 102 parts.  Declined (stock-loaded) battles: attract (0xf9)
only, which never shows the scene-12 freeze (ldchk.py).
    0x8002c9e4 / 0x8002c9f0  lui a1,0x801f -> lui a1,0x8001
    0x8002c9f4               ori a1,a1,0xce00 -> lw a1,0x1764(a1)     (load delay: the jal + delay slot follow)
"""
import os, struct

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
LDBUF_W, STOCK = 0x80011764, 0x801fce00
SITES = {0x8002c9e4: (0x3C05801F, 0x3C058001), 0x8002c9f0: (0x3C05801F, 0x3C058001),
         0x8002c9f4: (0x34A5CE00, 0x8CA51764)}


def patches():
    exe = open(os.path.join(ROOT, "games", "mvc", "disc", "SLUS_010.59"), "rb").read()
    rd = lambda a: struct.unpack_from("<I", exe, a - 0x80010000 + 0x800)[0]
    for a, (o, n) in SITES.items():
        assert rd(a) == o, f"ldbuf: {a:08x} not stock ({rd(a):08x})"
    assert (0x8CA51764 & 0xFFFF) == LDBUF_W & 0xFFFF and (0x3C058001 & 0xFFFF) == LDBUF_W >> 16
    return [(a, struct.pack("<I", n)) for a, (o, n) in SITES.items()]     # LDBUF_W itself: init_word() via mktag exopt_exe


def init_word(at):
    """LDBUF_W in the EXE: the blob's fixed buffer address (tagload.c ldbuf_at, read by mktag)"""
    assert at is not None
    return struct.pack("<I", at)


if __name__ == "__main__":
    for a, d in patches(): print(f"{a:08x} {d.hex()}")
