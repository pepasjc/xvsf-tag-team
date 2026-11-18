"""DSH1 encoder: the MSHvSF "strong" sprite codec (format: common/dsp/dsh.py; decoder common/dsp/dshdec.S).

XVH1-class: 4bpp pixels coded one at a time in raster order, canonical Huffman (max 12 bits), table chosen by the
causal neighbours (L, U, UL -> class via map1; class, UR -> table via map2), alphabet = 16 literals + 30
copy-from-the-row-above runs.  Each tile stream starts with a header (width code, overrun e), the tile is coded as
its pixels followed by the e overrun bytes the stock decoder writes (raw, or 'repeat the last byte').
Tiles in `rle` keep their stock RLE streams, behind the DSH1 part.

A port of common/dsp/dsh.py encode() (defaults: DSH_MAXLEN 12, DSH_RAW 1, DSH_REFINE 20) onto batched kernels.
The clustering and refinement keep the reference's arithmetic exactly: every cost is an integer sum (int32, checked
against overflow; kernels.cost_argmin_bb finds the same first minimum as the reference's float matmul + argmin
without computing every cost), every grouping an integer sum (np.bincount on exact float64 weights instead of
np.add.at), every deciding sort xvb.huff.argsort (numpy's scalar introsort, so equal keys keep the reference order).
The one float computation left is the reference's own: the log2 "ideal" cost that orders the contexts used to
reseed an empty table in cluster() (as in xvb.huff.cluster).
"""
import struct
import numpy as np
from xvb import kernels as xk
from xvb.huff import RUNS, NR, hufflens_rows, canon, argsort
from . import kernels as K
from .dspfile import assemble

MAGIC = 0x31485344                          # 'DSH1'
MAXLEN = 12
NS = 16 + NR
O_TOFS = 12
Q = 16                                      # second-level context values (UR)
REFINE = 20
MAXW = 240


def header(W, e, rep):
    """tile header bits -> (value, nbits): width code wc = W/16 - 1: '0' wc 0, '10' wc 1, '11' + 4 bits wc;
    then '10' no overrun, '0' + 4 bits e: e copies of the last byte, '11' + 4 bits e: e raw bytes"""
    assert W % 16 == 0
    wc = W // 16 - 1
    v, l = ((0, 1) if wc == 0 else (2, 2) if wc == 1 else ((3 << 4) | wc, 6))
    v2, l2 = ((2, 2) if e == 0 else (e, 5) if rep else ((3 << 4) | e, 6))
    return (v << l2) | v2, l + l2


class Sparse:
    """the non-zero entries of a dense integer matrix m[rows, ncols], row by row (CSR over the used rows, or over
    all rows), for exact grouped sums (np.bincount on exact float64 weights) and for cheapest()"""

    def __init__(self, m, all_rows=False):
        self.tot = m.sum(1, dtype=np.int64)
        self.used = np.arange(m.shape[0]) if all_rows else np.nonzero(self.tot)[0]
        sub = m[self.used]
        r, c = np.nonzero(sub)
        o = np.lexsort((-sub[r, c].astype(np.int64), r))          # in each row, larger counts first (speed only)
        r = r[o]; c = c[o]
        self.cols = c.astype(np.int32); self.vals = sub[r, c].astype(np.int32)
        self.indptr = np.concatenate([[0], np.cumsum(np.bincount(r, minlength=len(self.used)))]).astype(np.int32)
        self.row = self.used[r].astype(np.int64)                 # row in m of each entry
        self.col = c.astype(np.int64)
        self.wts = self.vals.astype(np.float64)
        self.rowmax = int(self.tot.max()) if len(self.tot) else 0

    def group(self, key_of_row, k, ncols):
        """th[k, ncols]: the rows summed by key_of_row[row] (exact integers)"""
        idx = (key_of_row[self.row].astype(np.int64) * ncols + self.col).astype(np.intp)
        return np.bincount(idx, weights=self.wts, minlength=k * ncols).astype(np.int64).reshape(k, ncols)

    def cheapest(self, L, hint):
        """L[k, ncols]: integer cost (> 0) of each column in table t -> (first cheapest table per row, its cost);
        equal to (m[used] @ L.T).argmin(1) and the matching minimum (xvb.huff.SparseRows.cheapest).
        hint[row] = a guess of the answer (speed only)"""
        k = L.shape[0]
        LT = np.ascontiguousarray(L.T, np.uint8)
        assert (LT == L.T).all() and LT.min() > 0 and self.rowmax * int(LT.max()) < (1 << 31)
        new = np.zeros(len(self.used), np.int32); cur = np.zeros(len(self.used), np.int32)
        K.cost_argmin_bb(self.indptr, self.cols, self.vals, LT.reshape(-1), k, np.ascontiguousarray(hint, np.int32), new, cur,
                         np.zeros(max(1, int(np.diff(self.indptr).max(initial=0))), np.int32), np.zeros(k, np.int32))
        return new, cur.astype(np.float64)


def cluster(hist, k, iters=12, limit=12, sp=None):
    """tools/nsp_codec.py cluster() (= xvb.huff.cluster) on a sparse histogram: group the rows of hist[nctx, NS]
    into k Huffman tables minimising the coded bits.  -> tmap[nctx], lens[k, NS]"""
    nctx, ns = hist.shape
    sp = sp or Sparse(hist)
    tot = sp.tot; used = sp.used
    if k >= len(used):
        tmap = np.zeros(nctx, np.int32); tmap[used] = np.arange(len(used))
        k = max(1, len(used))
    else:
        order = used[argsort(-tot[used])]
        tmap = np.full(nctx, k - 1, np.int32)
        tmap[order[:k - 1]] = np.arange(k - 1)
    lens = None
    for it in range(iters + 1):
        th = sp.group(tmap, k, ns)
        lens = hufflens_rows(th, limit)
        if it == iters or k >= len(used): break
        L = lens.astype(np.float64); L[L == 0] = 20.0
        new, cur = sp.cheapest(L, tmap[used])                   # = (hist[used] @ L.T).argmin(1) and its minimum
        present = np.zeros(k, bool); present[new] = True
        if not present.all():                         # reseed empty tables with the worst served contexts
            ideal = np.array([float((hist[c] * np.log2(np.maximum(tot[c], 1) / np.maximum(hist[c], 1))).sum()) for c in used])
            worst = argsort(-(cur - ideal))
            wi = 0
            for t in np.nonzero(~present)[0]:
                new[worst[wi]] = t; wi += 1
        tmap[used] = new
    return tmap, lens


def refine(sp1, map1, map2, lens, iters=REFINE):
    """common/dsp/dsh.py refine(): alternating re-assignment on the real coded bits: raw context -> class (given the
    tables of every (class, UR)), (class, UR) -> table, then new code lengths.  sp1 = Sparse(hist1[4096, Q*NS]).
    -> map1, map2, lens"""
    nc1 = int(map1.max()) + 1; Kt = lens.shape[0]
    used = sp1.used
    q_of = (sp1.col // NS); s_of = (sp1.col % NS)

    def th_of(m1, m2):                               # th[t, s] = sum of hist1[c12, q, s] over m2[m1[c12]*Q + q] == t
        key = m2[m1[sp1.row].astype(np.int64) * Q + q_of].astype(np.int64)
        idx = (key * NS + s_of).astype(np.intp)
        return np.bincount(idx, weights=sp1.wts, minlength=Kt * NS).astype(np.int64).reshape(Kt, NS)
    best = int((th_of(map1, map2) * lens).sum())
    for it in range(iters):
        L = lens.astype(np.float64); L[L == 0] = 24.0
        Lk = L[map2.reshape(nc1, Q)].reshape(nc1, -1)            # [class, Q * NS]
        m1 = map1.copy(); m1[used] = sp1.cheapest(Lk, map1[used])[0]
        h2 = sp1.group(m1, nc1, Q * NS).reshape(nc1 * Q, NS)   # hist2[class, q, s]
        m2 = Sparse(h2, all_rows=True).cheapest(L, map2)[0]
        th = th_of(m1, m2)
        ln = lens.copy(); nz = th.any(1)
        if nz.any(): ln[nz] = hufflens_rows(th[nz], MAXLEN)
        tot = int((th * ln).sum())
        if tot >= best: break
        best = tot; map1, map2, lens = m1.astype(np.int32), m2, ln
    return map1, map2, lens


def build_model(S, offs, Ws, c12, q, K_, C1, passes):
    """-> model bytes, lens, codes, tab, choice, ntab, nc1"""
    tot = int(offs[-1])
    cq = (c12 * Q + q).astype(np.int32)
    map1 = np.zeros(4096, np.int32); map2 = np.zeros(Q, np.int32)
    lens = np.full((1, NS), 3, np.uint8)
    choice = np.zeros(tot, np.int32); tab = np.zeros(tot, np.int32)
    nc1 = 1
    for p in range(passes + 1):
        hist = np.zeros(4096 * Q * NS, np.int32)
        xk.xvh_parse_acc(S, offs, Ws, tab, cq, np.ascontiguousarray(lens).reshape(-1), NS, RUNS, choice, hist)
        hist1 = hist.reshape(4096, Q * NS)
        if p == passes: break                              # last pass: parse only, with the final tables
        sp1 = Sparse(hist1)
        if C1 > 1:
            map1, _ = cluster(hist1, C1, iters=8, limit=15, sp=sp1)
        nc1 = int(map1.max()) + 1
        hist2 = sp1.group(map1, nc1, Q * NS).reshape(nc1 * Q, NS)
        map2, lens = cluster(hist2, K_, limit=MAXLEN)
        if REFINE: map1, map2, lens = refine(sp1, map1, map2, lens)
        tab = np.ascontiguousarray(map2[map1[c12] * Q + q], np.int32)
    ntab = lens.shape[0]
    rowkey = map2[(map1[:, None] * Q + np.arange(Q)[None, :]).ravel()]            # (c12, q) row -> table
    th = Sparse(hist1.reshape(4096 * Q, NS)).group(rowkey, ntab, NS)
    assert not ((th > 0) & (lens == 0)).any(), "symbol without code"
    codes, first, cnt, ss = canon(lens)
    assert ntab <= 256 and nc1 <= 256 and lens.max() <= MAXLEN
    o_recs = O_TOFS + 2 * ntab + 4096 + nc1 * Q
    recs = bytearray(); tofs = [0] * ntab
    for t in range(ntab):
        ml = int(lens[t].max())
        recs += bytes(int(cnt[t, l]) for l in range(ml, 0, -1))     # cnt[ml] .. cnt[1], then the symbols
        tofs[t] = o_recs + len(recs)
        recs += ss[t, :int((lens[t] > 0).sum())].astype(np.uint8).tobytes()
    model = struct.pack("<IIHH", MAGIC, 0, nc1, ntab) + struct.pack("<%dH" % ntab, *tofs) + map1.astype(np.uint8).tobytes() \
        + map2.astype(np.uint8).tobytes() + bytes(recs)
    assert len(map2) == nc1 * Q and len(model) < 65536
    return model, lens, codes, tab, choice, ntab, nc1


def encode(x, k=256, c1=256, rle=(), passes=6, verify=True):
    """x: dspfile.DSP of a stock file -> (new file bytes, stats)"""
    x.decode_all(); rle = set(int(i) for i in rle)
    uniq = {}; order = []; where = {}
    for i in range(x.n):
        if i in rle: continue
        key = (int(x.wb[i]), int(x.nbytes[i]), x.written(i))      # n too: same bytes written, different overrun
        j = uniq.get(key)
        if j is None: j = uniq[key] = len(order); order.append(i)
        where[i] = j
    oi = np.array(order, np.int64)
    assert (x.wb[oi] * 2 <= MAXW).all() and (x.wb[oi] % 2 == 0).all() and (x.wlen[oi] - x.nbytes[oi] <= 15).all()
    hv = np.zeros(len(order), np.int32); hl = np.zeros(len(order), np.int32)
    tails = []; tofs = [0]
    for j, i in enumerate(order):
        w = x.written(i); n = int(x.nbytes[i]); e = len(w) - n
        rep = e > 0 and w[n:] == w[n - 1:n] * e
        hv[j], hl[j] = header(int(x.wb[i]) * 2, e, rep)
        t = b"" if rep else w[n:]
        tails.append(t); tofs.append(tofs[-1] + len(t))
    tail = np.frombuffer(b"".join(tails) + b"\0", np.uint8).astype(np.int32)
    toff = np.array(tofs, np.int32)
    # per-pixel symbols and contexts, raster order: L, U, UL, UR (15 outside the tile)
    a = np.frombuffer(b"".join(x.raw(i) for i in order), np.uint8)
    S = np.empty(2 * len(a), np.int32); S[0::2] = a & 15; S[1::2] = a >> 4
    sizes = (x.nbytes[oi] * 2).astype(np.int64)
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    Ws = (x.wb[oi] * 2).astype(np.int32)
    tot = int(offs[-1])
    W = np.repeat(Ws.astype(np.int64), sizes.astype(np.intp))
    pos = np.arange(tot, dtype=np.int64) - np.repeat(offs[:-1].astype(np.int64), sizes.astype(np.intp))
    col = pos % W; row0 = pos < W
    g = np.arange(tot, dtype=np.int64)
    up = np.maximum(g - W, 0)
    L = np.where(col > 0, S[np.maximum(g - 1, 0)], 15)
    U = np.where(row0, 15, S[up])
    UL = np.where(row0 | (col == 0), 15, S[np.maximum(up - 1, 0)])
    UR = np.where(row0 | (col == W - 1), 15, S[np.minimum(up + 1, tot - 1)])
    c12 = ((L << 8) | (U << 4) | UL).astype(np.int32); q = UR.astype(np.int32)
    model, lens, codes, tab, choice, ntab, nc1 = build_model(S, offs, Ws, c12, q, k, c1, passes)
    out = np.zeros(tot * 2 + len(tail) + len(order) * 8 + 16, np.uint8); ooffs = np.zeros(len(order) + 1, np.int32)
    m = K.dsh_emit(S, offs, Ws, tab, choice, RUNS, np.ascontiguousarray(lens).reshape(-1), NS,
                   np.ascontiguousarray(codes, np.int32).reshape(-1), hv, hl, tail, toff, out, ooffs)
    sec0 = bytearray(model) + out[:m].tobytes()
    uoff = ooffs[:len(order)].astype(np.int64) + len(model)
    sec0 += b"\0" * (4 + (-len(sec0) % 4))
    struct.pack_into("<I", sec0, 4, len(sec0))
    dsh_end = len(sec0)
    newoff = np.zeros(x.n, np.int64)
    for i, j in where.items(): newoff[i] = uoff[j]
    done = {}
    for i in range(x.n):
        if i in rle:
            o = int(x.off[i])
            st = x.sec[0][o:o + int(x.clen[i]) + 1]         # +1: an odd literal reads one byte past the stream
            if st not in done: done[st] = len(sec0); sec0 += st
            newoff[i] = done[st]
    sec0 += b"\0" * (-len(sec0) % 4)
    new = assemble(x, sec0, newoff)
    if verify:
        mem = np.frombuffer(new[0x14:] + b"\0" * 64, np.uint8)
        want = np.frombuffer(b"".join(x.written(i) for i in range(x.n)), np.uint8)
        wofs = np.concatenate([[0], np.cumsum(x.wlen.astype(np.int64))]).astype(np.int32)
        bad = K.dsh_verify(mem, dsh_end, newoff.astype(np.int32), x.nbytes, want, wofs, RUNS,
                           np.zeros(1 << 17, np.uint8), np.zeros(260, np.int32))
        assert bad == 0, "DSH1 round trip failed (%d)" % bad
    return new, dict(old=len(x.d), new=len(new), old_pix=x.sizes[0], new_pix=len(sec0), model=len(model), tables=ntab,
                     classes=nc1, dsh_part=dsh_end, rle_tiles=len(rle), tiles=x.n, uniq=len(order))
