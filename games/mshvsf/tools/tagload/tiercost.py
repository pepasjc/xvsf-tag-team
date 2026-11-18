"""Expected sprite-decode cost per character and tier, for the loader's tier policy.

cost[c][t] = sum over tiles of play volume (games/mshvsf/work/dsp/hot/SP_PLxx.json: decoded bytes per tile in random
fights + the bench phases incl. supers / team supers) x cycles per byte of the codec that tile has in tier t (stock
RLE / hot tiles 7.3, DSM1 28, DSH1 79: common/dsp cost model, play-weighted).  Units: COST_UNIT cycles.
    python tiercost.py          prints the table
"""
import os, sys, json, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "common", "dsp"))
import dsp as D
RATE = {b"DSH1": 79.0, b"DSM1": 28.0, None: 7.3}
COST_UNIT = 65536
TIERDIRS = ["dsh_cut", "dsh", "dsh_hot4", "dsh_hot8", "dsh_hot16", "dsh_hot32", "dsm", "dsm_hot16", "dsm_hot32", "dsm_hot64"]    # = mktag.TIERDIRS


def vol(c):
    p = os.path.join(GAME, "work", "dsp", "hot", "SP_PL%02X.json" % c)
    return {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else None


def costs(c):
    """[cost of tier 0..6] (None: tier missing) for file character c (0x00..0x16)"""
    v = vol(c)
    files = [os.path.join(GAME, "work", "dsp", d, "SP_PL%02X.DSP" % c) for d in TIERDIRS] + [os.path.join(GAME, "work", "dsp", "files", "SP_PL%02X.DSP" % c)]
    out = []
    for f in files:
        if not os.path.exists(f): out.append(None); continue
        x = D.DSP(f)
        magic = x.sec[0][:4]; size = struct.unpack_from("<I", x.sec[0], 4)[0] if magic in RATE else 0
        tot = 0.0
        for t in x.tiles:
            n = v.get(t.idx, 0) if v else t.wb * t.h
            tot += n * (RATE[magic] if magic in RATE and t.off < size else RATE[None])
        out.append(tot)
    return out


def table():
    """{c: [u16 cost per tier]} scaled to COST_UNIT; characters without play data: tile bytes (uniform) scaled to the
    average measured volume"""
    raw = {c: costs(c) for c in range(0x17)}
    meas = [c for c in raw if vol(c)]
    unif = [c for c in raw if not vol(c)]
    if unif:   # bring uniform-weighted characters to the measured average (at tier 6)
        avg_m = sum(raw[c][-1] for c in meas) / len(meas)
        for c in unif:
            k = avg_m / raw[c][-1]
            raw[c] = [x * k if x is not None else None for x in raw[c]]
    return {c: [min(0xffff, int(x / COST_UNIT)) if x is not None else 0xffff for x in r] for c, r in raw.items()}


if __name__ == "__main__":
    T = table()
    for c, r in T.items(): print("%02x" % c, r, "measured" if vol(c) else "uniform")
