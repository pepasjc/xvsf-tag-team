"""MvC sprite tier codecs for the release builder: the model of a tier file is read back from the file (it is OUR data:
code tables / context maps / probability tables made by our encoders), the tile streams are re-emitted from tile
contents that the builder derives from the user's own disc.  The emitters are the encoders' own emission steps
(common/dsp/dsh.py, dsm.py, games/mvc/tools/codec2/dsr.py) with the model search replaced by the recorded model, so a
file made by those encoders comes out byte for byte.

    codec(T)                      -> "DSH1" | "DSM1" | "DSR1" | "RLE"   (magic at the start of the pixel section)
    model_of(codec, sec0)         -> (model bytes, parsed model)
    content(codec, base, t)       -> the bytes a tile decodes to (DSH1: incl. the stock decoder's overrun bytes)
    emit(codec, model, tiles)     -> stream bytes per tile (the coded part of the pixel section)
"""
import os, sys, struct
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.dirname(HERE)
REPO = os.path.dirname(BUILDER)
for p in (os.path.join(REPO, "tools"), os.path.join(REPO, "common", "dsp")):
    if p not in sys.path: sys.path.insert(0, p)
from mvcb import kern                                       # noqa: E402  (numba / python kernels)

MAGIC = {0x31485344: "DSH1", 0x314D5344: "DSM1", 0x31525344: "DSR1"}
Q = 16


def codec(sec0):
    m = struct.unpack_from("<I", sec0, 0)[0] if len(sec0) >= 4 else 0
    return MAGIC.get(m, "RLE")


# ------------------------------------------------------------------------------------------------ DSP container
class Tile:
    __slots__ = ("idx", "off", "flag", "wb", "h", "ent")

    @property
    def n(self): return self.wb * self.h


class DSPX:
    """kind-8 DSP: header + 4 sections (the same parse as common/dsp/dsp.py DSP)"""

    def __init__(self, d):
        self.d = bytes(d)
        self.kind = struct.unpack_from("<I", d, 0)[0]
        assert self.kind == 8, "kind %d" % self.kind
        self.offs = list(struct.unpack_from("<4I", d, 4))
        assert self.offs[0] == 0x14
        o = self.offs + [len(d)]
        self.sec = [self.d[o[i]:o[i + 1]] for i in range(4)]
        s2 = self.sec[2]; self.tiles = []
        for i in range(len(s2) // 5):
            e = s2[5 * i:5 * i + 5]; t = Tile()
            t.idx = i; t.off = e[0] | e[1] << 8 | e[2] << 16; t.flag = e[3] >> 7; t.wb = e[3] & 0x7F
            t.h = e[4] & 0x7F if t.flag else e[4]; t.ent = e
            self.tiles.append(t)
        self.tail2 = s2[5 * len(self.tiles):]


def rle_written(s0x, off, n):
    """bytes the stock RLE decoder writes for a tile (nbytes + overrun) = common/dsp/dsh.py written()"""
    out = bytearray(); p = off; extra = 0
    while len(out) < n:
        b = s0x[p]; p += 1
        if b & 0xF0:
            out += bytes([(b & 15) * 0x11]) * ((b >> 4) + 1); extra = 0
        else:
            c = (b & 15) + 1
            out += s0x[p:p + c]; p += c
            extra = c & 1
    if extra: out.append(s0x[p])
    return bytes(out), p - off


def rle_raw(s0x, off, n):
    return rle_written(s0x, off, n)[0][:n]


# ------------------------------------------------------------------------------------------------ DSH1
def dsh_model(s0):
    magic, size, nc1, ntab = struct.unpack_from("<IIHH", s0, 0)
    tofs = struct.unpack_from("<%dH" % ntab, s0, 12)
    M = 12 + 2 * ntab
    map1 = np.frombuffer(s0[M:M + 4096], np.uint8).astype(np.int32)
    map2 = np.frombuffer(s0[M + 4096:M + 4096 + nc1 * Q], np.uint8).astype(np.int32)
    p = M + 4096 + nc1 * Q
    lens = np.zeros((ntab, kern.NS_H), np.uint8)
    for k in range(ntab):
        ml = tofs[k] - p; cnt = list(s0[p:tofs[k]])[::-1]
        q = tofs[k]
        for l in range(1, ml + 1):
            for j in range(cnt[l - 1]): lens[k, s0[q]] = l; q += 1
        p = q
    return bytes(s0[:p]), dict(size=size, map1=map1, map2=map2, lens=lens, codes=kern.canon_codes(lens))


def dsh_decode_all(s0, tiles, size):
    """-> {idx: written bytes} of the DSH1-coded tiles (reference decoder)"""
    mem = np.frombuffer(bytes(s0) + b"\0" * 16, np.uint8); out = np.zeros(1 << 17, np.uint8); wr = {}
    for t in tiles:
        if t.off < size:
            m, used = kern.dsh_ref_decode(mem, t.off, t.n, 0, kern.R16, out, 1); wr[t.idx] = out[:m].tobytes()
    return wr


def dsh_emit(M, wb, n, w):
    """one tile stream (dsh.encode: header, symbols with the parse for this model, raw overrun bytes)"""
    e = len(w) - n
    rep = e > 0 and w[n:] == w[n - 1:n] * e
    hv, hl = kern.dsh_header(wb * 2, e, rep)
    tail = np.frombuffer(w[n:] if not rep else b"", np.uint8).astype(np.int64)
    S, c12, q = kern.dsh_tile_ctx(w[:n], wb)
    tb = M["map2"][M["map1"][c12] * Q + q].astype(np.int32)
    ch = np.zeros(len(S), np.int32)
    kern.parse2(S, wb * 2, tb, M["lens"], kern.R16, ch, 0)
    out = np.zeros(len(S) * 2 + 64, np.uint8)
    m = kern.dsh_enc_tile(S, hv, hl, tail, tb, M["lens"], M["codes"], kern.R16, ch, out)
    return out[:m].tobytes()


# ------------------------------------------------------------------------------------------------ DSM1
def dsm_model(s0):
    """model bytes + (tmap, lens) recovered by walking the decoder tables of every 12-bit code"""
    magic, size, o_fb, K = struct.unpack_from("<IIHH", s0, 0)
    O_MAP, O_LUT = 76, 76 + 4096
    tmap = np.frombuffer(s0[O_MAP:O_MAP + 4096], np.uint8).astype(np.int32)
    lut = np.frombuffer(s0[O_LUT:O_LUT + K * 128], "<u2").reshape(K, 64)
    o_long = o_fb + K * 32
    lens = np.zeros((K, kern.NS_M), np.uint8)
    NR = kern.NR
    nlong = 0
    for t in range(K):
        for w in range(4096):
            e = int(lut[t, w >> 6])
            if (e & 0xC000) == 0xC000:
                p = o_fb + (t << 5); sh = 5
                while True:
                    lim = struct.unpack_from("<H", s0, p)[0]
                    if w < lim: break
                    p += 4; sh -= 1
                adj = struct.unpack_from("<h", s0, p + 2)[0]
                a = adj + ((w >> sh) << 1)
                e = struct.unpack_from("<H", s0, a)[0]
                nlong = max(nlong, (a - o_long) // 2 + 1)
            l = e & 15
            if e & 0x8000:
                if e & 0x1000: s = 256 + 2 * NR
                elif e & 0x2000: s = 256 + NR + ((e >> 4) & 0xFF)
                else: s = 256 + ((e >> 4) & 0xFF)
            else: s = (e >> 4) & 0xFF
            lens[t, s] = l
    end = o_long + 2 * nlong
    model = bytes(s0[:end])
    chk = kern.dsm_make_model(tmap, lens)
    assert chk[4:] == model[4:] or chk[8:] == model[8:], "DSM1 model not recovered"
    return model, dict(size=size, tmap=tmap, lens=lens, codes=kern.canon_codes(lens))


def dsm_decode_all(s0, tiles, size):
    mem = np.frombuffer(bytes(s0) + b"\0" * 16, np.uint8); out = np.zeros(1 << 17, np.uint8); raw = {}
    for t in tiles:
        if t.off < size:
            kern.dsm_ref_decode(mem, t.off, t.n, 0, out); raw[t.idx] = out[:t.n].tobytes()
    return raw


def dsm_emit(M, wb, raw, pen=0):
    S, c = kern.dsm_tile_ctx(raw, wb)
    cc = np.zeros(len(S), np.int32)
    tab = M["tmap"][c]
    kern.dsm_parse(S, wb, tab, M["lens"], kern.R64, cc, pen)
    out = np.zeros(len(S) * 3 + 64, np.uint8)
    m = kern.dsm_emit(S, wb, tab, cc, kern.R64, M["lens"], M["codes"], out)
    return out[:m].tobytes()


# ------------------------------------------------------------------------------------------------ DSR1
def dsr_model(s0):
    magic, size, n4, nl, nent, z = struct.unpack_from("<IIHHHH", s0, 0)
    cont = np.frombuffer(s0[16:272], np.uint8).astype(np.int64)
    ents = struct.unpack_from("<64H", s0, 272)
    jb = s0[400:656]
    nn = n4 // 4
    words = struct.unpack_from("<%dI" % nn, s0, 656)
    pairs = kern.PAIRS
    nodes = []
    for w in words:
        if w & 0x8000:
            a = (w & 0x7FFF); assert a % 17 == 0; nodes.append(0x8000 | (a // 17))
        else:
            r = w >> 16; kind = (w >> 10) & 3; lo = w & 0x3FF
            if kind == 0: t = 5 * (lo >> 2) + (lo & 3)
            elif kind == 1: t = 5 * (lo >> 2) + 4
            else:
                i, j = (lo & 31) >> 2, (lo >> 5) >> 2
                t = 40 + [tuple(p) for p in pairs.tolist()].index((i, j))
            nodes.append(t | (r << 16))
    p = 656 + 4 * nn
    rec = s0[p:p + 17 * nl]
    probs = np.array([list(rec[17 * l:17 * l + 16]) for l in range(nl)], np.int64).reshape(nl, 16)
    lp = np.array([rec[17 * l + 16] for l in range(nl)], np.int64)
    jump = np.array([ents[b // 2] // 4 for b in jb], np.int64)
    end = p + 17 * nl
    end += -end % 4
    model = bytes(s0[:end])
    return model, dict(size=size, nodes=np.array(nodes, np.int64), jump=jump, cont=cont, lp=lp, probs=probs)


def dsr_decode_all(s0, tiles, size):
    M = dsr_model(s0)[1]
    mem = np.frombuffer(bytes(s0) + b"\0" * 16, np.uint8); out = np.zeros(1 << 17, np.uint8); raw = {}
    for t in tiles:
        if t.off < size:
            kern.dsr_ref_decode(mem, t.off, t.n, M["nodes"], kern.PAIRS, M["jump"], M["cont"], M["lp"], M["probs"], out)
            raw[t.idx] = out[:t.n].tobytes()
    return raw


def dsr_emit(M, wb, raw):
    a = np.frombuffer(raw, np.uint8)
    h = len(raw) // wb
    px = np.empty((h, wb * 2), np.int64); px[:, 0::2] = (a & 15).reshape(h, wb); px[:, 1::2] = (a >> 4).reshape(h, wb)
    n = px.size * 8 + 64
    bp = np.zeros(n, np.int64); bb = np.zeros(n, np.int64); ob = np.zeros(n // 4 + 64, np.int64)
    nd = kern.dsr_tile_decisions(px, M["nodes"], kern.PAIRS, M["jump"], M["cont"], M["lp"], M["probs"], bp, bb)
    nbyte = kern.dsr_rc_encode(bp, bb, nd, ob)
    st = bytes(int(v) for v in ob[:nbyte]); assert st[0] == 0
    return bytes([wb]) + st[1:]


# ------------------------------------------------------------------------------------------------ batched emission
# The same emission, all unique tiles of a file in ONE kernel call: the MSHvSF / XvSF builders' batched kernels
# (mshb.kernels dsh_emit / dsm_emit, xvb.kernels xvh_parse_acc / xvm_parse_acc: numba on the command line, their
# JavaScript twins in the browser) and mvcb.kern dsr_* for DSR1.  emit_batch(codec, M, tiles) -> [stream bytes]
# with tiles = [(wb, n, content)] in emission order.
def _bk():
    from mshb import kernels as K
    from xvb import kernels as XK
    if K.backend == "python": K.auto_backend()
    return K, XK


def dsh_batch(M, tiles):
    K, XK = _bk()
    from xvb.huff import RUNS
    hv = np.zeros(len(tiles), np.int32); hl = np.zeros(len(tiles), np.int32); tails = []; tofs = [0]; raws = []
    for j, (wb, n, w) in enumerate(tiles):
        e = len(w) - n; rep = e > 0 and w[n:] == w[n - 1:n] * e
        hv[j], hl[j] = kern.dsh_header(wb * 2, e, rep)
        t = b"" if rep else w[n:]; tails.append(t); tofs.append(tofs[-1] + len(t)); raws.append(w[:n])
    tail = np.frombuffer(b"".join(tails) + b"\0", np.uint8).astype(np.int32); toff = np.array(tofs, np.int32)
    a = np.frombuffer(b"".join(raws), np.uint8)
    S = np.empty(2 * len(a), np.int32); S[0::2] = a & 15; S[1::2] = a >> 4
    sizes = np.array([2 * n for wb, n, w in tiles], np.int64)
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    Ws = np.array([2 * wb for wb, n, w in tiles], np.int32)
    tot = int(offs[-1])
    W = np.repeat(Ws.astype(np.int64), sizes.astype(np.intp))
    pos = np.arange(tot, dtype=np.int64) - np.repeat(offs[:-1].astype(np.int64), sizes.astype(np.intp))
    col = pos % W; row0 = pos < W
    g = np.arange(tot, dtype=np.int64); up = np.maximum(g - W, 0)
    L = np.where(col > 0, S[np.maximum(g - 1, 0)], 15)
    U = np.where(row0, 15, S[up])
    UL = np.where(row0 | (col == 0), 15, S[np.maximum(up - 1, 0)])
    UR = np.where(row0 | (col == W - 1), 15, S[np.minimum(up + 1, tot - 1)])
    c12 = ((L << 8) | (U << 4) | UL).astype(np.int32); q = UR.astype(np.int32)
    lens = np.ascontiguousarray(M["lens"]).reshape(-1); NS = M["lens"].shape[1]
    tab = np.ascontiguousarray(M["map2"][M["map1"][c12] * Q + q], np.int32)
    choice = np.zeros(tot, np.int32); hist = np.zeros(4096 * Q * NS, np.int32)
    XK.xvh_parse_acc(S, offs, Ws, tab, (c12 * Q + q).astype(np.int32), lens, NS, RUNS, choice, hist)
    out = np.zeros(tot * 2 + len(tail) + len(tiles) * 8 + 16, np.uint8); ooffs = np.zeros(len(tiles) + 1, np.int32)
    m = K.dsh_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, np.ascontiguousarray(M["codes"], np.int32).reshape(-1), hv, hl, tail, toff, out, ooffs)
    ooffs[len(tiles)] = m
    return [out[ooffs[j]:ooffs[j + 1]].tobytes() for j in range(len(tiles))]


def dsm_batch(M, tiles, pen=0):
    K, XK = _bk()
    from xvb.huff import RUNS
    sizes = np.array([n for wb, n, w in tiles], np.int64)
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    Ws = np.array([wb for wb, n, w in tiles], np.int32)
    tot = int(offs[-1])
    S = np.frombuffer(b"".join(w for wb, n, w in tiles), np.uint8).astype(np.int32)
    start = np.repeat(offs[:-1].astype(np.int64), sizes.astype(np.intp))
    pos = np.arange(tot, dtype=np.int64) - start
    wrep = np.repeat(Ws.astype(np.int64), sizes.astype(np.intp))
    P = np.where(pos > 0, np.concatenate([[255], S[:-1]]), 255)
    U = np.where(pos >= wrep, S[np.maximum(np.arange(tot, dtype=np.int64) - wrep, 0)], 255)
    ctx = ((P >> 4) << 8 | U).astype(np.int32)
    lens = np.ascontiguousarray(M["lens"]).reshape(-1); NS = M["lens"].shape[1]
    tab = np.ascontiguousarray(M["tmap"][ctx], np.int32)
    choice = np.zeros(tot, np.int32); hist = np.zeros(4096 * NS, np.int32)
    XK.xvm_parse_acc(S, offs, Ws, tab, ctx, lens, NS, RUNS, pen, choice, hist)
    out = np.zeros(tot * 3 + len(tiles) * 8 + 16, np.uint8); ooffs = np.zeros(len(tiles) + 1, np.int32)
    m = K.dsm_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, np.ascontiguousarray(M["codes"], np.int32).reshape(-1), out, ooffs)
    ooffs[len(tiles)] = m
    return [out[ooffs[j]:ooffs[j + 1]].tobytes() for j in range(len(tiles))]


def dsr_batch(M, tiles):
    """DSR1: per-tile range-coder emission (numba kernels dsr_tile_decisions / dsr_rc_encode); the browser twin is a TODO
    (builder resume step 5).  Same streams as dsr_emit one tile at a time."""
    return [dsr_emit(M, wb, w) for wb, n, w in tiles]


BATCH = {"DSH1": dsh_batch, "DSM1": dsm_batch, "DSR1": dsr_batch}
MODEL = {"DSH1": dsh_model, "DSM1": dsm_model, "DSR1": dsr_model}
DECODE = {"DSH1": dsh_decode_all, "DSM1": dsm_decode_all, "DSR1": dsr_decode_all}
