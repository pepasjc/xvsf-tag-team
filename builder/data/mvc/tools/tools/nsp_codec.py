"""Codec experiments on XvSF .NSP tile pixel data. Every codec here is per-tile random access
(each tile decodes from its own byte-aligned stream + static per-character tables only) and
every number reported comes from a real encode followed by a verified decode.

  python nsp_codec.py run [ids...]     -> work/codec_results/PLxx.json   (multiprocess)
  python nsp_codec.py table            -> summary table from the json files
  python nsp_codec.py xdedupe          -> duplicate tiles within / across characters
"""
import sys, os, json, zlib, lzma, heapq, time
import numpy as np
import numba as nb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nsp import NSP

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
A0 = os.path.join(ROOT, "disc", "files", "A", "A0")
OUT = os.path.join(ROOT, "work", "codec_results")

RUNS = np.array(list(range(1, 17)) + [24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 2048, 4096], dtype=np.int64)
NR = len(RUNS)
LIMIT = 12          # max Huffman code length

# modes: (symbol unit, alphabet, n raw contexts, runs allowed)
M_BL, M_BLU, M_PLU, M_PLUUL, M_PLAIN, M_B0 = 0, 1, 2, 3, 4, 5
MODEINFO = {M_BL: (256, 16), M_BLU: (256, 4096), M_PLU: (16, 256), M_PLUUL: (16, 4096), M_PLAIN: (256, 1), M_B0: (256, 1)}


@nb.njit(cache=True)
def ctx_at(S, i, W, mode):
    if mode == 4 or mode == 5:
        return 0
    if mode == 0 or mode == 1:
        L = (S[i - 1] >> 4) if (i % W) else 15
        if mode == 0:
            return L
        U = S[i - W] if i >= W else 255
        return (L << 8) | U
    L = S[i - 1] if (i % W) else 15
    U = S[i - W] if i >= W else 15
    if mode == 2:
        return (L << 4) | U
    UL = S[i - W - 1] if (i >= W and (i % W)) else 15
    return (L << 8) | (U << 4) | UL


@nb.njit(cache=True)
def up_at(S, i, W, mode):
    if i >= W:
        return S[i - W]
    return 255 if mode < 2 or mode == 5 else 15


@nb.njit(cache=True)
def parse(S, W, mode, A, tmap, lens, RUNS, hist, choice_out):
    """Optimal parse (literal vs copy-from-row-above run) for given code lengths; adds to hist.
    Returns (n_literal_symbols, n_run_symbols)."""
    n = len(S)
    ctx = np.zeros(n, np.int32)
    runlen = np.zeros(n + 1, np.int32)
    for i in range(n):
        ctx[i] = ctx_at(S, i, W, mode)
    if mode != 4:
        for i in range(n - 1, -1, -1):
            runlen[i] = runlen[i + 1] + 1 if S[i] == up_at(S, i, W, mode) else 0
    cost = np.zeros(n + 1, np.int64)
    choice = np.zeros(n, np.int32)
    for i in range(n - 1, -1, -1):
        t = tmap[ctx[i]]
        l = lens[t, S[i]]
        if l == 0: l = 30
        best = cost[i + 1] + l; bc = 0
        rl = runlen[i]
        for r in range(len(RUNS)):
            if RUNS[r] > rl: break
            l = lens[t, A + r]
            if l == 0: l = 30
            c = cost[i + RUNS[r]] + l
            if c < best:
                best = c; bc = r + 1
        cost[i] = best; choice[i] = bc
    i = 0; nl = 0; nrun = 0
    while i < n:
        c = choice[i]
        choice_out[i] = c
        if c == 0:
            hist[ctx[i], S[i]] += 1; i += 1; nl += 1
        else:
            hist[ctx[i], A + c - 1] += 1; i += RUNS[c - 1]; nrun += 1
    return nl, nrun


@nb.njit(cache=True)
def encode(S, W, mode, A, tmap, lens, codes, RUNS, choice, out):
    """Writes MSB-first bitstream into out; returns byte length (padded to byte)."""
    n = len(S); i = 0; acc = 0; nb_ = 0; p = 0
    while i < n:
        t = tmap[ctx_at(S, i, W, mode)]
        c = choice[i]
        if c == 0:
            sym = S[i]; i += 1
        else:
            sym = A + c - 1; i += RUNS[c - 1]
        l = lens[t, sym]
        acc = (acc << l) | codes[t, sym]; nb_ += l
        while nb_ >= 8:
            out[p] = (acc >> (nb_ - 8)) & 255; p += 1; nb_ -= 8
        acc &= (1 << nb_) - 1
    if nb_:
        out[p] = (acc << (8 - nb_)) & 255; p += 1
    return p


@nb.njit(cache=True)
def decode(src, n, W, mode, A, tmap, first, cnt, offs, sorted_syms, RUNS):
    """Canonical-Huffman decoder + context model; returns decoded symbol array."""
    out = np.zeros(n, np.int32)
    i = 0; bp = 0
    while i < n:
        t = tmap[ctx_at(out, i, W, mode)]
        code = 0; l = 0; sym = -1
        while True:
            code = (code << 1) | ((src[bp >> 3] >> (7 - (bp & 7))) & 1); bp += 1; l += 1
            d = code - first[t, l]
            if d >= 0 and d < cnt[t, l]:
                sym = sorted_syms[t, offs[t, l] + d]; break
            if l > 14:
                return out[:0]
        if sym < A:
            out[i] = sym; i += 1
        else:
            r = RUNS[sym - A]
            for k in range(r):
                out[i] = up_at(out, i, W, mode); i += 1
    return out


def hufflens(counts, limit=LIMIT):
    counts = np.asarray(counts)
    idx = np.nonzero(counts)[0]
    lens = np.zeros(len(counts), np.uint8)
    if len(idx) == 0: return lens
    if len(idx) == 1:
        lens[idx[0]] = 1; return lens
    h = [(int(counts[i]), int(i), None, None) for i in idx]
    heapq.heapify(h); uid = len(counts)
    while len(h) > 1:
        a = heapq.heappop(h); b = heapq.heappop(h)
        heapq.heappush(h, (a[0] + b[0], uid, a, b)); uid += 1
    stack = [(h[0], 0)]
    while stack:
        (c, i, l, r), d = stack.pop()
        if l is None: lens[i] = d
        else: stack.append((l, d + 1)); stack.append((r, d + 1))
    if lens.max() > limit:
        lens[idx] = np.minimum(lens[idx], limit)
        K = int((1 << (limit - lens[idx].astype(np.int64))).sum())
        order = sorted(idx, key=lambda i: (-int(lens[i]), int(counts[i])))   # longest, rarest first
        while K > (1 << limit):
            for i in order:
                if lens[i] < limit:
                    K -= 1 << (limit - lens[i] - 1); lens[i] += 1
                    if K <= (1 << limit): break
            order = sorted(idx, key=lambda i: (-int(lens[i]), int(counts[i])))
        for i in sorted(idx, key=lambda i: -int(counts[i])):                 # use slack
            while lens[i] > 1 and K + (1 << (limit - lens[i])) <= (1 << limit):
                K += 1 << (limit - lens[i]); lens[i] -= 1
    return lens


def canon(lens):
    """lens[K, NS] -> codes, first, cnt, offs, sorted_syms for canonical decoding."""
    K, NS = lens.shape
    codes = np.zeros((K, NS), np.int64)
    first = np.zeros((K, 17), np.int64); cnt = np.zeros((K, 17), np.int64); offs = np.zeros((K, 17), np.int64)
    ss = np.zeros((K, NS), np.int32)
    for k in range(K):
        code = 0; pos = 0
        for l in range(1, 16):
            syms = np.nonzero(lens[k] == l)[0]
            first[k, l] = code; cnt[k, l] = len(syms); offs[k, l] = pos
            for s in syms:
                codes[k, s] = code; code += 1; ss[k, pos] = s; pos += 1
            code <<= 1
    return codes, first, cnt, offs, ss


def cluster(hist, K, iters=12, limit=LIMIT):
    """Group raw contexts into K Huffman tables minimising coded bits. Returns tmap, lens."""
    nctx, NS = hist.shape
    tot = hist.sum(1)
    used = np.nonzero(tot)[0]
    if K >= len(used):
        tmap = np.zeros(nctx, np.int32); tmap[used] = np.arange(len(used))
        K = max(1, len(used))
    else:
        order = used[np.argsort(-tot[used])]
        tmap = np.full(nctx, K - 1, np.int32)
        tmap[order[:K - 1]] = np.arange(K - 1)
    H = hist.astype(np.float64)
    lens = None
    for it in range(iters + 1):
        th = np.zeros((K, NS), np.int64)
        np.add.at(th, tmap[used], hist[used])
        lens = np.stack([hufflens(th[k], limit) for k in range(K)])
        if it == iters or K >= len(used): break
        L = lens.astype(np.float64); L[L == 0] = 20.0
        cost = H[used] @ L.T                      # [nused, K]
        new = cost.argmin(1).astype(np.int32)
        # reseed empty tables with the contexts that are worst served
        cur = cost[np.arange(len(used)), new]
        present = np.zeros(K, bool); present[new] = True
        if not present.all():
            ideal = np.array([float((hist[c] * np.log2(np.maximum(tot[c], 1) / np.maximum(hist[c], 1))).sum()) for c in used])
            worst = np.argsort(-(cur - ideal))
            wi = 0
            for k in np.nonzero(~present)[0]:
                new[worst[wi]] = k; wi += 1
        if (new == tmap[used]).all():
            tmap[used] = new; continue
        tmap[used] = new
    return tmap, lens


def ctx_huff(tiles_syms, mode, K, label, passes=3, limit=LIMIT):
    """tiles_syms: list of (S int32 array, W). Returns result dict; verifies round trip."""
    A, nctx = MODEINFO[mode]
    runs = RUNS if mode != M_PLAIN else RUNS[:0]
    NS = A + NR
    tmap = np.zeros(nctx, np.int32)
    lens = np.zeros((1, NS), np.uint8); lens[0, :A] = 6 if A == 256 else 3; lens[0, A:] = 3
    choices = [np.zeros(len(S), np.int32) for S, W in tiles_syms]
    for p in range(passes):
        hist = np.zeros((nctx, NS), np.int64)
        nl = nrun = 0
        for (S, W), ch in zip(tiles_syms, choices):
            a, b = parse(S, W, mode, A, tmap, lens, runs, hist, ch)
            nl += a; nrun += b
        tmap, lens = cluster(hist, K, limit=limit)
    codes, first, cnt, offs, ss = canon(lens)
    total = 0; buf = np.zeros(1 << 17, np.uint8)
    for (S, W), ch in zip(tiles_syms, choices):
        n = encode(S, W, mode, A, tmap, lens, codes, runs, ch, buf)
        dec = decode(buf[:n].copy(), len(S), W, mode, A, tmap, first, cnt, offs, ss, RUNS)
        if len(dec) != len(S) or not np.array_equal(dec, S):
            raise RuntimeError("round trip failed: " + label)
        total += n
    ntab = lens.shape[0]
    used_syms = int((lens > 0).sum())
    # model stored in file: per table NS code lengths at 4 bits, + context map (1 byte per raw ctx if clustered)
    model = ntab * ((NS * 4 + 7) // 8) + (nctx if ntab < nctx or nctx > 256 else 0)
    if nctx > 16 and ntab > 256: model += nctx
    nsym = nl + nrun
    return dict(label=label, data=total, model=model, total=total + model, tables=ntab,
                lit_syms=nl, run_syms=nrun, used_syms=used_syms,
                avg_len=float((total * 8) / max(1, nsym)))


# ---------------------------------------------------------------- LZSS (12-bit offset, 4-bit length)
@nb.njit(cache=True)
def lzss_encode(buf, start, out):
    """Optimal-parse classic LZSS: flag byte per 8 tokens, literal = 1 byte,
    match = 2 bytes (offset-1: 12 bits, length-3: 4 bits). buf[:start] is a preset dictionary."""
    n = len(buf); WIN = 4096; MINL = 3; MAXL = 18
    HS = 1 << 14
    head = np.full(HS, -1, np.int32); prev = np.full(n, -1, np.int32)
    mlen = np.zeros(n, np.int32); moff = np.zeros((n, MAXL + 1), np.int32)
    for i in range(n):
        if i + 2 < n:
            h = ((buf[i] << 8) ^ (buf[i + 1] << 4) ^ buf[i + 2]) & (HS - 1)
            if i >= start:
                j = head[h]; best = 0
                while j >= 0 and i - j <= WIN:
                    l = 0
                    while l < MAXL and i + l < n and buf[j + l] == buf[i + l]: l += 1
                    if l > best:
                        for q in range(best + 1, l + 1): moff[i, q] = i - j
                        best = l
                        if l == MAXL: break
                    j = prev[j]
                mlen[i] = best
            prev[i] = head[h]; head[h] = i
    cost = np.zeros(n + 1, np.int64); ch = np.zeros(n, np.int32)
    for i in range(n - 1, start - 1, -1):
        best = cost[i + 1] + 9; bc = 0
        for l in range(MINL, mlen[i] + 1):
            c = cost[i + l] + 17
            if c < best: best = c; bc = l
        cost[i] = best; ch[i] = bc
    p = 0; i = start; fpos = -1; fbit = 8; nlit = 0; nmat = 0
    while i < n:
        if fbit == 8:
            fpos = p; out[p] = 0; p += 1; fbit = 0
        l = ch[i]
        if l == 0:
            out[p] = buf[i]; p += 1; i += 1; nlit += 1
        else:
            out[fpos] |= 1 << fbit
            o = moff[i, l] - 1
            out[p] = o & 255; out[p + 1] = ((o >> 8) << 4) | (l - 3); p += 2; i += l; nmat += 1
        fbit += 1
    return p, nlit, nmat


@nb.njit(cache=True)
def lzss_decode(src, dic, n):
    d = len(dic); out = np.zeros(d + n, np.uint8); out[:d] = dic
    i = d; p = 0; fl = 0; fbit = 8
    while i < d + n:
        if fbit == 8:
            fl = src[p]; p += 1; fbit = 0
        if (fl >> fbit) & 1:
            o = (src[p] | ((src[p + 1] >> 4) << 8)) + 1; l = (src[p + 1] & 15) + 3; p += 2
            for k in range(l):
                out[i] = out[i - o]; i += 1
        else:
            out[i] = src[p]; p += 1; i += 1
        fbit += 1
    return out[d:d + n]


def lzss_all(raws, dic, label):
    d = np.frombuffer(dic, np.uint8) if dic else np.zeros(0, np.uint8)
    total = 0; nlit = nmat = 0; out = np.zeros(1 << 17, np.uint8)
    for r in raws:
        a = np.frombuffer(r, np.uint8)
        buf = np.concatenate([d, a])
        n, l, m = lzss_encode(buf, len(d), out)
        dec = lzss_decode(out[:n].copy(), d, len(a))
        if not np.array_equal(dec[:len(a)], a): raise RuntimeError("lzss round trip " + label)
        total += n; nlit += l; nmat += m
    return dict(label=label, data=total, model=len(d), total=total + len(d), lit_syms=nlit, run_syms=nmat)


def upxor(raw, wb):
    a = np.frombuffer(raw, np.uint8).reshape(-1, wb).copy()
    a[1:] ^= a[:-1].copy() if False else np.frombuffer(raw, np.uint8).reshape(-1, wb)[:-1]
    return a.tobytes()


def un_upxor(f, wb):
    a = np.frombuffer(f, np.uint8).reshape(-1, wb).copy()
    for y in range(1, a.shape[0]): a[y] ^= a[y - 1]
    return a.tobytes()


def flips(t):
    a = np.frombuffer(t.raw, np.uint8).reshape(t.h, t.wb)
    sw = ((a >> 4) | (a << 4)).astype(np.uint8)
    return [a.tobytes(), sw[:, ::-1].tobytes(), a[::-1].tobytes(), sw[::-1, ::-1].tobytes()]


def rawdefl(b, zd=None):
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zdict=zd) if zd else zlib.compressobj(9, zlib.DEFLATED, -15, 9)
    return c.compress(b) + c.flush()


def run_one(cid):
    import zstandard, lz4.block, brotli
    t0 = time.time()
    path = os.path.join(A0, "SP_PL%02X.NSP" % cid)
    n = NSP(path); n.decode_all()
    T = n.tiles
    res = dict(id=cid, file=os.path.basename(path), file_size=len(n.d), sec=n.sizes, tiles=len(T),
               raw=sum(len(t.raw) for t in T))
    # ---- dedupe
    seen = {}; dd = [0, 0, 0, 0]; ddb = [0, 0, 0, 0]
    for t in T:
        f = flips(t); hit = None
        for k, v in enumerate(f):
            if (t.wb, t.h, v) in seen: hit = k; break
        if hit is None: seen[(t.wb, t.h, f[0])] = t.idx
        else: dd[hit] += 1; ddb[hit] += t.clen
    res["dups"] = dd; res["dup_rle_bytes"] = ddb
    raws = [t.raw for t in T]; wbs = [t.wb for t in T]
    C = {}

    def add(label, data, model=0, **kw):
        C[label] = dict(label=label, data=data, model=model, total=data + model, **kw)
    add("orig RLE", sum(t.clen for t in T))
    # ---- general purpose compressors (bounds / references), all verified
    z = [rawdefl(r) for r in raws]
    assert all(zlib.decompress(c, -15) == r for c, r in zip(z, raws))
    add("deflate-9 per tile", sum(map(len, z)))
    filt = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "lc": 0, "lp": 0, "pb": 0}]
    lz = [lzma.compress(r, lzma.FORMAT_RAW, filters=filt) for r in raws]
    assert all(lzma.decompress(c, lzma.FORMAT_RAW, filters=filt) == r for c, r in zip(lz, raws))
    add("lzma per tile", sum(map(len, lz)))
    br = [brotli.compress(r, quality=11, lgwin=16) for r in raws]
    assert all(brotli.decompress(c) == r for c, r in zip(br, raws))
    add("brotli-11 per tile", sum(map(len, br)))
    cat = b"".join(raws)
    add("deflate-9 whole section (no random access)", len(rawdefl(cat)))
    filt4 = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "lc": 4, "lp": 0, "pb": 0}]
    add("lzma whole section (no random access)", len(lzma.compress(cat, lzma.FORMAT_RAW, filters=filt4)))
    l4 = [lz4.block.compress(r, mode="high_compression", compression=12, store_size=False) for r in raws]
    assert all(lz4.block.decompress(c, uncompressed_size=len(r)) == r for c, r in zip(l4, raws))
    add("LZ4-HC per tile", sum(map(len, l4)))
    fr = [upxor(r, w) for r, w in zip(raws, wbs)]
    assert all(un_upxor(f, w) == r for f, r, w in zip(fr, raws, wbs))
    l4f = [lz4.block.compress(r, mode="high_compression", compression=12, store_size=False) for r in fr]
    add("up-XOR filter + LZ4-HC per tile", sum(map(len, l4f)))
    add("up-XOR filter + deflate-9 per tile", sum(len(rawdefl(r)) for r in fr))
    dicts = {}
    for ds in (4096, 16384, 65536):
        try:
            zd = zstandard.train_dictionary(ds, raws, level=19)
        except Exception as e:
            continue
        content = zd.as_bytes()[-ds:]
        dicts[ds] = content
        c = [lz4.block.compress(r, mode="high_compression", compression=12, store_size=False, dict=content) for r in raws]
        assert all(lz4.block.decompress(x, uncompressed_size=len(r), dict=content) == r for x, r in zip(c, raws))
        add("LZ4-HC per tile + %dK shared dict" % (ds // 1024), sum(map(len, c)), ds)
        if ds <= 32768:
            add("deflate-9 per tile + %dK shared dict" % (ds // 1024), sum(len(rawdefl(r, content)) for r in raws), ds)
        zc = zstandard.ZstdCompressor(level=19, dict_data=zd, write_content_size=False, write_checksum=False, write_dict_id=False)
        zdc = zstandard.ZstdDecompressor(dict_data=zd)
        c = [zc.compress(r) for r in raws]
        assert all(zdc.decompress(x, max_output_size=len(r)) == r for x, r in zip(c, raws))
        add("zstd-19 per tile + %dK shared dict" % (ds // 1024), sum(map(len, c)), len(zd.as_bytes()))
    # ---- own LZSS
    C["LZSS(12/4) per tile"] = lzss_all(raws, b"", "LZSS(12/4) per tile")
    C["up-XOR filter + LZSS(12/4) per tile"] = lzss_all(fr, b"", "up-XOR + LZSS")
    if 4096 in dicts:
        C["LZSS(12/4) per tile + 3.8K shared dict"] = lzss_all(raws, dicts[4096][-3840:], "LZSS+dict")
    # ---- Huffman family
    bytesyms = [(np.frombuffer(r, np.uint8).astype(np.int32), w) for r, w in zip(raws, wbs)]
    pixsyms = []
    for r, w in zip(raws, wbs):
        a = np.frombuffer(r, np.uint8)
        p = np.empty(len(a) * 2, np.int32); p[0::2] = a & 15; p[1::2] = a >> 4
        pixsyms.append((p, w * 2))
    s2 = n.sec[2]
    rlesyms = [(np.frombuffer(s2[t.off:t.off + t.clen], np.uint8).astype(np.int32), max(1, t.clen)) for t in T]

    def H(label, syms, mode, K, limit=LIMIT):
        r = ctx_huff(syms, mode, K, label, limit=limit); C[label] = r
    H("static Huffman over existing RLE stream", rlesyms, M_PLAIN, 1)
    H("Huffman bytes + up-runs, no context", bytesyms, M_B0, 1)
    H("Huffman bytes + up-runs, ctx=left pixel (16 tables)", bytesyms, M_BL, 16)
    H("Huffman bytes + up-runs, ctx=left pixel (16 tables), max code 10 bits", bytesyms, M_BL, 16, 10)
    H("Huffman bytes + up-runs, ctx=left pixel (16 tables), max code 9 bits", bytesyms, M_BL, 16, 9)
    H("Huffman bytes + up-runs, ctx=(left px, up byte) -> 32 tables, max code 9 bits", bytesyms, M_BLU, 32, 9)
    for K in (16, 32, 64, 128):
        H("Huffman bytes + up-runs, ctx=(left px, up byte) -> %d tables" % K, bytesyms, M_BLU, K)
    H("Huffman pixels + up-runs, ctx=(left, up) 256 tables", pixsyms, M_PLU, 256)
    H("Huffman pixels + up-runs, ctx=(left, up) -> 64 tables", pixsyms, M_PLU, 64)
    H("Huffman pixels + up-runs, ctx=(left, up, upleft) -> 256 tables", pixsyms, M_PLUUL, 256)
    res["codecs"] = C
    res["secs"] = time.time() - t0
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, "PL%02X.json" % cid), "w"), indent=1)
    return cid, res["secs"]


def table():
    rs = [json.load(open(os.path.join(OUT, f))) for f in sorted(os.listdir(OUT)) if f.endswith(".json")]
    print("char  file    sec0   sec1   sec2(px)  sec3   tiles  raw     dups(exact,fx,fy,fxy)")
    for r in rs:
        print("PL%02X %7d %6d %6d %8d %6d %6d %7d %s" % (r["id"], r["file_size"], *r["sec"], r["tiles"], r["raw"], r["dups"]))
    tot = lambda k: sum(r["sec"][k] for r in rs)
    fs = sum(r["file_size"] for r in rs)
    print("ALL  %7d %6d %6d %8d %6d   non-pixel = %.1f%% of files" % (fs, tot(0), tot(1), tot(2), tot(3), 100 * (fs - tot(2)) / fs))
    labels = list(rs[0]["codecs"].keys())
    base = sum(r["codecs"]["orig RLE"]["total"] for r in rs)
    print("\n%-64s %9s %8s %7s %7s  %s" % ("codec (sum over %d chars)" % len(rs), "total", "avg/char", "vs RLE", "model", "syms/outbyte lit,run"))
    rawsum = sum(r["raw"] for r in rs)
    for l in labels:
        cs = [r["codecs"][l] for r in rs if l in r["codecs"]]
        if len(cs) != len(rs): continue
        t = sum(c["total"] for c in cs); m = sum(c["model"] for c in cs)
        extra = ""
        if "lit_syms" in cs[0]:
            extra = "%.3f %.3f" % (sum(c["lit_syms"] for c in cs) / rawsum, sum(c["run_syms"] for c in cs) / rawsum)
        print("%-64s %9d %8d %6.1f%% %7d  %s" % (l, t, t // len(rs), 100.0 * t / base, m // len(rs), extra))
    return rs


def percharacter(label):
    rs = [json.load(open(os.path.join(OUT, f))) for f in sorted(os.listdir(OUT)) if f.endswith(".json")]
    for r in rs:
        c = r["codecs"][label]; o = r["codecs"]["orig RLE"]["total"]
        print("PL%02X  rle %7d  new %7d (data %7d + model %5d)  %.1f%%  file %7d -> %7d" % (
            r["id"], o, c["total"], c["data"], c["model"], 100 * c["total"] / o, r["file_size"], r["file_size"] - o + c["total"]))


def xdedupe():
    import hashlib
    seen = {}; stats = {}
    for cid in range(0x13):
        n = NSP(os.path.join(A0, "SP_PL%02X.NSP" % cid)); n.decode_all()
        within = cross = wb = cb = 0
        local = set()
        for t in n.tiles:
            f = flips(t)
            keys = [hashlib.md5(bytes([t.wb, t.h]) + v).digest() for v in f]
            if any(k in local for k in keys): within += 1; wb += t.clen
            elif any(k in seen for k in keys): cross += 1; cb += t.clen
            local.add(keys[0])
        for k in local: seen.setdefault(k, cid)
        print("PL%02X tiles %5d  dup within %4d (%6d rle bytes)  dup of earlier character %4d (%6d rle bytes)" % (cid, len(n.tiles), within, wb, cross, cb))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        ids = [int(x, 16) for x in sys.argv[2:]] or list(range(0x13))
        if len(ids) == 1:
            print(run_one(ids[0]))
        else:
            run_one.__module__ = "__main__"
            from multiprocessing import Pool
            with Pool(min(8, len(ids))) as p:
                for r in p.imap_unordered(run_one, ids): print(r, flush=True)
    elif cmd == "table":
        table()
    elif cmd == "char":
        percharacter(sys.argv[2])
    elif cmd == "xdedupe":
        xdedupe()
