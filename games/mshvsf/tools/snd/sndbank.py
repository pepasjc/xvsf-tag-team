"""Full character sound banks for the MSHvSF tag hack (v10): every character in a tag battle, partners included,
gets its own character bank (PLxx_10.A0 section 3) instead of the helper bank HLPxx.SE.

Bank format (.SE, the game's own; the sound upload 0x8007ae24 reads it):
    u16 n, 18 bytes 0, n x 20-byte entries from +0x14, sample data from (n + 1) * 20.
    entry: +0 id, +2 volume, +4 SPU offset / 8 in the bank, +6 ADSR1, +8 ADSR2, +0xa / +0xc voice masks,
           +0xe note, +0xf sample note (rate = 44100 * 2^((note - sample note) / 12)), +0x10 priority, +0x11 bank,
           +0x12 bank bits, +0x13 0.
    sample: one zero block (flags 0), data blocks (flags 4 on the first, 1 on the last; looping sounds 2 ... 3).

What we build here (from the user's disc at build time; nothing derived is committed):
  * the bank REORDERED: the entries and samples a partner needs first, the win-quote voices (ids >= 0x600, only
    ever in the two mains' banks on the stock game, never in a helper bank) last.  A partner uploads the prefix
    (npart entries, dpart sample bytes), a main the whole bank.  Same bytes otherwise: the level-0 bank replaces
    section 3 in our copy of PLxx_10.A0 (same size; relocations only touch sections 1 and 2), so a lossless battle
    reads nothing extra.
  * levels: the SPU cannot hold four stock banks (see docs/SOUND.md), so a battle may need smaller ones.  Level L
    caps every sample at CAPS[L] semitones below 44.1 kHz: a sample played above the cap is resampled down by k
    semitones (tools/snd/resample.py, Kaiser sinc) and re-encoded (tools/snd/adpcm.py, search encoder); the
    sample note of each of its entries is raised by k, so it plays at the same pitch.  Looping samples stay as they
    are.  The game sets only whole semitones (note / sample note bytes), so the steps are exact.

    python sndbank.py stats            sizes per character and level
    python sndbank.py wav C LEVEL ID   decode a sample to work/v10/wav (listening checks)
"""
import os, sys, struct, hashlib, math
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools")]
from snd import adpcm, resample                # XvSF 1.2 tools/snd (integer resampler, search ADPCM encoder)

FILES = os.path.join(GAME, "work", "loader", "files")
CACHE = os.path.join(GAME, "build", "snd")
NCHAR = 0x17
QUOTE = 0x600                       # ids >= 0x600: win-quote voices (table 0x8006f6bc; COMMON 0x62e / 0x630): never requested
                                    # in versus, arcade, boss, ending (traced) - left out of every bank (the stock helper
                                    # banks never had them either)
COMMON = NCHAR                      # bank index of COMMON.SE (bank 0 in the game) in the level tables
# Voices (move shouts, KO screams, name calls, announcer) play on the voice channels 3-5 (entry voice mask & 0x38);
# effects (hits, fireballs ...) on the others.  Levels: (voice cap, effect cap) in semitones below 44.1 kHz, 0 = as on
# the disc.  Effects go down first (to EFLOOR = 43, 3679 Hz), voices only after that.
EFLOOR = 43
LADDER = [(0, 0)] + [(0, e) for e in range(30, EFLOOR + 1)] + [(v, EFLOOR) for v in range(30, 51)]
NL = len(LADDER)
CAPS = [0] + list(range(30, 51))    # (v9 single cap per level, kept for old tools)
FIELDS = ("id", "vol", "off", "adsr1", "adsr2", "vm", "vm2", "note", "snote", "prio", "bank", "bits", "pad")
FMT = "<7H6B"


def a0(c):
    return open(os.path.join(FILES, "PL%02X_10.A0" % c), "rb").read()


def se_source(c):
    """the stock bank bytes: COMMON.SE, or section 3 of PLxx_10.A0"""
    if c == COMMON: return open(os.path.join(FILES, "COMMON.SE"), "rb").read()
    b = a0(c); o, s = sec3(b); return b[o:o + s]


def is_voice(users):
    return any(e["vm"] & 0x38 for e in users)


def sec3(b):
    o, s = struct.unpack_from("<2I", b, 20)
    assert o + s == len(b) or o + s <= len(b)
    return o, s


def parse(b):
    n, = struct.unpack_from("<H", b, 0)
    ents = [dict(zip(FIELDS, struct.unpack_from(FMT, b, 0x14 + 20 * i))) for i in range(n)]
    return ents, b[(n + 1) * 20:]


def pack(ents):
    return b"".join(struct.pack(FMT, *[e[k] for k in FIELDS]) for e in ents)


def sample_blocks(data, off):
    """bytes of the sample at off: zero block + data blocks through the one with the end flag"""
    p = off
    while p < len(data):
        p += 16
        if data[p - 15] & 1: break
    return data[off:p]


def is_loop(blk):
    return any(blk[i + 1] & 2 for i in range(0, len(blk), 16))


def resample_sample(blk, k):
    """non-looping sample (zero block + data blocks) -> k semitones lower rate, same layout"""
    assert blk[:16] == bytes(16) and not is_loop(blk)
    pcm = adpcm.decode(blk[16:])
    num, den = resample.pow2_ratio(k * 128, steps=1536)
    out = resample.resample(pcm, num, den)
    d = bytearray(adpcm.encode(out))
    if not d: d = bytearray(16)
    n = len(d) // 16
    for i in range(n): d[i * 16 + 1] = 0
    d[1] |= 4; d[(n - 1) * 16 + 1] |= 1
    return bytes(16) + bytes(d)


class Bank:
    """one bank at one ladder level: .data (SE file bytes; win quotes last), .nall / .npart entries (all / without the
    quotes), .dall / .dpart sample bytes; .cls[sample offset] = 'V' voice / 'E' effect / 'Q' quote"""
    def __init__(self, c, level, src=None):
        self.c, self.level = c, level
        self.orig = src if src is not None else se_source(c)
        ents, data = parse(self.orig)
        vcap, ecap = LADDER[level]
        offs = []
        for e in ents:
            if e["off"] not in offs: offs.append(e["off"])
        users = {o_: [e for e in ents if e["off"] == o_] for o_ in offs}
        quote_only = {o_ for o_ in offs if all(e["id"] >= QUOTE for e in users[o_])}
        order = [o_ for o_ in offs if o_ not in quote_only] + [o_ for o_ in offs if o_ in quote_only]
        out = bytearray(); newoff = {}; shift = {}
        self.k = {}; self.cls = {}
        for o_ in order:
            blk = sample_blocks(data, o_ * 8)
            cl = "Q" if o_ in quote_only else ("V" if is_voice(users[o_]) else "E")
            cap = vcap if cl in "VQ" else ecap
            r = min(e["snote"] - e["note"] for e in users[o_])         # semitones below 44.1 kHz (highest use)
            k = 0 if (cap == 0 or is_loop(blk)) else max(0, cap - r)
            if k and max(e["snote"] for e in users[o_]) + k > 127: k = 127 - max(e["snote"] for e in users[o_])
            if k: blk = resample_sample(blk, k)
            newoff[o_] = len(out) // 8; shift[o_] = k; self.k[o_] = k; self.cls[o_] = cl
            if o_ in quote_only and not hasattr(self, "dpart"): self.dpart = len(out)
            out += blk
        if not hasattr(self, "dpart"): self.dpart = len(out)
        self.dall = len(out)
        part = [e for e in ents if e["id"] < QUOTE] ; quote = [e for e in ents if e["id"] >= QUOTE]
        new = []
        for e in part + quote:
            e = dict(e); o_ = e["off"]; e["off"] = newoff[o_]; e["snote"] += shift[o_]
            new.append(e)
        self.nall, self.npart = len(new), len(part)
        hdr = struct.pack("<H", len(new)) + bytes(18) + pack(new)
        assert len(hdr) == (len(new) + 1) * 20
        self.data = hdr + bytes(out)
        assert all(e["off"] * 8 < self.dpart for e in new[:self.npart])
        self.ents = new


def build(c, level):
    """cached Bank (pickled bytes)"""
    import pickle
    os.makedirs(CACHE, exist_ok=True)
    src = se_source(c)
    key = hashlib.sha1(src + bytes([level]) + open(__file__, "rb").read()).hexdigest()[:16]
    p = os.path.join(CACHE, ("COMMON" if c == COMMON else f"PL{c:02X}") + f"_L{level:02d}_{key}.pkl")
    if os.path.exists(p):
        return pickle.load(open(p, "rb"))
    bk = Bank(c, level, src)
    del bk.orig
    pickle.dump(bk, open(p, "wb"))
    return bk


def stash_size(c, src=None):
    """bytes the game stashes in SPU for a main (pixel section of the kind-6 set in section 2), 16-aligned"""
    b = src if src is not None else a0(c)
    o2, = struct.unpack_from("<I", b, 12)
    k, x0, x1 = struct.unpack_from("<3I", b, o2)
    assert k == 6
    return (x1 - x0 + 15) & ~15


def patch_a0(c, a):
    """our A0 copy: section 3 = the level-0 (reordered, lossless) bank; same size"""
    o, s = sec3(a)
    bk = build(c, 0)
    assert len(bk.data) <= s, (c, len(bk.data), s)           # the stock bank has unused bytes between samples
    return a[:o] + bk.data + bytes(s - len(bk.data)) + a[o + s:]


def levels(c):
    """[Bank] for every level (same object repeated where the bytes do not change)"""
    out = []
    for L in range(NL):
        bk = build(c, L)
        if out and bk.data == out[-1].data: bk = out[-1]
        out.append(bk)
    return out


def main(a):
    if a[1] == "stats":
        for c in range(NCHAR + 1):
            ls = levels(c)
            print("%02X" % c, "n %d/%d" % (ls[0].nall, ls[0].npart), " ".join("%d/%d" % (b.dall // 1024, b.dpart // 1024) for b in ls))
    if a[1] == "wav":
        import wave, numpy as np
        c, L, i = int(a[2], 16), int(a[3]), int(a[4], 16)
        bk = build(c, L); ents, data = parse(bk.data)
        e = next(e for e in ents if e["id"] == i)
        blk = sample_blocks(data, e["off"] * 8)
        pcm = adpcm.decode(blk[16:])
        rate = round(44100 * 2 ** ((e["note"] - e["snote"]) / 12))
        out = os.path.join(GAME, "work", "v10", "wav"); os.makedirs(out, exist_ok=True)
        p = os.path.join(out, "PL%02X_%03x_L%02d_%dHz.wav" % (c, i, L, rate))
        w = wave.open(p, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.astype("<i2").tobytes()); w.close()
        print(p)


if __name__ == "__main__":
    main(sys.argv)
