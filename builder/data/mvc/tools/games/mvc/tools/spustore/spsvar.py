"""SPU store tier variants (mktag.py --spustore; docs/TAGLOAD.md "SPU store").

A variant is the same DSH1-family tier file (dsh, dsh_cutN, dsx) with its pixel part re-ordered:

    sec0 = [part header + model][warm streams, original order][cold streams: least cold first, most cold last]

Every cold stream starts 8-aligned (sec0-relative) and is <= 2048 bytes; the part's size word still covers the whole
sec0 (cold tiles that stay in RAM decode as before).  The loader (tagload.c SPUSTORE) moves a suffix of the cold
region (one of the cut sizes below) to SPU RAM, truncates the file in RAM and turns those tiles' table entries into
proxies 0x80210000 + (class << 16 | spu >> 3) that the RAM front end (spsfe.py) fetches by SPU DMA.

Cold order (most cold first): tiles never referenced by any frame group of this tier, then tiles with zero play
volume in the soak profiles (tools/speed4/mix.py volumes(): hot.py fight runs + fxscan every-move run).  Override
for the dx worker: env SPS_COLD = json file {"PLxx_10": {"TIER": [tile idx, most cold first], ...}, ...}; only the
streams of the listed tiles are used, in that order.

    variant(c, tier, data) -> (variant bytes, [cut bytes x NCUT], stats) or None (tier not eligible)
    python spsvar.py verify TIER [ids]   every tile of the variant vs the base tier on the real MIPS decoders
"""
import os, sys, struct, json, hashlib, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
os.environ.setdefault("MVC_FXW", os.path.join(GAME, "work", "fxhalf", "root_v5", "games", "mvc", "work", "dsp"))
sys.path.insert(0, os.path.join(GAME, "tools", "speed4"))
import mix as M

D, DM = M.D, M.DM
DSH1 = 0x31485344
GROUP = 2048                                       # cut unit: the cold region is k exact 2 KB groups
CUTS = [GROUP * k for k in range(1, 13)]    # SPU share choices per character (exact bytes: stream boundaries)
NCUT = len(CUTS)
MAXCOLD = CUTS[-1]
MAXSTREAM = 2040                                   # + <= 7 pad: <= 32 x 64 bytes per fetch
CACHE = os.path.join(GAME, "build", "spustore")
_vol = {}


def eligible(tier):
    return tier.startswith(("dsh", "dsx")) and "hot" not in tier


def _cold_override(c, tier):
    p = os.environ.get("SPS_COLD")
    if not p: return None
    j = json.load(open(p)).get("PL%02X_10" % c, {})
    return j.get(tier)


def _order(c, tier, y, size, st):
    """cold streams, most cold first"""
    by = {}
    for t in y.tiles:
        if t.off < size: by.setdefault(t.off, []).append(t.idx)
    ok = lambda o: len(st[o]) <= MAXSTREAM
    ov = _cold_override(c, tier)
    if ov is not None:
        out, seen = [], set()
        for i in ov:
            o = y.tiles[i].off
            if o in by and o not in seen and ok(o): seen.add(o); out.append(o)
        return out
    if c not in _vol: _vol[c] = M.volumes(c, M.stock_raw(c))
    vol = _vol[c]
    used = {pt.tile for s_, h, g in y.groups() for pt in g}
    unref = [o for o in sorted(by) if ok(o) and not any(i in used for i in by[o])]
    zero = [o for o in sorted(by) if ok(o) and o not in unref and all(vol.get(i, 0) == 0 for i in by[o])]
    return unref + zero


def variant(c, tier, data):
    if not eligible(tier) or data is None or c not in M.CHARS: return None     # Onslaught (0x11): no store
    key = hashlib.sha1(data + tier.encode() + bytes([c]) + open(__file__, "rb").read()
                       + (open(os.environ["SPS_COLD"], "rb").read() if os.environ.get("SPS_COLD") else b"")
                       + (("relax%s" % os.environ.get("SPS_NCUT", "32")).encode() if os.environ.get("SPS_RELAX") == "1" else b"")).hexdigest()[:16]
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, "PL%02X_%s_%s.pkl" % (c, tier, key))
    if os.path.exists(cp): return pickle.load(open(cp, "rb"))
    y = D.DSP(data)
    magic, size, mend, st = M.split_part(y)
    relax = os.environ.get("SPS_RELAX") == "1"            # --assist builds (assists lead, rc4.4): sec0 padded past the part
    trail = y.sec[0][size:] if relax else b""            # (1-3 B) or tiles stored after it (War Machine hover, Shadow
    if magic != DSH1 or (not relax and (any(t.off >= size for t in y.tiles) or size != len(y.sec[0]))):   # Lady): the tail
        r = None                                          # stays warm, right after the warm streams
    else:
        order = _order(c, tier, y, size, st)
        NCUT = int(os.environ.get("SPS_NCUT", "32")) if relax else globals()["NCUT"]   # --assist: up to 64 KB per character
        groups, cur, used, left = [], [], 0, list(order)   # exact 2 KB groups, most cold group first:
        for o in order:                                   # the loader's cut = k groups = k x 2048 bytes
            if len(groups) == NCUT: break
            need = len(st[o]) + (-len(st[o]) % 8)
            if used + need > GROUP:
                groups.append(cur); cur, used = [], 0
                if len(groups) == NCUT: break
            cur.append(o); used += need
        if cur and len(groups) < NCUT and used: groups.append(cur)
        if groups and sum(len(st[o]) + (-len(st[o]) % 8) for o in groups[-1]) < GROUP // 2: groups.pop()   # mostly padding
        pick = [o for g in groups for o in g]
        cold = set(pick)
        new = bytearray(y.sec[0][:mend]); noff = {}
        for o in sorted(st):
            if o not in cold: noff[o] = len(new); new += st[o]
        if trail:
            t0 = len(new); new += trail
            for t in y.tiles:
                if t.off >= size: noff[t.off] = t0 + t.off - size
        new += bytes(-len(new) % 8)
        for g in reversed(groups):                        # least cold group first: the cut takes a suffix
            g0 = len(new)
            for o in g:
                noff[o] = len(new); new += st[o]; new += bytes(-len(new) % 8)
            assert len(new) - g0 <= GROUP
            new += bytes(GROUP - (len(new) - g0))
        struct.pack_into("<I", new, 4, len(new))
        cuts = [GROUP * (k + 1) for k in range(len(groups))]
        out = DM.assemble(y, bytes(new), {t.idx: noff[t.off] for t in y.tiles})
        r = (out, cuts, dict(tier=tier, size=len(data), new=len(out), cold=GROUP * len(groups), streams=len(pick), cuts=cuts))
    pickle.dump(r, open(cp, "wb"))
    return r


def verify(tier, ids):
    run = M.unicorn_run()
    bad = tot = 0
    for c in ids:
        base = M.base_file(c, tier)
        r = variant(c, tier, base)
        if not r: continue
        new = r[0]
        y, yr = D.DSP(new), D.DSP(base)
        b1 = run.load(new); outs = [run.call(b1 + u.off, u.n) for u in y.tiles]
        b0 = run.load(base); nb = 0
        for u, ur, o in zip(y.tiles, yr.tiles, outs):
            q = run.call(b0 + ur.off, ur.n)
            nb += 1; bad += q[:u.n] != o[:u.n]
        tot += nb
        print("PL%02X %s tiles %d cold %d B, cuts %s, mismatching so far %d" % (c, tier, nb, r[2]["cold"], r[1], bad), flush=True)
    print("TOTAL %s tiles %d mismatching %d" % (tier, tot, bad))
    return bad


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "verify":
        sys.exit(1 if verify(a[1], [int(v, 16) for v in a[2:]] or M.CHARS) else 0)
