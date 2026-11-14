"""PS1 SPU ADPCM ("VAG" body data) decoder and encoders.

Block format (16 bytes, 28 samples per block):

    byte 0      filter << 4 | shift      filter 0..4 (5..7 behave as 4),
                                         shift 0..12 (13..15 behave as 9)
    byte 1      flags                    bit0 loop end, bit1 repeat, bit2 loop start
    bytes 2..15 28 signed 4-bit samples, low nibble first

Decoding one sample (exact SPU semantics, all integer):

    t      = sign_extend(nibble) << 12 >> shift
    pred   = (s1 * pos + s2 * neg + 32) >> 6          (arithmetic shift)
    sample = clamp_int16(t + pred);  s2 = s1;  s1 = sample

with (pos, neg) = FILTERS[filter]. Shift 13..15 decode like shift 9 (what the
SPU does per the psx-spx documentation and DuckStation); the game data never
uses them and the encoders never emit them.

Encoders (all output bytes are a pure function of the input integers; no
float arithmetic is used anywhere on the data path, ties are broken by fixed
index order, and results do not depend on thread count):

  encode_greedy  baseline in the style of the Sony tools: every block tries all
                 5 filters x 13 shifts, quantises each sample to the nearest
                 nibble against the exact decoder state, keeps the combination
                 with the lowest squared error.

  encode         search encoder. Keeps a beam of `block_beam` candidate decoder
                 states across block boundaries. For every carried state the
                 `combos` best (filter, shift) pairs by greedy error are
                 re-quantised with a trellis/beam search over nibble choices
                 (`beam` paths, each sample tries the rounded nibble +-`radius`)
                 that runs the exact decoder including clamping. Distinct
                 decoder states (s1, s2) are de-duplicated, because equal
                 states have identical futures. The objective is the int64 sum
                 of squared errors against the input over the whole sound.

  vag_body       the block layout of the game's VB files (see its docstring).

numba is used when available (integer code only). Without numba (or with
NUMBA_DISABLE_JIT=1) the same functions run as plain Python and produce the
same bytes, just very slowly.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

try:
    import numba as _nb

    def _jit(f):
        return _nb.njit(cache=True, nogil=True)(f)
except ImportError:  # pure-Python fallback, identical results
    _nb = None

    def _jit(f):
        return f

# (pos, neg) prediction coefficients, /64
FILTERS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))
_F0 = np.array([f[0] for f in FILTERS], dtype=np.int64)
_F1 = np.array([f[1] for f in FILTERS], dtype=np.int64)

# Default search settings (see encode()).
DEFAULT_BEAM = 8
DEFAULT_BLOCK_BEAM = 4
DEFAULT_COMBOS = 6
DEFAULT_RADIUS = 1

BLOCK_SAMPLES = 28
BLOCK_BYTES = 16


# --------------------------------------------------------------------------
# decoder
# --------------------------------------------------------------------------

@_jit
def _decode_core(b, nblk, s1, s2, out):
    for k in range(nblk):
        o = k * 16
        hdr = np.int64(b[o])
        sh = hdr & 15
        if sh > 12:
            sh = 9
        f = (hdr >> 4) & 7
        if f > 4:
            f = 4
        f0 = _F0[f]
        f1 = _F1[f]
        for i in range(28):
            n = (np.int64(b[o + 2 + (i >> 1)]) >> ((i & 1) * 4)) & 15
            if n >= 8:
                n -= 16
            s = ((n << 12) >> sh) + ((s1 * f0 + s2 * f1 + 32) >> 6)
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            s2 = s1
            s1 = s
            out[k * 28 + i] = s
    return s1, s2


def decode(blocks, s1=0, s2=0):
    """Decode ADPCM blocks (bytes, len multiple of 16; a trailing partial block
    is ignored) to an int16 array of 28 samples per block. Flags are ignored
    (every block is decoded). s1/s2 = previous two output samples."""
    b = np.frombuffer(bytes(blocks), dtype=np.uint8)
    nblk = len(b) // 16
    out = np.zeros(nblk * 28, dtype=np.int64)
    _decode_core(b, nblk, np.int64(s1), np.int64(s2), out)
    return out.astype(np.int16)


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def _prep(pcm):
    """int16-range samples -> int64 array padded with zeros to whole blocks."""
    x = np.asarray(pcm)
    if x.dtype.kind not in "iu":
        raise TypeError("pcm must be an integer array")
    x = x.astype(np.int64)
    if len(x) and (x.min() < -32768 or x.max() > 32767):
        raise ValueError("pcm out of int16 range")
    nblk = (len(x) + 27) // 28
    xp = np.zeros(nblk * 28, dtype=np.int64)
    xp[:len(x)] = x
    return xp, nblk


@_jit
def _greedy_err(x, o, s1, s2, f0, f1, sh):
    """Squared error of nearest-nibble quantisation of one block."""
    qs = 12 - sh
    step = np.int64(1) << qs
    half = step >> 1
    err = np.int64(0)
    for i in range(28):
        xi = x[o + i]
        pred = (s1 * f0 + s2 * f1 + 32) >> 6
        n = (xi - pred + half) >> qs
        if n > 7:
            n = 7
        elif n < -8:
            n = -8
        s = n * step + pred
        if s > 32767:
            s = 32767
        elif s < -32768:
            s = -32768
        e = xi - s
        err += e * e
        s2 = s1
        s1 = s
    return err


@_jit
def _greedy_block(x, o, s1, s2, f0, f1, sh, nib):
    """Nearest-nibble quantisation of one block; fills nib[0..27], returns
    the final (s1, s2)."""
    qs = 12 - sh
    step = np.int64(1) << qs
    half = step >> 1
    for i in range(28):
        xi = x[o + i]
        pred = (s1 * f0 + s2 * f1 + 32) >> 6
        n = (xi - pred + half) >> qs
        if n > 7:
            n = 7
        elif n < -8:
            n = -8
        s = n * step + pred
        if s > 32767:
            s = 32767
        elif s < -32768:
            s = -32768
        nib[i] = n
        s2 = s1
        s1 = s
    return s1, s2


@_jit
def _pack(out, o, f, sh, nib):
    out[o] = (f << 4) | sh
    out[o + 1] = 0
    for j in range(14):
        out[o + 2 + j] = (nib[2 * j] & 15) | ((nib[2 * j + 1] & 15) << 4)


# --------------------------------------------------------------------------
# baseline encoder
# --------------------------------------------------------------------------

@_jit
def _encode_greedy_core(x, nblk, s1, s2, out):
    nib = np.zeros(28, dtype=np.int64)
    for k in range(nblk):
        o = k * 28
        best = np.int64(-1)
        bf = 0
        bs = 0
        for f in range(5):
            for sh in range(13):
                e = _greedy_err(x, o, s1, s2, _F0[f], _F1[f], np.int64(sh))
                if best < 0 or e < best:
                    best = e
                    bf = f
                    bs = sh
        s1, s2 = _greedy_block(x, o, s1, s2, _F0[bf], _F1[bf], np.int64(bs), nib)
        _pack(out, k * 16, bf, bs, nib)


def encode_greedy(pcm, s1=0, s2=0):
    """Baseline encoder: per block best (filter, shift) by squared error with
    nearest-nibble rounding. Returns ceil(n/28) data blocks, flags 0."""
    xp, nblk = _prep(pcm)
    out = np.zeros(nblk * 16, dtype=np.uint8)
    _encode_greedy_core(xp, nblk, np.int64(s1), np.int64(s2), out)
    return out.tobytes()


@_jit
def _encode_sony_core(x, nblk, s1, s2, out):
    nib = np.zeros(28, dtype=np.int64)
    o1 = np.int64(0)     # open-loop history (input samples), as in the
    o2 = np.int64(0)     # classic Sony tool
    for k in range(nblk):
        o = k * 28
        best = np.int64(-1)
        bf = 0
        for f in range(5):
            a1 = o1
            a2 = o2
            mx = np.int64(0)
            for i in range(28):
                d = x[o + i] - ((a1 * _F0[f] + a2 * _F1[f] + 32) >> 6)
                if d < 0:
                    d = -d
                if d > mx:
                    mx = d
                a2 = a1
                a1 = x[o + i]
            if best < 0 or mx <= best:
                best = mx
                bf = f
            if best <= 7:
                bf = 0
                break
        o1 = x[o + 27]
        o2 = x[o + 26]
        sh = 0
        mask = np.int64(0x4000)
        while sh < 12:
            if mask & (best + (mask >> 3)):
                break
            sh += 1
            mask >>= 1
        s1, s2 = _greedy_block(x, o, s1, s2, _F0[bf], _F1[bf], np.int64(sh), nib)
        _pack(out, k * 16, bf, sh, nib)


def encode_sony(pcm, s1=0, s2=0):
    """Integer rendition of the classic Sony VAG tool, for reference only:
    filter = smallest peak open-loop prediction residual, shift derived from
    that peak, then nearest-nibble rounding. Weaker than encode_greedy."""
    xp, nblk = _prep(pcm)
    out = np.zeros(nblk * 16, dtype=np.uint8)
    _encode_sony_core(xp, nblk, np.int64(s1), np.int64(s2), out)
    return out.tobytes()


# --------------------------------------------------------------------------
# search encoder
# --------------------------------------------------------------------------

@_jit
def _beam_block(x, o, s1, s2, f0, f1, sh, B, R, keep,
                cs1, cs2, cerr, ns1, ns2, nerr,
                ccost, cs, cpar, cnib, order, bpar, bnib,
                fin_s1, fin_s2, fin_err, fin_nib):
    """Trellis/beam quantisation of one block with fixed (filter, shift),
    starting from decoder state (s1, s2).

    Keeps up to B partial paths with distinct decoder states; every path tries
    nibbles round(residual) +- R. Writes the best `keep` finished paths
    (ascending error) to fin_*; returns how many there are."""
    qs = 12 - sh
    step = np.int64(1) << qs
    half = step >> 1
    nb = 1
    cs1[0] = s1
    cs2[0] = s2
    cerr[0] = 0
    for i in range(28):
        xi = x[o + i]
        nc = 0
        for b in range(nb):
            p1 = cs1[b]
            pred = (p1 * f0 + cs2[b] * f1 + 32) >> 6
            n0 = (xi - pred + half) >> qs
            if n0 > 7:
                n0 = 7
            elif n0 < -8:
                n0 = -8
            lo = n0 - R
            hi = n0 + R
            if lo < -8:
                lo = -8
            if hi > 7:
                hi = 7
            base = cerr[b]
            for n in range(lo, hi + 1):
                s = n * step + pred
                if s > 32767:
                    s = 32767
                elif s < -32768:
                    s = -32768
                e = xi - s
                ccost[nc] = base + e * e
                cs[nc] = s
                cpar[nc] = b
                cnib[nc] = n
                nc += 1
        # stable insertion sort of candidate indices by cost
        for a in range(nc):
            v = ccost[a]
            j = a - 1
            while j >= 0 and ccost[order[j]] > v:
                order[j + 1] = order[j]
                j -= 1
            order[j + 1] = a
        # take the best B with distinct (s1, s2)
        k = 0
        for a in range(nc):
            c = order[a]
            s = cs[c]
            p = cs1[cpar[c]]
            dup = False
            for q in range(k):
                if ns1[q] == s and ns2[q] == p:
                    dup = True
                    break
            if dup:
                continue
            ns1[k] = s
            ns2[k] = p
            nerr[k] = ccost[c]
            bpar[i, k] = cpar[c]
            bnib[i, k] = cnib[c]
            k += 1
            if k == B:
                break
        for q in range(k):
            cs1[q] = ns1[q]
            cs2[q] = ns2[q]
            cerr[q] = nerr[q]
        nb = k
    # paths are already sorted by error (selection was in cost order)
    nf = nb if nb < keep else keep
    for q in range(nf):
        fin_s1[q] = cs1[q]
        fin_s2[q] = cs2[q]
        fin_err[q] = cerr[q]
        p = q
        for i in range(27, -1, -1):
            fin_nib[q, i] = bnib[i, p]
            p = bpar[i, p]
    return nf


@_jit
def _encode_core(x, nblk, s1, s2, K, M, B, R, out):
    """Beam search over blocks: K carried states, M (filter, shift) pairs per
    state, B in-block paths, nibble radius R."""
    NC = B * (2 * R + 1)
    # in-block workspace
    cs1 = np.zeros(B, np.int64)
    cs2 = np.zeros(B, np.int64)
    cerr = np.zeros(B, np.int64)
    ns1 = np.zeros(B, np.int64)
    ns2 = np.zeros(B, np.int64)
    nerr = np.zeros(B, np.int64)
    ccost = np.zeros(NC, np.int64)
    cs = np.zeros(NC, np.int64)
    cpar = np.zeros(NC, np.int64)
    cnib = np.zeros(NC, np.int64)
    order = np.zeros(NC, np.int64)
    bpar = np.zeros((28, B), np.int64)
    bnib = np.zeros((28, B), np.int64)
    fin_s1 = np.zeros(K, np.int64)
    fin_s2 = np.zeros(K, np.int64)
    fin_err = np.zeros(K, np.int64)
    fin_nib = np.zeros((K, 28), np.int64)
    # combo pre-selection
    cerr_c = np.zeros(M, np.int64)
    cidx_c = np.zeros(M, np.int64)
    # pool of block results
    P = K * M * K
    pcost = np.zeros(P, np.int64)
    ps1_ = np.zeros(P, np.int64)
    ps2_ = np.zeros(P, np.int64)
    ppar = np.zeros(P, np.int64)
    pcombo = np.zeros(P, np.int64)
    pnib = np.zeros((P, 28), np.int64)
    porder = np.zeros(P, np.int64)
    # carried states
    ks1 = np.zeros(K, np.int64)
    ks2 = np.zeros(K, np.int64)
    kerr = np.zeros(K, np.int64)
    nk = 1
    ks1[0] = s1
    ks2[0] = s2
    # back-pointers per block
    bt_par = np.zeros((nblk, K), np.int64)
    bt_combo = np.zeros((nblk, K), np.int64)
    bt_nib = np.zeros((nblk, K, 28), np.int8)
    for blk in range(nblk):
        o = blk * 28
        npool = 0
        for p in range(nk):
            # rank all 65 (filter, shift) pairs by greedy error, keep best M
            nm = 0
            for combo in range(65):
                f = combo // 13
                sh = combo - f * 13
                e = _greedy_err(x, o, ks1[p], ks2[p], _F0[f], _F1[f], np.int64(sh))
                if nm < M:
                    j = nm
                    nm += 1
                elif e < cerr_c[M - 1]:
                    j = M - 1
                else:
                    continue
                while j > 0 and cerr_c[j - 1] > e:
                    cerr_c[j] = cerr_c[j - 1]
                    cidx_c[j] = cidx_c[j - 1]
                    j -= 1
                cerr_c[j] = e
                cidx_c[j] = combo
            for m in range(nm):
                combo = cidx_c[m]
                f = combo // 13
                sh = combo - f * 13
                nf = _beam_block(x, o, ks1[p], ks2[p], _F0[f], _F1[f], np.int64(sh),
                                 B, R, K, cs1, cs2, cerr, ns1, ns2, nerr,
                                 ccost, cs, cpar, cnib, order, bpar, bnib,
                                 fin_s1, fin_s2, fin_err, fin_nib)
                for q in range(nf):
                    pcost[npool] = kerr[p] + fin_err[q]
                    ps1_[npool] = fin_s1[q]
                    ps2_[npool] = fin_s2[q]
                    ppar[npool] = p
                    pcombo[npool] = combo
                    for i in range(28):
                        pnib[npool, i] = fin_nib[q, i]
                    npool += 1
        # stable sort pool by cost, keep the best K distinct states
        for a in range(npool):
            v = pcost[a]
            j = a - 1
            while j >= 0 and pcost[porder[j]] > v:
                porder[j + 1] = porder[j]
                j -= 1
            porder[j + 1] = a
        k = 0
        for a in range(npool):
            c = porder[a]
            dup = False
            for q in range(k):
                if ks1[q] == ps1_[c] and ks2[q] == ps2_[c]:
                    dup = True
                    break
            if dup:
                continue
            # ks1/ks2 slots < k already hold the new states; the parent index
            # refers to the previous block's states, saved in bt_par.
            bt_par[blk, k] = ppar[c]
            bt_combo[blk, k] = pcombo[c]
            for i in range(28):
                bt_nib[blk, k, i] = pnib[c, i]
            # new state goes into slot k; old slot k (if any) is no longer
            # needed because all pool entries already copied their data.
            ks1[k] = ps1_[c]
            ks2[k] = ps2_[c]
            kerr[k] = pcost[c]
            k += 1
            if k == K:
                break
        nk = k
    # backtrack from the best final state (slot 0)
    nib = np.zeros(28, np.int64)
    p = 0
    for blk in range(nblk - 1, -1, -1):
        combo = bt_combo[blk, p]
        f = combo // 13
        sh = combo - f * 13
        for i in range(28):
            nib[i] = bt_nib[blk, p, i]
        _pack(out, blk * 16, f, sh, nib)
        p = bt_par[blk, p]


def _check_knobs(beam, block_beam, combos, radius):
    if not (1 <= beam <= 256 and 1 <= block_beam <= 64 and 1 <= combos <= 65
            and 0 <= radius <= 15):
        raise ValueError("bad encoder settings")


def encode(pcm, s1=0, s2=0, beam=DEFAULT_BEAM, block_beam=DEFAULT_BLOCK_BEAM,
           combos=DEFAULT_COMBOS, radius=DEFAULT_RADIUS):
    """Search encoder. Returns ceil(n/28) data blocks (flags byte 0; the
    caller sets flags), the tail padded with zero samples.

    pcm         integer array, values in int16 range
    s1, s2      decoder state before the first block (previous two samples)
    beam        in-block paths per (state, filter, shift)       quality/speed
    block_beam  decoder states carried across block boundaries quality/speed
    combos      (filter, shift) pairs searched per carried state (of 65)
    radius      nibbles tried around the rounded one (1 -> 3 choices)

    beam=1, block_beam=1, combos=65, radius=0 reproduces encode_greedy."""
    _check_knobs(beam, block_beam, combos, radius)
    xp, nblk = _prep(pcm)
    out = np.zeros(nblk * 16, dtype=np.uint8)
    if nblk:
        _encode_core(xp, nblk, np.int64(s1), np.int64(s2), np.int64(block_beam),
                     np.int64(combos), np.int64(beam), np.int64(radius), out)
    return out.tobytes()


def encode_many(pcms, threads=None, **kw):
    """encode() for a list of independent sounds on a thread pool (the numba
    code releases the GIL). Output is identical for any thread count."""
    pcms = list(pcms)
    if threads is None:
        threads = os.cpu_count() or 1
    if threads <= 1 or len(pcms) <= 1:
        return [encode(p, **kw) for p in pcms]
    # longest first for better load balance; results are put back in order
    order = sorted(range(len(pcms)), key=lambda i: -len(pcms[i]))
    res = [None] * len(pcms)
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {i: ex.submit(encode, pcms[i], **kw) for i in order}
        for i, fu in futs.items():
            res[i] = fu.result()
    return res


# --------------------------------------------------------------------------
# game VB layout
# --------------------------------------------------------------------------

ZERO_BLOCK = bytes(16)
FILLER_BLOCK = bytes([0x00, 0x07]) + bytes([0x77]) * 14


def frame_body(data_blocks):
    """Wrap encoded data blocks in the game's VAG layout:

        block 0          16 zero bytes (decoder state is 0 after it)
        data blocks      flags 4 on the first, 1 on the last, 0 elsewhere
                         (a single data block gets 4|1 = 5)
        filler block     00 07 77 77 ... 77

    i.e. the flags column reads (0, 4, 0, ..., 0, 1, 7) as in all game VAGs."""
    d = bytearray(data_blocks)
    if len(d) == 0:
        d = bytearray(16)  # empty sound: one silent block
    n = len(d) // 16
    for k in range(n):
        d[k * 16 + 1] = 0
    d[1] |= 4
    d[(n - 1) * 16 + 1] |= 1
    return ZERO_BLOCK + bytes(d) + FILLER_BLOCK


def vag_body(pcm, **kw):
    """PCM -> game-layout VAG body (see frame_body) using encode(**kw)."""
    return frame_body(encode(pcm, 0, 0, **kw))


def vag_bodies(pcms, threads=None, **kw):
    """vag_body() for many sounds in parallel (deterministic)."""
    return [frame_body(d) for d in encode_many(pcms, threads=threads, s1=0, s2=0, **kw)]


def sse(pcm, blocks, s1=0, s2=0):
    """Integer sum of squared errors of decode(blocks) vs pcm (zero padded)."""
    x = np.asarray(pcm, dtype=np.int64)
    y = decode(blocks, s1, s2).astype(np.int64)
    xp = np.zeros(len(y), np.int64)
    xp[:len(x)] = x
    d = xp - y
    return int(np.dot(d, d))
