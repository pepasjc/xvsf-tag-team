"""Hot loops of the sprite encoders, written once in a restricted Python that

  * numba compiles when it is installed (command-line build: seconds per file),
  * runs as it is when numba is missing (correct, but minutes per file), and
  * is mirrored line by line in patcher/kernels.js for the browser build (Pyodide has no numba).

Every kernel works on FLAT arrays and on a whole sprite file per call (all tiles concatenated,
`offs[i]..offs[i+1]` = tile i), so that the browser pays the Python<->JavaScript bridge once per pass
and not once per tile.  Integer widths: everything fits 32 bits (costs are a few million at most).

The algorithms are those of tools/nsp_mid.py (XVM1) and tools/nsp_huff.py (XVH1); the output of the
encoders built on them is compared byte for byte with the files those tools produced.

Backends: set_backend("numba" | "python" | <object with the kernel functions>); the default is numba
when it can be imported, else python.  The browser installs its JavaScript object.
"""
import numpy as np

NR = 30                       # run-length symbols (RUNS in huff.py)


# ---------------------------------------------------------------- game RLE (decoder 0x8001b5b0)
def rle_decode(mem, pos, n, out, o):
    """Model of the game's tile decoder: n output bytes to out[o:], returns source bytes used.
    Output past n (the decoder's overrun) is dropped."""
    p = pos; k = 0
    while k < n:
        b = np.int64(mem[p]); p += 1
        if b & 0xF0:                                   # run: (hi+1) bytes of value lo*0x11
            v = (b & 15) * 0x11; c = (b >> 4) + 1
            for j in range(c):
                if k < n: out[o + k] = v
                k += 1
        else:                                          # literal: (lo+1) raw bytes
            c = (b & 15) + 1
            for j in range(c):
                if k < n: out[o + k] = mem[p + j]
                k += 1
            p += c
    return p - pos


def rle_decode_all(mem, base, toff, tn, out, ooff, clen):
    """every tile of a stock file: toff[i] = offset in sec2 (mem[base:]), tn[i] = decoded size;
    out[ooff[i]:] receives the tile, clen[i] its stream length"""
    for i in range(len(toff)):
        clen[i] = rle_decode(mem, base + toff[i], tn[i], out, ooff[i])
    return 0


# ---------------------------------------------------------------- XVM1 (byte symbols)
def xvm_parse_acc(S, offs, Ws, tab, ctx, lens, NS, RUNS, pen, choice, hist):
    """Optimal parse of every tile for the code lengths lens[table*NS + symbol] (costs in quarter
    bits, `pen` added to every run symbol), then hist[context*NS + symbol] += 1 per coded symbol.
    choice[i]: 0 literal, 1+r copy RUNS[r] from the row above, 1+NR+r repeat the previous byte."""
    NRr = len(RUNS); ESC = 256 + 2 * NRr
    for ti in range(len(Ws)):
        b = offs[ti]; n = offs[ti + 1] - b; W = Ws[ti]
        up = np.zeros(n + 1, np.int32); rep = np.zeros(n + 1, np.int32); eq = np.zeros(n + 1, np.int32)
        for i in range(n - 1, -1, -1):
            s = S[b + i]
            u = S[b + i - W] if i >= W else 255
            if s == u: up[i] = up[i + 1] + 1 if i != W - 1 else 1
            else: up[i] = 0
            eq[i] = eq[i + 1] + 1 if (i + 1 < n and S[b + i + 1] == s and i != W - 1) else 1
        for i in range(n):
            pv = S[b + i - 1] if i else 255
            rep[i] = eq[i] if S[b + i] == pv else 0
        cost = np.zeros(n + 1, np.int32)
        for i in range(n - 1, -1, -1):
            t = tab[b + i] * NS
            l = lens[t + S[b + i]]
            if l == 0: l = lens[t + ESC] + 8
            best = cost[i + 1] + 4 * l; bc = 0
            lim = up[i]
            for r in range(NRr):
                if RUNS[r] > lim: break
                l = lens[t + 256 + r]
                if l == 0: continue
                c = cost[i + RUNS[r]] + 4 * l + pen
                if c < best: best = c; bc = 1 + r
            lim = rep[i]
            for r in range(NRr):
                if RUNS[r] > lim: break
                l = lens[t + 256 + NRr + r]
                if l == 0: continue
                c = cost[i + RUNS[r]] + 4 * l + pen
                if c < best: best = c; bc = 1 + NRr + r
            cost[i] = best; choice[b + i] = bc
        i = 0
        while i < n:
            c = choice[b + i]
            if c == 0: hist[ctx[b + i] * NS + S[b + i]] += 1; i += 1
            else: hist[ctx[b + i] * NS + 255 + c] += 1; i += RUNS[(c - 1) % NRr]
    return 0


def xvm_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, out, ooffs):
    """Tile streams, one after the other in out[]; ooffs[i] = start of tile i.  MSB first, byte aligned
    per tile: 4 bits width code, then the codes (an escape is followed by 8 raw bits).  -> bytes written"""
    NRr = len(RUNS); ESC = 256 + 2 * NRr; p = 0
    for ti in range(len(Ws)):
        b = offs[ti]; n = offs[ti + 1] - b; W = Ws[ti]
        ooffs[ti] = p
        acc = (W >> 3) - 1; nb = 4; i = 0
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


def xvm_ref_decode(mem, src, n, model, out):
    """Model of the MIPS decoder xvm_dec (tools/nspdec/nspdec.S): 32-bit MSB-first bit buffer,
    c = bits available - 16, 16-bit refills, the same table walks.  -> source bytes consumed"""
    fbo = model + (np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8))
    buf = (np.int64(mem[src]) * 16777216) + ((np.int64(mem[src + 1]) << 16) | (np.int64(mem[src + 2]) << 8) | np.int64(mem[src + 3]))
    src0 = src; src += 4
    W = ((buf >> 28) + 1) << 3
    buf = (buf << 4) & 0xFFFFFFFF
    c = 12
    P = 255; ph = 15 << 8
    o = 0
    while o < n:
        U = np.int64(out[o - W]) if o >= W else 255
        t = np.int64(mem[model + 76 + (ph | U)])
        a = model + 4172 + (t << 7) + ((buf >> 25) & 0x7e)
        e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        if (e & 0xC000) == 0xC000:                         # code longer than 6 bits
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
            if e & 0x1000:                                 # escape: 8 raw bits
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


def xvm_verify(mem, o2, o3, xvm_end, woff, tn, raw, roff, scratch):
    """Decode every tile of a finished XVM1 file image with the decoder models and compare with the
    original pixels raw[roff[i]:+tn[i]].  woff[i] = stream offset in sec2; offsets >= xvm_end are stock
    RLE streams.  -> number of bad tiles, or -1 - i when tile i reads past its region."""
    bad = 0
    for i in range(len(woff)):
        n = tn[i]
        if woff[i] >= xvm_end:
            used = rle_decode(mem, o2 + woff[i], n, scratch, 0)
            if o2 + woff[i] + used > o3: return -1 - i
        else:
            used = xvm_ref_decode(mem, o2 + woff[i], n, o2, scratch)
            if woff[i] + used > xvm_end: return -1 - i
        r = roff[i]
        for k in range(n):
            if scratch[k] != raw[r + k]:
                bad += 1; break
    return bad


# ---------------------------------------------------------------- XVH1 (pixel symbols)
def xvh_parse_acc(S, offs, Ws, tab, cq, lens, NS, RUNS, choice, hist):
    """Optimal parse (literal pixel vs copy-from-the-row-above run), then hist[cq*NS + symbol] += 1.
    S: pixels, Ws: tile width in pixels, tab: table per pixel, cq = context (c12 * 16 + UR) per pixel."""
    NRr = len(RUNS)
    for ti in range(len(Ws)):
        b = offs[ti]; n = offs[ti + 1] - b; W = Ws[ti]
        runlen = np.zeros(n + 1, np.int32)
        for i in range(n - 1, -1, -1):
            u = S[b + i - W] if i >= W else 15
            runlen[i] = runlen[i + 1] + 1 if S[b + i] == u else 0
        cost = np.zeros(n + 1, np.int32)
        for i in range(n - 1, -1, -1):
            t = tab[b + i] * NS
            l = lens[t + S[b + i]]
            if l == 0: l = 30
            best = cost[i + 1] + l; bc = 0
            rl = runlen[i]
            for r in range(NRr):
                if RUNS[r] > rl: break
                l = lens[t + 16 + r]
                if l == 0: l = 30
                c = cost[i + RUNS[r]] + l
                if c < best: best = c; bc = r + 1
            cost[i] = best; choice[b + i] = bc
        i = 0
        while i < n:
            c = choice[b + i]
            if c == 0: hist[cq[b + i] * NS + S[b + i]] += 1; i += 1
            else: hist[cq[b + i] * NS + 15 + c] += 1; i += RUNS[c - 1]
    return 0


def xvh_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, out, ooffs):
    """Tile streams: 4 bits width code (pixels/16 - 1), then the codes, MSB first.  -> bytes written"""
    p = 0
    for ti in range(len(Ws)):
        b = offs[ti]; n = offs[ti + 1] - b; W = Ws[ti]
        ooffs[ti] = p
        acc = (W >> 4) - 1; nb = 4; i = 0
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
        if nb:
            out[p] = (acc << (8 - nb)) & 255; p += 1
    return p


def xvh_ref_decode(mem, src, n, model, RUNS, out, rb):
    """Model of the MIPS decoder nsp_dec (tools/nspdec): bit-serial canonical decode.
    rb = scratch of 258 ints (the row above).  -> source bytes consumed"""
    for i in range(258): rb[i] = 15
    src0 = src
    map2 = model + np.int64(mem[model + 8]) + (np.int64(mem[model + 9]) << 8)
    tofs = model + np.int64(mem[model + 10]) + (np.int64(mem[model + 11]) << 8)
    buf = np.int64(mem[src]) * 16777216 + 0x800000; src += 1
    W = ((buf >> 28) + 1) * 16
    buf = (buf << 4) & 0xFFFFFFFF
    x = 0; L = 15 << 8; UL = 15; lo = 0; o = 0; run = 0
    while o < n:
        U = rb[x]
        if run == 0:
            c1 = np.int64(mem[model + 12 + (L | (U << 4) | UL)])
            t = np.int64(mem[map2 + ((c1 << 4) | rb[x + 1])])
            rec = model + (np.int64(mem[tofs + 2 * t]) | (np.int64(mem[tofs + 2 * t + 1]) << 8))
            sp = rec + 12
            d = 0
            while True:
                tt = (buf << 1) & 0xFFFFFFFF
                if tt == 0:
                    buf = np.int64(mem[src]) * 16777216 + 0x800000; src += 1
                    tt = (buf << 1) & 0xFFFFFFFF
                d = d * 2 + (buf >> 31)
                buf = tt
                c = np.int64(mem[rec]); rec += 1
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
            x = 0; L = 15 << 8; UL = 15
        else:
            L = p << 8; UL = U
    return src - src0


def xvh_verify(mem, o2, o3, woff, tn, raw, roff, RUNS, scratch, rb):
    """as xvm_verify, for an XVH1 file"""
    bad = 0
    for i in range(len(woff)):
        n = tn[i]
        used = xvh_ref_decode(mem, o2 + woff[i], n, o2, RUNS, scratch, rb)
        if o2 + woff[i] + used > o3: return -1 - i
        r = roff[i]
        for k in range(n):
            if scratch[k] != raw[r + k]:
                bad += 1; break
    return bad


# ---------------------------------------------------------------- Huffman code lengths
def hufflens_many(counts, NS, K, limit, lens, work):
    """Code lengths for K count rows (counts[k*NS + s] -> lens[k*NS + s]), exactly the lengths
    huff.hufflens() gives: package merge is NOT used - a plain Huffman tree built with the tie rule
    "smaller (count, node id) first" (leaf id = symbol, internal ids count up from NS), then the same
    length-limiting heuristic.  work = int32 scratch of at least 8 * NS entries."""
    # work layout: cnt[2NS] | parent[2NS] | alive list[2NS] | order[NS] | depth scratch[NS]
    C = 0; PAR = 2 * NS; AL = 4 * NS; ORD = 6 * NS
    for k in range(K):
        base = k * NS
        m = 0
        for s in range(NS):
            lens[base + s] = 0
            if counts[base + s] != 0:
                work[C + s] = counts[base + s]; work[AL + m] = s; m += 1
        if m == 0: continue
        if m == 1:
            lens[base + work[AL]] = 1; continue
        nidx = m
        for j in range(m): work[ORD + j] = work[AL + j]              # the used symbols, ascending
        # binary min-heap of node ids in work[AL:], ordered by (count, id)
        for j in range(m // 2 - 1, -1, -1):                          # heapify
            q = j
            while True:
                c1 = 2 * q + 1
                if c1 >= m: break
                c2 = c1 + 1
                x = work[AL + c1]
                if c2 < m:
                    y = work[AL + c2]
                    if work[C + y] < work[C + x] or (work[C + y] == work[C + x] and y < x):
                        c1 = c2; x = y
                y = work[AL + q]
                if work[C + x] < work[C + y] or (work[C + x] == work[C + y] and x < y):
                    work[AL + q] = x; work[AL + c1] = y; q = c1
                else: break
        uid = NS; alive = m
        while alive > 1:
            a = 0; b = 0
            for rep in range(2):                                     # pop the two smallest
                top = work[AL]
                alive -= 1
                last = work[AL + alive]
                q = 0
                while True:                                          # sift `last` down from the root
                    c1 = 2 * q + 1
                    if c1 >= alive: break
                    c2 = c1 + 1
                    x = work[AL + c1]
                    if c2 < alive:
                        y = work[AL + c2]
                        if work[C + y] < work[C + x] or (work[C + y] == work[C + x] and y < x):
                            c1 = c2; x = y
                    if work[C + x] < work[C + last] or (work[C + x] == work[C + last] and x < last):
                        work[AL + q] = x; q = c1
                    else: break
                if alive > 0: work[AL + q] = last
                if rep == 0: a = top
                else: b = top
            work[C + uid] = work[C + a] + work[C + b]
            work[PAR + a] = uid; work[PAR + b] = uid
            q = alive; alive += 1                                    # push the new node, sift up
            while q > 0:
                par = (q - 1) // 2
                y = work[AL + par]
                if work[C + uid] < work[C + y] or (work[C + uid] == work[C + y] and uid < y):
                    work[AL + q] = y; q = par
                else: break
            work[AL + q] = uid
            uid += 1
        root = uid - 1
        mx = 0
        for j in range(nidx):
            s = work[ORD + j]; d = 0; x = s
            while x != root:
                x = work[PAR + x]; d += 1
            lens[base + s] = d
            if d > mx: mx = d
        if mx > limit:
            Kr = 0
            for j in range(nidx):
                s = work[ORD + j]
                if lens[base + s] > limit: lens[base + s] = limit
                Kr += 1 << (limit - lens[base + s])
            full = 1 << limit
            while Kr > full:
                # symbols by (longest code first, rarest first), stable in symbol order; lengthen the
                # ones that are still shorter than the limit until the code is feasible
                done = False
                for j in range(nidx): work[AL + j] = work[ORD + j]
                for j in range(1, nidx):                             # insertion sort, stable
                    x = work[AL + j]; q = j - 1
                    while q >= 0:
                        y = work[AL + q]
                        if lens[base + y] < lens[base + x] or (lens[base + y] == lens[base + x] and counts[base + y] > counts[base + x]):
                            work[AL + q + 1] = y; q -= 1
                        else: break
                    work[AL + q + 1] = x
                for j in range(nidx):
                    s = work[AL + j]
                    if lens[base + s] < limit:
                        Kr -= 1 << (limit - lens[base + s] - 1); lens[base + s] += 1
                        if Kr <= full:
                            done = True; break
                if done: break
            # use the slack, most frequent symbols first (stable in symbol order)
            for j in range(nidx): work[AL + j] = work[ORD + j]
            for j in range(1, nidx):
                x = work[AL + j]; q = j - 1
                while q >= 0:
                    y = work[AL + q]
                    if counts[base + y] < counts[base + x]:
                        work[AL + q + 1] = y; q -= 1
                    else: break
                work[AL + q + 1] = x
            for j in range(nidx):
                s = work[AL + j]
                while lens[base + s] > 1 and Kr + (1 << (limit - lens[base + s])) <= full:
                    Kr += 1 << (limit - lens[base + s]); lens[base + s] -= 1
    return 0


# ---------------------------------------------------------------- argsort with a defined tie order
def argsort_np(v, idx, stack):
    """idx <- the permutation numpy's default (unstable) argsort gives for the float64 keys v.

    The encoders seed and repair their table clustering from argsort results, and the original files
    were produced with numpy's scalar introsort, whose order of EQUAL keys is an accident of the
    algorithm.  numpy builds with SIMD sorts (AVX-512, AVX2 from numpy 2.0) order ties differently, so
    np.argsort itself is not reproducible across machines.  This is that introsort, spelled out
    (numpy/core/src/npysort/quicksort.cpp, aquicksort: median of three, insertion sort up to 16
    elements, heapsort when the recursion gets too deep).  stack = int32 scratch, 512 entries."""
    num = len(v)
    for i in range(num): idx[i] = i
    if num < 2: return 0
    pl = 0; pr = num - 1; sp = 0
    cdepth = 0; t = num
    while t > 1:                                           # npy_get_msb(num) * 2
        t >>= 1; cdepth += 1
    cdepth *= 2
    while True:
        if cdepth < 0:
            # heapsort of idx[pl..pr] (1-based heap on a = idx[pl - 1 + k])
            n = pr - pl + 1; a = pl - 1
            l = n >> 1
            while l > 0:
                tmp = idx[a + l]; i = l; j = l << 1
                while j <= n:
                    if j < n and v[idx[a + j]] < v[idx[a + j + 1]]: j += 1
                    if v[tmp] < v[idx[a + j]]:
                        idx[a + i] = idx[a + j]; i = j; j += j
                    else: break
                idx[a + i] = tmp
                l -= 1
            while n > 1:
                tmp = idx[a + n]; idx[a + n] = idx[a + 1]; n -= 1
                i = 1; j = 2
                while j <= n:
                    if j < n and v[idx[a + j]] < v[idx[a + j + 1]]: j += 1
                    if v[tmp] < v[idx[a + j]]:
                        idx[a + i] = idx[a + j]; i = j; j += j
                    else: break
                idx[a + i] = tmp
        else:
            while pr - pl > 15:
                pm = pl + ((pr - pl) >> 1)
                if v[idx[pm]] < v[idx[pl]]: tmp = idx[pm]; idx[pm] = idx[pl]; idx[pl] = tmp
                if v[idx[pr]] < v[idx[pm]]: tmp = idx[pr]; idx[pr] = idx[pm]; idx[pm] = tmp
                if v[idx[pm]] < v[idx[pl]]: tmp = idx[pm]; idx[pm] = idx[pl]; idx[pl] = tmp
                vp = v[idx[pm]]
                pi = pl; pj = pr - 1
                tmp = idx[pm]; idx[pm] = idx[pj]; idx[pj] = tmp
                while True:
                    pi += 1
                    while v[idx[pi]] < vp: pi += 1
                    pj -= 1
                    while vp < v[idx[pj]]: pj -= 1
                    if pi >= pj: break
                    tmp = idx[pi]; idx[pi] = idx[pj]; idx[pj] = tmp
                pk = pr - 1
                tmp = idx[pi]; idx[pi] = idx[pk]; idx[pk] = tmp
                cdepth -= 1
                if pi - pl < pr - pi:                      # the larger partition waits on the stack
                    stack[sp] = pi + 1; stack[sp + 1] = pr; stack[sp + 2] = cdepth; sp += 3
                    pr = pi - 1
                else:
                    stack[sp] = pl; stack[sp + 1] = pi - 1; stack[sp + 2] = cdepth; sp += 3
                    pl = pi + 1
            for pi in range(pl + 1, pr + 1):               # insertion sort
                vi = idx[pi]; vp = v[vi]
                pj = pi
                while pj > pl and vp < v[idx[pj - 1]]:
                    idx[pj] = idx[pj - 1]; pj -= 1
                idx[pj] = vi
        if sp == 0: break
        sp -= 3
        pl = stack[sp]; pr = stack[sp + 1]; cdepth = stack[sp + 2]
    return 0


# ---------------------------------------------------------------- clustering: cheapest table per context
def cost_argmin(indptr, cols, vals, LT, K, new, cur, acc):
    """For every context row r (sparse histogram: columns cols[indptr[r]:indptr[r+1]], counts vals[...]):
    acc[t] = sum(count * LT[column * K + t]) = coded size of the row with table t;  new[r] = the first
    cheapest table, cur[r] = its cost.  All values are integers held in float64 (exact), so this is the
    dense product hist @ lens.T followed by argmin - without the 99 % zeros (numpy under Pyodide has no
    BLAS; the dense product was most of the browser build's time)."""
    for r in range(len(indptr) - 1):
        for t in range(K): acc[t] = 0.0
        for j in range(indptr[r], indptr[r + 1]):
            b = cols[j] * K; v = vals[j]
            for t in range(K): acc[t] += v * LT[b + t]
        best = 0
        for t in range(1, K):
            if acc[t] < acc[best]: best = t
        new[r] = best; cur[r] = acc[best]
    return 0


NAMES = ["rle_decode_all", "xvm_parse_acc", "xvm_emit", "xvm_verify", "xvh_parse_acc", "xvh_emit", "xvh_verify", "hufflens_many", "argsort_np", "cost_argmin"]
_INNER = ["rle_decode", "xvm_ref_decode", "xvh_ref_decode"]
_py = {n: globals()[n] for n in NAMES + _INNER}
backend = "python"


def set_backend(b):
    """b: "numba", "python", or an object/dict that provides the kernels (the browser's JavaScript module)"""
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


def auto_backend():
    try:
        import numba  # noqa: F401
    except Exception:
        return set_backend("python")
    set_backend("numba")
