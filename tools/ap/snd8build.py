"""Arcade sound samples for the 8 MB build (tag hack 1.2): the samples the PS1 port does not have at all, taken from
the user's own arcade ROM set (CPS2 QSound sample ROMs xvs.11m + xvs.12m, sample table in the Z80 program xvs.01 +
xvs.02), for tools/mkap8disc.py --snd8=OUTDIR (tools/sndpatch.py level8()).  Nothing from the ROMs is in the patch.

    python tools/ap/snd8build.py --arcade xmvsfu.zip [xmvsf.zip ...] --out OUTDIR

OUTDIR/SND8.BIN: "XS8\\x01", u32 count, then per sample: u16 sound id, u16 arcade sample index, u32 rate (Hz),
u32 n, n bytes signed 8-bit PCM (padded to 4).  OUTDIR/manifest.json: file name + SHA-1.

Which samples (work/sound/IMPLEMENT.md): the game requests these on the PS1 and no PS1 bank has their sound:
    0x19e  Wolverine's third tag voice (+0x1e; the other two are restored from his own bank) - arcade sample 229
The common effects 0x8b / 0x8d / 0x93 / 0x9e that the port also lacks are never requested by the PS1 game (traced):
not added.
"""
import sys, os, json, zipfile, hashlib, struct, argparse

# the sound ROMs of every supported set (xmvsf, xmvsfu, xmvsfu1d share them)
SOUND = {"01": "fefcff8a9a5c83df7655a16187cf9ba3e7efbb25", "02": "75920e88bf46fcd33a7957777a1d799818ffb0d6",
         "11m": "64d3bd53b04daec84c9af4aa3ff010867b3d306d", "12m": "a581c84acaaf0ce056841c15a6f36889e88be68d"}
SAMP_TAB, SAMP_LEN = 0x54F6, 0xE20                  # Z80 sample table (VGMTrans CPS2 driver 1.16 layout; 16-bit fields LE)
RATE = 24038
WANT = {0x19e: 229}                                 # sound id -> arcade sample index


class Fail(Exception):
    pass


def read_sound(paths):
    files = {}
    for p in paths:
        if os.path.isdir(p):
            for n in os.listdir(p): files.setdefault(n.lower(), os.path.join(p, n))
        else:
            try: z = zipfile.ZipFile(p)
            except (zipfile.BadZipFile, OSError): raise Fail("arcade set: %s is not a zip file or a folder of ROM files" % p)
            for n in z.namelist(): files.setdefault(os.path.basename(n).lower(), (z, n))
    roms = {}
    for n, src in files.items():
        ext = n.rsplit(".", 1)[-1]
        if ext in SOUND and ext not in roms:
            d = open(src, "rb").read() if isinstance(src, str) else src[0].read(src[1])
            if hashlib.sha1(d).hexdigest() == SOUND[ext]: roms[ext] = d
    miss = [k for k in SOUND if k not in roms]
    if miss: raise Fail("arcade set: no matching sound ROM ." + ", .".join(miss) + " (a clone zip needs its parent zip too)")
    z80 = roms["01"] + roms["02"]
    q = bytearray(roms["11m"] + roms["12m"])
    q[0::2], q[1::2] = q[1::2], q[0::2][:]           # 16-bit byte swap
    return z80, bytes(q)


def sample(z80, q, i):
    b, s, l, e, k = struct.unpack_from("<BHHHB", z80, SAMP_TAB + 8 * i)
    st = b << 16 | s
    en = (b + 1) << 16 if e == 0 else (b << 16 | e)
    return q[st:max(st, en)]


def build(paths, out):
    z80, q = read_sound(paths)
    os.makedirs(out, exist_ok=True)
    body = b""
    for sid, i in sorted(WANT.items()):
        pcm = sample(z80, q, i)
        body += struct.pack("<HHII", sid, i, RATE, len(pcm)) + pcm + bytes(-len(pcm) % 4)
    data = b"XS8\x01" + struct.pack("<I", len(WANT)) + body
    open(os.path.join(out, "SND8.BIN"), "wb").write(data)
    json.dump(dict(file="SND8.BIN", sha1=hashlib.sha1(data).hexdigest(), samples={"%x" % k: v for k, v in WANT.items()}),
              open(os.path.join(out, "manifest.json"), "w"), indent=1)
    return data


def load(d):
    """-> {sound id: (rate, int8 PCM bytes)} of OUTDIR (checked against its manifest)"""
    m = json.load(open(os.path.join(d, "manifest.json")))
    data = open(os.path.join(d, m["file"]), "rb").read()
    assert hashlib.sha1(data).hexdigest() == m["sha1"] and data[:4] == b"XS8\x01", "SND8.BIN does not match its manifest"
    n = struct.unpack_from("<I", data, 4)[0]; o = 8; out = {}
    for _ in range(n):
        sid, i, rate, k = struct.unpack_from("<HHII", data, o); o += 12
        out[sid] = (rate, data[o:o + k]); o += (k + 3) & ~3
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arcade", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        d = build(a.arcade, a.out)
    except Fail as e:
        sys.exit(str(e))
    print("SND8.BIN %d bytes, %d samples -> %s" % (len(d), len(WANT), a.out))
