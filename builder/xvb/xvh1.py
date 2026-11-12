"""XVH1 encoder: the "strong" sprite codec (format and decoder: tools/nsp_huff.py, tools/nspdec).

One 4bpp pixel per symbol, canonical Huffman (max 12 bits), 16 literals + 30 "copy from the row above"
runs; the code table is selected by the four causal neighbours through two maps:
    class = map1[L<<8 | U<<4 | UL]      table = map2[class<<4 | UR]

This is a port of tools/nsp_huff.py build() onto the batched kernels; it produces the same bytes.
"""
import struct
import numpy as np
from . import kernels as K
from .huff import RUNS, NR, cluster, canon

MAGIC = 0x31485658            # 'XVH1'
MAXLEN = 12
NS = 16 + NR


def encode(n, k=256, c1=256, passes=3):
    """n: nspfile.NSP of a stock file -> re-encoded file (bytes)"""
    n.decode_all()
    assert n.offs[0] == 16 and all(o % 4 == 0 for o in n.offs)
    assert not ((n.word >> 22) & 3).any()
    order, where = n.unique()
    Sl, Cl, Ql = [], [], []
    for i in order:                                        # per-pixel symbols and contexts, raster order
        h, wb = int(n.h[i]), int(n.wb[i])
        a = n.tile(i).reshape(h, wb)
        px = np.empty((h, wb * 2), np.int32); px[:, 0::2] = a & 15; px[:, 1::2] = a >> 4
        P = np.full((h + 1, wb * 2 + 2), 15, np.int32); P[1:, 1:-1] = px
        Sl.append(px.ravel())
        Cl.append(((P[1:, :-2] << 8) | (P[:-1, 1:-1] << 4) | P[:-1, :-2]).ravel())      # L, U, UL
        Ql.append(P[:-1, 2:].ravel())                                                 # UR
    S = np.concatenate(Sl).astype(np.int32); c12 = np.concatenate(Cl).astype(np.int32); q = np.concatenate(Ql).astype(np.int32)
    del Sl, Cl, Ql
    sizes = (n.nbytes[np.array(order)] * 2).astype(np.int64)
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    Ws = (n.wb[np.array(order)] * 2).astype(np.int32)
    tot = int(offs[-1])
    cq = (c12 * 16 + q).astype(np.int32)
    map1 = np.zeros(4096, np.int32); map2 = np.zeros(16, np.int32)
    lens = np.full((1, NS), 3, np.uint8)
    choice = np.zeros(tot, np.int32); tab = np.zeros(tot, np.int32)
    for p in range(passes + 1):
        hist1 = np.zeros(4096 * 16 * NS, np.int32)
        K.xvh_parse_acc(S, offs, Ws, tab, cq, np.ascontiguousarray(lens).reshape(-1), NS, RUNS, choice, hist1)
        hist1 = hist1.reshape(4096, 16, NS).astype(np.int64)
        if p == passes: break                              # last pass: parse only, with the final tables
        if c1 > 1:
            map1, _ = cluster(hist1.reshape(4096, 16 * NS), c1, iters=8, limit=15)
        nc1 = int(map1.max()) + 1
        hist2 = np.zeros((nc1, 16, NS), np.int64)
        np.add.at(hist2, map1, hist1)
        map2, lens = cluster(hist2.reshape(nc1 * 16, NS), k, limit=MAXLEN)
        tab = np.ascontiguousarray(map2[map1[c12] * 16 + q], np.int32)
    ntab = lens.shape[0]
    th = np.zeros((ntab, NS), np.int64)
    np.add.at(th, map2[(map1[:, None] * 16 + np.arange(16)[None, :])].ravel(), hist1.reshape(-1, NS))
    assert not ((th > 0) & (lens == 0)).any(), "symbol without code"
    codes, first, cnt, ss = canon(lens)
    assert ntab <= 256 and nc1 <= 256 and lens.max() <= MAXLEN
    # model
    o_map2 = 12 + 4096
    o_tofs = o_map2 + nc1 * 16
    o_recs = o_tofs + 2 * ntab
    recs = bytearray(); tofs = []
    for t in range(ntab):
        tofs.append(o_recs + len(recs))
        recs += bytes(int(cnt[t, l]) for l in range(1, MAXLEN + 1))
        recs += ss[t, :int((lens[t] > 0).sum())].astype(np.uint8).tobytes()
    model = bytearray(struct.pack("<IIHH", MAGIC, 0, o_map2, o_tofs)) + map1.astype(np.uint8).tobytes() \
        + map2.astype(np.uint8).tobytes() + struct.pack("<%dH" % ntab, *tofs) + recs
    assert len(model) < 65536 and o_tofs % 2 == 0
    # streams
    out = np.zeros(tot * 2 + len(order) * 4 + 16, np.uint8); ooffs = np.zeros(len(order) + 1, np.int32)
    m = K.xvh_emit(S, offs, Ws, tab, choice, RUNS, np.ascontiguousarray(lens).reshape(-1), NS,
                   np.ascontiguousarray(codes, np.int32).reshape(-1), out, ooffs)
    sec2 = bytearray(model) + out[:m].tobytes()
    uoff = ooffs[:len(order)] + len(model)
    sec2 += b"\0" * (-len(sec2) % 4)
    assert len(sec2) < (1 << 22)
    struct.pack_into("<I", sec2, 4, len(sec2))
    newoff = np.zeros(n.n, np.int64)
    for i, j in where.items(): newoff[i] = uoff[j]
    sec1 = ((n.word & ~0x3FFFFF) | newoff).astype("<u4").tobytes()
    o1, o2 = n.offs[1], n.offs[2]; o3 = o2 + len(sec2)
    new = struct.pack("<4I", 16, o1, o2, o3) + n.sec[0] + sec1 + bytes(sec2) + n.sec[3]
    bad = K.xvh_verify(np.frombuffer(new + b"\0" * 8, np.uint8), o2, o3, newoff.astype(np.int32), n.nbytes, n.raw, n.roff, RUNS,
                       np.zeros(1 << 16, np.uint8), np.zeros(258, np.int32))
    assert bad == 0, "XVH1 round trip failed (%d)" % bad
    return new
