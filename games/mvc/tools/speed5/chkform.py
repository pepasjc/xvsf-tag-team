"""Checker tile form (fx worker, 2026-11-19; mktag --chk).  MvC's fake translucency = a tile whose odd (or even) checker
positions are all colour 15 (transparent).  Such tiles compress badly in every codec (War Machine's super panel: one
144x48 checker tile = 3.5 KB, ~100 decode lines on DSA1).  Form: the tile's stream is replaced by
    FILLED tile = the checker tile with every masked pixel set to its left (else right) neighbour (exact where it counts)
stored in the game's byte RLE BEHIND the coded section (the decoder dispatch sends any source past a section's end to the
RLE route), plus a 4-byte record {u32 rle_offset | phase << 31}.  The tile entry's offset = 0x200000 | record offset
(bit 21: sections are < 2 MB).  At run time CHK (chkrt.S, hook 0x8008c5cc) decodes the record's stream and ORs the
transparent nibbles back in: phase 0 = (x + y) even kept -> even rows keep the low nibble.  Exact by construction.

    chkform.tiles(dsp)            -> tile indices in checker form (>= MINB bytes)
    chkform.apply(x, idx)         -> tier file bytes with the form applied (header offsets shifted)
    python chkform.py CHAR [TIER_FILE]  -> self-check (model decode of every form tile == stock pixels)
"""
import os, sys, struct
sys.path.insert(0, r"C:\playground\xvsf\common\dsp")
import dsp as D
import numpy as np

MINB = 64                                   # smaller tiles stay as they are (decode cost ~ call overhead)
BIT = 0x200000


def _pix(t):
    a = np.frombuffer(bytes(t.raw), np.uint8)
    return np.stack([a & 15, a >> 4], 1).reshape(t.h, t.wb * 2)


def form_of(t):
    """-> (phase, filled raw bytes) or None"""
    if t.n < MINB or t.flag: return None
    p = _pix(t); yy, xx = np.indices(p.shape)
    for ph in (0, 1):
        keep = ((yy + xx) & 1) == ph
        if np.all(p[~keep] == 15) and np.any(p[keep] != 15):
            f = p.copy()
            sh = np.roll(p, 1, axis=1); sh[:, 0] = p[:, 1]           # left neighbour (col 0: right one)
            f[~keep] = sh[~keep]
            b = (f[:, 0::2] | (f[:, 1::2] << 4)).astype(np.uint8).tobytes()
            return ph, b
    return None


def rle(raw):
    """the game's byte RLE: c >= 0x10 -> (c >> 4) + 1 bytes of (c & 15) * 0x11 (runs of 2..16), else (c & 15) + 1 literals"""
    out = bytearray(); i = 0; n = len(raw)
    while i < n:
        b = raw[i]; j = i
        if (b >> 4) == (b & 15):
            while j < n and raw[j] == b and j - i < 16: j += 1
            if j - i >= 2:
                out.append(((j - i - 1) << 4) | (b & 15)); i = j; continue
        j = i
        while j < n and j - i < 16:
            if (raw[j] >> 4) == (raw[j] & 15) and j + 1 < n and raw[j + 1] == raw[j]: break
            j += 1
        if j == i: j = i + 1
        out.append(j - i - 1); out += raw[i:j]; i = j
    return bytes(out)


def mask(raw, ph, wb):
    """runtime model: OR the transparent nibbles back"""
    a = bytearray(raw)
    for i in range(len(a)):
        y = i // wb
        a[i] |= 0xF0 if (y + ph) % 2 == 0 else 0x0F     # phase 0: even row keeps x even = low nibble
    return bytes(a)


def tiles(d):
    d.decode_all()
    out = []                                 # only real fake translucency: the filled stream < half the stock RLE
    for t in d.tiles:
        f = form_of(t)
        if f and 2 * len(rle(f[1])) < t.clen: out.append(t.idx)
    return out


def apply(x, stock, idx):
    """x = tier file (DSP + trailing A0 part as tier_file gives it), stock = the stock / fx DSP (pixels), idx = tile list"""
    y = D.DSP(x); stock.decode_all()
    o1, o2, o3 = y.offs[1], y.offs[2], y.offs[3]
    s0 = bytearray(x[0x14:o1]); add = bytearray(); recs = {}
    s2 = bytearray(x[o2:o3])
    # cut the converted tiles' own streams (a stream = its offset .. the next distinct offset / the coded part's end),
    # unless another tile still uses an offset inside it; later offsets shift down
    coded = s0[:4] in (b"DSM1", b"DSH1", b"DSA1", b"DSR1")      # DSR1: CPU worker (tools/codec2)
    cend = struct.unpack_from("<I", s0, 4)[0] if coded else len(s0)
    ents = [(t.idx, t.off) for t in y.tiles]
    offs = sorted(set(o for i, o in ents))
    conv = set(idx); cuts = []
    for i in idx:
        o = y.tiles[i].off
        lim = cend if o < cend else len(s0)
        nxt = min([q for q in offs if q > o] + [lim]); nxt = min(nxt, lim)
        if any(o <= q < nxt for j, q in ents if j not in conv): continue
        cuts.append((o, nxt))
    cuts = sorted(set(cuts))
    def shift(q): return q - sum(b - a for a, b in cuts if b <= q)
    for a_, b_ in reversed(cuts): del s0[a_:b_]
    if coded: struct.pack_into("<I", s0, 4, shift(cend))
    for j, q in ents:
        if j in conv: continue
        nq = shift(q)
        s2[5 * j:5 * j + 3] = bytes([nq & 0xff, nq >> 8 & 0xff, (s2[5 * j + 2] & 0xc0) | (nq >> 16 & 0x3f)])
    s0 += bytes(-len(s0) % 4)
    base = len(s0)
    for i in idx:
        t = stock.tiles[i]; ph, f = form_of(t)
        r = rle(f)
        assert D.rle_decode(r + bytes(32), 0, t.n)[0][:t.n] == f
        so = base + len(add); add += r + b"\0"                 # +1: the RLE run overrun never reads past
        add += bytes(-len(add) % 4)
        ro = base + len(add); add += struct.pack("<I", so | ph << 31)
        assert ro < BIT
        e = BIT | ro
        s2[5 * i:5 * i + 3] = bytes([e & 0xff, e >> 8 & 0xff, e >> 16 & 0xff])
        assert (s2[5 * i + 2] & 0x3f) == (e >> 16 & 0x3f)
    s0 += add; s0 += bytes(-len(s0) % 4)
    d = len(s0) - (o1 - 0x14)
    hdr = struct.pack("<5I", y.kind, 0x14, o1 + d, o2 + d, o3 + d)
    return hdr + bytes(s0) + x[o1:o2] + bytes(s2) + x[o3:]


def model_check(xf, stock, idx):
    """decode every form tile of the applied file like chkrt.S does -> mismatches"""
    y = D.DSP(xf); stock.decode_all(); bad = 0
    for i in idx:
        e = y.tiles[i].ent; off = e[0] | e[1] << 8 | (e[2] & 0x3f) << 16
        assert off & BIT
        w = struct.unpack_from("<I", y.sec[0], off & (BIT - 1))[0]
        t = stock.tiles[i]
        raw = D.rle_decode(y.sec[0], w & 0x7fffffff, t.n)[0][:t.n]
        bad += mask(raw, w >> 31, t.wb) != bytes(t.raw)
    return bad


if __name__ == "__main__":
    c = int(sys.argv[1], 16)
    b, base, l = D.char_dsp("mvc", c); st = D.DSP(b, base)
    idx = tiles(st)
    print("%02X: %d checker tiles, %d B raw: %s" % (c, len(idx), sum(st.tiles[i].n for i in idx), idx))
    x = sys.argv[2] if len(sys.argv) > 2 else None
    x = open(x, "rb").read() if x else st.d
    xf = apply(x, st, idx)
    print("applied: file %d -> %d B, model mismatches %d" % (len(x), len(xf), model_check(xf, st, idx)))
