"""Hot loops of the MSHvSF sprite encoders (DSM1, DSH1) that builder/xvb/kernels.py does not already have.

Same rules as xvb/kernels.py: restricted Python that numba compiles when it is installed, that runs as it is
without numba (slow but correct), and that is mirrored line by line in patcher/src/kernels_msh.js for the browser
(Pyodide has no numba).  Flat arrays, one call per file, integer arithmetic only (everything fits 32 bits).

The shared pieces (optimal parses xvh_parse_acc / xvm_parse_acc, hufflens_many, argsort_np, cost_argmin) stay in
xvb.kernels; set_backend() here switches both modules.

Algorithms: common/dsp/dsp.py (stock RLE), common/dsp/dsm.py (DSM1 emit / ref_decode), common/dsp/dsh.py (DSH1
enc_tile / ref_decode / written).
"""
import numpy as np
from xvb import kernels as xk


# ---------------------------------------------------------------- stock RLE (game decoder 0x8001bd68)
def dsp_rle_all(mem, base, toff, tn, out, ooff, clen, wlen):
    """Every tile of a stock .DSP: the bytes the game's RLE decoder WRITES for tile i (tn[i] bytes plus its overrun:
    the rest of the last run or literal, and the extra byte an odd literal stores) -> out[ooff[i]:ooff[i] + wlen[i]];
    clen[i] = stream bytes used (without the extra byte).  out[ooff[i]:+tn[i]] = the tile's pixels.
    mem[base + toff[i]:] = the stream (mem extends past the pixel section)."""
    for i in range(len(toff)):
        p = base + toff[i]; n = tn[i]; o = ooff[i]; k = 0; extra = 0
        while k < n:
            b = np.int64(mem[p]); p += 1
            if b & 0xF0:
                v = (b & 15) * 0x11
                for j in range((b >> 4) + 1):
                    out[o + k] = v; k += 1
                extra = 0
            else:
                c = (b & 15) + 1
                for j in range(c):
                    out[o + k] = mem[p + j]; k += 1
                p += c; extra = c & 1
        clen[i] = p - base - toff[i]
        if extra:
            out[o + k] = mem[p]; k += 1
        wlen[i] = k
    return 0


def rle_n(mem, pos, n, out):
    """game RLE decode of n bytes to out[0:n] (overrun dropped) -> source bytes used"""
    p = pos; k = 0
    while k < n:
        b = np.int64(mem[p]); p += 1
        if b & 0xF0:
            v = (b & 15) * 0x11; c = (b >> 4) + 1
            for j in range(c):
                if k < n: out[k] = v
                k += 1
        else:
            c = (b & 15) + 1
            for j in range(c):
                if k < n: out[k] = mem[p + j]
                k += 1
            p += c
    return p - pos


def rle_written(mem, pos, n, out):
    """game RLE decode with everything it writes (overrun, odd-literal extra byte) to out[0:] -> bytes written"""
    p = pos; k = 0; extra = 0
    while k < n:
        b = np.int64(mem[p]); p += 1
        if b & 0xF0:
            v = (b & 15) * 0x11
            for j in range((b >> 4) + 1):
                out[k] = v; k += 1
            extra = 0
        else:
            c = (b & 15) + 1
            for j in range(c):
                out[k] = mem[p + j]; k += 1
            p += c; extra = c & 1
    if extra:
        out[k] = mem[p]; k += 1
    return k


# ---------------------------------------------------------------- DSM1 (byte symbols)
def dsm_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, out, ooffs):
    """Tile streams one after the other in out[]; ooffs[i] = start of tile i.  Per tile: one byte = row width in
    bytes, then the codes MSB first (an escape is followed by 8 raw bits).  -> bytes written"""
    NRr = len(RUNS); ESC = 256 + 2 * NRr; p = 0
    for ti in range(len(Ws)):
        b = offs[ti]; n = offs[ti + 1] - b; W = Ws[ti]
        ooffs[ti] = p
        out[p] = W; p += 1
        acc = 0; nb = 0; i = 0
        while i < n:
            t = tab[b + i] * NS; c = choice[b + i]; raw = -1
            if c == 0:
                sym = S[b + i]; i += 1
                if lens[t + sym] == 0: raw = sym; sym = ESC
            else:
                sym = 255 + c; i += RUNS[(c - 1) % NRr]
            l = lens[t + sym]
            acc = (acc << l) | codes[t + sym]; nb += l
            if raw >= 0:
                acc = (acc << 8) | raw; nb += 8
            while nb >= 8:
                out[p] = (acc >> (nb - 8)) & 255; p += 1; nb -= 8
            acc &= (1 << nb) - 1
        if nb:
            out[p] = (acc << (8 - nb)) & 255; p += 1
    return p


def dsm_ref_decode(mem, src, n, model, out):
    """Model of the MIPS decoder dsm_dec (common/dsp/dsmdec.S): width byte, then a 32-bit MSB-first bit buffer,
    c = bits available - 16, 16-bit refills.  -> source bytes consumed (incl. the width byte)"""
    fbo = model + (np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8))
    W = np.int64(mem[src])
    buf = (np.int64(mem[src + 1]) * 16777216) + ((np.int64(mem[src + 2]) << 16) | (np.int64(mem[src + 3]) << 8) | np.int64(mem[src + 4]))
    src0 = src; src += 5
    c = 16
    P = 255; ph = 15 << 8
    o = 0
    while o < n:
        U = np.int64(out[o - W]) if o >= W else 255
        t = np.int64(mem[model + 76 + (ph | U)])
        a = model + 4172 + (t << 7) + ((buf >> 25) & 0x7e)
        e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        if (e & 0xC000) == 0xC000:
            w = buf >> 20
            p = fbo + (t << 5); sh = 5
            while True:
                lim = np.int64(mem[p]) | (np.int64(mem[p + 1]) << 8)
                if w < lim: break
                p += 4; sh -= 1
            adj = np.int64(mem[p + 2]) | (np.int64(mem[p + 3]) << 8)
            if adj & 0x8000: adj -= 0x10000
            a = model + adj + ((w >> sh) << 1)
            e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        l = e & 15
        buf = (buf << l) & 0xFFFFFFFF; c -= l
        if e & 0x8000:
            if e & 0x1000:
                P = buf >> 24
                buf = (buf << 8) & 0xFFFFFFFF; c -= 8
                out[o] = P; o += 1
            else:
                a = model + 12 + ((e >> 3) & 0x3e)
                r = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
                if e & 0x2000:
                    for k in range(r):
                        out[o] = P; o += 1
                else:
                    for k in range(r):
                        out[o] = out[o - W] if o >= W else 255
                        o += 1
                    P = np.int64(out[o - 1])
        else:
            P = (e >> 4) & 255
            out[o] = P; o += 1
        ph = (P >> 4) << 8
        if c < 0:
            v = (np.int64(mem[src]) << 8) | np.int64(mem[src + 1])
            buf = (buf | (v << (-c))) & 0xFFFFFFFF
            src += 2; c += 16
    return src - src0


def dsm_verify(mem, end, woff, tn, raw, roff, scratch):
    """Decode every tile of a finished DSM1 pixel section mem (sec0 + padding) and compare with the stock pixels
    raw[roff[i]:+tn[i]].  woff[i] = the tile's offset in sec0; offsets >= end (= end of the DSM1 part) are stock RLE
    streams.  -> number of bad tiles, or -1 - i when tile i reads past the DSM1 part"""
    bad = 0
    for i in range(len(woff)):
        n = tn[i]
        if woff[i] >= end:
            rle_n(mem, woff[i], n, scratch)
        else:
            used = dsm_ref_decode(mem, woff[i], n, 0, scratch)
            if woff[i] + used > end: return -1 - i
        r = roff[i]
        for k in range(n):
            if scratch[k] != raw[r + k]:
                bad += 1; break
    return bad


# ---------------------------------------------------------------- DSH1 (pixel symbols)
def dsh_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, hv, hl, tail, toff, out, ooffs):
    """Tile streams one after the other in out[]; ooffs[i] = start of tile i.  Per tile: the header bits
    (hv[i], hl[i] bits), the codes MSB first, then the tail bytes tail[toff[i]:toff[i+1]] (8 bits each: the raw
    overrun bytes), padded to a byte.  -> bytes written"""
    p = 0
    for ti in range(len(Ws)):
        b = offs[ti]; n = offs[ti + 1] - b
        ooffs[ti] = p
        acc = hv[ti]; nb = hl[ti]; i = 0
        while i < n:
            t = tab[b + i] * NS; c = choice[b + i]
            if c == 0:
                sym = S[b + i]; i += 1
            else:
                sym = 15 + c; i += RUNS[c - 1]
            l = lens[t + sym]
            acc = (acc << l) | codes[t + sym]; nb += l
            while nb >= 8:
                out[p] = (acc >> (nb - 8)) & 255; p += 1; nb -= 8
            acc &= (1 << nb) - 1
        for k in range(toff[ti], toff[ti + 1]):
            acc = (acc << 8) | tail[k]
            out[p] = (acc >> nb) & 255; p += 1
            acc &= (1 << nb) - 1
        if nb:
            out[p] = (acc << (8 - nb)) & 255; p += 1
    return p


def dsh_ref_decode(mem, src, n, model, RUNS, out, rb):
    """Model of the MIPS decoder (common/dsp/dshdec.S, MSHvSF width code, raw overrun bytes): decodes n + e bytes
    (e from the tile header).  rb = scratch of 260 ints (the row above).  -> (bytes written, source bytes consumed)"""
    for i in range(260): rb[i] = 15
    src0 = src
    m1 = model + 12 + 2 * (np.int64(mem[model + 10]) | (np.int64(mem[model + 11]) << 8))
    buf = 0; nbits = 0
    v = 0; k = 0; wc = 0
    while True:                                        # width code: '0' 0, '10' 1, '11' + 4 bits
        if nbits == 0:
            buf = np.int64(mem[src]); src += 1; nbits = 8
        nbits -= 1; v = v * 2 + ((buf >> nbits) & 1); k += 1
        if (k == 1 and v == 0) or (k == 2 and v == 2):
            wc = v >> 1; break
        if k == 6:
            wc = v & 15; break
    W = (wc + 1) * 16
    v = 0; k = 0; rep = 0; e = 0
    while True:                                        # overrun: '10' none, '0' + 4 bits repeat, '11' + 4 bits raw
        if nbits == 0:
            buf = np.int64(mem[src]); src += 1; nbits = 8
        nbits -= 1; v = v * 2 + ((buf >> nbits) & 1); k += 1
        if k == 2 and v == 2:
            e = 0; break
        if k == 5 and (v >> 4) == 0:
            e = v & 15; rep = 1; break
        if k == 6:
            e = v & 15; break
    x = 0; L = 15; UL = 15; lo = 0; o = 0; run = 0
    while o < n:
        U = rb[x]
        if run == 0:
            c1 = np.int64(mem[m1 + ((L << 8) | (U << 4) | UL)])
            t = np.int64(mem[m1 + 4096 + ((c1 << 4) | rb[x + 1])])
            sp = model + (np.int64(mem[model + 12 + 2 * t]) | (np.int64(mem[model + 13 + 2 * t]) << 8))
            rec = sp - 1
            d = 0
            while True:
                if nbits == 0:
                    buf = np.int64(mem[src]); src += 1; nbits = 8
                nbits -= 1
                d = d * 2 + ((buf >> nbits) & 1)
                c = np.int64(mem[rec]); rec -= 1
                if d < c: break
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
            x = 0; L = 15; UL = 15
        else:
            L = p; UL = U
    if rep:
        for k in range(e):
            out[n + k] = out[n - 1]
    else:
        for k in range(e):
            v = 0
            for j in range(8):
                if nbits == 0:
                    buf = np.int64(mem[src]); src += 1; nbits = 8
                nbits -= 1; v = v * 2 + ((buf >> nbits) & 1)
            out[n + k] = v
    return n + e, src - src0


def dsh_verify(mem, end, woff, tn, want, wofs, RUNS, scratch, rb):
    """Decode every tile of a finished DSH1 file (mem = the file from its pixel section on, padded) and compare
    with what the stock decoder writes, want[wofs[i]:wofs[i+1]] (pixels + overrun).  woff[i] = the tile's offset;
    offsets >= end (= end of the DSH1 part) are stock RLE streams.  -> number of bad tiles, or -1 - i when tile i
    reads past the DSH1 part"""
    bad = 0
    for i in range(len(woff)):
        n = tn[i]
        if woff[i] >= end:
            m = rle_written(mem, woff[i], n, scratch)
        else:
            r = dsh_ref_decode(mem, woff[i], n, 0, RUNS, scratch, rb)
            m = r[0]
            if woff[i] + r[1] > end: return -1 - i
        w0 = wofs[i]
        if m != wofs[i + 1] - w0:
            bad += 1; continue
        for k in range(m):
            if scratch[k] != want[w0 + k]:
                bad += 1; break
    return bad


# ---------------------------------------------------------------- clustering: cheapest table per context
def cost_argmin_bb(indptr, cols, vals, LT, K, hint, new, cur, bj, acc):
    """For every row r of a sparse integer matrix (columns cols[indptr[r]:indptr[r+1]], counts vals[...] > 0):
    cost(t) = sum(count * LT[column * K + t]) for the K tables t (all LT > 0); new[r] = the FIRST cheapest table,
    cur[r] = its cost: exactly (m @ L.T).argmin(1) and the minimum (xvb.kernels.cost_argmin), without computing
    every cost in full.  The first two entries of the row are summed for every table (acc[K], a streaming loop);
    then branch and bound: table hint[r] (a guess, e.g. the current assignment) is costed in full first, and every
    other table is abandoned as soon as its partial sum can no longer win (the terms are positive, so partial sums
    only grow; on equal cost the lower table wins).  Integer sums: exact in any order (the caller checks they stay
    below 2**31); entries sorted by decreasing count make the bound bite early.  bj = int32 scratch (longest row)."""
    for r in range(len(indptr) - 1):
        j0 = indptr[r]; m = indptr[r + 1] - j0
        for j in range(m): bj[j] = cols[j0 + j] * K
        p = m if m < 2 else 2
        for t in range(K): acc[t] = 0
        for j in range(p):
            b = bj[j]; v = vals[j0 + j]
            for t in range(K): acc[t] += v * LT[b + t]
        bt = hint[r]; bc = acc[bt]
        for j in range(p, m): bc += vals[j0 + j] * LT[bj[j] + bt]
        for t in range(K):
            if t == bt: continue
            s = acc[t]; j = p
            if t < bt:
                if s > bc: continue
                while j < m:
                    s += vals[j0 + j] * LT[bj[j] + t]
                    if s > bc: break
                    j += 1
                if s <= bc:
                    bt = t; bc = s
            else:
                if s >= bc: continue
                while j < m:
                    s += vals[j0 + j] * LT[bj[j] + t]
                    if s >= bc: break
                    j += 1
                if s < bc:
                    bt = t; bc = s
        new[r] = bt; cur[r] = bc
    return 0


# ---------------------------------------------------------------- backends
NAMES = ["dsp_rle_all", "dsm_emit", "dsm_verify", "dsh_emit", "dsh_verify", "cost_argmin_bb"]
_INNER = ["rle_n", "rle_written", "dsm_ref_decode", "dsh_ref_decode"]
_py = {n: globals()[n] for n in NAMES + _INNER}
backend = "python"


def set_backend(b, xv=None):
    """b: "numba", "python", or an object/dict with the kernels of this module (the JavaScript MSK object);
    xv: the same for xvb.kernels (default: b when b is a string; an external b needs xv given)"""
    global backend
    g = globals()
    if b == "python":
        for n, f in _py.items(): g[n] = f
    elif b == "numba":
        import numba
        for n in _INNER: g[n] = numba.njit(cache=True)(_py[n])        # callees first: the callers bind them at compile time
        for n in NAMES: g[n] = numba.njit(cache=True)(_py[n])
    else:
        for n in NAMES: g[n] = b[n] if isinstance(b, dict) else getattr(b, n)
    backend = b if isinstance(b, str) else "external"
    if xv is None and isinstance(b, str): xv = b
    if xv is not None: xk.set_backend(xv)


def auto_backend():
    try:
        import numba  # noqa: F401
    except Exception:
        return set_backend("python")
    set_backend("numba")


def use_js(msk, xvk):
    """the browser's kernels: msk = MSK.forPyodide() (patcher/src/kernels_msh.js), xvk = XVK.forPyodide()
    (patcher/src/kernels.js).  numpy integers become plain ints on the way (as xvb.web.use_js_kernels)."""
    def wrap(f):
        def call(*args):
            return f(*[int(a) if isinstance(a, np.integer) else a for a in args])
        return call
    set_backend({n: wrap(getattr(msk, n)) for n in NAMES}, {n: wrap(getattr(xvk, n)) for n in xk.NAMES})
