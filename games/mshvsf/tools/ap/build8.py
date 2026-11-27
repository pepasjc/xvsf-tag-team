"""MSHvSF 8 MB "arcade frames" content builder: restores the animation frames the PS1 port dropped.

    python build8.py --arcade SET.zip [PARENT.zip ...] --disc mshvsf.bin --out OUTDIR [--chars 1,2,9] [--sheet]

Reads the user's own arcade ROM set (CPS2 Marvel Super Heroes vs. Street Fighter: program ROMs .03-.10, graphics
.13m-.20m) and the user's own PS1 disc (SLUS-00793) and writes per restored character xx (hex id):
    OUTDIR/SP_PLxx.DSP   the stock sprite file + appended tiles (stock RLE), frames (sec1 groups)
    OUTDIR/PLxx.AP8      animation patch for PLxx_10.A0 (format below), applied by the 8 MB loader (tools/ap8/ap8.c)
    OUTDIR/manifest.json
Everything in OUTDIR is derived from the two inputs and must never be committed or shipped.  This file holds no data
from either: the tables are located by structure.

How (same engine as X-Men vs. Street Fighter; see the XvSF notes work/ap/SPEC.md):
  * arcade: per-character animation tables (pointer table of 26 longs, the last three repeat entries 2, 8, 7), records
    of 16 bytes (u16, u16 end|duration, u32 sprite definition, 8 bytes); sprite definitions = lists of CPS2 blocks
    (code, nx, ny, attribute) with positions.
  * PS1: the same tables in the character overlay PLxx_10.A0 ("blob": 4 x u32 offsets: group table, records, frame-id
    table, info records), records of 4 bytes (info | duration << 9, frame index (12 bits) | 0x8000 end; end records
    +4 bytes); frame id = 0xffff << 16 | offset of a frame (group) in sec1 of SP_PLxx.DSP.
  * every animation whose record count is the same on both sides is paired record by record.  A record whose PS1
    frame does not show its arcade sprite (the port reused a neighbouring frame) gets a new frame built from the
    arcade sprite: one tile per arcade block (deduplicated against the stock tiles by pixels), flags = the arcade
    attribute (palette, flips), VRAM rectangle packed in 16-pixel cells.
  * kept as stock: frames with a sec3 record or a shared VRAM slot (effects that share a slot), sprites larger than
    15 x 15 cells, more than MAXPARTS parts or more decoded bytes than the largest stock frame, and KEEP_STOCK.

PLxx.AP8 (little endian): 'MA81', u32 blob offset in PLxx_10.A0, u32 frames in the stock frame-id table, u32 frames
after the patch (n), u32 record patches (m), then (n - stock) u32 new frame ids, then m x (u32 record offset in
PLxx_10.A0, u32 new frame index).  The loader copies the stock table + the new ids behind the character's code,
points the blob's table offset (blob + 8, read by the game at run time) at the copy and rewrites the records' frame
index (byte 0 and bits 12-14 of the second half-word).
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
NFRAMES = 2048                   # 11-bit frame index (record byte 0 + bits 12-14 of its second word)
INTRO_FX = {}                    # {char: {animation groups}}: effect animations whose frames use a SHARED VRAM slot (group
                                 # header byte 2) or flag-0x80 parts are restored too (mkap8 --introfx; 2026-11-24:
                                 # Blackheart's intro pool / bubbles / creatures = group 19); the new frame keeps the stock
                                 # frame's slot and must fit its rectangle
INTRO_FX_SET = {8: {(19, 13), (19, 14), (19, 67)}}   # Blackheart's pool: the three bubbling halves (4 frames each)
SLICE_GROUPS = {0}               # animation groups whose slice records are restored (0 = movement: walk; cache arena budget)
KEEP_STOCK = {}                  # {char: [(group, index)]} animations kept stock for speed (filled after measuring)
GFXROMS = ["13m", "14m", "15m", "16m", "17m", "18m", "19m", "20m"]


class Fail(Exception):
    pass


# ------------------------------------------------------------------------------------------------ inputs
# (2026-11-27) program ROMs .03-.10 (SHA-1, in that order) of the MAME / FBNeo sets of this game: in a MERGED zip (the
# parent with every clone inside) the files of one set are chosen together, never a mix of revisions
PRG_SETS = {
    "mshvsf": ("61bd581ea4b969298f8a39fe03023b5456cac750", "2d45dbf7bc277b84c6bcd9615ab3b80c42af7781", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfa": ("6a129274711765bbf5acbb225e3fce6d93d7f421", "758fc9c453a864e32588c7fb33166c93e798a39c", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfa1": ("34e6a074734032af74afa52bfebbc213a9c886d7", "f340dda7d5339645fd1ea523e72783fb7bb7aba1", "1b368ebe7680796dc068b511b72359eec546cd9f", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfb": ("0664fad64996118df86e9887bd6e301d04d84978", "a16f262fd14e726c7837980d0556a9c3bdc7fb11", "b813082a480d42d663c713062892245faabe9101", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfb1": ("85d0026a691682c195d6e617bf28def50029cb03", "c6fa2b8b727a1192fd21131496067447053b5547", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfcph": ("6c13774ef6d9e295ef8fc38b51220143e29b6373", "2d45dbf7bc277b84c6bcd9615ab3b80c42af7781", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfem": ("7dc683ed8cf5bc205851375deab0438a1105d581", "36db3a3aeaf29369977593c051bf5665cffefb2d", "924a7c82456bb44d7b0be65af11dbe1a2420a3f0", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfh": ("dd926a9cac4bff05845615d0b61948e2dc4b1ed8", "594e4383eb776c09075577cd1f4e42ef11748f0f", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfj": ("16820cf3bc7285477e61bd598a3ed4ea5e0e770d", "36db3a3aeaf29369977593c051bf5665cffefb2d", "924a7c82456bb44d7b0be65af11dbe1a2420a3f0", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfj1": ("b2d8a62e394c2eb4070cac742b0f403252e46a25", "ecac71b032b431c63a4cf73a1d1d1be1faebc12b", "eafa877fd4a4e58e7c98336658e986a4a27d6b91", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfj2": ("e9fb93249e48e1bb7c769c3ce674dd4be404574f", "471e44268cebba631b81f131bf31e27b8a28c548", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfu": ("939fb1e3c06c33fc212b26ecfceac3180e108e9d", "787924e04508c83ecd4c3a872882d2be9e57eb50", "b813082a480d42d663c713062892245faabe9101", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfu1": ("1fa7e6534d02ec8059153705b1161a55b9cfe803", "e95f7a3fb281e1bafdbe7a1b22532c4fab5ec89d", "738a27f83704c208d36d73bf766d861ef2d51a89", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
    "mshvsfu1d": ("53ab6df85a900b221cabd62948e68d91cf6146e4", "51ebede487f955e3f838b7906b619830e67fea52", "777bf7c74110c029c44a363ce79e50c1863950c2", "fbbaa915324815246738f3426232e623f039ce26", "683da09c5ba55e31b59aa95a8e13c45dc574ab3c", "49e5d4bc48f90c8146cb6aafb9240aff0119f1a7", "9ab132a3cac55fcccebe6c99b6fb0ba1305f8f6e", "f4c1f8a6e7a79ecc6241d5268b3039f8a09ea516"),
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
                        " (a clone zip needs its parent zip too).  Supported: mshvsf or any of its clones (mshvsfu, mshvsfj ...), merged or "
                        "non-merged zip, or a split clone zip together with mshvsf.zip")
    def sw(d):
        a = np.frombuffer(d, dtype=np.uint8); b = a.copy(); b[0::2] = a[1::2]; b[1::2] = a[0::2]; return b.tobytes()
    prg = b"".join(sw(roms[k]) for k in ("03", "04", "05", "06", "07", "08", "09", "10"))
    desc = {k: hashlib.sha1(v).hexdigest() for k, v in sorted(roms.items())}
    return prg, roms, desc


def find_chtab(D):
    """26 longs -> per-character animation tables (word table, first word = 2 * groups), entries 23/24/25 = 2/8/7"""
    for a in range(0, len(D) - 104, 2):
        v = struct.unpack_from(">26I", D, a)
        if v[23] != v[2] or v[24] != v[8] or v[25] != v[7]: continue
        if not all(0x1000 <= x < len(D) - 2 and not x & 1 for x in v): continue
        if all(D[x] == 0 and 0x30 <= D[x + 1] <= 0x40 and not D[x + 1] & 1 for x in v): return a
    raise Fail("animation pointer table not found in the arcade program ROMs")


class PS1Files:
    def __init__(self, disc):
        from iso import Disc
        self.d = Disc(disc); self.files = {}
        for full, lba, sz, fl in self.d.walk():
            self.files[full.split("/")[-1].split(";")[0]] = (lba, sz)

    def get(self, name):
        lba, sz = self.files[name]
        return self.d.read(lba, sz)


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
def build(ctx, ps1, ch, chtab):
    A0 = ps1.get("PL%02X_10.A0" % ch)
    T = ctx.be32(chtab + 4 * ch); first = ctx.D[T + 1:T + 2] + ctx.D[T:T + 1]
    pb = Blob(A0, first)
    n = dsp.DSP(ps1.get("SP_PL%02X.DSP" % ch)); n.decode_all()
    gr = {off: (hdr, g) for off, hdr, g in n.groups()}
    ag = ctx.arc_groups(T); pg = pb.groups()
    keep = set(KEEP_STOCK.get(ch, ()))
    pairs = []; anims = matched = 0; anim_recs = []; rec_group = {}; rec_anim = {}
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
            for y in pr: rec_group.setdefault(y[0], k); rec_anim.setdefault(y[0], (k, j))
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
        if hdr[2] or hdr[3] or any(p.flags & 0x80 or p.tile >= len(n.tiles) for p in g): return None
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
    if bank is None: raise Fail("character %02X: the PS1 sprite file and the arcade graphics do not match" % ch)

    def arc_img(s):
        return canvas([(x, y, flip(ctx.block(c, nx, ny, bank), lo)) for c, nx, ny, lo, x, y in ctx.arc_parts(s)])

    # tiles of the stock file by pixels (exact shape)
    tmap = {}
    for t in n.tiles: tmap.setdefault((t.wb, t.h, t.raw), t.idx)
    s0 = bytearray(n.sec[0]); s1 = bytearray(n.sec[1]); s2 = bytearray(n.sec[2])
    s1 += bytes(-len(s1) % 4)
    newtile = 0
    def tile_for(px):
        nonlocal newtile
        raw = tile_bytes(px); wb = px.shape[1] // 2; h = px.shape[0]
        key = (wb, h, raw)
        if key in tmap: return tmap[key]
        idx = len(s2) // 4
        if idx >= 4096: raise OverflowError("tiles")
        off = len(s0)
        s0.extend(rle_encode(raw)); s0.extend(bytes(-len(s0) % 2))
        s2.extend(struct.pack("<I", off | (wb // 8 - 1) << 24 | (h // 16 - 1) << 28))
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
    order = pairs
    if INTRO_FX.get(ch):                         # intro effect records first (sec1 64 KB budget: they get room first)
        order = [p for p in pairs if rec_anim.get(p[1][0]) in INTRO_FX[ch]] + [p for p in pairs if rec_anim.get(p[1][0]) not in INTRO_FX[ch]]
    for x, (ra, fi, dur, end) in order:
        s = x.spr
        pimg = imgcache[fi]
        # the port's slice frames (frame id high half != 0xffff: a cheap variant of a whole group, e.g. Blackheart's
        # walk = one gliding pose) cannot be drawn statically, so they are never "kept"; they are restored like the
        # other records of their animation (2026-11-24 ground-truth audit gt8.py: the stock walk pose is WRONG vs the
        # arcade walk; before, the no-MIXED rule left the whole walk stock).  Other special frames (sec3 records,
        # shared VRAM slots, flag 0x80 parts) stay stock.
        slice_ = pb.frameid(fi) >> 16 != 0xffff and rec_group.get(ra) in SLICE_GROUPS
        shared = None                            # (W, H, slot, b3) of a shared-slot stock frame (INTRO_FX groups)
        if pimg is None and not slice_ and rec_anim.get(ra) in INTRO_FX.get(ch, ()) and pb.frameid(fi) >> 16 == 0xffff                 and (pb.frameid(fi) & 0xffff) in gr:
            hd = gr[pb.frameid(fi) & 0xffff][0]
            if not hd[3]: shared = (hd[0], hd[1], hd[2], hd[3]); stats["intro fx (shared slot)"] += 1
        if pimg is None and not slice_ and shared is None: stats["stock: special frame"] += 1; continue
        if slice_: stats["slice restored"] += 1
        if not ctx.valid_def(s): stats["stock: arcade sprite not readable"] += 1; continue
        if kept.get(fi) == s: stats["stock frame kept"] += 1; shows.add(ra); continue
        nk = s if shared is None else (s, shared)
        if nk not in newframe:
            newframe[nk] = None
            ap = ctx.arc_parts(s)
            blocks = [(nx + 1, ny + 1) for c, nx, ny, lo, xx, yy in ap]
            raw = sum(w * h * 128 for w, h in blocks)
            if len(ap) > MAXPARTS: skipped["parts"] += 1; continue
            if raw > MAXRAW: skipped["decoded size"] += 1; continue
            mw, mh = (MAXW, MAXH) if shared is None else (shared[0], shared[1])
            if max(w for w, h in blocks) > mw or max(h for w, h in blocks) > mh: skipped["block"] += 1; continue
            pk = pack(blocks, mw, mh)
            if pk is None and shared is not None:   # too big for the shared slot: a frame of its own (own VRAM rectangle)
                pk = pack(blocks, MAXW, MAXH)
                if pk is not None: shared = (pk[0], pk[1], 0, 0); stats["intro fx own rectangle"] += 1
            if pk is None: skipped["vram rectangle" + ("" if shared is None else " (shared slot)")] += 1; continue
            W, H, pos = pk
            if shared is not None and shared[2]: W, H = shared[0], shared[1]      # the slot's rectangle, as the stock frame
            if nf0 + len(newids) >= NFRAMES: skipped["frame index"] += 1; continue
            try:
                parts = [enc_part(lo & 0x7f, tile_for(ctx.block(c, nx, ny, bank)), pos[i][1] << 4 | pos[i][0], xx, yy)
                         for i, (c, nx, ny, lo, xx, yy) in enumerate(ap)]
            except OverflowError:
                skipped["tiles"] += 1; continue
            off = len(s1)
            rec = struct.pack("<H", len(ap)) + bytes([W, H, 0 if shared is None else shared[2], 0]) + b"".join(parts)
            if off + len(rec) > 0xffff: skipped["sec1 64 KB"] += 1; continue
            s1 += rec + bytes(-len(rec) % 2)
            newframe[nk] = nf0 + len(newids); newids.append(0xffff0000 | off)
        if newframe[nk] is None: stats["stock: limits"] += 1; continue
        recpatch.append((ra, newframe[nk])); stats["restored"] += 1
        if shared is not None: stats["intro fx restored"] += 1
    # no mixed animations: a paired animation either gets every record that needs an arcade sprite, or none.  (The
    # port drew some animations as one frame + its slice variants (frame ids without 0xffff, e.g. Blackheart's walk:
    # frame 3 + slices 4..9 of the same group); those records stay stock (no image to compare), so restoring only the
    # others made the walk alternate between arcade poses and the stock pose - the 1.0 "Blackheart walk" bug.)
    patched = {ra for ra, f in recpatch}
    while True:
        bad = set()
        for recs in anim_recs:
            if any(r in patched for r in recs) and any(r not in patched and r not in shows for r in recs):
                bad |= {r for r in recs if r in patched}
        if not bad: break
        patched -= bad
    stats["stock: mixed animation"] = sum(1 for ra, f in recpatch if ra not in patched)
    stats["restored"] -= stats["stock: mixed animation"]
    recpatch = [(ra, f) for ra, f in recpatch if ra in patched]
    s0 += bytes(-len(s0) % 4); s1 += bytes(-len(s1) % 4)
    offs = [0x14, 0x14 + len(s0), 0x14 + len(s0) + len(s1), 0x14 + len(s0) + len(s1) + len(s2)]
    dspf = struct.pack("<5I", 6, *offs) + bytes(s0) + bytes(s1) + bytes(s2) + n.sec[3]
    ap8 = (b"MA81" + struct.pack("<4I", pb.B, nf0, nf0 + len(newids), len(recpatch)) +
           b"".join(struct.pack("<I", v) for v in newids) + b"".join(struct.pack("<2I", a, f) for a, f in recpatch))
    stats["stock: ambiguous record"] = ambiguous
    info = dict(ch=ch, bank=bank, anims=anims, matched=matched, records=len(pairs), stats=dict(stats), skipped=dict(skipped),
                new_frames=len(newids), new_tiles=newtile, stock_dsp=len(n.d), dsp=len(dspf), ap8=len(ap8),
                frames=nf0 + len(newids), tiles=len(s2) // 4, sec1=len(s1))
    return dspf, ap8, info


def check(dspf, ap8, ps1, ch):
    """the restored file parses, its old frames are the stock ones, every patched record's new frame exists"""
    n = dsp.DSP(dspf); st = dsp.DSP(ps1.get("SP_PL%02X.DSP" % ch))
    assert n.sec[0][:len(st.sec[0])] == st.sec[0] and n.sec[2][:len(st.sec[2])] == st.sec[2]
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


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--arcade", nargs="+", required=True)
    ap.add_argument("--disc", default=os.path.join(GAME, "disc", "mshvsf.bin"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--chars", default="")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--introfx", action="store_true")     # INTRO_FX: Blackheart's intro effect animations (group 19)
    a = ap.parse_args(argv[1:])
    if a.introfx: INTRO_FX.update(INTRO_FX_SET)
    prg, roms, desc = read_arcade(a.arcade)
    gcache = os.path.join(GAME, "work", "ap", "gfx_%s.npy" % desc["13m"][:12])
    if os.path.exists(gcache): G = np.load(gcache)
    else:
        G = aplib.gfx_decode(lambda r: roms[r]); os.makedirs(os.path.dirname(gcache), exist_ok=True); np.save(gcache, G)
    chtab = find_chtab(prg)
    ctx = aplib.Ctx(prg, G, None, chtab=chtab)
    ps1 = PS1Files(a.disc)
    chars = [int(c, 16) for c in a.chars.split(",")] if a.chars else list(range(0x17))
    os.makedirs(a.out, exist_ok=True)
    man = dict(arcade=desc, chtab=chtab, chars={})
    for ch in chars:
        try:
            dspf, ap8, info = build(ctx, ps1, ch, chtab)
            check(dspf, ap8, ps1, ch)
        except Fail as e:
            print("%02X: not restored: %s" % (ch, e)); man["chars"]["%02X" % ch] = dict(error=str(e)); continue
        open(os.path.join(a.out, "SP_PL%02X.DSP" % ch), "wb").write(dspf)
        open(os.path.join(a.out, "PL%02X.AP8" % ch), "wb").write(ap8)
        info["sha1"] = dict(dsp=hashlib.sha1(dspf).hexdigest(), ap8=hashlib.sha1(ap8).hexdigest())
        man["chars"]["%02X" % ch] = info
        print("%02X: %d/%d anims paired, %d records: %s; new frames %d, new tiles %d, file %d -> %d, skipped %s" % (
            ch, info["matched"], info["anims"], info["records"], info["stats"], info["new_frames"], info["new_tiles"],
            info["stock_dsp"], info["dsp"], info["skipped"]), flush=True)
        if a.sheet: sheet(ctx, dspf, ap8, os.path.join(a.out, "new_%02X.png" % ch))
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    try: main(sys.argv)
    except Fail as e: sys.exit("error: " + str(e))
