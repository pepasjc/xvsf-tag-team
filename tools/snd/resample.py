"""Band-limited integer resampler for PCM sound effects.

resample(pcm, num, den) changes the sample rate by the exact rational ratio
out_rate / in_rate = num / den, e.g. to bake a pitch change into a sample:
playing the result at the original rate sounds lower by den/num.

Method: windowed-sinc interpolation with a Kaiser window, evaluated from a
committed integer table (sinc_table.TABLE) of one half of the prototype
low-pass. The prototype is defined in units of the *output* sample period:

    h(u) = sinc(CUTOFF * u) * kaiser(u / HALF_WIDTH, BETA),  |u| < HALF_WIDTH

so it passes up to CUTOFF * Nyquist of the lower of the two rates; with
CUTOFF 0.95, HALF_WIDTH 64 and BETA 10 the passband is flat (< 0.001 dB)
to 0.9 Nyquist, -6 dB at 0.95 and >= ~95 dB down from 1.0 Nyquist on.
The table holds h at u = i / PHASES for i = 0 .. HALF_WIDTH * PHASES, scaled
to TABLE[0] = 2**22; values between entries are linearly interpolated with a
15-bit weight.

Output sample j sits at input position t = j * den / num (sample 0 of both
streams coincide). For every input sample k within reach the tap weight is
h((t - k) * min(num, den) / den) for downsampling (h(t - k) for upsampling);
input outside [0, n) counts as 0. The output is the weighted sum divided by
the sum of all tap weights of that output (exact unity DC gain at every
phase), rounded to nearest and clamped to int16. Output length is
ceil(n * num / den), so the duration is preserved.

Everything on the data path is integer arithmetic. All positions are tracked
incrementally as (quotient, remainder) pairs, and with den < 2**36 every
intermediate stays below 2**53 (a JavaScript port can use plain Numbers;
divisions must be exact integer floor divisions, not float divide + floor).
The table was generated once with float math (see _generate_table) and is
committed as integer literals; that table is the definition.
"""
from fractions import Fraction
from math import gcd

import numpy as np

from .sinc_table import TABLE, PHASES, HALF_WIDTH, CUTOFF, BETA, SCALE

try:
    import numba as _nb

    def _jit(f):
        return _nb.njit(cache=True, nogil=True)(f)
except ImportError:  # pure-Python fallback, identical results
    def _jit(f):
        return f

_H = np.array(TABLE, dtype=np.int64)
_NTAB = HALF_WIDTH * PHASES          # last valid interpolation base index + 1
assert len(_H) == _NTAB + 1 and _H[_NTAB] == 0

WBITS = 15                            # interpolation weight precision
MAX_DEN_BITS = 36


@_jit
def _resample_core(x, n, num, den, D, nout, H, NTAB, P, out):
    # reciprocal for the interpolation weight: w = rem * inv >> 32 ~ rem/D*2^15
    inv = (np.int64(1) << (WBITS + 32)) // D
    # output position step in input samples: den/num = dq + dr/num
    dq = den // num
    dr = den - dq * num
    # tap step in table units: num*P/D = tq + tr/D
    tq = (num * P) // D
    tr = num * P - tq * D
    ip = np.int64(0)
    fr = np.int64(0)
    for j in range(nout):
        acc = np.int64(0)
        ssum = np.int64(0)
        # taps at and left of t: k = ip - m, distance (m*num + fr)/num
        a = fr * P
        i = a // D
        r = a - i * D
        k = ip
        while i < NTAB:
            w = (r * inv) >> 32
            h0 = H[i]
            c = h0 + (((H[i + 1] - h0) * w) >> WBITS)
            ssum += c
            if 0 <= k < n:
                acc += x[k] * c
            k -= 1
            i += tq
            r += tr
            if r >= D:
                r -= D
                i += 1
        # taps right of t: k = ip + m, distance (m*num - fr)/num, m >= 1
        a = (num - fr) * P
        i = a // D
        r = a - i * D
        k = ip + 1
        while i < NTAB:
            w = (r * inv) >> 32
            h0 = H[i]
            c = h0 + (((H[i + 1] - h0) * w) >> WBITS)
            ssum += c
            if 0 <= k < n:
                acc += x[k] * c
            k += 1
            i += tq
            r += tr
            if r >= D:
                r -= D
                i += 1
        y = (2 * acc + ssum) // (2 * ssum)
        if y > 32767:
            y = 32767
        elif y < -32768:
            y = -32768
        out[j] = y
        # advance t by den/num
        ip += dq
        fr += dr
        if fr >= num:
            fr -= num
            ip += 1


def _norm_ratio(num, den):
    if den is None:
        fr = Fraction(num)
        num, den = fr.numerator, fr.denominator
    num, den = int(num), int(den)
    if num <= 0 or den <= 0:
        raise ValueError("ratio must be positive")
    g = gcd(num, den)
    num //= g
    den //= g
    if max(num, den) >= 1 << MAX_DEN_BITS:
        raise ValueError("ratio terms too large (reduce to < 2**%d)" % MAX_DEN_BITS)
    return num, den


def out_length(n, num, den=None):
    """Number of output samples: ceil(n * num / den)."""
    num, den = _norm_ratio(num, den)
    return (n * num + den - 1) // den


def resample(pcm, num, den=None):
    """Resample int16 PCM by out_rate/in_rate = num/den (positive integers,
    any size up to 2**36 after reduction; or pass a Fraction as num and
    leave den None). Returns an int16 array of ceil(n*num/den) samples.
    num == den returns a copy of the input."""
    num, den = _norm_ratio(num, den)
    x = np.asarray(pcm)
    if x.dtype.kind not in "iu":
        raise TypeError("pcm must be an integer array")
    if num == den:
        return x.astype(np.int16).copy()
    x = x.astype(np.int64)
    n = len(x)
    nout = (n * num + den - 1) // den
    out = np.zeros(nout, dtype=np.int64)
    if nout:
        D = max(num, den)
        _resample_core(x, np.int64(n), np.int64(num), np.int64(den), np.int64(D),
                       np.int64(nout), _H, np.int64(_NTAB), np.int64(PHASES), out)
    return out.astype(np.int16)


def pow2_ratio(k, steps=1536, bits=32):
    """Exact integer (num, den) for the ratio 2**(-k/steps), k >= 0:
    den = 2**bits, num = floor(2**bits * 2**(-k/steps)) (computed with exact
    big-integer arithmetic, so it is the same on every platform). Use it as
    resample(pcm, *pow2_ratio(k)) to lower the pitch by k/steps octaves."""
    if k < 0:
        raise ValueError("k must be >= 0 (downsampling)")
    den = 1 << bits
    if k == 0:
        return den, den
    # largest y with y**steps <= 2**(bits*steps - k)
    target = 1 << (bits * steps - k)
    lo, hi = 0, den
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if mid ** steps <= target:
            lo = mid
        else:
            hi = mid - 1
    return lo, den


def _generate_table():
    """Regenerate the prototype table with float math (NOT used at run time;
    sinc_table.py holds the committed integer result). Kept for reference."""
    n = HALF_WIDTH * PHASES
    u = np.arange(n + 1) / PHASES
    win = np.i0(BETA * np.sqrt(np.clip(1.0 - (u / HALF_WIDTH) ** 2, 0.0, 1.0))) / np.i0(BETA)
    h = np.sinc(CUTOFF * u) * win
    t = np.round(h * SCALE).astype(np.int64)
    t[n] = 0
    return [int(v) for v in t]
