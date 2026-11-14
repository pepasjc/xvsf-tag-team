"""CPU difficulty fix for the tag hack - X-Men vs. Street Fighter (SLUS-00627).  See work/diff, work/bal, work/arcade.

  * The difficulty option (0x800421a4, 0..7 = 1..8 stars, 1 on a fresh boot) is copied to 0x80042a00
    when a game starts (0x80031cd8) and picks a row of the rank-cap table 0x80090d6c[difficulty]
    [fights won]; the CPU brain reads the rank 0x80042a02 (0..31).
  * The arcade program has the SAME cap table (0x8cfce in the 961004 program, used by every region
    but Japan), the same thresholds and the same code.  Factory difficulty: index 1 (Europe, Asia,
    Japan, ...) or 7 (USA, Hispanic).  So "2 stars" already is the Euro arcade default.
  * PORT BUG, fixed here (rank_patches): the rank ticker lost its 60-frame prescaler reload, so the
    PS1 rank sits at the cap from the first frame of every fight and the continue penalty never
    lasts.  Arcade: rank 0 at the start of a game, +1 every 5 s until the cap.  Measured, idle
    player, rank sampled every 5 s:
        arcade (Euro default)   fight 1: 1 2 3 4 5 6 7 8 9 10     fight 2: 13 14 14 14 ...
        PS1 tag19, 2 stars      fight 1: 10 10 10 ...             fight 2: 14 14 14 ...
        PS1 tag19 + this patch  fight 1: 1 2 3 4 5 6 7 8 9 10     fight 2: 13 14 14 14 ...

RANK_CAPS is an independent switch (None = leave the stock table alone).
(The tuning of the old invented CPU tag heuristic that used to live here is gone together with
that heuristic: tools/aipatch.py now lets the CPU tag through the game's own arcade path.)
"""
import hashlib, os, struct, sys

CAP_TABLE = 0x80090d6c          # 8 difficulty rows x 8 fights, max rank 0..0x1f
STOCK_CAPS = "f243757271da49e02a910530726caa27340df979"   # SHA-1 of the stock 64-byte table
RANK_CAPS = None                # e.g. a 64-byte table; not used by default

RANK_TICK = 0x80031d3c           # 7 words of the rank ticker 0x80031d34
RANK_TICK_ORIG = "39314b760f9a243711912d1f5bd7054f990bba1b"   # SHA-1 of the 7 stock words


def rank_patches():
    """The arcade ticker (0x7c428 in the 961004 program) counts a 60-frame prescaler:
           subq.b #1,c38 / bcc return / move.b #$3b,c38 / tick
    The port lost the reload: its byte runs free, so it "ticks" on 128 of every 256 frames (30 x too
    fast).  Every 5th tick adds 80 performance points (= one rank) to both players, so the PS1 rank
    reaches the cap of the difficulty table before the first round starts and can never fall (the
    continue penalty is refilled at once).  Same 7 words, with the reload:
           lbu v0,(v1) / ori t0,zero,0x3b / addiu v0,v0,-1 / bgez v0,ret / sb v0,(v1) / sb t0,(v1) / nop"""
    ws = (0x90620000, 0x3408003B, 0x2442FFFF, 0x0441002D, 0xA0620000, 0xA0680000, 0x00000000)
    return [(RANK_TICK, struct.pack("<7I", *ws))]


def rule_patches(*a, **k):
    """Kept for callers of the old interface: the CPU tag heuristic no longer exists."""
    return []


def patches():
    out = rank_patches()
    if RANK_CAPS is not None:
        assert len(RANK_CAPS) == 64 and max(RANK_CAPS) <= 0x1f
        out.append((CAP_TABLE, bytes(RANK_CAPS)))
    return out


def apply_ram(emu):
    """Only before the first fight of a session (I-cache)."""
    t = emu.ram(CAP_TABLE, 64)
    assert hashlib.sha1(t).hexdigest() == STOCK_CAPS or (RANK_CAPS is not None and t == bytes(RANK_CAPS)), "unexpected rank-cap table"
    r = emu.ram(RANK_TICK, 28)
    assert hashlib.sha1(r).hexdigest() == RANK_TICK_ORIG or r == rank_patches()[0][1], "unexpected rank ticker code"
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "disc", "files", "SLUS_006.27"), "rb").read()
    assert hashlib.sha1(exe[CAP_TABLE - 0x80010000 + 0x800:][:64]).hexdigest() == STOCK_CAPS
    assert hashlib.sha1(exe[RANK_TICK - 0x80010000 + 0x800:][:28]).hexdigest() == RANK_TICK_ORIG
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data[:16].hex()}")
