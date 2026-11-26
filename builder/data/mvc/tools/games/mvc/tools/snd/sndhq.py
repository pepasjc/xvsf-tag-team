"""--voicehq sample pipeline for the MvC sound ladder (voice worker, 2026-11-23; numbers in docs/SOUND.md "Voice HQ").

The stock ladder (sndbank.Bank) resamples a sample k semitones lower with the band-limited resampler and re-encodes
it.  Two things made the low levels sound worse than the bandwidth alone explains:

* the SPU's 4-tap gaussian interpolation (gauss.py) is a low-pass relative to the sample rate: -2.1 dB at 0.2 fs,
  -3.3 dB at 0.25 fs, -8.5 dB at 0.4 fs.  At the stock 7-12 kHz that is above the voice formants; at 3-4.6 kHz it eats
  the whole 0.8-2 kHz presence band (muffled);
* together with the lost band the voices came out 2-5 dB quieter than stock (RMS of the played sound).

Here, for every resampled sample: resample (same resampler) -> pre-compensation FIR at the new rate whose response is
Gs(f / fs0) / Gs(f / fs1) (= the stock playback response divided by the new one, capped CAP_DB) -> loudness makeup
(the played sound's RMS back to the stock one's, at most MAKEUP_DB; inside the sample as far as the peak allows
(<= max(stock peak, 30000)), the rest returned as an entry volume factor) -> ADPCM (same beam encoder).
Everything is deterministic integer / float64 math on fixed inputs (cached per level like the stock banks).
"""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
from tools.snd import adpcm, resample          # noqa: E402
from gauss import GAUSS                         # noqa: E402

CAP_DB = 10.0
MAKEUP_DB = 4.0
NT = 31
G = np.array(GAUSS, dtype=np.int64)

_h = np.zeros(1024)
for _p in range(256):
    for _k, _v in enumerate((GAUSS[255 - _p], GAUSS[511 - _p], GAUSS[256 + _p], GAUSS[_p])):
        _h[(3 - _k) * 256 + _p] = _v
_NF = 1 << 14
_H = np.abs(np.fft.rfft(_h, _NF * 256)); _H /= _H[0]


def gs(fn):
    """gaussian interpolation magnitude at fn = f / fs (0 .. 0.5)"""
    return np.interp(np.asarray(fn, dtype=np.float64), np.arange(len(_H)) / _NF, _H)


def design(fs0, fs1, cap_db=CAP_DB, nt=NT, shelf_db=0.0):
    """stock playback / new playback (capped), times a high shelf of shelf_db (0 below 0.15 fs1, full from 0.35 fs1)"""
    nf = 512; fn = np.arange(nf + 1) / (2 * nf)
    t = gs(np.minimum(fn * fs1 / fs0, 0.5)) / np.maximum(gs(fn), 1e-6)
    if shelf_db:
        w = np.clip((fn - 0.15) / 0.20, 0.0, 1.0); w = w * w * (3 - 2 * w)
        t = t * 10 ** (shelf_db * w / 20)
    t = np.minimum(t, 10 ** (cap_db / 20))
    t[fn > 0.47] = t[fn <= 0.47][-1]
    h = np.fft.irfft(t, 2 * nf)
    h = np.roll(h, nt // 2)[:nt] * np.kaiser(nt, 6)
    return h / h.sum() * t[0]


def play_pcm(pcm, fs):
    """SPU playback model: pcm at rate fs -> 44.1 kHz (pitch = round(4096 fs / 44100), gaussian interpolation)"""
    step = max(1, int(round(4096 * fs / 44100)))
    x = np.concatenate([np.zeros(3, np.int64), np.asarray(pcm, np.int64), np.zeros(1, np.int64)])
    n = (len(pcm) * 4096) // step
    c = np.arange(n, dtype=np.int64) * step
    p = c >> 12; i = (c >> 4) & 0xff
    out = (G[0xff - i] * x[p] >> 15) + (G[0x1ff - i] * x[p + 1] >> 15) + (G[0x100 + i] * x[p + 2] >> 15) + (G[i] * x[p + 3] >> 15)
    return np.clip(out, -32768, 32767)


def rms(x):
    x = np.asarray(x, np.float64)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def resample_hq(blk, k, fs0, cap_db=CAP_DB, makeup_db=MAKEUP_DB):
    """non-looping sample (zero block + data blocks) -> (k semitones lower, same layout; entry volume factor >= 1)"""
    assert blk[:16] == bytes(16)
    src = adpcm.decode(blk[16:]).astype(np.int64)
    num, den = resample.pow2_ratio(k * 128, steps=1536)
    pcm = resample.resample(src, num, den).astype(np.float64)
    fs1 = fs0 * 2 ** (-k / 12)
    h = design(fs0, fs1, cap_db)
    y = np.convolve(pcm, h)[NT // 2:NT // 2 + len(pcm)]
    lim = float(min(32000, max(int(np.abs(src).max()) if len(src) else 0, 30000)))
    r0 = rms(play_pcm(src, fs0)); r1 = rms(play_pcm(np.round(y), fs1))
    g = min(10 ** (makeup_db / 20), r0 / r1) if r1 > 0 else 1.0
    g = max(g, 1.0)
    pk = float(np.abs(y).max()) if len(y) else 0.0
    gin = min(g, lim / pk) if pk > 0 else 1.0                 # inside the sample (may be < 1: EQ peak guard)
    y = np.round(y * gin)
    volf = g / gin if gin < g else 1.0
    d = bytearray(adpcm.encode(np.clip(y, -32768, 32767).astype(np.int64)))
    if not d: d = bytearray(16)
    n = len(d) // 16
    for i in range(n): d[i * 16 + 1] = 0
    d[1] |= 4; d[(n - 1) * 16 + 1] |= 1
    return bytes(16) + bytes(d), volf


# --voicevol (voice 3, 2026-11-23): voices louder than stock + brighter
FIXED_DB = 3.0               # (voice 3, user 2026-11-23: one modest setting) played RMS over stock, --voicehq
VOICE_GAIN_DB = 6.0           # played RMS target over stock (the EX row scales the entry volume back: NORMAL -6, +3 -3, +6 0)
SHELF_DB = 3.0                # extra high shelf on resampled voices (0.15 -> 0.35 fs1)
VCAP_DB = 14.0
CEIL = 30000.0
LIM_DB = 8.0
LIM = 10 ** (LIM_DB / 20)


def limit(y, ceil=CEIL, fs=11025):
    """look-ahead peak limiter: gain envelope = running min of ceil/|y| over +-1.5 ms, release 10 ms (no clipping)"""
    y = np.asarray(y, np.float64)
    if not len(y): return y
    g = np.minimum(1.0, ceil / np.maximum(np.abs(y), 1e-9))
    n = max(1, int(fs * 0.0015))
    from numpy.lib.stride_tricks import sliding_window_view
    gp = np.pad(g, (n, n), mode="edge")
    gm = sliding_window_view(gp, 2 * n + 1).min(axis=1)
    a = np.exp(-1.0 / max(1.0, fs * 0.010))
    env = np.empty_like(gm); cur = 1.0
    for i in range(len(gm)):                              # instant attack (the window looks ahead), slow release
        cur = gm[i] if gm[i] < cur else a * cur + (1 - a) * gm[i]
        if cur > gm[i]: cur = gm[i]
        env[i] = cur
    return y * env


def voice_hq(blk, k, fs0, gain_db=VOICE_GAIN_DB, shelf_db=SHELF_DB):
    """voice sample (zero block + data blocks, non-looping) -> (k semitones lower (k may be 0), entry volume factor):
    resample, stock-matching EQ + high shelf (k > 0), played RMS -> stock * gain_db, in the sample up to CEIL through the
    limiter (at most LIM_DB of limiting), the rest as the entry volume factor"""
    assert blk[:16] == bytes(16)
    src = adpcm.decode(blk[16:]).astype(np.int64)
    fs1 = fs0 * 2 ** (-k / 12)
    if k:
        num, den = resample.pow2_ratio(k * 128, steps=1536)
        pcm = resample.resample(src, num, den).astype(np.float64)
        h = design(fs0, fs1, VCAP_DB, shelf_db=shelf_db)
        y = np.convolve(pcm, h)[NT // 2:NT // 2 + len(pcm)]
    else:
        y = src.astype(np.float64)
    r0 = rms(play_pcm(src, fs0)); r1 = rms(play_pcm(np.round(y), fs1))
    g = (r0 / r1 if r1 > 0 else 1.0) * 10 ** (gain_db / 20)
    pk = float(np.abs(y).max()) if len(y) else 0.0
    gin = min(g, LIM * CEIL / pk) if pk > 0 else 1.0        # the limiter takes at most LIM_DB off the peaks
    z = limit(y * gin, CEIL, int(fs1))
    r2 = rms(play_pcm(np.round(z), fs1))
    volf = (r0 * 10 ** (gain_db / 20)) / r2 if r2 > 0 else 1.0
    d = bytearray(adpcm.encode(np.clip(np.round(z), -32768, 32767).astype(np.int64)))
    if not d: d = bytearray(16)
    n = len(d) // 16
    for i in range(n): d[i * 16 + 1] = 0
    d[1] |= 4; d[(n - 1) * 16 + 1] |= 1
    return bytes(16) + bytes(d), volf
