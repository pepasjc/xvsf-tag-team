"""Mixed sprite tiers (idea 3 of the dx task): one character file = a STRONG part (DSA1 or DSX/DSH1, the existing
tier file with its hot tiles' streams removed) + an embedded DSM1 sub-part holding the most-played tiles.

Why: a tile that moves from DSH1/DSX to DSM1 costs ~+15 % of its compressed bytes but decodes ~2-3x faster (DSX 67,
DSH1 89, DSA1 ~580 cycles per byte vs DSM1 33); the existing hot tiers move tiles to stock RLE instead (+100 % bytes
vs DSH1, +105 % vs DSA1).  Per byte of RAM DSM1-hot buys ~5x more decode time than RLE-hot once the 4-6 KB DSM1 model
is paid for.

sec0 layout (kind 8 DSP, sections 1-3 = the base file's, sec2 offsets rewritten):
    [base model][base streams of the cold tiles][pad4][DSM1 sub-part: model (K tables) + streams][pad4]
    ['MIX1'][u32 S = offset of the DSM1 sub-part]          <- the base part's +4 size field covers all of this
    [stock RLE hot tiles of the base, if any]
Dispatch (EXE, unchanged): a tile inside the base part goes through dshptr / dsaptr -> the RAM front end
(tools/speed4/fe.S): if the last 8 bytes of the part are 'MIX1' S and src >= part + S -> a3 = part + S, j dsm_dec.
Exact: every tile through the real MIPS decoders (Unicorn, this file's `verify`) vs the base file.

    python mix.py build BASE NAME KB [ids hex..]   -> games/mvc/work/speed4/dsp/NAME/PLxx_10.DSP + stats.json
           BASE = tier name (dsa, dsa_cut48, dsh_cut16, dsx, dsx_cut16 = DSX-converted dsh_cut16 ...), KB = budget
           of DSM1 stream bytes (model not counted)
    python mix.py verify NAME [ids]                 every tile, Unicorn, front end + RAM decoders
Env: MVC_FXW (default root_v4 tree), DX_K (DSM1 tables, default 12), DX_FXW8 (weight of the fxscan every-move volume
vs the hot.py fight volume, default 0.5).
"""
import os, sys, struct, json, glob, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "common", "dsp"), os.path.join(ROOT, "tools")]
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(ROOT, "work", "nbcache"))
import dsp as D
import dsm as DM
import dsx as DSX
import nsp_mid as XM

FXW = os.environ.get("MVC_FXW") or os.path.join(GAME, "work", "fxhalf", "root_v4", "games", "mvc", "work", "dsp")
OUT = os.path.join(GAME, "work", "speed4", "dsp")
MIX = 0x3158494D                                   # 'MIX1'
K = int(os.environ.get("DX_K", "12"))
FXWT = float(os.environ.get("DX_FXW8", "0.5"))
CHARS = [c for c in range(1, 0x17) if c != 0x11]


def base_file(c, base):
    if base.startswith("dsx"):
        p = os.path.join(FXW, "dsh" + base[3:], "PL%02X_10.DSP" % c)
        return DSX.convert(open(p, "rb").read())[0] if os.path.exists(p) else None
    p = os.path.join(FXW, base, "PL%02X_10.DSP" % c)
    return open(p, "rb").read() if os.path.exists(p) else None


def stock_raw(c):
    """option-B stock-format DSP of the shadow tree (RLE) -> decoded tiles (the reference pixels)"""
    b = open(os.path.join(FXW, "files", "PL%02X_10.A0" % c), "rb").read()
    n, = struct.unpack_from("<I", b); fs = [struct.unpack_from("<2I", b, 4 + 8 * i) for i in range(n)]
    x = D.DSP(b[fs[1][0]:fs[1][0] + fs[1][1]] + b[fs[1][0] + fs[1][1]:fs[1][0] + fs[1][1] + 64])
    x.decode_all()
    return x


def volumes(c, x):
    """per tile index: play volume (bytes decoded), hot.py fight runs + FXWT x fxscan every-move run, each normalised"""
    hv = {}
    for p in (os.path.join(FXW, "hot", "PL%02X_10.json" % c), os.path.join(GAME, "work", "dsp", "hot", "PL%02X_10.json" % c)):
        if os.path.exists(p):
            hv = {int(k): v for k, v in json.load(open(p)).items()}; break
    fv = {}
    p = os.path.join(GAME, "work", "fxscan", "mv_%x.json" % c)
    if os.path.exists(p):
        j = json.load(open(p))
        grp = {start: [pt.tile for pt in g] for start, hdr, g in x.groups()}
        ps = {}
        for o in j["objs"]:                        # the scanned character = P1 main; its effects use its set slot
            if o["kind"] == "P0" and o["char"] == c: ps.update(o["slots"])
        myslots = set(ps)
        for o in j["objs"]:
            mine = (o["kind"] == "P0" and o["char"] == c) or (o["kind"] == "E" and myslots & set(o["slots"]))
            if not mine or not o["ndec"]: continue
            ts = grp.get(o["group"])
            if not ts: continue
            gb = sum(x.tiles[t].n for t in ts if t < len(x.tiles)) or 1
            ndec = o["dbytes"] / gb                # how many times the group was decoded (approximately)
            for t in ts:
                if t < len(x.tiles): fv[t] = fv.get(t, 0) + ndec * x.tiles[t].n
    hs = sum(hv.values()) or 1; fs_ = sum(fv.values()) or 1
    out = {}
    for t in set(hv) | set(fv):
        out[t] = hv.get(t, 0) / hs + FXWT * fv.get(t, 0) / fs_
    return out


def split_part(y):
    """-> (magic, part size, model end, {offset: stream bytes})"""
    s0 = y.sec[0]
    magic, size = struct.unpack_from("<2I", s0)
    offs = sorted({t.off for t in y.tiles if t.off < size})
    mend = offs[0]
    st = {}
    for i, o in enumerate(offs):
        st[o] = s0[o:(offs[i + 1] if i + 1 < len(offs) else size)]
    return magic, size, mend, st


def build_one(c, base, kb):
    data = base_file(c, base)
    if data is None: return None
    y = D.DSP(data); x = stock_raw(c)
    assert len(x.tiles) == len(y.tiles)
    magic, size, mend, st = split_part(y)
    assert magic in (0x31415344, 0x31485344), hex(magic)
    used = set()
    for start, hdr, g in y.groups():
        for pt in g: used.add(pt.tile)
    vol = volumes(c, x)
    # candidate streams: inside the base part, used by a referenced tile; score = volume per stored byte
    by_off = {}
    for t in y.tiles:
        if t.off < size: by_off.setdefault(t.off, []).append(t.idx)
    cand = []
    for o, ids in by_off.items():
        if not any(i in used for i in ids): continue
        v = sum(vol.get(i, 0) for i in ids)
        if v <= 0: continue
        cand.append((v / len(st[o]), v, o))
    cand.sort(reverse=True)
    cap = kb * 1024; est = 0; hot = []
    for r, v, o in cand:                         # DSM1 stream ~ 1.15 x the DSX / DSH1 stream, ~1.0 x DSA1 x 1.18
        e = int(len(st[o]) * (1.18 if magic == 0x31415344 else 1.12))
        if est + e > cap: continue
        est += e; hot.append(o)
    hot = sorted(hot)
    hotset = set(hot)
    # DSM1 sub-part over the hot tiles' pixels AS THE BASE FILE DECODES THEM (real MIPS decoders, Unicorn): cut tiers
    # zero their freed tiles, so the stock pixels are not always the base's
    reps = [by_off[o][0] for o in hot]
    run = unicorn_run()
    b0 = run.load(data)
    braw = [bytes(run.call(b0 + y.tiles[i].off, y.tiles[i].n)[:y.tiles[i].n]) for i in reps]
    data_ = [XM.tile_ctx(r, x.tiles[i].wb) + (x.tiles[i].wb,) for r, i in zip(braw, reps)]
    model, tmap, lens, codes, ch, hist = DM.build_model(data_, K)
    sub = bytearray(model); uoff = {}
    buf = np.zeros(1 << 17, np.uint8)
    for (S, cx, W), cc, o in zip(data_, ch, hot):
        m = DM.emit(S, W, tmap[cx], cc, DM.R, lens, codes, buf)
        uoff[o] = len(sub); sub += buf[:m].tobytes()
    sub += bytes(4 + (-len(sub) % 4))
    struct.pack_into("<I", sub, 4, len(sub))
    # new sec0
    s0 = y.sec[0]
    new = bytearray(s0[:mend]); noff = {}
    for o in sorted(st):
        if o in hotset: continue
        noff[o] = len(new); new += st[o]
    new += bytes(-len(new) % 4)
    S = len(new); new += sub
    for o in hot: noff[o] = S + uoff[o]
    new += bytes(-len(new) % 4)
    new += struct.pack("<2I", MIX, S)
    struct.pack_into("<I", new, 4, len(new))
    tail0 = len(new)
    rl = {}
    for t in y.tiles:                             # the base's RLE hot tiles (behind its part)
        if t.off >= size and t.off not in rl:
            pass
    tails = sorted({t.off for t in y.tiles if t.off >= size})
    if tails:
        new += s0[size:]
        for o in tails: noff[o] = o - size + tail0
    offs = {t.idx: noff[t.off] for t in y.tiles}
    out = DM.assemble(y, bytes(new), offs)
    vt = sum(vol.values()) or 1
    f = sum(vol.get(i, 0) for o in hot for i in by_off[o]) / vt
    return out, dict(base=base, size=len(data), new=len(out), delta=len(out) - len(data), dsm_part=len(sub),
                     dsm_model=len(model), dsm_streams=len(sub) - len(model), hot_streams=len(hot),
                     moved_bytes=sum(len(st[o]) for o in hot), vol_frac=round(f, 4))


def cmd_build(base, name, kb, ids):
    od = os.path.join(OUT, name); os.makedirs(od, exist_ok=True)
    sp = os.path.join(od, "stats.json")
    stats = json.load(open(sp)) if os.path.exists(sp) else {}
    for c in ids:
        r = build_one(c, base, kb)
        if r is None:
            print("PL%02X: no %s file" % (c, base)); continue
        out, s = r
        assert MIX not in [struct.unpack_from("<I", base_file(c, base), 0)[0]]
        open(os.path.join(od, "PL%02X_10.DSP" % c), "wb").write(out)
        stats["PL%02X_10" % c] = s
        print("PL%02X %s -> %s: %7d -> %7d (%+6d)  dsm model %5d streams %6d (%d tiles, %d B moved)  volume in DSM1 %.1f %%" % (
            c, base, name, s["size"], s["new"], s["delta"], s["dsm_model"], s["dsm_streams"], s["hot_streams"], s["moved_bytes"],
            100 * s["vol_frac"]), flush=True)
    json.dump(stats, open(sp, "w"), indent=1)


# ---------------------------------------------------------------- verification on the real MIPS decoders (Unicorn)
_RUN = None


def unicorn_run():
    """the fight RAM image + the tag build's dispatch + front ends + RAM decoders (dsmpatch.TEST layout)"""
    global _RUN
    if _RUN: return _RUN
    sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "decode")); sys.path.insert(0, HERE)
    import dsmtest as T, dsmpatch as P, fe, dlib as DL
    t = P.TEST["mvc"]
    code, dsa_off = fe.payload(t["dsh_at"])
    pokes = list(P.patches("mvc", dshptr=t["dshptr"], dsaptr=t["dsaptr"]))
    pokes += [(t["dsh_at"], code), (t["dshptr"], struct.pack("<2I", t["dsh_at"], t["dsh_at"] + dsa_off))]
    m = bytearray(open(os.path.join(ROOT, T.RAM["mvc"]), "rb").read())
    for a, d in pokes: m[a & 0x1fffff:(a & 0x1fffff) + len(d)] = d
    run = T.Run.__new__(T.Run); run.g = "mvc"; run.uc = DL.UC(m); run.uc.mu.mem_map(0x1f800000, 0x1000)
    run.fn = P.GAMES["mvc"]["dec"][0]
    _RUN = run
    return run
def fe_code(at):
    import fe
    return fe.payload(at)


def cmd_verify(name, ids):
    sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "decode")); sys.path.insert(0, HERE)
    import dsmtest as T, dsmpatch as P, fe
    t = P.TEST["mvc"]
    code, dsa_off = fe.payload(t["dsh_at"])
    pokes = list(P.patches("mvc", dshptr=t["dshptr"], dsaptr=t["dsaptr"]))
    pokes += [(t["dsh_at"], code), (t["dshptr"], struct.pack("<2I", t["dsh_at"], t["dsh_at"] + dsa_off))]
    m = bytearray(open(os.path.join(ROOT, T.RAM["mvc"]), "rb").read())
    for a, d in pokes: m[a & 0x1fffff:(a & 0x1fffff) + len(d)] = d
    import dlib as DL
    run = T.Run.__new__(T.Run); run.g = "mvc"; run.uc = DL.UC(m); run.uc.mu.mem_map(0x1f800000, 0x1000)
    run.fn = P.GAMES["mvc"]["dec"][0]
    st = json.load(open(os.path.join(OUT, name, "stats.json")))
    tot = bad = 0
    for c in ids:
        p = os.path.join(OUT, name, "PL%02X_10.DSP" % c)
        if not os.path.exists(p): continue
        new = open(p, "rb").read(); y = D.DSP(new)
        ref = base_file(c, st["PL%02X_10" % c]["base"]); yr = D.DSP(ref)
        S = struct.unpack_from("<I", y.sec[0], struct.unpack_from("<I", y.sec[0], 4)[0] - 4)[0]
        b1 = run.load(new); outs = []
        for u in y.tiles: outs.append(run.call(b1 + u.off, u.n))
        b0 = run.load(ref); nb = 0
        for u, ur, o in zip(y.tiles, yr.tiles, outs):
            r = run.call(b0 + ur.off, ur.n)
            k = u.n if S <= u.off < struct.unpack_from("<I", y.sec[0], 4)[0] else u.n + T.SLACK
            nb += 1; bad += r[:k] != o[:k]
        tot += nb
        print("PL%02X %s tiles %5d mismatching so far %d" % (c, name, nb, bad), flush=True)
    print("TOTAL %s tiles %d mismatching %d" % (name, tot, bad))
    return bad


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "build":
        cmd_build(a[1], a[2], int(a[3]), [int(v, 16) for v in a[4:]] or CHARS)
    elif a[0] == "verify":
        sys.exit(1 if cmd_verify(a[1], [int(v, 16) for v in a[2:]] or CHARS) else 0)


def hot_frac(c, t):
    """hot.py play-volume share of the tiles in the DSM1 sub-part of mixed tier file t (the tiercost.json volume)"""
    x = D.DSP(open(os.path.join(OUT, t, "PL%02X_10.DSP" % c), "rb").read())
    s0 = x.sec[0]; size = struct.unpack_from("<I", s0, 4)[0]; S = struct.unpack_from("<I", s0, size - 4)[0]
    hp = os.path.join(FXW, "hot", "PL%02X_10.json" % c)
    if not os.path.exists(hp): hp = os.path.join(GAME, "work", "dsp", "hot", "PL%02X_10.json" % c)
    if not os.path.exists(hp): return 0.0
    v = {int(k): w for k, w in json.load(open(hp)).items()}
    tot = sum(v.values()) or 1
    return sum(w for k, w in v.items() if k < len(x.tiles) and S <= x.tiles[k].off < size) / tot


def mixcost(c, t, row, cutpen=(0, 5)):
    """planner cost (cycles per byte x 10, as tiercost.json) of mixed tier t for character c: the base codec on the
    volume left in it, DSM1 on the volume moved, plus the base's cut penalty (mktag.py costs())"""
    p = os.path.join(OUT, t, "stats.json")
    s = json.load(open(p)).get("PL%02X_10" % c) if os.path.exists(p) else None
    if not s: return 65000
    b = s["base"]; codec = "dsa" if b.startswith("dsa") else "dsx" if b.startswith("dsx") else "dsh"
    f = hot_frac(c, t)
    v = (1 - f) * row.get(codec, 900) + f * row.get("dsm", 330)
    if "_cut" in b:
        n = int(b.split("_cut")[1])
        v += (cutpen[0] + cutpen[1] * n) if codec != "dsa" else 20000 + 900 * n
    return int(min(v, 65000))


def is_mix(data):
    """True when a tier file's strong part ends in the MIX1 trailer"""
    s0 = 0x14
    size = struct.unpack_from("<I", data, s0 + 4)[0]
    return data[s0 + size - 8:s0 + size - 4] == b"MIX1"
