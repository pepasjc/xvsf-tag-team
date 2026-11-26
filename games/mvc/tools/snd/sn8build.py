"""8 MB voice streaming files (.SN8) of the MvC tag hack 8 MB build (tools/ap8: s8.c engine, snd8.inc battle sound).
Port of games/mshvsf/tools/snd/sn8build.py (same .SE engine and file layout).

One file per bank (sndbank.bank_names(): COMMON, the 21 characters' CHRxx_0.SE, Mega Man's six variants CHR101-106),
built from the 1.0 level-0 bank (sndbank.Bank(name, 0): lossless, --voicehq as the 2 MB build has it):

    +0  'SN81', nent, bank_off, bank_len, samp, vox_off, vox_len, npf, pf_off      (u32 each)
    bank: the .SE image (u16 n, 18 bytes 0, n x 20-byte entries, resident samples); `samp` = resident sample bytes,
          64-rounded.  Resident = effects and looping samples.  Every entry's spare byte 0x13 = 0xc1 (S8_MARK).
    vox:  struct s8vox: u32 n, n x {u32 off, u32 size, u16 bpf, u16 0}, the voice samples (zero block + ADPCM blocks,
          end flag on the last), 64-byte steps.  The entries of a streamed sample carry offset 0x8000 | item.
    pf:   u16 item list, the order the battle loader prefetches them into the SPU pool (shortest first).

Voices (sndbank.is_voice, not looping) are streamed.  With the user's arcade ROM (--arcade mvsc.zip: sound ROMs
mvc.01/.02/.11m/.12m, SHA-1 checked) every voice sample listed in arcvox.json (PS1 sample -> arcade sample index, start
lag, loudness gain: matched once at dev time, games/mvc/work/audio8/m) becomes the arcade sample: QSound 8-bit PCM at
11,720 Hz, from the match lag to its own end (user: FULL arcade voice length; 2 ms end fade), loudness matched to the
PS1 sample (look-ahead limiter), resampled to 11,681 Hz (44100 * 2^(-23/12): the game sets rates in whole semitones),
encoded (tools/snd/adpcm.py search encoder); the entries' sample note drops by the semitones the rate went up, so pitch
and timing stay the PS1's.  Without the ROM every voice streams as the 1.0 level-0 sample.  Nothing derived from the
ROM is written anywhere but the build cache (build/snd8, never committed) and the disc image.

    python sn8build.py stats [--arcade ZIP]
    python sn8build.py wav BANK ITEM [--arcade ZIP]     one item -> work/audio8/wav (listening)
"""
import os, sys, struct, json, hashlib, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sndbank as S
ROOT = S.ROOT
sys.path.insert(0, os.path.join(ROOT, "tools"))
from snd import adpcm, resample
import numpy as np

GAME = S.GAME
CACHE = os.path.join(GAME, "build", "snd8v2")
MATCH = os.environ.get("SN8MATCH") or os.path.join(HERE, "arcvox.json")   # voice v2 (2026-11-25: promoted from work/mvc8r, arcvox.json = arcvox2.json)
ROMS = ("mvc.01", "mvc.02", "mvc.11m", "mvc.12m")
RA = 11720                       # arcade voice rate as heard on the PS1 (waveform match: rate factor 1.000)
RT = 11681                       # 44100 * 2^(-23/12)
RT_SEMI = 23
TAB, NSAMP = 0x5000, 818         # Z80 sample table (u8 bank, u16 start, u16 loop, u16 end, u8 key)
FADE_FULL = 24                   # samples at RA (2 ms): end fade of a full-length voice (click guard)
MARK = 0xc1                      # entry byte 0x13: ours (s8_play streams marked entries with offset bit 15 only)


def r64(x): return (x + 63) & ~63


def arcade_samples(zips):
    files = {}
    for z in zips:
        with zipfile.ZipFile(z) as f:
            for n in ROMS:
                if n not in files and n in f.namelist(): files[n] = f.read(n)
    missing = [n for n in ROMS if n not in files]
    if missing: raise SystemExit("arcade sound ROMs missing: %s" % missing)
    want = json.load(open(MATCH))["sha1"]
    for n, d in files.items():
        if hashlib.sha1(d).hexdigest() != want[n]: raise SystemExit("%s: unexpected SHA-1 (not the mvsc sound ROM)" % n)
    z80 = files["mvc.01"] + files["mvc.02"]
    q = bytearray(files["mvc.11m"] + files["mvc.12m"]); q[0::2], q[1::2] = q[1::2], q[0::2][:]
    out = []
    for i in range(NSAMP):
        b, s, l, e, k = struct.unpack_from("<BHHHB", z80, TAB + 8 * i)
        st = b << 16 | s; en = (b + 1) << 16 if e == 0 else b << 16 | e
        out.append(np.frombuffer(bytes(q[st:en]), dtype=np.int8).astype(np.int32) * 256)
    return out


def limiter(x, ceil=30000.0, win=96):
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    if not len(x): return 1.0
    need = np.minimum(1.0, ceil / np.maximum(np.abs(x), 1.0))
    g = minimum_filter1d(need, 2 * win + 1, mode="nearest")
    return np.minimum(uniform_filter1d(g, win, mode="nearest"), need)


FADE = 176                       # samples at RA (15 ms): end fade of a voice cut to the PS1 span
LONG = 1.5                       # an arcade sample > 1.5 x the PS1 voice from the match on holds more than this line (the
                                 # PS1 cut a longer take): cut it to the PS1 span (+15 ms) instead of its full length


def arcade_voice(a, lag, gain, ra=RA, rt=RT, plen=None, ref=None):
    """arcade sample (int, played at ra) from `lag` to its end (or to the PS1 span when it is much longer) -> PCM at rt;
    ref = the PS1 sample (PCM at rt's grid source rate rp, as numpy) for the loudness match (RMS over the PS1 span)"""
    st = max(0, lag)
    n = len(a) - st
    cut = plen is not None and n > LONG * plen
    if cut: n = int(plen) + FADE
    x = a[st:st + n].astype(np.float64) * gain
    f = min(FADE if cut else FADE_FULL, len(x))
    if f: x[len(x) - f:] *= np.linspace(1, 0, f)
    if ref is not None and plen:                         # loudness = the shipped PS1 voice (1.0: --voicehq makeup)
        k = min(len(x), int(plen))
        ra_rms = np.sqrt((x[:k] ** 2).mean()) if k else 0
        if ra_rms > 1: x *= min(3.0, max(0.5, ref / ra_rms))
    x *= limiter(x)
    x = np.round(x).astype(np.int32)
    return resample.resample(x, int(round(rt)), int(round(ra))).astype(np.int32)


def blocks(pcm):
    d = bytearray(adpcm.encode(pcm))
    if not d: d = bytearray(16)
    n = len(d) // 16
    for i in range(n): d[i * 16 + 1] = 0
    d[1] |= 4; d[(n - 1) * 16 + 1] |= 1
    return bytes(16) + bytes(d)


def build(name, arc=None, ahash=""):
    """SN8 bytes of bank `name` (sndbank.bank_names()); arc = arcade_samples() or None (stock voices)"""
    os.makedirs(CACHE, exist_ok=True)
    src = S.se_source(name)
    key = hashlib.sha1(src + (ahash + ("HQ" if S.VOICEHQ else "")).encode() + open(__file__, "rb").read()
                       + (open(MATCH, "rb").read() if arc else b"")).hexdigest()[:16]
    p = os.path.join(CACHE, name + "_" + key + ".sn8")
    if os.path.exists(p): return open(p, "rb").read()
    match = json.load(open(MATCH))["voices"] if arc else {}
    bk = S.build(name, 0)
    ents, data = S.parse(bk.data)
    offs = []
    for e in ents:
        if e["off"] not in offs: offs.append(e["off"])
    # stock sample offsets of the level-0 bank (matching keys are stock offsets: level 0 keeps the stock order)
    sents, sdata = S.parse(src)
    soffs = []
    for e in sents:
        if e["off"] not in soffs: soffs.append(e["off"])
    assert len(soffs) == len(offs), name
    stock_of = dict(zip(offs, soffs))
    res = bytearray(); items = []; newoff = {}; dsemi = {}
    for o in offs:
        us = [e for e in ents if e["off"] == o]
        blk = S.sample_blocks(data, o * 8)
        if S.is_voice(name, us) and not S.is_loop(blk):
            m = match.get("%s:%x" % (name, stock_of[o]))
            d = 0
            rp = max(44100 * 2 ** ((e["note"] - e["snote"]) / 12) for e in us)
            if m:
                ra = m[3] if len(m) > 3 else RA
                semi = int(round(12 * np.log2(44100 / ra)))       # target: the semitone grid rate nearest the arcade rate
                rt = 44100 * 2 ** (-semi / 12)
                sn = min(e["snote"] - e["note"] for e in us)      # semitones below 44.1 kHz of the fastest use
                d = sn - semi
                if d > 0 and min(e["snote"] for e in us) - d >= 0:
                    ps = np.asarray(adpcm.decode(blk[16:]), dtype=np.float64)
                    tsc = m[4] if len(m) > 4 else 1.0                 # v2: PS1 take time-compressed by tsc (Capcom side)
                    blk = blocks(arcade_voice(arc[m[0]], m[1], m[2], ra, rt, len(ps) * ra / rp * tsc,
                                              float(np.sqrt((ps ** 2).mean())) if len(ps) else None))
                    rp = rt
                else:
                    d = 0                                            # PS1 sample already at / above the arcade rate
            dsemi[o] = d
            newoff[o] = 0x8000 | len(items)
            items.append((blk, int(rp * 256 / 1680) + 1))
        else:
            newoff[o] = len(res) // 8; dsemi[o] = 0
            res += blk
    out_ents = []
    for e in ents:
        e = dict(e); o = e["off"]; e["off"] = newoff[o]; e["snote"] -= dsemi[o]; e["pad"] = MARK; out_ents.append(e)
    bank = struct.pack("<H", len(out_ents)) + bytes(18) + S.pack(out_ents) + bytes(res)
    samp = r64(len(res))
    nv = len(items)
    hdr_len = r64(4 + 12 * nv)
    vdata = bytearray(); recs = b""
    for blk, bpf in items:
        recs += struct.pack("<2I2H", hdr_len + len(vdata), r64(len(blk)), bpf, 0)
        vdata += blk + bytes(r64(len(blk)) - len(blk))
    vox = struct.pack("<I", nv) + recs
    vox += bytes(hdr_len - len(vox)) + bytes(vdata)
    pf = sorted(range(nv), key=lambda i: len(items[i][0]))
    pfb = struct.pack("<%dH" % nv, *pf)
    bank_off = 64
    vox_off = r64(bank_off + len(bank))
    pf_off = vox_off + len(vox)
    out = struct.pack("<4s8I", b"SN81", len(out_ents), bank_off, len(bank), samp, vox_off, len(vox), nv, pf_off)
    out += bytes(bank_off - len(out)) + bank
    out += bytes(vox_off - len(out)) + vox + pfb
    out += bytes(-len(out) % 4)
    open(p, "wb").write(out)
    return out


def all_files(zips=None):
    """{bank name: SN8 bytes}; arcade voices when zips are given"""
    arc = arcade_samples(zips) if zips else None
    return {n: build(n, arc, "arc" if arc else "") for n in S.bank_names()}


def info(b):
    m, nent, bo, bl, samp, vo, vl, npf, pfo = struct.unpack_from("<4s8I", b)
    return dict(nent=nent, samp=samp, vox=vl, size=len(b))


def main(a):
    zips = []
    if "--arcade" in a:
        i = a.index("--arcade") + 1
        while i < len(a) and not a[i].startswith("--"): zips.append(a[i]); i += 1
    if a[1] == "stats":
        fs = all_files(zips or None)
        for n, b in fs.items(): print(n, info(b))
        print("max char file", max(len(b) for n, b in fs.items() if n != S.COMMON), "COMMON", len(fs[S.COMMON]))
    if a[1] == "wav":
        import wave
        name, i = a[2], int(a[3])
        fs = build(name, arcade_samples(zips) if zips else None, "arc" if zips else "")
        m, nent, bo, bl, samp, vo, vl, npf, pfo = struct.unpack_from("<4s8I", fs)
        off, size, bpf, _ = struct.unpack_from("<2I2H", fs, vo + 4 + 12 * i)
        blk = fs[vo + off: vo + off + size]
        pcm = adpcm.decode(blk[16:])
        rate = round(bpf * 1680 / 256)
        out = os.path.join(GAME, "work", "audio8", "wav"); os.makedirs(out, exist_ok=True)
        p = os.path.join(out, "%s_%d_%s.wav" % (name, i, "arc" if zips else "stock"))
        w = wave.open(p, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.asarray(pcm).astype("<i2").tobytes()); w.close(); print(p)


if __name__ == "__main__":
    main(sys.argv)
