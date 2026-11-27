"""MvC 8 MB "arcade frames" content builder: restores the animation frames the PS1 port dropped (port of the MSHvSF
builder games/mshvsf/tools/ap/build8.py; study docs/MVC_8MB_RESTORE.md section 2).

    python games/mvc/tools/ap/build8.py --arcade mvsc.zip [PARENT.zip] [--disc mvc.bin] --out OUTDIR [--chars 1,2]

Reads the user's own arcade ROM set (CPS2 Marvel vs. Capcom: program ROMs .03-.10, graphics .13m-.20m) and the user's
own PS1 disc (SLUS-01059) and writes per character xx (hex id 01-16) OUTDIR/PLxx.R8 (format below) + manifest.json.
Everything in OUTDIR is derived from the two inputs and must never be committed or shipped: the 8 MB disc builder
(tools/ap8/mkap8.py --frames8) runs this at build time from the user's ROM.  This file holds no data from either.

MvC specifics (vs MSHvSF): the sprite file is section 1 of DAT/PLxx_10.A0 (kind 8: 5-byte tile entries u24 offset,
u8 width bytes, u8 rows); part flag 0x80 = "reuse the previous decode" (drawable); the arcade per-character table is
23 longs (found by structure: first words = the PS1 group-table first words); Venom / Red Venom: arcade 62 groups,
PS1 31 (blob found by the PS1 header).

PLxx.R8 (little endian u32 words; offsets from the file start; read whole into an upper-RAM record by the 8 MB module,
tools/ap8/ap8r.c):
   0 'R8F1'   1 char id   2 DSP size   3 DSP offset (word 3 = section-1 offset of an A0 header: the loader's D = A + ah[3])
   4 frame-id table offset (nf words: the stock table + the new frame ids)   5 nf   6 nf0 (stock frames)
   7 code-item offset of the animation blob (= PLxx_10.A0 file offset)   8 record patches m   9 patch offset
  10 file size   11 restored records   12-15 0
  patches: m x (u32 code-item offset of the record, u16 new frame index, u16 stock frame index)
  then the table, then (16-aligned) the sprite file: the stock DSP + appended tiles (stock RLE) + frames (sec1).
"""
import re, os, sys, json, zipfile, hashlib, struct, argparse, collections
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "ap"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "common", "dsp")]
import aplib, dsp

MAXW = MAXH = 15                 # VRAM rectangle of a frame, 16-pixel cells (stock max 15 x 15)
MAXPARTS = 92                    # stock max
MAXRAW = 18816                   # decoded bytes of one frame (largest stock frame)
KMIN = int(os.environ.get("FR8_KMIN", "2"))   # anchor rule: stock frames == arcade sprite needed per restored animation
NFRAMES = 2048                   # 11-bit frame index (record byte 0 + bits 12-14 of its second word)
STOCKCH = {int(x, 16) for x in os.environ.get("FR8_STOCKCH", "").split(",") if x}   # (bisect) these mains: no restored anims
KEEP_STOCK = {}                  # {char: [(group, index)]} animations kept stock for speed: keep8.json (measured)
_kp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keep8.json")
if os.path.exists(_kp):
    KEEP_STOCK = {int(k, 16): [tuple(x) for x in v] for k, v in json.load(open(_kp)).items() if not k.startswith("_")}
for _kp2 in filter(None, [os.environ.get("FR8_KEEP")]):     # mkap8 --frames8-speed: keep8_speed.json on top
    for k, v in json.load(open(_kp2)).items():
        if not k.startswith("_"): KEEP_STOCK.setdefault(int(k, 16), []).extend(tuple(x) for x in v)
GFXROMS = ["13m", "14m", "15m", "16m", "17m", "18m", "19m", "20m"]


class Fail(Exception):
    pass


# ------------------------------------------------------------------------------------------------ inputs
# (2026-11-27) program ROMs .03-.10 (SHA-1, in that order) of the MAME / FBNeo sets of this game: in a MERGED zip (the
# parent with every clone inside) the files of one set are chosen together, never a mix of revisions
PRG_SETS = {
    "mvsc": ("5c79c166d988d8a75d9941f4ee6fa4d6476e55e1", "82f4586e888f2550c53bfdc93a53791a595e05bd", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvsca": ("74cc3656a265f912c72cc6e591de14791fa9a50d", "3e4c91753b19c6307abd0ad87a0184730a418efb", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscar1": ("c27b987ffb631c3433aa32a29989dbf2b3e53f1e", "363770ecd5f4e160db6448845ba6d7fd0beea291", "a0097109e9f4aba40791932269d600c0ffa099a7", "375372adf0a508bb6fc6a79326b2d4171db9ca0f", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscb": ("acd1f86bc24636a02aeef566994d38ffa6dbf72f", "c513f430e7c4f32e220a800c53ffdcea68c6cfcf", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscem": ("17db6f6afbe7866a4803bf2a20fb9b01b2b80250", "c5420e9bd580910c1f1d0264240aeef20aac30a7", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvsch": ("62d7b28cc9ddf975ccdc8992d51bd3d085e3e136", "3a79400a7ac6e7594ca7e0fbb2486ddf6c759d18", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscj": ("2b91da6e5dd792967337e873ebb08ecf5194a97b", "c5420e9bd580910c1f1d0264240aeef20aac30a7", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscjr1": ("00e3500ed334bb80d4d159eacf439860a2bfc3b7", "965fa3bdc29bd901e9efcc53b195c6be3a74c9f9", "a0097109e9f4aba40791932269d600c0ffa099a7", "375372adf0a508bb6fc6a79326b2d4171db9ca0f", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscr1": ("d2feffb5505a2f8940192ae267f49561fc580b87", "1e34fa55bb93c7573ab0205f8c5620a51765d3eb", "a0097109e9f4aba40791932269d600c0ffa099a7", "375372adf0a508bb6fc6a79326b2d4171db9ca0f", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscu": ("c027c1a204345ce611cb042d60939e4de156763f", "872bbcf5d344d634f3523318fa4763e6d6302bb5", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "d35589847e0753e869ffcd7c3abed925bfdb0fa2", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscud": ("5453056da68cdd4675cb585a9c6ae85e073193f5", "742b35a45eadea3457bfb93808cbba599e9744e3", "b07d640a734c5d336054ed05195786224c9a6cd4", "cd065c05268ab581b05676da544baf6af642acac", "b47a7057abd18d85ff9d86483ecb7ab783b3e791", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "5fa684d823b4f4eec61ed9e9b8938af5272ae1ed"),
    "mvscur1": ("229520c5f4171abae1acdfb9544b356b568b5f2d", "8989192b575fb717c13bfb8175e83d7f1a285310", "32942c4690253c1545ce05dc084de227e46d942a", "b6543d40fb98eabec82787e0fd60fbc59069e72e", "59726e535d1fd9cc4ddfdd02c936121d70723ced", "0b6735a071a9274f7ab25c743271fc30411fe819", "6e9969246c57269d7ba0992a5cc319c8910bf8a9", "ee6bdbf14bd524f76f4f756f332315331d5e1e4b"),
}
PRG_EXTS = ['03', '04', '05', '06', '07', '08', '09', '10']


def _pick_prg(cand, zname):
    """cand {ext: [(zip index, bytes)]} -> {ext: bytes} of the known set to use, or None.  Rank: the zip its .03 comes
    from (SET.zip before PARENT.zip), then the set named like that zip, then the order of PRG_SETS (parent first)"""
    import hashlib as _h
    hs = {e: [(z, _h.sha1(d).hexdigest(), d) for z, d in v] for e, v in cand.items()}
    best = None
    for k, (name, want) in enumerate(PRG_SETS.items()):
        got = {}
        for e, w in zip(PRG_EXTS, want):
            m = [(z, d) for z, h, d in hs.get(e, []) if h == w]
            if not m: break
            got[e] = min(m, key=lambda x: x[0])
        else:
            z = got["03"][0]; rank = (z, name != zname.get(z), k)
            if best is None or rank < best[0]: best = (rank, {e: d for e, (z_, d) in got.items()})
    return best[1] if best else None


def read_arcade(paths):
    """-> (program image, {rom: bytes}, description).  Program = .03 .04 .05 .06 .07 .08 .09 .10 (16-bit swapped)."""
    files = {}; zipno = {}; zname = {}
    for i, p in enumerate(paths):
        zname[i] = re.sub(r"^set\d+_", "", os.path.splitext(os.path.basename(p))[0].lower())    # (the web page: setN_<name>.zip)
        if os.path.isdir(p):
            for n in sorted(os.listdir(p)):
                if n.lower() not in files: files[n.lower()] = open(os.path.join(p, n), "rb").read(); zipno[n.lower()] = i
        else:
            try: z = zipfile.ZipFile(p)
            except (zipfile.BadZipFile, OSError): raise Fail("arcade set: %s is not a zip file or a folder of ROM files" % p)
            for n in z.namelist():
                k = os.path.basename(n).lower()
                if k and k not in files: files[k] = z.read(n); zipno[k] = i
    roms = {}; cand = {}
    for n, d in files.items():
        ext = n.rsplit(".", 1)[-1]
        if ext in GFXROMS and len(d) == 0x400000: roms.setdefault(ext, d)
        elif ext[:2] in PRG_EXTS and len(d) == 0x80000: roms.setdefault(ext[:2], d); cand.setdefault(ext[:2], []).append((zipno.get(n, 0), d))
    pick = _pick_prg(cand, zname)                          # a known set, complete: its files (else the first per extension)
    if pick: roms.update(pick)
    miss = [k for k in GFXROMS + ["03", "04", "05", "06", "07", "08", "09", "10"] if k not in roms]
    if miss: raise Fail("arcade set incomplete: no ROM with extension " + ", ".join("." + m for m in miss) +
                        " (a clone zip needs its parent zip too).  Supported: mvsc or any of its clones (mvscu, mvscj ...), merged or "
                        "non-merged zip, or a split clone zip together with mvsc.zip")
    def sw(d):
        a = np.frombuffer(d, dtype=np.uint8); b = a.copy(); b[0::2] = a[1::2]; b[1::2] = a[0::2]; return b.tobytes()
    prg = b"".join(sw(roms[k]) for k in ("03", "04", "05", "06", "07", "08", "09", "10"))
    desc = {k: hashlib.sha1(v).hexdigest() for k, v in sorted(roms.items())}
    return prg, roms, desc


def find_chtab(D, firsts):
    """23 longs -> per-character animation tables (word table, first word = 2 * groups); firsts = {char: PS1 group-table
    first word}: at least 18 of the 22 characters must agree (Venom / Red Venom do not: 0x7c / 0x54 vs 0x3e)"""
    best = None
    for a in range(0, len(D) - 92, 2):
        if D[a] != 0: continue
        v = struct.unpack_from(">23I", D, a)
        if not all(0x1000 <= x < len(D) - 2 and not x & 1 for x in v): continue
        if not all(D[x] == 0 and 0x20 <= D[x + 1] <= 0x80 and not D[x + 1] & 1 for x in v): continue
        n = sum(1 for c, f in firsts.items() if D[v[c] + 1] == f)
        if n >= 18 and (best is None or n > best[1]): best = (a, n)
    if best is None: raise Fail("animation pointer table not found in the arcade program ROMs")
    return best[0]


class PS1Files:
    """the stock disc: PLxx_10.A0 = [u32 n, (offset, size) x n]: section 0 = header + code + data (animation blob),
    section 1 = the sprite file (DSP kind 8).  get("PLxx_10.A0") -> section 0, get("SP_PLxx.DSP") -> section 1"""
    def __init__(self, disc):
        from iso import Disc
        self.d = Disc(disc); self.files = {}
        for full, lba, sz, fl in self.d.walk():
            self.files[full.split("/")[-1].split(";")[0]] = (lba, sz)
        self.cache = {}

    def a0(self, ch):
        if ch not in self.cache:
            lba, sz = self.files["PL%02X_10.A0" % ch]
            f = self.d.read(lba, sz); n = struct.unpack_from("<I", f, 0)[0]
            self.cache[ch] = (f, [struct.unpack_from("<II", f, 4 + 8 * i) for i in range(n)])
        return self.cache[ch]

    def get(self, name):
        if name.endswith(".A0"):
            f, s = self.a0(int(name[2:4], 16)); return f[s[0][0]:s[0][0] + s[0][1]]
        f, s = self.a0(int(name[5:7], 16)); return f[s[1][0]:s[1][0] + s[1][1]]

    def h0(self, ch): return self.a0(ch)[1][0][0]

    def da(self, a):
        """special partner a: DAxx_11.A0 -> (section 0 = code + animation blob, section 1 = sprite file)"""
        lba, sz = self.files["DA%02X_11.A0" % a]
        f = self.d.read(lba, sz); s = [struct.unpack_from("<II", f, 4 + 8 * i) for i in range(2)]
        return f[s[0][0]:s[0][0] + s[0][1]], f[s[1][0]:s[1][0] + s[1][1]]          # file offset of section 0 (0x1c; Onslaught 0x24)


def ps1_firsts(ps1):
    """PS1 group-table first word (low byte) per character, from the blob header"""
    firsts = {}
    for c in range(1, 0x17):
        A0 = ps1.get("PL%02X_10.A0" % c)
        for i in range(0, len(A0) - 16, 4):
            h = struct.unpack_from("<4I", A0, i)
            if h[0] == 0x10 and 0x10 < h[1] < h[2] < h[3] < len(A0) - i and h[3] - h[2] < 0x4000 and A0[i + 17] == 0:
                firsts[c] = A0[i + 16]; break
    return firsts


class Blob:
    """animation data in PLxx_10.A0"""
    def __init__(self, A0, first):
        P = self.P = A0
        for i in range(0, len(P) - 16, 4):
            h = struct.unpack_from("<4I", P, i)
            if h[0] == 0x10 and 0x10 < h[1] < h[2] < h[3] < len(P) - i and h[3] - h[2] < 0x4000 and P[i + 16:i + 18] == first:
                self.B = i; self.h = h; return
        raise Fail("animation data not found in the character overlay")

    def u16(self, a): return struct.unpack_from("<H", self.P, a)[0]

    def groups(self):
        T = self.B + self.h[0]; n = self.u16(T) // 2; g = [self.u16(T + 2 * i) for i in range(n)]; out = []
        for k in range(n):
            if g[k] == 0: out.append([]); continue
            nxt = min([x for x in g if x > g[k]] + [self.h[1] - self.h[0]])
            out.append([self.u16(T + g[k] + 2 * j) for j in range((nxt - g[k]) // 2)])
        return out

    def walk(self, off, limit=400):
        out = []; a = self.B + self.h[1] + off
        while len(out) < limit:
            f = self.P[a]; dur = self.P[a + 1]; w1 = self.u16(a + 2)
            out.append((a, f | ((w1 >> 12) & 7) << 8, dur, w1 >> 15)); a += 4 + (4 if w1 >> 15 else 0)
            if w1 >> 15: break
        return out

    def nframes(self): return (self.h[3] - self.h[2]) // 4
    def frameid(self, i): return struct.unpack_from("<I", self.P, self.B + self.h[2] + 4 * i)[0]


# ------------------------------------------------------------------------------------------------ helpers
def canvas(items):
    """[(x, y, pixels)] -> (x0, y0, image) with 15 = transparent; the first item is on top"""
    if not items: return (0, 0, np.zeros((0, 0), np.uint8))
    x0 = min(x for x, y, p in items); y0 = min(y for x, y, p in items)
    x1 = max(x + p.shape[1] for x, y, p in items); y1 = max(y + p.shape[0] for x, y, p in items)
    img = np.full((y1 - y0, x1 - x0), 15, np.uint8)
    for x, y, p in reversed(items):
        reg = img[y - y0:y - y0 + p.shape[0], x - x0:x - x0 + p.shape[1]]; m = p != 15; reg[m] = p[m]
    return (x0, y0, img)


def flip(p, fl):
    if fl & 0x20: p = p[:, ::-1]
    if fl & 0x40: p = p[::-1, :]
    return p


def img_diff(a, b):
    """differing pixels of two canvases on their union box (transparent = 15)"""
    x0 = min(a[0], b[0]); y0 = min(a[1], b[1])
    x1 = max(a[0] + a[2].shape[1], b[0] + b[2].shape[1]); y1 = max(a[1] + a[2].shape[0], b[1] + b[2].shape[0])
    A = np.full((y1 - y0, x1 - x0), 15, np.uint8); B = A.copy()
    A[a[1] - y0:a[1] - y0 + a[2].shape[0], a[0] - x0:a[0] - x0 + a[2].shape[1]] = a[2]
    B[b[1] - y0:b[1] - y0 + b[2].shape[0], b[0] - x0:b[0] - x0 + b[2].shape[1]] = b[2]
    return int((A != B).sum()), int(((A != 15) | (B != 15)).sum())


SAME_PX, SAME_FRAC = 48, 0.02    # a PS1 frame "shows" an arcade sprite when they differ in at most this many pixels


def enc_part(flags, tile, cell, x, y):
    """part record of sec1 (dsp.parse_part): flags, tile | xmode << 12 | ymode << 14, VRAM cell, x, y"""
    def mode(v):
        if -128 <= v <= 127: return 0, bytes([v & 255])
        if 0 <= v <= 255: return 1, bytes([v])
        if -255 <= v <= 0: return 2, bytes([-v])
        return 3, struct.pack("<h", v)
    xm, xb = mode(x); ym, yb = mode(y)
    w = tile | xm << 12 | ym << 14
    return bytes([flags, w & 255, w >> 8, cell]) + xb + yb


def rle_encode(raw):
    """the game's byte RLE (dsp.rle_decode): run byte (n-1) << 4 | v for n >= 2 equal bytes v*0x11 (v = 0..15), else
    literals (n-1, n <= 16 raw bytes)"""
    out = bytearray(); lit = bytearray(); i = 0; n = len(raw)
    def flush():
        while lit:
            c = lit[:16]; del lit[:16]; out.append(len(c) - 1); out.extend(c)
    while i < n:
        b = raw[i]
        if (b >> 4) == (b & 15):
            j = i
            while j < n and raw[j] == b and j - i < 16: j += 1
            if j - i >= 2:
                flush(); out.append(((j - i - 1) << 4) | (b & 15)); i = j; continue
        lit.append(b); i += 1
    flush()
    return bytes(out)


def pack(blocks, maxw=MAXW, maxh=MAXH):
    """VRAM rectangle (16-pixel cells) for the parts: fewest rows first, then fewest columns (the stock frames are
    wide and flat: 84% have at most 5 rows).  -> (W, H, [(x, y)]) or None"""
    best = None
    order = sorted(range(len(blocks)), key=lambda i: (-blocks[i][1], -blocks[i][0], i))
    for W in range(max(b[0] for b in blocks), maxw + 1):
        occ = np.zeros((maxh + 16, W), dtype=bool); pos = [None] * len(blocks); H = 0
        for i in order:
            w, h = blocks[i]
            for y in range(0, maxh + 16 - h):
                x = next((x for x in range(0, W - w + 1) if not occ[y:y + h, x:x + w].any()), None)
                if x is not None:
                    occ[y:y + h, x:x + w] = True; pos[i] = (x, y); H = max(H, y + h); break
        if H <= maxh and (best is None or (H, W) < (best[1], best[0])): best = (W, H, pos)
    return best


def tile_bytes(px):
    """pixels [h, w] (4 bpp indices) -> PS1 tile bytes, low nibble = left pixel"""
    return (px[:, 0::2] | (px[:, 1::2] << 4)).astype(np.uint8).tobytes()


# ------------------------------------------------------------------------------------------------ one character
def build(ctx, ps1, ch, chtab, assist=False):
    """assist=True: ch = special partner id, PS1 DAxx_11.A0 (group 0) <-> arcade table entry 0, group ch"""
    if assist:
        A0, D0 = ps1.da(ch)
        pb = Blob(A0, bytes([4, 0]))
        n = dsp.DSP(D0)
        T = ctx.be32(chtab)
        ag = [ctx.arc_groups(T)[ch]]; pg = pb.groups()[:1]
    else:
        A0 = ps1.get("PL%02X_10.A0" % ch)
        T = ctx.be32(chtab + 4 * ch); first = ctx.D[T + 1:T + 2] + ctx.D[T:T + 1]
        try: pb = Blob(A0, first)
        except Fail: pb = Blob(A0, bytes([0x3e, 0]))     # MvC Venom / Red Venom: arcade table holds 62 groups (0x7c), PS1 31
        n = dsp.DSP(ps1.get("SP_PL%02X.DSP" % ch))
        ag = ctx.arc_groups(T); pg = pb.groups()
    n.decode_all()
    gr = {off: (hdr, g) for off, hdr, g in n.groups()}
    # per-character limits (2026-11-24, hardware safety): a new frame never needs more VRAM cells (W, H, W * H), parts or
    # decoded bytes than this character's own largest stock frame (the game sizes per-character VRAM / buffers by them)
    lw = lh = la = lp = lr = 0
    for hdr, g in gr.values():
        if hdr[2] or hdr[3]: continue
        lw = max(lw, hdr[0]); lh = max(lh, hdr[1]); la = max(la, hdr[0] * hdr[1]); lp = max(lp, len(g))
        lr = max(lr, sum(n.tiles[p.tile].w * n.tiles[p.tile].h // 2 for p in g if p.tile < len(n.tiles)))
    if os.environ.get("FR8_NOCHARLIM"): lw, lh, la, lp, lr = MAXW, MAXH, MAXW * MAXH, MAXPARTS, MAXRAW
    lw, lh, lp, lr = min(lw, MAXW), min(lh, MAXH), min(lp, MAXPARTS), min(lr, MAXRAW)
    keep = set() if assist else set(KEEP_STOCK.get(ch, ()))
    pairs = []; anims = matched = 0; anim_recs = []
    for k in range(min(len(ag), len(pg))):
        for j, a in enumerate(ag[k]):
            if a is None or j >= len(pg[k]): continue
            anims += 1
            if pg[k][j] % 4: continue
            ar = ctx.arc_walk(a); pr = pb.walk(pg[k][j])
            if len(ar) != len(pr) or any(x.end != y[3] for x, y in zip(ar, pr)) or not pr[-1][3]: continue
            matched += 1
            if (k, j) in keep: continue
            pairs += [(x, y) for x, y in zip(ar, pr)]
            anim_recs.append([y[0] for y in pr])
    # a PS1 record reached from several animations must get the same arcade sprite from each, else it stays stock
    spr_of = collections.defaultdict(set)
    for x, y in pairs: spr_of[y[0]].add(x.spr)
    nrec = len(pairs)
    seen_rec = set(); uniq = []
    for x, y in pairs:
        if len(spr_of[y[0]]) == 1 and y[0] not in seen_rec: seen_rec.add(y[0]); uniq.append((x, y))
    ambiguous = sum(1 for v in spr_of.values() if len(v) > 1)
    pairs = uniq

    def ps1_img(fi):
        fid = pb.frameid(fi)
        if fid >> 16 != 0xffff or (fid & 0xffff) not in gr: return None
        hdr, g = gr[fid & 0xffff]
        if hdr[2] or hdr[3] or any(p.tile >= len(n.tiles) for p in g): return None
        return canvas([(p.x, p.y, flip(dsp.tile_pixels(n.tiles[p.tile]), p.flags)) for p in g])

    # graphics bank: the one where the stock tiles of kept frames equal the arcade blocks
    votes = collections.Counter()
    for x, (ra, fi, dur, end) in pairs[:3000]:
        fid = pb.frameid(fi)
        if fid >> 16 != 0xffff or (fid & 0xffff) not in gr or not ctx.valid_def(x.spr): continue
        g = gr[fid & 0xffff][1]
        at = {(xx, yy, 16 * (nx + 1), 16 * (ny + 1)): (c, nx, ny) for c, nx, ny, lo, xx, yy in ctx.arc_parts(x.spr)}
        for p in g:
            if p.tile >= len(n.tiles): continue
            t = n.tiles[p.tile]; q = at.get((p.x, p.y, t.w, t.h))
            if q is None: continue
            for bk in (0, 0x10000, 0x20000, 0x30000):
                if (dsp.tile_pixels(t) == ctx.block(q[0], q[1], q[2], bk)).all(): votes[bk] += 1
        if sum(votes.values()) > 100: break
    bank = votes.most_common(1)[0][0] if votes and votes.most_common(1)[0][1] >= 5 else None
    if bank is None and assist:                      # assists: PS1 tiles re-cut (not arcade blocks): vote by whole frames
        for x, (ra, fi, dur, end) in pairs:
            pi = ps1_img(fi)
            if pi is None or not ctx.valid_def(x.spr): continue
            for bk in (0, 0x10000, 0x20000, 0x30000):
                ai = canvas([(xx, yy, flip(ctx.block(c, nx, ny, bk), lo)) for c, nx, ny, lo, xx, yy in ctx.arc_parts(x.spr)])
                d, area = img_diff(pi, ai)
                if d <= max(SAME_PX, SAME_FRAC * area): votes[bk] += 1
        bank = votes.most_common(1)[0][0] if votes and votes.most_common(1)[0][1] >= 3 else None
    if bank is None: raise Fail("character %02X: the PS1 sprite file and the arcade graphics do not match" % ch)
    if not assist and ch in STOCKCH: pairs = []; anim_recs = []      # (bisect FR8_STOCKCH) no restored animations

    def arc_img(s):
        return canvas([(x, y, flip(ctx.block(c, nx, ny, bank), lo)) for c, nx, ny, lo, x, y in ctx.arc_parts(s)])

    # tiles of the stock file by pixels (exact shape)
    tmap = {}
    for t in n.tiles: tmap.setdefault((t.wb, t.h, t.raw), t.idx)
    s0 = bytearray(n.sec[0]); s1 = bytearray(n.sec[1]); s2 = bytearray(n.sec[2][:5 * len(n.tiles)])   # kind 8: drop the stock pad bytes before appending entries
    s1 += bytes(-len(s1) % 4)
    newtile = 0
    def tile_for(px):
        nonlocal newtile
        raw = tile_bytes(px); wb = px.shape[1] // 2; h = px.shape[0]
        key = (wb, h, raw)
        if key in tmap: return tmap[key]
        idx = len(s2) // 5
        if idx >= 4096: raise OverflowError("tiles")
        off = len(s0)
        s0.extend(rle_encode(raw)); s0.extend(bytes(-len(s0) % 2))
        if wb > 0x7f or h > 0xff: raise OverflowError("tiles")          # MvC kind 8: u24 offset, u8 width bytes (bit 7 = half-res flag), u8 rows
        s2.extend(bytes([off & 255, off >> 8 & 255, off >> 16, wb, h]))
        tmap[key] = idx; newtile += 1
        return idx

    nf0 = pb.nframes(); newids = []; newframe = {}; skipped = collections.Counter()
    ok_img = {}; recpatch = []; stats = collections.Counter()
    imgcache = {}; shows = set()             # shows: records whose stock frame already is their arcade sprite
    # per PS1 frame: the arcade sprite closest to it keeps the stock frame (when it is close enough), the others get
    # their own frame
    byframe = collections.defaultdict(set)
    for x, (ra, fi, dur, end) in pairs: byframe[fi].add(x.spr)
    kept = {}
    for fi, sprs in byframe.items():
        imgcache[fi] = ps1_img(fi)
        if imgcache[fi] is None: continue
        best = None
        for s in sorted(sprs):
            if not ctx.valid_def(s): continue
            if s not in ok_img: ok_img[s] = arc_img(s)
            d, area = img_diff(imgcache[fi], ok_img[s])
            if best is None or d < best[0]: best = (d, s, area)
        if best and best[0] <= max(SAME_PX, SAME_FRAC * best[2]): kept[fi] = best[1]
    for x, (ra, fi, dur, end) in pairs:
        s = x.spr
        pimg = imgcache[fi]
        if pimg is None: stats["stock: special frame"] += 1; continue
        if not ctx.valid_def(s): stats["stock: arcade sprite not readable"] += 1; continue
        if kept.get(fi) == s: stats["stock frame kept"] += 1; shows.add(ra); continue
        if s not in newframe:
            newframe[s] = None
            ap = ctx.arc_parts(s)
            blocks = [(nx + 1, ny + 1) for c, nx, ny, lo, xx, yy in ap]
            raw = sum(w * h * 128 for w, h in blocks)
            if len(ap) > lp: skipped["parts"] += 1; continue
            if raw > lr: skipped["decoded size"] += 1; continue
            if max(w for w, h in blocks) > lw or max(h for w, h in blocks) > lh: skipped["block"] += 1; continue
            pk = pack(blocks, lw, lh)
            if pk is not None and pk[0] * pk[1] > la: pk = None
            if pk is None: skipped["vram rectangle"] += 1; continue
            W, H, pos = pk
            if nf0 + len(newids) >= NFRAMES: skipped["frame index"] += 1; continue
            try:
                parts = [enc_part(lo & 0x7f, tile_for(ctx.block(c, nx, ny, bank)), pos[i][1] << 4 | pos[i][0], xx, yy)
                         for i, (c, nx, ny, lo, xx, yy) in enumerate(ap)]
            except OverflowError:
                skipped["tiles"] += 1; continue
            off = len(s1)
            rec = struct.pack("<H", len(ap)) + bytes([W, H, 0, 0]) + b"".join(parts)
            if off + len(rec) > 0xffff: skipped["sec1 64 KB"] += 1; continue
            s1 += rec + bytes(-len(rec) % 2)
            newframe[s] = nf0 + len(newids); newids.append(0xffff0000 | off)
        if newframe[s] is None: stats["stock: limits"] += 1; continue
        recpatch.append((ra, newframe[s])); stats["restored"] += 1
    # no mixed animations: a paired animation either gets every record that needs an arcade sprite, or none.  (The
    # port drew some animations as one frame + its slice variants (frame ids without 0xffff, e.g. Blackheart's walk:
    # frame 3 + slices 4..9 of the same group); those records stay stock (no image to compare), so restoring only the
    # others made the walk alternate between arcade poses and the stock pose - the 1.0 "Blackheart walk" bug.)
    patched = {ra for ra, f in recpatch}
    # anchor rule (2026-11-24, after the MSHvSF Blackheart walk = block-sprite bug): an animation is restored only when at
    # least KMIN of its records keep a stock PS1 frame that is pixel-identical to the paired arcade sprite.  That proves
    # independently of the index pairing that the arcade animation is the same action, aligned record by record (a
    # wrong pairing - another action - has no such anchors: Shadow Lady / assist 0E had none).
    noanchor = set()
    for recs in anim_recs:
        if sum(1 for r in recs if r in shows) < KMIN: noanchor |= {r for r in recs if r in patched}
    patched -= noanchor
    while True:
        bad = set()
        for recs in anim_recs:
            if any(r in patched for r in recs) and any(r not in patched and r not in shows for r in recs):
                bad |= {r for r in recs if r in patched}
        if not bad: break
        patched -= bad
    stats["stock: no anchor"] = sum(1 for ra, f in recpatch if ra in noanchor)
    stats["stock: mixed animation"] = sum(1 for ra, f in recpatch if ra not in patched and ra not in noanchor)
    stats["restored"] -= stats["stock: mixed animation"] + stats["stock: no anchor"]
    recpatch = [(ra, f) for ra, f in recpatch if ra in patched]
    s0 += bytes(-len(s0) % 4); s1 += bytes(-len(s1) % 4)
    s2 += bytes(-len(s2) % 4)                        # (kind 8: 5-byte entries; tile count = stock + new, sec2 padded)
    # offsets AFTER the pad (2026-11-24 hardware READY freeze): the header's sec3 offset must be the real, word-aligned
    # sec3 start.  Taken before the pad it pointed 1-3 bytes early: sec3 reads shifted, and the L1b REMAP probe
    # `lw 0(sec3 base)` raised AdEL on real R3000s (MiSTer: EPC 0x801fd374, BadVaddr odd) = freeze at Strider's intro.
    offs = [0x14, 0x14 + len(s0), 0x14 + len(s0) + len(s1), 0x14 + len(s0) + len(s1) + len(s2)]
    assert all(o % 4 == 0 for o in offs), offs
    dspf = struct.pack("<5I", 8, *offs) + bytes(s0) + bytes(s1) + bytes(s2) + n.sec[3]
    ap8 = (b"MA81" + struct.pack("<4I", pb.B, nf0, nf0 + len(newids), len(recpatch)) +
           b"".join(struct.pack("<I", v) for v in newids) + b"".join(struct.pack("<2I", a, f) for a, f in recpatch))
    stats["stock: ambiguous record"] = ambiguous
    info = dict(ch=ch, bank=bank, anims=anims, matched=matched, records=len(pairs), stats=dict(stats), skipped=dict(skipped),
                new_frames=len(newids), new_tiles=newtile, stock_dsp=len(n.d), dsp=len(dspf), ap8=len(ap8),
                frames=nf0 + len(newids), tiles=len(s2) // 5, sec1=len(s1))
    return dspf, ap8, info


def check(dspf, ap8, ps1, ch):
    """the restored file parses, its old frames are the stock ones, every patched record's new frame exists"""
    n = dsp.DSP(dspf); st = dsp.DSP(ps1.get("SP_PL%02X.DSP" % ch))
    assert n.sec[0][:len(st.sec[0])] == st.sec[0] and n.sec[2][:5 * len(st.tiles)] == st.sec[2][:5 * len(st.tiles)]
    assert n.sec[3] == st.sec[3], "sec3 differs from the stock file's (section offsets)"
    assert all(struct.unpack_from("<I", dspf, 4 + 4 * k)[0] % 4 == 0 for k in range(4)), "DSP section offset not word-aligned"
    m, boff, nf0, nf, nr = struct.unpack_from("<4s4I", ap8)
    ids = struct.unpack_from("<%dI" % (nf - nf0), ap8, 20)
    n.decode_all()
    for i in ids:
        hdr, g = group_at(n, i & 0xffff)
        for p in g:
            t = n.tiles[p.tile]; c = p.b3 & 15; r = p.b3 >> 4
            assert c + t.w // 16 <= hdr[0] and r + t.h // 16 <= hdr[1]


def group_at(n, off):
    s = n.sec[1]; cnt = s[off] | s[off + 1] << 8; p = off + 6; g = []
    for k in range(cnt):
        pt = dsp.parse_part(s, p); g.append(pt); p += pt.size
    return s[off + 2:off + 6], g


def sheet(ctx_unused, dspf, ap8, out, limit=120):
    n = dsp.DSP(dspf); n.decode_all()
    m, boff, nf0, nf, nr = struct.unpack_from("<4s4I", ap8)
    ids = struct.unpack_from("<%dI" % (nf - nf0), ap8, 20)
    ims = [dsp.render_group(n, group_at(n, i & 0xffff)[1]) for i in ids[:limit]]
    dsp.sheet(ims, out, cols=12)


R8MAGIC = 0x31463852                                   # 'R8F1'


ASSIST = 0x100                                         # R8 word 1 = ASSIST | id for a special partner (DAxx_11.A0)


def r8_file(ps1, ch, dspf, ap8, restored, assist=False):
    """MA81 patch (build) + restored DSP -> PLxx.R8 / DAxx.R8 (format in the module doc; assists: item offset = section 0
    offset, H = 0, word 1 = ASSIST | id)"""
    m, boff, nf0, nf, nr = struct.unpack_from("<4s4I", ap8)
    assert m == b"MA81"
    if assist: A0 = ps1.da(ch)[0]; H = 0
    else: A0 = ps1.get("PL%02X_10.A0" % ch); H = ps1.h0(ch)
    T = boff + struct.unpack_from("<I", A0, boff + 8)[0]
    stock = [struct.unpack_from("<I", A0, T + 4 * i)[0] for i in range(nf0)]
    newids = list(struct.unpack_from("<%dI" % (nf - nf0), ap8, 20))
    pat = [struct.unpack_from("<2I", ap8, 20 + 4 * (nf - nf0) + 8 * k) for k in range(nr)]
    pb = bytearray()
    for ra, fnew in pat:
        w1 = struct.unpack_from("<H", A0, ra + 2)[0]
        fold = A0[ra] | ((w1 >> 12) & 7) << 8
        assert fnew < 2048 and fold < nf0
        pb += struct.pack("<IHH", H + ra, fnew, fold)
    tab = struct.pack("<%dI" % nf, *(stock + newids))
    po = 64; to = po + len(pb); do = (to + len(tab) + 15) & ~15
    size = do + len(dspf)
    hdr = struct.pack("<16I", R8MAGIC, ch | (ASSIST if assist else 0), len(dspf), do, to, nf, nf0, H + boff, nr, po, size, restored, 0, 0, 0, 0)
    out = hdr + bytes(pb) + tab
    return out + bytes(do - len(out)) + dspf


def r8_parse(r):
    """PLxx.R8 -> (char, DSP bytes, MA81 patch bytes as build() made it, H) (audits read the shipped file back)"""
    w = struct.unpack_from("<16I", r, 0)
    assert w[0] == R8MAGIC
    ch, dn, do, to, nf, nf0, bo, m, po = w[1:10]
    H = 0 if ch & ASSIST else 0x24 if ch == 0x11 else 0x1c
    pat = [struct.unpack_from("<IHH", r, po + 8 * k) for k in range(m)]
    tab = struct.unpack_from("<%dI" % nf, r, to)
    ap8 = (b"MA81" + struct.pack("<4I", bo - H, nf0, nf, m) + b"".join(struct.pack("<I", v) for v in tab[nf0:]) +
           b"".join(struct.pack("<2I", a - H, f) for a, f, o in pat))
    return ch, r[do:do + dn], ap8, H


def open_arcade(paths):
    """-> (ctx, chtab, desc) for the user's arcade set"""
    prg, roms, desc = read_arcade(paths)
    gcache = os.path.join(GAME, "work", "ap", "gfx_%s.npy" % desc["13m"][:12])
    if os.path.exists(gcache): G = np.load(gcache)
    else:
        G = aplib.gfx_decode(lambda r: roms[r]); os.makedirs(os.path.dirname(gcache), exist_ok=True); np.save(gcache, G)
    return prg, G, desc


def setup(paths, disc):
    """-> (ctx, ps1, chtab, desc): what main() reads once (the web patcher's sub-workers keep it for their jobs)"""
    prg, G, desc = open_arcade(paths)
    ps1 = PS1Files(disc)
    chtab = find_chtab(prg, ps1_firsts(ps1))
    return aplib.Ctx(prg, G, None, chtab=chtab), ps1, chtab, desc


def char_r8(ctx, ps1, ch, chtab, out, man, sheet_=False):
    """one character: PLxx.R8 into out, its manifest entry into man["chars"]"""
    try:
        dspf, ap8, info = build(ctx, ps1, ch, chtab)
        check(dspf, ap8, ps1, ch)
        if not info["stats"].get("restored", 0):    # nothing restored: the stock sprite file exactly, no patches
            m_, boff, nf0, nf, nr = struct.unpack_from("<4s4I", ap8)
            dspf, ap8 = ps1.get("SP_PL%02X.DSP" % ch), b"MA81" + struct.pack("<4I", boff, nf0, nf0, 0)
    except Fail as e:
        print("%02X: not restored: %s" % (ch, e)); man["chars"]["%02X" % ch] = dict(error=str(e)); return
    r8 = r8_file(ps1, ch, dspf, ap8, info["stats"].get("restored", 0))
    c2, d2, a2, H = r8_parse(r8)
    assert c2 == ch and d2 == dspf and a2 == ap8, "R8 round trip"
    open(os.path.join(out, "PL%02X.R8" % ch), "wb").write(r8)
    info["sha1"] = dict(r8=hashlib.sha1(r8).hexdigest())
    info["r8"] = len(r8)
    man["chars"]["%02X" % ch] = info
    print("%02X: %d/%d anims paired, %d records: %s; new frames %d, new tiles %d, file %d -> %d, R8 %d, skipped %s" % (
        ch, info["matched"], info["anims"], info["records"], info["stats"], info["new_frames"], info["new_tiles"],
        info["stock_dsp"], info["dsp"], len(r8), info["skipped"]), flush=True)
    if sheet_: sheet(ctx, dspf, ap8, os.path.join(out, "new_%02X.png" % ch))


def assist_r8(ctx, ps1, x, chtab, out, man):
    """one special partner: DAxx.R8 into out, its entry into man["assists"] (every assist gets a record: stock frame
    table, undoes the 2 MB --ascut cuts on 8 MB; restored frames where any)"""
    try:
        dspf, ap8, info = build(ctx, ps1, x, chtab, assist=True)
        if not info["stats"].get("restored", 0): raise Fail("nothing restored")
    except Fail as e:                                # (no arcade match: stock sprite file + table, no patches)
        A0, D0 = ps1.da(x); pb = Blob(A0, bytes([4, 0]))
        dspf, ap8 = D0, b"MA81" + struct.pack("<4I", pb.B, pb.nframes(), pb.nframes(), 0)
        info = dict(stats={}, new_frames=0, note=str(e))
    r8 = r8_file(ps1, x, dspf, ap8, info["stats"].get("restored", 0), assist=True)
    c2, d2, a2, H = r8_parse(r8)
    assert c2 == ASSIST | x and d2 == dspf and a2 == ap8, "R8 round trip"
    open(os.path.join(out, "DA%02X.R8" % x), "wb").write(r8)
    man["assists"]["%02X" % x] = dict(restored=info["stats"].get("restored", 0), new_frames=info["new_frames"],
                                      r8=len(r8), sha1=hashlib.sha1(r8).hexdigest(), note=info.get("note", ""))
    print("assist %02X: restored %d records, new frames %d, R8 %d %s" % (x, info["stats"].get("restored", 0),
          info["new_frames"], len(r8), info.get("note", "")), flush=True)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--arcade", nargs="+", required=True)
    ap.add_argument("--disc", default=os.path.join(GAME, "disc", "mvc.bin"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--chars", default="")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args(argv[1:])
    prg, G, desc = open_arcade(a.arcade)
    ps1 = PS1Files(a.disc)
    chtab = find_chtab(prg, ps1_firsts(ps1))
    ctx = aplib.Ctx(prg, G, None, chtab=chtab)
    chars = [int(c, 16) for c in a.chars.split(",")] if a.chars else list(range(1, 0x17))
    os.makedirs(a.out, exist_ok=True)
    man = dict(arcade=desc, chtab=chtab, chars={})
    for ch in chars: char_r8(ctx, ps1, ch, chtab, a.out, man, a.sheet)
    man["assists"] = {}
    for x in range(0x16): assist_r8(ctx, ps1, x, chtab, a.out, man)
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    try: main(sys.argv)
    except Fail as e: sys.exit("error: " + str(e))
