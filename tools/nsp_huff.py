"""XVH1: re-encode X-Men vs. Street Fighter character .NSP pixel sections (sec2).

Codec (per tile, random access, static per-file model):
  pixels are coded one 4bpp pixel at a time in raster order with canonical Huffman codes
  (max 12 bits).  Alphabet = 16 literal pixel values + 30 "copy from the row above" run
  symbols (run lengths RUNS, in pixels; above the first row "up" is colour 15).
  The code table is selected by the four causal neighbours (15 outside the tile):
      c1    = map1[L<<8 | U<<4 | UL]        (4096 bytes -> class)
      table = map2[c1<<4 | UR]              (16 bytes per class -> table, <=256 tables)
  Each tile stream is byte aligned, MSB first: 4 bits width code (pixels/16-1), then codes.

sec2 layout of a re-encoded file:
  +0   u32 magic 'XVH1'
  +4   u32 size of sec2 in bytes (model + streams, padded to 4)
  +8   u16 offset of map2, +10 u16 offset of tabofs (both from sec2 start)
  +12  u8  map1[4096]
  ...  u8  map2[16*classes]
  ...  u16 tabofs[tables]      offset from sec2 start to table record
  ...  table records: u8 cnt[12] (number of codes of length 1..12), then symbols in canonical order
  ...  tile streams (sec1 offsets stay relative to sec2 start)
sec0, sec1 (except the offset bits) and sec3 are copied unchanged.

  python nsp_huff.py encode [ids hex...] [-k tables] [-c classes]  -> build/nsp/SP_PLxx.NSP + stats.json
  python nsp_huff.py verify [ids hex...]     -> reference-decode every tile of the built files
  python nsp_huff.py table
"""
import sys, os, json, struct, time
os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'nbcache'))
import numpy as np
import numba as nb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nsp import NSP
from nsp_codec import cluster, canon, RUNS, NR, A0, ROOT

OUTDIR = os.path.join(ROOT, "build", "nsp")
MAGIC = 0x31485658            # 'XVH1'
MAXLEN = 12
RUNS16 = RUNS.astype(np.int64)
# experimental 'repeat left pixel' run symbols: measured WORSE (+2.5KB/char), keep 0 (decoder has no support)
NLEFT = int(os.environ.get('XV_NLEFT', '0'))


@nb.njit
def parse2(S, W, tab, lens, RUNS, choice, NL):
    """Optimal parse (literal vs up-run) for the given per-pixel table index and code lengths."""
    n = len(S)
    runlen = np.zeros(n + 1, np.int32)
    for i in range(n - 1, -1, -1):
        up = S[i - W] if i >= W else 15
        runlen[i] = runlen[i + 1] + 1 if S[i] == up else 0
    lrun = np.zeros(n + 1, np.int32)        # pixels from i on equal to the pixel left of i (15 at row start)
    eq = np.zeros(n + 1, np.int32)          # run of equal pixels starting at i
    for i in range(n - 1, -1, -1):
        eq[i] = eq[i + 1] + 1 if (i + 1 < n and S[i + 1] == S[i]) else 1
    for i in range(n):
        lv = S[i - 1] if (i % W) else 15
        lrun[i] = eq[i] if S[i] == lv else 0
    cost = np.zeros(n + 1, np.int64)
    for i in range(n - 1, -1, -1):
        t = tab[i]
        l = lens[t, S[i]]
        if l == 0: l = 30
        best = cost[i + 1] + l; bc = 0
        rl = runlen[i]
        for r in range(len(RUNS)):
            if RUNS[r] > rl: break
            l = lens[t, 16 + r]
            if l == 0: l = 30
            c = cost[i + RUNS[r]] + l
            if c < best:
                best = c; bc = r + 1
        rl = lrun[i]
        if NL:
            for r in range(1, len(RUNS)):
                if RUNS[r] > rl: break
                l = lens[t, 16 + len(RUNS) + r]
                if l == 0: l = 30
                c = cost[i + RUNS[r]] + l
                if c < best:
                    best = c; bc = len(RUNS) + r + 1
        cost[i] = best; choice[i] = bc


@nb.njit
def acc_hist(S, c12, q, choice, RUNS, hist1):
    """hist1[c12, q, sym] += 1 for every coded symbol."""
    n = len(S); i = 0
    while i < n:
        c = choice[i]
        if c == 0:
            hist1[c12[i], q[i], S[i]] += 1; i += 1
        else:
            hist1[c12[i], q[i], 16 + c - 1] += 1; i += RUNS[(c - 1) % len(RUNS)]


@nb.njit
def enc_tile(S, W, tab, lens, codes, RUNS, choice, out):
    n = len(S); i = 0; p = 0
    acc = (W >> 4) - 1; nb_ = 4
    while i < n:
        t = tab[i]
        c = choice[i]
        if c == 0:
            sym = S[i]; i += 1
        else:
            sym = 16 + c - 1; i += RUNS[(c - 1) % len(RUNS)]
        l = lens[t, sym]
        acc = (acc << l) | codes[t, sym]; nb_ += l
        while nb_ >= 8:
            out[p] = (acc >> (nb_ - 8)) & 255; p += 1; nb_ -= 8
        acc &= (1 << nb_) - 1
    if nb_:
        out[p] = (acc << (8 - nb_)) & 255; p += 1
    return p


@nb.njit
def ref_decode(mem, src, n, model, RUNS, out):
    """Exact model of the MIPS decoder nsp_dec(src, dst, n, model) in tools/nspdec.c.
    mem = whole file image; src/model = byte offsets into it. Returns source bytes consumed."""
    rb = np.full(258, 15, np.int64)          # rb[x] = pixel above x; rb[W] stays 15
    src0 = src
    map2 = model + np.int64(mem[model + 8]) + (np.int64(mem[model + 9]) << 8)
    tofs = model + np.int64(mem[model + 10]) + (np.int64(mem[model + 11]) << 8)
    buf = (np.int64(mem[src]) << 24) | 0x800000; src += 1
    W = ((buf >> 28) + 1) * 16
    buf = (buf << 4) & 0xFFFFFFFF
    x = 0; L = 15 << 8; UL = 15; lo = 0; o = 0; run = 0
    while o < n:
        U = rb[x]
        if run == 0:
            c1 = np.int64(mem[model + 12 + (L | (U << 4) | UL)])
            t = np.int64(mem[map2 + ((c1 << 4) | rb[x + 1])])
            rec = model + (np.int64(mem[tofs + 2 * t]) | (np.int64(mem[tofs + 2 * t + 1]) << 8))
            sp = rec + 12
            d = 0
            while True:
                tt = (buf << 1) & 0xFFFFFFFF
                if tt == 0:
                    buf = (np.int64(mem[src]) << 24) | 0x800000; src += 1
                    tt = (buf << 1) & 0xFFFFFFFF
                d = d * 2 + (buf >> 31)
                buf = tt
                c = np.int64(mem[rec]); rec += 1
                if d < c:
                    break
                d -= c; sp += c
            sym = np.int64(mem[sp + d])
            if sym < 16:
                p = sym
            else:
                run = RUNS[sym - 16] - 1
                p = U
        else:
            run -= 1
            p = U
        rb[x] = p
        if x & 1:
            out[o] = lo | (p << 4); o += 1
        else:
            lo = p
        x += 1
        if x == W:
            x = 0; L = 15 << 8; UL = 15
        else:
            L = p << 8; UL = U
    return src - src0


def tile_ctx(t):
    """per-pixel S, c12 = L<<8|U<<4|UL, q = UR (15 outside the tile), raster order."""
    a = np.frombuffer(t.raw, np.uint8).reshape(t.h, t.wb)
    px = np.empty((t.h, t.wb * 2), np.int32); px[:, 0::2] = a & 15; px[:, 1::2] = a >> 4
    P = np.full((t.h + 1, t.wb * 2 + 2), 15, np.int32); P[1:, 1:-1] = px
    L = P[1:, :-2]; U = P[:-1, 1:-1]; UL = P[:-1, :-2]; UR = P[:-1, 2:]
    return px.ravel().copy(), ((L << 8) | (U << 4) | UL).ravel().astype(np.int32), UR.ravel().astype(np.int32)


def build(cid, K=256, C1=256, passes=3):
    t0 = time.time()
    path = os.path.join(A0, "SP_PL%02X.NSP" % cid)
    n = NSP(path); n.decode_all()
    assert n.offs[0] == 16 and all(o % 4 == 0 for o in n.offs)
    T = n.tiles
    assert all(t.flag == 0 and (t.word >> 22) & 1 == 0 for t in T)
    uniq = {}; order = []
    for t in T:
        k = (t.wb, t.raw)
        if k not in uniq:
            uniq[k] = len(order); order.append(t)
    data = [tile_ctx(t) + (t.wb * 2,) for t in order]
    NS = 16 + NR + (NR if NLEFT else 0)
    map1 = np.zeros(4096, np.int32); map2 = np.zeros(16, np.int32)
    lens = np.full((1, NS), 3, np.uint8)
    choices = [np.zeros(len(d[0]), np.int32) for d in data]
    tabs = [np.zeros(len(d[0]), np.int32) for d in data]
    nc1 = 1
    for p in range(passes + 1):
        hist1 = np.zeros((4096, 16, NS), np.int64)
        for (S, c12, q, W), ch, tb in zip(data, choices, tabs):
            parse2(S, W, tb, lens, RUNS16, ch, NLEFT)
            acc_hist(S, c12, q, ch, RUNS16, hist1)
        if p == passes: break            # last pass: parse only, with the final tables
        if C1 > 1:
            map1, _ = cluster(hist1.reshape(4096, 16 * NS), C1, iters=8, limit=15)
        nc1 = int(map1.max()) + 1
        hist2 = np.zeros((nc1, 16, NS), np.int64)
        np.add.at(hist2, map1, hist1)
        map2, lens = cluster(hist2.reshape(nc1 * 16, NS), K, limit=MAXLEN)
        for (S, c12, q, W), tb in zip(data, tabs):
            tb[:] = map2[map1[c12] * 16 + q]
    ntab = lens.shape[0]
    th = np.zeros((ntab, NS), np.int64)
    np.add.at(th, map2[(map1[:, None] * 16 + np.arange(16)[None, :])].ravel(), hist1.reshape(-1, NS))
    assert not ((th > 0) & (lens == 0)).any(), "symbol without code"
    codes, first, cnt, offs, ss = canon(lens)
    assert ntab <= 256 and nc1 <= 256 and lens.max() <= MAXLEN
    # ---- model blob
    o_map2 = 12 + 4096
    o_tofs = o_map2 + nc1 * 16
    o_recs = o_tofs + 2 * ntab
    recs = bytearray(); tofs = []
    for k in range(ntab):
        tofs.append(o_recs + len(recs))
        recs += bytes(int(cnt[k, l]) for l in range(1, MAXLEN + 1))
        nused = int((lens[k] > 0).sum())
        recs += bytes(int(s) for s in ss[k, :nused])
    model = bytearray(struct.pack("<IIHH", MAGIC, 0, o_map2, o_tofs)) + bytes(int(x) for x in map1) \
        + bytes(int(x) for x in map2) + struct.pack("<%dH" % ntab, *tofs) + recs
    assert len(model) < 65536 and o_tofs % 2 == 0
    # ---- streams
    out = np.zeros(1 << 17, np.uint8)
    sec2 = bytearray(model); uoff = []
    for (S, c12, q, W), ch, tb in zip(data, choices, tabs):
        m = enc_tile(S, W, tb, lens, codes, RUNS16, ch, out)
        uoff.append(len(sec2)); sec2 += out[:m].tobytes()
    sec2 += b"\0" * (-len(sec2) % 4)
    assert len(sec2) < (1 << 22)
    struct.pack_into("<I", sec2, 4, len(sec2))
    sec1 = bytearray(n.sec[1])
    for t in T:
        w = (t.word & ~0x3FFFFF) | uoff[uniq[(t.wb, t.raw)]]
        struct.pack_into("<I", sec1, t.idx * 4, w)
    o1, o2 = n.offs[1], n.offs[2]
    o3 = o2 + len(sec2)
    new = struct.pack("<4I", 16, o1, o2, o3) + n.sec[0] + bytes(sec1) + bytes(sec2) + n.sec[3]
    assert len(n.sec[0]) == o1 - 16 and len(sec1) == o2 - o1
    bad = verify_bytes(new, n)
    assert bad == 0, "round trip failed"
    st = dict(id=cid, old=len(n.d), new=len(new), old_sec2=n.sizes[2], new_sec2=len(sec2), model=len(model),
              streams=len(sec2) - len(model), tables=ntab, classes=nc1, tiles=len(T), uniq=len(order),
              other=len(new) - len(sec2), raw=sum(len(t.raw) for t in T), secs=time.time() - t0)
    return new, st


def verify_bytes(new, orig):
    """Decode every tile of the new file image with ref_decode; compare with the original tiles."""
    mem = np.frombuffer(new, np.uint8)
    o1, o2, o3 = struct.unpack_from("<3I", new, 4)
    assert struct.unpack_from("<I", new, o2)[0] == MAGIC
    out = np.zeros(1 << 16, np.uint8); bad = 0
    orig.decode_all()
    assert (o2 - o1) // 4 == len(orig.tiles)
    for t in orig.tiles:
        w = struct.unpack_from("<I", new, o1 + 4 * t.idx)[0]
        assert w >> 22 == t.word >> 22
        nbytes = t.wb * t.h
        used = ref_decode(mem, o2 + (w & 0x3FFFFF), nbytes, o2, RUNS16, out)
        if out[:nbytes].tobytes() != t.raw: bad += 1
        assert o2 + (w & 0x3FFFFF) + used <= o3
    return bad


def _job(a):
    cid, K, C1 = a
    new, st = build(cid, K, C1)
    os.makedirs(OUTDIR, exist_ok=True)
    open(os.path.join(OUTDIR, "SP_PL%02X.NSP" % cid), "wb").write(new)
    return st


def main():
    args = sys.argv[1:]
    K = 256; C1 = 256
    if "-k" in args:
        i = args.index("-k"); K = int(args[i + 1]); del args[i:i + 2]
    if "-c" in args:
        i = args.index("-c"); C1 = int(args[i + 1]); del args[i:i + 2]
    cmd = args[0]
    ids = [int(x, 16) for x in args[1:]] or list(range(0x13))
    if cmd == "encode":
        from multiprocessing import Pool
        sp = os.path.join(OUTDIR, "stats.json")
        os.makedirs(OUTDIR, exist_ok=True)
        stats = json.load(open(sp)) if os.path.exists(sp) else {}
        with Pool(min(6, len(ids))) as p:
            for st in p.imap_unordered(_job, [(c, K, C1) for c in ids]):
                stats["%02X" % st["id"]] = st
                print("PL%02X old %7d new %7d  sec2 %7d -> %7d (model %5d, %3d tables, %3d classes)  %.0fs" % (
                    st["id"], st["old"], st["new"], st["old_sec2"], st["new_sec2"], st["model"], st["tables"], st["classes"], st["secs"]), flush=True)
        json.dump(stats, open(sp, "w"), indent=1)
    elif cmd == "verify":
        tot = 0
        for c in ids:
            new = open(os.path.join(OUTDIR, "SP_PL%02X.NSP" % c), "rb").read()
            o = NSP(os.path.join(A0, "SP_PL%02X.NSP" % c))
            bad = verify_bytes(new, o); tot += bad
            assert new[16:struct.unpack_from("<I", new, 4)[0]] == o.sec[0] and new[struct.unpack_from("<I", new, 12)[0]:] == o.sec[3]
            print("PL%02X tiles %5d mismatching %d  (sec0/sec3 identical)" % (c, len(o.tiles), bad), flush=True)
        print("TOTAL mismatching tiles:", tot)
    elif cmd == "table":
        stats = json.load(open(os.path.join(OUTDIR, "stats.json")))
        print("char   old file  new file   old px   streams  model  non-px  tiles uniq")
        for k in sorted(stats):
            s = stats[k]
            print("PL%s  %8d  %8d  %7d  %7d  %5d  %6d  %5d %5d" % (k, s["old"], s["new"], s["old_sec2"], s["streams"], s["model"], s["other"], s["tiles"], s["uniq"]))
        n = len(stats); S = lambda f: sum(s[f] for s in stats.values())
        print("avg   %8d  %8d  %7d  %7d  %5d  %6d" % (S("old") // n, S("new") // n, S("old_sec2") // n, S("streams") // n, S("model") // n, S("other") // n))


if __name__ == "__main__":
    main()
