"""XVG1: the FAST region inside an XVM1 sprite file - for tiles that are decoded in bursts / every tick.
(Successor of XVF1: same LUT decoder idea, but the model is sized for a small subset of tiles.)

  byte symbols, canonical Huffman, max 8+S bits (S = 2..4), bits packed LSB first:
      0..255   literal byte        256+r  copy RUNS[r] bytes from the row above (never in row 0)
      286+r    repeat the previous output byte (0xFF before the first byte)
  State machine instead of a context computation: up to 8 code tables; every literal entry carries
  the table to use next (a clustering of the previous byte); after a copy-from-above run and at the
  start of a tile the table is `start`; a repeat run leaves the table unchanged.
  Tile stream: byte aligned; 4 bits width code (bytes/8-1), then the codes (first bit first).

region layout (placed after the XVM1 part of sec2; the dispatch stub finds it by address):
  +0   u32 'XVG1'   +4 u32 region size   +8 u16 ((1<<S)-1)<<1   +10 u16 start table offset (table*512)
  +12  u16 RUNS[32]
  +76  s16 lut[ntab][256]        index = next 8 stream bits
  ...  s16 sub-tables (1<<S entries)
  ...  tile streams
  entry:  literal  len | byte<<4 | next_table<<12
          run      0x8000 | len | r<<4 | 0x2000 if "repeat previous byte"
          long     0xC000 | (offset of the sub-table from the lut start / 2)   (consumes 8 bits first)
"""
import struct
import numpy as np
import numba as nb
from nsp_codec import hufflens, canon, cluster, RUNS, NR

MAGIC = 0x31475658            # 'XVG1'
K = 8
NS = 256 + 2 * NR
R = RUNS.astype(np.int64)
START = 256                   # context id of "start of tile / after a copy-from-above run"


@nb.njit
def parse(S, W, tmap, lens, RUNS, choice, pen):
    """Optimal parse with two states per position: f = 0 the table follows from the previous byte,
    f = 1 we are right after a copy run (table `start`).  choice[f, i]; costs in quarter bits."""
    n = len(S); NRr = len(RUNS)
    up = np.zeros(n + 1, np.int32); rep = np.zeros(n + 1, np.int32); eq = np.zeros(n + 1, np.int32)
    for i in range(n - 1, -1, -1):
        up[i] = up[i + 1] + 1 if (i >= W and S[i] == S[i - W]) else 0
        eq[i] = eq[i + 1] + 1 if (i + 1 < n and S[i + 1] == S[i]) else 1
    for i in range(n):
        pv = S[i - 1] if i else 255
        rep[i] = eq[i] if S[i] == pv else 0
    cost = np.zeros((2, n + 1), np.int64)
    for i in range(n - 1, -1, -1):
        for f in range(2):
            t = tmap[256] if (f == 1 or i == 0) else tmap[S[i - 1]]
            l = lens[t, S[i]]
            if l == 0: l = 60
            best = cost[0, i + 1] + 4 * l; bc = 0
            for r in range(NRr):
                if RUNS[r] > up[i]: break
                l = lens[t, 256 + r]
                if l == 0: continue
                c = cost[1, i + RUNS[r]] + 4 * l + pen
                if c < best: best = c; bc = 1 + r
            for r in range(NRr):
                if RUNS[r] > rep[i]: break
                l = lens[t, 256 + NRr + r]
                if l == 0: continue
                # after a repeat run the table stays the one in use now
                keep = 1 if (f == 1 or i == 0) else 0
                c = cost[keep, i + RUNS[r]] + 4 * l + pen
                if c < best: best = c; bc = 1 + NRr + r
            cost[f, i] = best; choice[f, i] = bc


@nb.njit
def walk(S, W, tmap, choice, RUNS, hist, lens, rcodes, out):
    """Follow the parse: accumulate hist[context, symbol]; emit the stream when out is not empty."""
    n = len(S); i = 0; p = 0; NRr = len(RUNS); f = 1
    acc = (W >> 3) - 1; nb_ = 4
    emit = len(out) > 0
    while i < n:
        ctx = 256 if f == 1 else S[i - 1]
        t = tmap[ctx]
        c = choice[f, i]
        if c == 0:
            sym = S[i]; i += 1; f = 0
        elif c <= NRr:
            sym = 255 + c; i += RUNS[c - 1]; f = 1
        else:
            sym = 255 + c; i += RUNS[c - 1 - NRr]
        hist[ctx, sym] += 1
        if emit:
            acc |= rcodes[t, sym] << nb_; nb_ += lens[t, sym]
            while nb_ >= 8:
                out[p] = acc & 255; p += 1; acc >>= 8; nb_ -= 8
    if emit and nb_:
        out[p] = acc & 255; p += 1
    return p


@nb.njit
def ref_decode(mem, src, n, model, out):
    """Exact model of the MIPS decoder xvg_dec (tools/nspdec/nspdec.S)."""
    M = 0xFFFFFFFF
    lut = model + 76
    submask = np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8)
    start = lut + (np.int64(mem[model + 10]) | (np.int64(mem[model + 11]) << 8))
    w = np.int64(mem[src]) | (np.int64(mem[src + 1]) << 8) | (np.int64(mem[src + 2]) << 16) | (np.int64(mem[src + 3]) << 24)
    src0 = src; src += 4
    W = ((w & 15) + 1) << 3
    buf = (w >> 3) & 0xFFFFFFFE
    c = 12
    last = 255
    tbl = start
    o = 0
    while o < n:
        a = tbl + (buf & 0x1fe)
        e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        if (e & 0xC000) == 0xC000:
            buf >>= 8; c -= 8
            a = lut + ((e & 0x3fff) << 1) + (buf & submask)
            e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        l = e & 15
        buf >>= l; c -= l
        if e & 0x8000:
            a = lut - 64 + ((e & 0x1f0) >> 3)
            r = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
            if e & 0x2000:
                for k in range(r):
                    out[o] = last; o += 1
            else:
                for k in range(r):
                    out[o] = out[o - W]; o += 1
                last = np.int64(out[o - 1])
                tbl = start
        else:
            last = (e >> 4) & 255
            tbl = lut + ((e >> 3) & 0xe00)
            out[o] = last; o += 1
        if c < 0:
            v = np.int64(mem[src]) | (np.int64(mem[src + 1]) << 8)
            buf = (buf | (v << (c + 17))) & M
            src += 2; c += 16
    return src - src0


def bitrev(c, l):
    r = 0
    for _ in range(l):
        r = (r << 1) | (c & 1); c >>= 1
    return r


def make_model(tmap, lens, S):
    ntab = lens.shape[0]
    codes = canon(lens)[0]
    lut = np.zeros((ntab, 256), np.int64)
    subs = []
    rcodes = np.zeros(lens.shape, np.int64)
    for t in range(ntab):
        submap = {}
        for sym in range(NS):
            l = int(lens[t, sym])
            if not l: continue
            rc = bitrev(int(codes[t, sym]), l); rcodes[t, sym] = rc
            if sym < 256: ent = lambda ll, sym=sym: ll | sym << 4 | int(tmap[sym]) << 12
            elif sym < 256 + NR: ent = lambda ll, sym=sym: 0x8000 | ll | (sym - 256) << 4
            else: ent = lambda ll, sym=sym: 0xA000 | ll | (sym - 256 - NR) << 4
            if l <= K:
                for j in range(1 << (K - l)): lut[t, rc | j << l] = ent(l)
            else:
                assert l - K <= S
                p = rc & 255
                if p not in submap:
                    submap[p] = len(subs); subs.append(np.zeros(1 << S, np.int64))
                    off = ntab * 256 + (submap[p] << S)            # entries from the lut start
                    assert off < 0x4000
                    lut[t, p] = 0xC000 | off
                st = subs[submap[p]]; hi = rc >> 8; ll = l - K
                for j in range(1 << (S - ll)): st[hi | j << ll] = ent(ll)
    runs = [int(x) for x in RUNS] + [0, 0]
    m = struct.pack("<IIHH", MAGIC, 0, ((1 << S) - 1) << 1, int(tmap[START]) * 512) + struct.pack("<32H", *runs)
    m += struct.pack("<%dH" % lut.size, *[int(x) for x in lut.ravel()])
    for st in subs: m += struct.pack("<%dH" % (1 << S), *[int(x) for x in st])
    return m, rcodes


def encode_region(tiles, pen=0, passes=5):
    """tiles: list of (raw bytes, width in bytes).  -> (region bytes, [stream offset per tile], info)
    Tries table counts 1/2/4/8 and code limits 10..12 and keeps the smallest region."""
    data = [(np.frombuffer(raw, np.uint8).astype(np.int32), wb) for raw, wb in tiles]
    best = None
    none = np.zeros(0, np.uint8); zc = np.zeros((8, NS), np.int64)
    for ntab in (1, 2, 4, 8):
        for S in (2, 3, 4):
            limit = K + S
            tmap = np.zeros(257, np.int32)
            lens = np.zeros((1, NS), np.uint8); lens[:, :256] = 7; lens[:, 256:] = 6
            ch = [np.zeros((2, len(d[0])), np.int32) for d in data]
            for p in range(passes + 1):
                hist = np.zeros((257, NS), np.int64)
                for (Sy, W), cc in zip(data, ch):
                    parse(Sy, W, tmap, lens, R, cc, pen)
                    walk(Sy, W, tmap, cc, R, hist, lens, zc, none)
                if p == passes: break
                if ntab == 1:
                    lens = hufflens(hist.sum(0), limit)[None, :]
                else:
                    tmap, lens = cluster(hist, ntab, limit=limit)
            th = np.zeros((lens.shape[0], NS), np.int64); np.add.at(th, tmap, hist)
            if ((th > 0) & (lens == 0)).any(): continue
            model, rcodes = make_model(tmap, lens, S)
            out = np.zeros(1 << 17, np.uint8); h2 = np.zeros((257, NS), np.int64)
            reg = bytearray(model); offs = []
            for (Sy, W), cc in zip(data, ch):
                m = walk(Sy, W, tmap, cc, R, h2, lens, rcodes, out)
                offs.append(len(reg)); reg += out[:m].tobytes()
            reg += b"\0" * (4 + (-len(reg) % 4))              # the decoder reads up to 4 bytes ahead
            if best is None or len(reg) < len(best[0]):
                best = (reg, offs, dict(ntab=int(lens.shape[0]), S=S, model=len(model)))
    reg, offs, info = best
    struct.pack_into("<I", reg, 4, len(reg))
    return bytes(reg), offs, info
