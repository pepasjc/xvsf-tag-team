"""Huffman code construction and context clustering shared by the two sprite encoders.

Ports of tools/nsp_codec.py (hufflens, canon, cluster) with the code-length construction moved into
a kernel (kernels.hufflens_many).  Results are identical; see tests/ in builder/README.md.

The sorts that decide something go through argsort() below, which reproduces numpy's scalar introsort
(see kernels.argsort_np): np.argsort's order of equal keys depends on the numpy build.
"""
import numpy as np
from . import kernels as K

RUNS = np.array(list(range(1, 17)) + [24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 2048, 4096], dtype=np.int32)
NR = len(RUNS)
assert NR == K.NR


def argsort(a):
    """np.argsort(a) as numpy's scalar introsort orders it, on every machine"""
    v = np.ascontiguousarray(a, np.float64)
    assert v.ndim == 1 and (v == np.asarray(a)).all()      # keys must be exact in float64
    idx = np.zeros(len(v), np.int32)
    K.argsort_np(v, idx, np.zeros(512, np.int32))
    return idx.astype(np.int64)


def hufflens_rows(counts, limit):
    """counts[K, NS] (non-negative ints) -> uint8 lens[K, NS], length-limited Huffman code lengths"""
    counts = np.ascontiguousarray(counts, dtype=np.int32)
    k, ns = counts.shape
    lens = np.zeros((k, ns), np.uint8)
    work = np.zeros(8 * ns, np.int32)
    K.hufflens_many(counts.reshape(-1), ns, k, limit, lens.reshape(-1), work)
    return lens


def hufflens(counts, limit):
    return hufflens_rows(np.asarray(counts).reshape(1, -1), limit)[0]


def canon(lens):
    """lens[K, NS] -> codes, first, cnt, sorted symbols (canonical code, shorter codes first, symbols ascending)"""
    k, ns = lens.shape
    codes = np.zeros((k, ns), np.int64)
    first = np.zeros((k, 17), np.int64); cnt = np.zeros((k, 17), np.int64)
    ss = np.zeros((k, ns), np.int32)
    for t in range(k):
        code = 0; pos = 0
        row = lens[t]
        for l in range(1, 16):
            syms = np.nonzero(row == l)[0]
            first[t, l] = code; cnt[t, l] = len(syms)
            if len(syms):
                codes[t, syms] = code + np.arange(len(syms)); ss[t, pos:pos + len(syms)] = syms
                code += len(syms); pos += len(syms)
            code <<= 1
    return codes, first, cnt, ss


class SparseRows:
    """the non-zero entries of an integer matrix, row by row, for kernels.cost_argmin"""

    def __init__(self, m):
        r, c = np.nonzero(m)
        self.n = m.shape[0]
        self.cols = c.astype(np.int32); self.vals = m[r, c].astype(np.float64)
        self.indptr = np.concatenate([[0], np.cumsum(np.bincount(r, minlength=self.n))]).astype(np.int32)

    def cheapest(self, L):
        """L[k, NS]: cost of symbol s in table t (integer-valued) -> (table per row, its cost per row);
        equal to (m @ L.T).argmin(1) and the matching minimum"""
        k = L.shape[0]
        new = np.zeros(self.n, np.int32); cur = np.zeros(self.n, np.float64)
        K.cost_argmin(self.indptr, self.cols, self.vals, np.ascontiguousarray(L.T, np.float64).reshape(-1), k, new, cur, np.zeros(k, np.float64))
        return new, cur


def group_sum(hist, used, tmap_used, k):
    """th[k, NS] = sum of the rows hist[used] by table (exact integer sums)"""
    th = np.zeros((k, hist.shape[1]), np.int64)
    order = np.argsort(tmap_used, kind="stable")
    keys = tmap_used[order]
    if len(order):
        starts = np.flatnonzero(np.concatenate([[True], keys[1:] != keys[:-1]]))
        th[keys[starts]] = np.add.reduceat(hist[used][order], starts, axis=0)
    return th


def cluster(hist, k, iters=12, limit=12):
    """Group the raw contexts hist[nctx, NS] into k Huffman tables minimising the coded bits
    (tools/nsp_codec.py cluster()).  -> tmap[nctx], lens[k, NS]"""
    nctx, ns = hist.shape
    tot = hist.sum(1)
    used = np.nonzero(tot)[0]
    if k >= len(used):
        tmap = np.zeros(nctx, np.int32); tmap[used] = np.arange(len(used))
        k = max(1, len(used))
    else:
        order = used[argsort(-tot[used])]
        tmap = np.full(nctx, k - 1, np.int32)
        tmap[order[:k - 1]] = np.arange(k - 1)
    H = SparseRows(hist[used])
    lens = None
    for it in range(iters + 1):
        th = group_sum(hist, used, tmap[used], k)
        lens = hufflens_rows(th, limit)
        if it == iters or k >= len(used): break
        L = lens.astype(np.float64); L[L == 0] = 20.0
        new, cur = H.cheapest(L)                      # = (hist[used] @ L.T).argmin(1) and its minimum
        present = np.zeros(k, bool); present[new] = True
        if not present.all():                         # reseed empty tables with the worst served contexts
            ideal = np.array([float((hist[c] * np.log2(np.maximum(tot[c], 1) / np.maximum(hist[c], 1))).sum()) for c in used])
            worst = argsort(-(cur - ideal))
            wi = 0
            for t in np.nonzero(~present)[0]:
                new[worst[wi]] = t; wi += 1
        tmap[used] = new
    return tmap, lens
