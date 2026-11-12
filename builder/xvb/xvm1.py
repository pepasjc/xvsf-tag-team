"""XVM1 encoder: the hack's default sprite codec (format and decoder: tools/nsp_mid.py, tools/nspdec).

Byte symbols; the code table is chosen by a clustered (left pixel, byte above) context; a compact
model (6-bit primary LUT + canonical fallback).  Tiles listed in `rle` keep their ORIGINAL RLE streams,
stored behind the XVM1 part of sec2 (the game's own decoder handles them: no decode cost).

This is a port of tools/nsp_mid.py encode_file() onto the batched kernels; it produces the same bytes.
"""
import struct
import numpy as np
from . import kernels as K
from .huff import RUNS, NR, hufflens_rows, canon, group_sum, argsort, SparseRows

MAGIC = 0x314D5658            # 'XVM1'
KB = 6                        # primary LUT bits
LIMIT = 12
ESC = 256 + 2 * NR; NS = ESC + 1
O_LUT = 76 + 4096


def tab_lens(th, model_bits):
    """Code lengths for the tables th[K, NS].  Literals that are too rare to pay for their 2-byte
    long-code entry are left to the escape (decided once from the unpruned code, against a notional
    16-bit escape); escape code <= 8 bits."""
    h = th.astype(np.int64).copy(); h[:, ESC] = 0
    hh = h.copy(); hh[:, ESC] = 1
    l0 = hufflens_rows(hh, LIMIT).astype(np.int64)
    keep = h > 0
    sav = h[:, :256] * (16 - l0[:, :256])
    keep[:, :256] &= ~((l0[:, :256] > KB) & (sav < model_bits))
    hh = np.where(keep, h, 0)
    hh[:, ESC] = np.maximum(1, np.where(keep[:, :256], 0, h[:, :256]).sum(1))
    l = hufflens_rows(hh, LIMIT)
    while True:
        bad = np.nonzero(l[:, ESC] > 8)[0]
        if not len(bad): return l
        hh[bad, ESC] *= 2
        l[bad] = hufflens_rows(hh[bad], LIMIT)


def cluster(hist, k, model_bits, iters=8):
    nctx = hist.shape[0]; tot = hist.sum(1); used = np.nonzero(tot)[0]
    order = used[argsort(-tot[used])]
    tmap = np.zeros(nctx, np.int32)
    if k >= len(used):
        tmap[used] = np.arange(len(used)); k = max(1, len(used))
    else:
        tmap[:] = k - 1; tmap[order[:k - 1]] = np.arange(k - 1)
    H = SparseRows(hist[used])
    for it in range(iters + 1):
        lens = tab_lens(group_sum(hist, used, tmap[used], k), model_bits)
        if it == iters: break
        L = lens.astype(np.float64)
        esc = L[:, ESC:ESC + 1] + 8
        Lc = np.where(L > 0, L, 0); Lc[:, :256] = np.where(L[:, :256] > 0, L[:, :256], esc)
        Lc[:, 256:ESC] = np.where(L[:, 256:ESC] > 0, L[:, 256:ESC], 40)
        new, cur = H.cheapest(Lc)                     # = (hist[used] @ Lc.T).argmin(1) and its minimum
        present = np.zeros(k, bool); present[new] = True
        if not present.all():
            worst = argsort(-cur); wi = 0
            for t in np.nonzero(~present)[0]: new[worst[wi]] = t; wi += 1
        if (new == tmap[used]).all(): break
        tmap[used] = new
    return tmap, lens


def entry(sym, l):
    if sym < 256: return l | sym << 4
    if sym < 256 + NR: return 0x8000 | l | (sym - 256) << 4
    if sym < ESC: return 0xA000 | l | (sym - 256 - NR) << 4
    return 0x9000 | l


def make_model(tmap, lens):
    k = lens.shape[0]
    codes, first, cnt, ss = canon(lens)
    lut = np.zeros((k, 1 << KB), np.int64)
    fb = np.zeros((k, 8, 2), np.int64)
    o_fb = O_LUT + k * (2 << KB)
    o_long = o_fb + k * 32
    longs = []
    for t in range(k):
        for l in range(1, LIMIT + 1):
            syms = np.nonzero(lens[t] == l)[0]
            f = int(first[t, l])
            if l <= KB:
                for s in syms:
                    c = int(codes[t, s]) << (KB - l)
                    lut[t, c:c + (1 << (KB - l))] = entry(int(s), l)
            else:
                for s in syms:
                    lut[t, int(codes[t, s]) >> (l - KB)] = 0xC000
                    longs.append(entry(int(s), l))
                adj = o_long + 2 * (len(longs) - len(syms)) - 2 * f
                assert -32768 <= adj < 32768
                fb[t, l - KB - 1] = ((f + len(syms)) << (LIMIT - l), adj & 0xFFFF)
        fb[t, LIMIT - KB - 1, 0] = max(fb[t, LIMIT - KB - 1, 0], 4096)     # the walk always stops here
    runs = [int(x) for x in RUNS] + [0, 0]
    m = struct.pack("<IIHH", MAGIC, 0, o_fb, k) + struct.pack("<32H", *runs) + tmap.astype(np.uint8).tobytes()
    m += lut.astype("<u2").tobytes() + fb.astype("<u2").tobytes() + np.array(longs, "<u2").tobytes()
    assert len(m) == o_long + 2 * len(longs) and len(m) < 32768
    return m, codes


def encode(n, k=48, pen=8, rle=(), model_bits=32, passes=4):
    """n: nspfile.NSP of a stock file -> re-encoded file (bytes)"""
    n.decode_all()
    assert n.offs[0] == 16 and all(o % 4 == 0 for o in n.offs)
    assert not ((n.word >> 22) & 3).any()
    rle = set(int(x) for x in rle)
    order, where = n.unique(skip=rle)
    oi = np.array(order, np.int64)
    sizes = n.nbytes[oi].astype(np.intp)                   # intp: np.repeat insists (32 bits under Pyodide)
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    Ws = n.wb[oi].astype(np.int32)
    tot = int(offs[-1])
    idx = np.concatenate([np.arange(n.roff[i], n.roff[i + 1]) for i in order]) if order else np.zeros(0, np.int64)
    S = n.raw[idx].astype(np.int32)
    # context per byte: P = previous byte of the tile (255 at its start), U = byte above (255 in row 0)
    pos = np.arange(tot) - np.repeat(offs[:-1].astype(np.int64), sizes)
    wrep = np.repeat(Ws.astype(np.int64), sizes)
    P = np.where(pos > 0, np.concatenate([[255], S[:-1]]), 255)
    U = np.where(pos >= wrep, S[np.maximum(np.arange(tot) - wrep, 0)], 255)
    ctx = ((P >> 4) << 8 | U).astype(np.int32)
    tmap = np.zeros(4096, np.int32)
    lens = np.zeros((1, NS), np.uint8); lens[0, :256] = 7; lens[0, 256:ESC] = 6; lens[0, ESC] = 8
    choice = np.zeros(tot, np.int32)
    for p in range(passes + 1):
        hist = np.zeros(4096 * NS, np.int32)
        tab = np.ascontiguousarray(tmap[ctx], np.int32)
        K.xvm_parse_acc(S, offs, Ws, tab, ctx, np.ascontiguousarray(lens).reshape(-1), NS, RUNS, pen, choice, hist)
        hist = hist.reshape(4096, NS).astype(np.int64)
        if p == passes: break
        tmap, lens = cluster(hist, k, model_bits)
    th = np.zeros((lens.shape[0], NS), np.int64); np.add.at(th, tmap, hist)
    assert not ((th[:, 256:ESC] > 0) & (lens[:, 256:ESC] == 0)).any() and (lens[:, ESC] > 0).all() and (lens[:, ESC] <= 8).all()
    model, codes = make_model(tmap, lens)
    out = np.zeros(tot * 2 + len(order) * 4 + 16, np.uint8); ooffs = np.zeros(len(order) + 1, np.int32)
    m = K.xvm_emit(S, offs, Ws, tab, choice, RUNS, np.ascontiguousarray(lens).reshape(-1), NS,
                   np.ascontiguousarray(codes, np.int32).reshape(-1), out, ooffs)
    sec2 = bytearray(model) + out[:m].tobytes()
    uoff = ooffs[:len(order)] + len(model)
    sec2 += b"\0" * (4 + (-len(sec2) % 4))                 # the decoder reads up to 4 bytes ahead
    struct.pack_into("<I", sec2, 4, len(sec2))             # end of the XVM1 part
    xvm_end = len(sec2)
    newoff = np.zeros(n.n, np.int64)
    for i, j in where.items(): newoff[i] = uoff[j]
    rdone = {}
    for i in range(n.n):                                   # stock streams, in tile order, identical ones once
        if i in rle:
            st = n.sec[2][n.off[i]:n.off[i] + n.clen[i]]
            if st not in rdone: rdone[st] = len(sec2); sec2 += st
            newoff[i] = rdone[st]
    sec2 += b"\0" * (-len(sec2) % 4)
    assert len(sec2) < (1 << 22)
    sec1 = ((n.word & ~0x3FFFFF) | newoff).astype("<u4").tobytes()
    o1, o2 = n.offs[1], n.offs[2]; o3 = o2 + len(sec2)
    new = struct.pack("<4I", 16, o1, o2, o3) + n.sec[0] + sec1 + bytes(sec2) + n.sec[3]
    bad = K.xvm_verify(np.frombuffer(new + b"\0" * 8, np.uint8), o2, o3, xvm_end, newoff.astype(np.int32), n.nbytes, n.raw, n.roff,
                       np.zeros(1 << 16, np.uint8))
    assert bad == 0, "XVM1 round trip failed (%d)" % bad
    return new
