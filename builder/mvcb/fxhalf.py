"""Half-resolution effect tiles (games/mvc/tools/fxhalf/fxhalf.py build(), the 2 MB tag build's option B): the A0 of a
character with the listed tiles point-sampled to half size (+ the edge columns / row the GPU needs), re-coded as stock
RLE.  The tile lists are our data (data/mvc/fxhalf.json: which tiles are effect-only, from our play measurements and
review); the pixels come from the user's disc.

    flagged_of(fx_a0)            -> sorted tile indices with the half-res flag (bake)
    build(stock_a0, flagged)     -> the A0 bytes (= fxhalf.build)
"""
import struct
from mvcb import codecs as C


def dsp_base(a0): return struct.unpack_from("<I", a0, 12)[0]


def flagged_of(a0):
    x = C.DSPX(a0[dsp_base(a0):])
    return [t.idx for t in x.tiles if t.flag]


def rle(raw):
    out = bytearray(); i = 0; n = len(raw); lit = bytearray()
    def flush():
        while lit:
            k = min(16, len(lit)); out.append(k - 1); out.extend(lit[:k]); del lit[:k]
    while i < n:
        b = raw[i]; j = i
        if (b >> 4) == (b & 15):
            while j < n and raw[j] == b and j - i < 16: j += 1
        if j - i >= 2:
            flush(); out.append((j - i - 1) << 4 | (b & 15)); i = j
        else:
            lit.append(b); i += 1
    flush()
    return bytes(out)


def half(wb, h, raw):
    W = wb * 2; H = h
    px = [[(raw[y * wb + (x >> 1)] >> (4 * (x & 1))) & 15 for x in range(W)] for y in range(H)]
    cw = W // 2; hr = (H + 1) // 2
    tw = (cw + 1 + 3) & ~3; pad = tw - cw
    assert pad in (2, 4)
    hb = tw // 2; th = hr + 1
    out = bytearray(hb * th)
    for y in range(th):
        sy = 2 * min(y, hr - 1)
        for x in range(tw):
            p = px[sy][2 * min(x, cw - 1)]
            out[y * hb + (x >> 1)] |= p << (4 * (x & 1))
    return hb, th, pad // 4, bytes(out)


def build(b, flagged):
    base = dsp_base(b)
    x = C.DSPX(b[base:]); s0 = x.sec[0]; fl = set(flagged)
    s0x = x.d[0x14:]
    sec0 = bytearray(); offs = {}; ents = {}; done = {}
    for t in sorted(x.tiles, key=lambda t: t.off):
        if t.off in done:
            offs[t.idx], e = done[t.off]
            if e: ents[t.idx] = e
            continue
        raw, clen = C.rle_written(s0x, t.off, t.n)
        if t.idx in fl:
            hb, hr, narrow, hraw = half(t.wb, t.h, raw[:t.n])
            s = rle(hraw); o = len(sec0); sec0 += s
            e = (0x80 | hb, narrow << 7 | hr)
        else:
            o = len(sec0); sec0 += s0[t.off:t.off + _clen(s0, t.off, t.n)]; e = None
        done[t.off] = (o, e); offs[t.idx] = o
        if e: ents[t.idx] = e
    sec0 += b"\0" * (-len(sec0) % 4)
    s2 = bytearray(x.sec[2])
    for t in x.tiles:
        o = offs[t.idx]; s2[5 * t.idx:5 * t.idx + 3] = bytes((o & 255, o >> 8 & 255, o >> 16))
        if t.idx in ents: s2[5 * t.idx + 3], s2[5 * t.idx + 4] = ents[t.idx]
    o1 = 0x14 + len(sec0); o2 = o1 + len(x.sec[1]); o3 = o2 + len(s2)
    newdsp = struct.pack("<5I", 8, 0x14, o1, o2, o3) + bytes(sec0) + x.sec[1] + bytes(s2) + x.sec[3]
    k = struct.unpack_from("<I", b, 0)[0]
    parts = [list(struct.unpack_from("<II", b, 4 + 8 * i)) for i in range(k)]
    assert parts[1][0] == base
    a0 = bytearray(b[:base]) + newdsp
    d = len(newdsp) - len(b[base:])
    parts[1][1] += d
    for i in range(2, k): parts[i][0] += d
    for i in range(k): struct.pack_into("<II", a0, 4 + 8 * i, *parts[i])
    return bytes(a0)


def _clen(s0, off, n):
    """length of the RLE stream (common/dsp/dsp.py rle_decode clen: the bytes consumed for n bytes)"""
    p = off; o = 0
    while o < n:
        b = s0[p]; p += 1
        if b & 0xF0: o += (b >> 4) + 1
        else: c = (b & 15) + 1; o += c; p += c
    return p - off
