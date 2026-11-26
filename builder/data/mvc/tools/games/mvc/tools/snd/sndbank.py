"""Full character sound banks for the MvC tag hack (SLUS-01059) - port of games/mshvsf/tools/snd/sndbank.py.

The .SE format and the engine are the MSHvSF ones (entry: +0 id, +2 volume, +4 SPU offset / 8, +6 / +8 ADSR, +0xa /
+0xc voice masks, +0xe note, +0xf sample note, +0x10 priority, +0x11 bank, +0x12 bank bits).  MvC differences:
banks are CHRxx_0.SE files (Mega Man: six variants CHR101-106, one chosen at random per battle) and COMMON.SE (bank 0,
loaded ONCE at boot, never reloaded); entries are reached through a u8 index table (0x80089bb8[id] = slot + 1) into
the 250-slot table 0x800887d8; no win-quote ids (all ids < 0x501).

Levels (same ladder as MSHvSF v10snd): (voice cap, effect cap) in semitones below 44.1 kHz, 0 = as on the disc;
effects go down first (to EFLOOR), then voices.  A sample is a voice when one of its entries plays on a voice channel
(voice mask & VOICEMASK); COMMON's ids below 0x100 and from 0x45d on (announcer / menu sounds) count as voices too, so
they stay lossless until the voices go down.  The COMMON bank keeps its stock entry order (its table slots / id
indices stay what the boot set up); character banks too (order does not matter there).

    python sndbank.py stats      sizes per bank and level
"""
import os, sys, struct, hashlib, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
_spec = importlib.util.spec_from_file_location("msh_sndbank", os.path.join(ROOT, "games", "mshvsf", "tools", "snd", "sndbank.py"))
M = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(M)
parse, pack, sample_blocks, is_loop, resample_sample, FIELDS = M.parse, M.pack, M.sample_blocks, M.is_loop, M.resample_sample, M.FIELDS

FILES = os.path.join(GAME, "work", "snd", "disc")          # extracted stock files (sndbuild.extract fills it from the disc)
CACHE = os.path.join(GAME, "build", "snd")
COMMON = "COMMON"
VOICEMASK = 0x1f8
EFLOOR = 43
LADDER = [(0, 0)] + [(0, e) for e in range(30, EFLOOR + 1)] + [(v, EFLOOR) for v in range(30, 51)]
NL = len(LADDER)
CHARS = list(range(1, 0x10)) + list(range(0x11, 0x17))     # 0x10 Mega Man: banks "101".."106"
MM = ["10%d" % k for k in range(1, 7)]
# --voicehq (voice worker 2026-11-23, sndhq.py): resampled samples get the gaussian pre-compensation + loudness makeup.
# Off = the stock ladder files byte for byte.
VOICEHQ = "--voicehq" in sys.argv or os.environ.get("VOICEHQ") == "1"
VOICEVOL = VOICEHQ and ("--voicevol" in sys.argv or os.environ.get("VOICEVOL") == "1")   # (voice 3) needs snd.c -DVOLROW
if VOICEHQ:
    sys.path.insert(0, HERE)
    import sndhq as HQ


def bank_names():
    return [COMMON] + ["%02X" % c for c in CHARS] + MM


def se_source(name):
    f = "COMMON.SE" if name == COMMON else "CHR%s_0.SE" % name
    return open(os.path.join(FILES, f), "rb").read()


def is_voice(name, users):
    if name == COMMON and all(e["id"] < 0x100 or e["id"] >= 0x45d for e in users): return True
    return any((e["vm"] & VOICEMASK) and e["vm"] != 0xffff for e in users)


class Bank:
    """one bank at one level: .data (SE bytes, stock entry order), .n entries, .dsize sample bytes, .cls per sample"""
    def __init__(self, name, level, src=None):
        self.name, self.level = name, level
        src = src if src is not None else se_source(name)
        ents, data = parse(src)
        vcap, ecap = LADDER[level]
        offs = []
        for e in ents:
            if e["off"] not in offs: offs.append(e["off"])
        users = {o: [e for e in ents if e["off"] == o] for o in offs}
        out = bytearray(); newoff = {}; shift = {}; self.cls = {}
        for o in offs:
            blk = sample_blocks(data, o * 8)
            cl = "V" if is_voice(name, users[o]) else "E"
            cap = vcap if cl == "V" else ecap
            r = min(e["snote"] - e["note"] for e in users[o])
            k = 0 if (cap == 0 or is_loop(blk)) else max(0, cap - r)
            if k and max(e["snote"] for e in users[o]) + k > 127: k = 127 - max(e["snote"] for e in users[o])
            volf = 1.0
            if VOICEHQ and cl == "V" and not is_loop(blk):      # (voice 3) every voice: treble restore + HQ.FIXED_DB over
                blk, volf = HQ.voice_hq(blk, k, 44100 * 2 ** (-r / 12),     # stock loudness; --voicevol (test only):
                                        HQ.VOICE_GAIN_DB if VOICEVOL else HQ.FIXED_DB)   # +6 dB + flag 0x8000 for snd.c
                for e in users[o]: e["vol"] = (0x8000 if VOICEVOL else 0) | max(1, min(127, int(round(e["vol"] * volf))))
                volf = 1.0
            elif k and VOICEHQ: blk, volf = HQ.resample_hq(blk, k, 44100 * 2 ** (-r / 12))
            elif k: blk = resample_sample(blk, k)
            if volf > 1.0:
                for e in users[o]: e["vol"] = min(127, int(round(e["vol"] * volf)))
            newoff[o] = len(out) // 8; shift[o] = k; self.cls[o] = (cl, len(blk))
            out += blk
        new = []
        for e in ents:
            e = dict(e); o = e["off"]; e["off"] = newoff[o]; e["snote"] += shift[o]; new.append(e)
        self.n = len(new); self.dsize = len(out); self.ents = new
        self.data = struct.pack("<H", len(new)) + bytes(18) + pack(new) + bytes(out)


def build(name, level):
    import pickle
    os.makedirs(CACHE, exist_ok=True)
    src = se_source(name)
    # cache key: the --voicehq edit of this file keeps the stock path's output, so off = the pre-voicehq file's key
    me = os.path.join(HERE, "sndbank.py.pre_voicehq")
    me = me if os.path.exists(me) else __file__
    key = hashlib.sha1(src + bytes([level]) + open(me, "rb").read() + open(M.__file__, "rb").read()
                       + ((b"HQ" + (b"VOL3" if VOICEVOL else b"") + open(HQ.__file__, "rb").read() + open(os.path.join(HERE, "gauss.py"), "rb").read()) if VOICEHQ else b"")).hexdigest()[:16]
    p = os.path.join(CACHE, f"{name}_L{level:02d}_{key}.pkl")
    if os.path.exists(p): return pickle.load(open(p, "rb"))
    bk = Bank(name, level, src); pickle.dump(bk, open(p, "wb")); return bk


def levels(name):
    out = []
    for L in range(NL):
        bk = build(name, L)
        if out and bk.data == out[-1].data: bk = out[-1]
        out.append(bk)
    return out


def char_banks(c):
    return MM if c == 0x10 else ["%02X" % c]


if __name__ == "__main__":
    if sys.argv[1:] == ["stats"]:
        for n in bank_names():
            ls = levels(n)
            print(n, "n", ls[0].n, " ".join(str(b.dsize // 1024) for b in ls))
