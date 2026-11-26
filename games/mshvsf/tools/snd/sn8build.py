"""8 MB voice streaming files (.SN8) for the MSHvSF tag hack 8 MB build (tools/ap8/s8, tools/ap8/snd8.c).

One file per character bank (PLxx_10.A0 section 3, the v10 level-0 bank without the win quotes) and one for COMMON:

    +0  'SN81', nent, bank_off, bank_len, samp, vox_off, vox_len, npf, pf_off      (u32 each)
    bank: the .SE image the game's upload takes (u16 n, 18 bytes 0, n x 20-byte entries, resident samples); `samp`
          = resident sample bytes, 64-rounded.  Resident = effects and looping samples.
    vox:  struct s8vox (tools/ap8/s8/s8.h): u32 n, n x {u32 off, u32 size, u16 bpf, u16 0}, the voice samples (zero
          block + ADPCM blocks, end flag on the last), 64-byte steps.  The entries of a streamed sample carry
          offset 0x8000 | item.
    pf:   u16 item list, the order the battle loader prefetches them into the SPU pool (shortest first).

Voices (entry voice mask & 0x38, not looping) are streamed.  With the user's arcade ROM (--arcade mshvsf.zip, the
sound ROMs mvs.01/.02/.11m/.12m, SHA-1 checked) every voice sample listed in arcvox.json (PS1 sample -> arcade sample
index, start lag, loudness gain[, time scale]: matched once at dev time, games/mshvsf/work/audio8/match2.py / match3.py,
v2: m4/matcht.py time-scale aware spectral matcher over the full 873-entry table) is replaced by
the arcade sample: QSound 8-bit PCM at 12,050 Hz, cut to the PS1 sample's span (start lag, PS1 length + 15 ms fade),
loudness matched to the PS1 sample, resampled up to 12,375 Hz (the game sets rates in whole semitones: 44100 * 2^(-22/12)),
encoded (tools/snd/adpcm.py search encoder).  The entries' sample note drops by the semitones the rate went up, so
pitch and timing stay the PS1's.  Without the ROM every voice streams as the stock sample (same bytes, same rate).
Nothing derived from the ROM is written anywhere but the build cache (build/snd8, never committed) and the disc image.

    python sn8build.py stats [--arcade ZIP]        sizes per bank
    python sn8build.py wav C ITEM [--arcade ZIP]  one item -> work/audio8/wav (listening)
"""
import os, sys, struct, json, hashlib, zipfile, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sndbank as S
from snd import adpcm, resample
import numpy as np

GAME = S.GAME
CACHE = os.path.join(GAME, "build", "snd8")
MATCH = os.path.join(HERE, "arcvox.json")
ROMS = ("mvs.01", "mvs.02", "mvs.11m", "mvs.12m")      # SHA-1 in arcvox.json
RA = 12050                       # arcade voice rate as heard on the PS1 (spectral + waveform match, all characters)
RT = 12375                       # target rate: 44100 * 2^(-22/12)
TAB, NSAMP = 0x6000, 873         # Z80 sample table (u8 bank, u16 start, u16 loop, u16 end, u8 key)
FADE = 180                       # samples at RA (15 ms)
FULL = False                     # --sn8full (user, 1.1 8 MB): the arcade sample to its own end (no cut to the PS1 span)
FADE_FULL = 24                   # samples at RA (2 ms): end fade of a full-length voice (click guard only)


def r64(x): return (x + 63) & ~63


def arcade_samples(zips):
    """[int16 arrays] of the QSound samples, from the user's zip(s) (a clone zip may need its parent)"""
    files = {}
    for z in zips:
        with zipfile.ZipFile(z) as f:
            for n in ROMS:
                if n not in files and n in f.namelist(): files[n] = f.read(n)
    missing = [n for n in ROMS if n not in files]
    if missing: raise SystemExit("arcade sound ROMs missing: %s" % missing)
    want = json.load(open(MATCH))["sha1"]
    for n, d in files.items():
        if hashlib.sha1(d).hexdigest() != want[n]: raise SystemExit("%s: unexpected SHA-1 (not mshvsf sound ROM)" % n)
    z80 = files["mvs.01"] + files["mvs.02"]
    q = bytearray(files["mvs.11m"] + files["mvs.12m"]); q[0::2], q[1::2] = q[1::2], q[0::2][:]
    out = []
    for i in range(NSAMP):
        b, s, l, e, k = struct.unpack_from("<BHHHB", z80, TAB + 8 * i)
        st = b << 16 | s; en = (b + 1) << 16 if e == 0 else b << 16 | e
        out.append(np.frombuffer(bytes(q[st:en]), dtype=np.int8).astype(np.int32) * 256)
    return out


def limiter(x, ceil=30000.0, win=96):
    """look-ahead peak limiter gain (<= 1): the gain each sample needs, minimum over +-win samples (8 ms at RA), then
    a moving average over win: smooth, and never above what any sample in reach needs.  Keeps the PS1 loudness on loud
    voices (Norimaro: gains up to 3.5) without clipping."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    if not len(x): return 1.0
    need = np.minimum(1.0, ceil / np.maximum(np.abs(x), 1.0))
    g = minimum_filter1d(need, 2 * win + 1, mode="nearest")
    return np.minimum(uniform_filter1d(g, win, mode="nearest"), need)


def arcade_voice(a, lag, plen, gain):
    """arcade sample (int, RA) -> PCM at RT for a PS1 sample of plen samples at RA starting `lag` samples in"""
    st = max(0, lag)
    n = len(a) - st if FULL else min(len(a) - st, int(plen) + FADE)
    x = a[st:st + n].astype(np.float64) * gain
    f = min(FADE_FULL if FULL and n == len(a) - st else FADE, n)
    x[n - f:] *= np.linspace(1, 0, f)
    x *= limiter(x)
    x = np.round(x).astype(np.int32)
    return resample.resample(x, RT, RA).astype(np.int32)


def blocks(pcm):
    d = bytearray(adpcm.encode(pcm))
    if not d: d = bytearray(16)
    n = len(d) // 16
    for i in range(n): d[i * 16 + 1] = 0
    d[1] |= 4; d[(n - 1) * 16 + 1] |= 1
    return bytes(16) + bytes(d)


def build(c, arc=None, ahash=""):
    """SN8 bytes of bank c (S.COMMON = COMMON); arc = arcade_samples() or None (stock voices)"""
    os.makedirs(CACHE, exist_ok=True)
    src = S.se_source(c)
    key = hashlib.sha1(src + (ahash + ("full" if FULL and arc else "")).encode() + open(__file__, "rb").read() + open(MATCH, "rb").read()).hexdigest()[:16]
    p = os.path.join(CACHE, ("COMMON" if c == S.COMMON else "PL%02X" % c) + "_" + key + ".sn8")
    if os.path.exists(p): return open(p, "rb").read()
    match = json.load(open(MATCH))["voices"] if arc else {}
    bk = S.build(c, 0)
    ents, data = S.parse(bk.data)
    ents = ents[:bk.npart]                                 # v10: no win quotes
    offs = []
    for e in ents:
        if e["off"] not in offs: offs.append(e["off"])
    res = bytearray(); items = []; newoff = {}; dsemi = {}
    tag = "COM" if c == S.COMMON else "%02X" % c
    for o in offs:
        us = [e for e in ents if e["off"] == o]
        blk = S.sample_blocks(data, o * 8)
        if S.is_voice(us) and not S.is_loop(blk):
            m = match.get("%s:%x" % (tag, o))
            d = 0
            rp = max(44100 * 2 ** ((e["note"] - e["snote"]) / 12) for e in us)
            if m:
                sn = min(e["snote"] - e["note"] for e in us)                  # semitones below 44.1 kHz of the fastest use
                d = sn - 22
                assert d > 0 and min(e["snote"] for e in us) - d >= 0
                tsc = m[3] if len(m) > 3 else 1.0                     # v2: PS1 take time-compressed by tsc (arcade dur / PS1 dur)
                pcm = arcade_voice(arc[m[0]], m[1], len(adpcm.decode(blk[16:])) * RA / rp * tsc, m[2])
                blk = blocks(pcm)
                rp = RT
            dsemi[o] = d
            newoff[o] = 0x8000 | len(items)
            items.append((blk, int(rp * 256 / 1680) + 1))
        else:
            newoff[o] = len(res) // 8; dsemi[o] = 0
            res += blk
    out_ents = []
    for e in ents:
        e = dict(e); o = e["off"]; e["off"] = newoff[o]; e["snote"] -= dsemi[o]; out_ents.append(e)
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


def all_files(zips=None, full=False):
    """{bank: SN8 bytes} for chars 0..0x16 and COMMON (S.COMMON); arcade voices when zips are given (full: --sn8full)"""
    global FULL
    FULL = full
    arc = arcade_samples(zips) if zips else None
    ah = "arc" if arc else ""
    return {c: build(c, arc, ah) for c in list(range(S.NCHAR)) + [S.COMMON]}


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
        for c, b in fs.items():
            print("COM" if c == S.COMMON else "%02X" % c, info(b))
        print("max char file", max(len(b) for c, b in fs.items() if c != S.COMMON))
    if a[1] == "wav":
        import wave
        c = S.COMMON if a[2] == "COM" else int(a[2], 16); i = int(a[3])
        fs = build(c, arcade_samples(zips) if zips else None, "arc" if zips else "")
        m, nent, bo, bl, samp, vo, vl, npf, pfo = struct.unpack_from("<4s8I", fs)
        off, size, bpf, _ = struct.unpack_from("<2I2H", fs, vo + 4 + 12 * i)
        blk = fs[vo + off: vo + off + size]
        pcm = adpcm.decode(blk[16:])
        rate = round(bpf * 1680 / 256)
        out = os.path.join(GAME, "work", "audio8", "wav"); os.makedirs(out, exist_ok=True)
        p = os.path.join(out, "%s_%d_%s.wav" % (a[2], i, "arc" if zips else "stock"))
        w = wave.open(p, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.asarray(pcm).astype("<i2").tobytes()); w.close(); print(p)


if __name__ == "__main__":
    main(sys.argv)
