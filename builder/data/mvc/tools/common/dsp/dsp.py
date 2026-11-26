"""Capcom PS1 .DSP sprite files (Marvel Super Heroes vs. Street Fighter SLUS-00793, Marvel vs. Capcom
SLUS-01059): parser, exact model of the game's tile decoder, renderer.  Format notes: games/mshvsf/docs/DSP.md.

Layout (all little endian):
  +0   u32 kind     6 = tile table of u32 words (every MSHvSF file, MvC effect/select/VC files)
                    8 = tile table of 5-byte entries (MvC characters: the DSP inside DAT/PLxx_10.A0 / _20.A0,
                        and DAT/SP_xxX_0/1.DSP)
                    7 = multi-set file (SP_EFF0/1, SP_SEL0: header 0x60 = 23 offsets, 0xffffffff = unused); not
                        parsed here
  +4   u32 off[4]   section offsets from the file start (off[0] = 0x14)
  sec0 pixels       per-tile byte RLE streams (rle_decode); the tile table points into it
  sec1 groups       frames: u16 nparts, 4 bytes, then nparts part records of 6..8 bytes (parse_part)
  sec2 tile table   kind 6: u32  bits 0-21 offset into sec0, bit 23 flag, bits 24-27 bytes/8-1, 28-31 rows/16-1
                    kind 8: 5 bytes  u24 offset into sec0, u8 width in bytes, u8 rows
  sec3 animation / frame-script data (not pixels)

    python dsp.py info FILE [base]           sections, tiles, groups (base = byte offset of the DSP in FILE)
    python dsp.py render FILE OUT.png [base] [max]   contact sheet of assembled frames (sec1 groups)
    python dsp.py tiles FILE OUT.png [base]  tile atlas
"""
import os, sys, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def rle_decode(src, pos, n):
    """Exact model of the game's decoder (MSHvSF 0x8001bd68, MvC 0x8001bd48; same code as XvSF 0x8001b5b0):
    control byte c: c & 0xf0 -> run of (c >> 4) + 1 bytes (c & 15) * 0x11; else literal (c & 15) + 1 raw bytes.
    Stops when the output count reaches n (it is decremented per op, so a run may write past n; a literal is
    copied two bytes at a time from the end, i.e. an odd literal also stores one extra byte, later overwritten).
    -> (bytes[n], source bytes used, run overrun past n)"""
    out = bytearray(); p = pos
    while len(out) < n:
        b = src[p]; p += 1
        if b & 0xF0:
            out += bytes([(b & 15) * 0x11]) * ((b >> 4) + 1)
        else:
            c = (b & 15) + 1
            out += src[p:p + c]; p += c
    return bytes(out[:n]), p - pos, len(out) - n


def rle_encode(raw):
    """A valid stream for rle_decode (greedy; not the game's own encoder, used only for tests)."""
    out = bytearray(); i = 0; n = len(raw)
    while i < n:
        b = raw[i]
        if (b >> 4) == (b & 15):
            j = i
            while j < n and raw[j] == b and j - i < 16: j += 1
            if j - i >= 2 or True:
                out.append(((j - i - 1) << 4) | (b & 15)); i = j; continue
        j = i
        while j < n and j - i < 16 and not ((raw[j] >> 4) == (raw[j] & 15) and j + 1 < n and raw[j + 1] == raw[j]):
            j += 1
        if j == i: j = i + 1
        out.append(j - i - 1); out += raw[i:j]; i = j
    return bytes(out)


class Tile:
    __slots__ = ("idx", "off", "flag", "wb", "h", "raw", "clen", "over", "word", "ent")

    @property
    def w(self): return self.wb * 2

    @property
    def n(self): return self.wb * self.h


class Part:
    __slots__ = ("flags", "tile", "x", "y", "size", "xm", "ym", "b3")


def _s8(v): return v - 256 if v & 0x80 else v
def _s16(v): return v - 65536 if v & 0x8000 else v


def parse_part(d, p):
    """Model of MSHvSF 0x80082d9c (MvC 0x8008c6a8, normal branch): b0 flags (0x20 h-flip, 0x40 v-flip, 0x80 = reuse
    the previous decode), b1|b2<<8: tile (12 bits), x mode (bits 12-13), y mode (14-15); b3 nibbles (VRAM cell);
    then x, y: mode 3 = s16, 2 = -u8, 1 = u8, 0 = s8."""
    r = d[p:p + 8] + b"\0" * 8
    pt = Part(); pt.flags = r[0]; pt.b3 = r[3]
    v = r[1] | r[2] << 8
    pt.tile = v & 0xFFF; xm = (v >> 12) & 3; ym = v >> 14; pt.xm, pt.ym = xm, ym
    sm = lambda b, m: -b if m == 2 else (_s8(b) if m == 0 else b)
    if xm == 3 and ym == 3:
        pt.x = _s16(r[4] | r[5] << 8); pt.y = _s16(r[6] | r[7] << 8); pt.size = 8
    elif xm == 3:
        pt.x = _s16(r[4] | r[5] << 8); pt.y = sm(r[6], ym); pt.size = 7
    elif ym == 3:
        pt.x = sm(r[4], xm); pt.y = _s16(r[5] | r[6] << 8); pt.size = 7
    else:
        pt.x = sm(r[4], xm); pt.y = sm(r[5], ym); pt.size = 6
    return pt


class DSP:
    def __init__(self, data, base=0, name=""):
        if isinstance(data, str):
            name = name or os.path.basename(data); data = open(data, "rb").read()
        d = self.d = bytes(data[base:])
        self.name = name
        self.kind = struct.unpack_from("<I", d, 0)[0]
        assert self.kind in (6, 8), "kind %d not handled" % self.kind
        self.offs = list(struct.unpack_from("<4I", d, 4))
        assert self.offs[0] == 0x14
        self.end = len(d)
        o = self.offs + [self.end]
        self.sec = [d[o[i]:o[i + 1]] for i in range(4)]
        self.sizes = [len(s) for s in self.sec]
        s2 = self.sec[2]; self.tiles = []
        es = 4 if self.kind == 6 else 5
        for i in range(len(s2) // es):
            t = Tile(); t.idx = i; t.raw = None; t.clen = 0; t.over = 0
            if es == 4:
                w = struct.unpack_from("<I", s2, i * 4)[0]
                t.word = w; t.off = w & 0x3FFFFF; t.flag = (w >> 23) & 1
                t.wb = ((w >> 24 & 15) + 1) * 8; t.h = ((w >> 28) + 1) * 16
            else:
                e = s2[i * 5:i * 5 + 5]
                t.word = None; t.off = e[0] | e[1] << 8 | e[2] << 16; t.flag = e[3] >> 7; t.wb = e[3] & 0x7F
                t.h = e[4] & 0x7F if t.flag else e[4]       # MvC tag build option B: bit 7 = half-res tile (rows bit 7 = narrow)
            t.ent = s2[i * es:i * es + es]
            self.tiles.append(t)
        self.tail2 = s2[len(self.tiles) * es:]

    def decode_all(self):
        for t in self.tiles:
            if t.raw is None:
                t.raw, t.clen, t.over = rle_decode(self.sec[0], t.off, t.n)
        return self.tiles

    def groups(self):
        s = self.sec[1]; p = 0; out = []
        while p + 6 <= len(s):
            cnt = s[p] | s[p + 1] << 8; hdr = s[p + 2:p + 6]; start = p; p += 6; g = []
            for k in range(cnt):
                pt = parse_part(s, p); g.append(pt); p += pt.size
            if p > len(s): break
            out.append((start, hdr, g))
        self.sec1_tail = len(s) - p
        return out

    def stats(self):
        self.decode_all()
        used = set()
        for t in self.tiles: used.add((t.off, t.clen))
        return dict(file=len(self.d), header=0x14, pixels=self.sizes[0], groups=self.sizes[1], tiletab=self.sizes[2],
                    anim=self.sizes[3], tiles=len(self.tiles), raw=sum(t.n for t in self.tiles),
                    uniq=len({(t.wb, t.raw) for t in self.tiles}), streams=sum(c for o, c in used))


def char_dsp(game, cid, which=0):
    """-> (bytes of the whole container, base offset of the DSP, label).  MSHvSF: DAT/SP_PLxx.DSP.
    MvC: the DSP inside DAT/PLxx_10.A0 (A0 header u32 3, offsets; the DSP is the 3rd part)."""
    if game == "mshvsf":
        p = os.path.join(ROOT, "games", "mshvsf", "work", "dsp", "files", "SP_PL%02X.DSP" % cid)
        return open(p, "rb").read(), 0, "SP_PL%02X" % cid
    p = os.path.join(ROOT, "games", "mvc", "work", "dsp", "files", "PL%02X_%d0.A0" % (cid, 1 + which))
    b = open(p, "rb").read()
    return b, struct.unpack_from("<I", b, 12)[0], "PL%02X_%d0" % (cid, 1 + which)


def char_ids(game):
    if game == "mshvsf": return list(range(0x17))
    import glob
    return sorted(int(os.path.basename(f)[2:4], 16) for f in glob.glob(os.path.join(ROOT, "games", "mvc", "work", "dsp", "files", "PL*_10.A0")))


def extract(game):
    """copy every .DSP (and MvC PL*.A0) from the disc image to games/<game>/work/dsp/files"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from iso import Disc
    out = os.path.join(ROOT, "games", game, "work", "dsp", "files"); os.makedirs(out, exist_ok=True)
    d = Disc(os.path.join(ROOT, "games", game, "disc", game + ".bin"))
    for full, lba, sz, fl in d.walk():
        n = full.split("/")[-1].split(";")[0]
        if n.endswith(".DSP") or (game == "mvc" and n.startswith("PL") and n.endswith(".A0")):
            open(os.path.join(out, n), "wb").write(d.read(lba, sz))


# ------------------------------------------------------------------------------------------- render
GRAY = [(i * 16, i * 16, i * 16) for i in range(15)] + [(40, 0, 60)]
TRANSP = 15


def tile_pixels(t):
    import numpy as np
    a = np.frombuffer(t.raw, dtype=np.uint8).reshape(t.h, t.wb)
    px = np.empty((t.h, t.wb * 2), dtype=np.uint8)
    px[:, 0::2] = a & 15; px[:, 1::2] = a >> 4
    return px


def render_group(dsp, g, pal=GRAY, transp=TRANSP):
    import numpy as np
    from PIL import Image
    boxes = [(pt, dsp.tiles[pt.tile]) for pt in g if pt.tile < len(dsp.tiles)]
    if not boxes: return None
    x0 = min(pt.x for pt, t in boxes); y0 = min(pt.y for pt, t in boxes)
    x1 = max(pt.x + t.w for pt, t in boxes); y1 = max(pt.y + t.h for pt, t in boxes)
    if x1 - x0 > 1024 or y1 - y0 > 1024: return None
    img = np.full((y1 - y0, x1 - x0), transp, dtype=np.uint8)
    for pt, t in reversed(boxes):
        px = tile_pixels(t)
        if pt.flags & 0x20: px = px[:, ::-1]
        if pt.flags & 0x40: px = px[::-1, :]
        reg = img[pt.y - y0:pt.y - y0 + t.h, pt.x - x0:pt.x - x0 + t.w]
        m = px != transp
        reg[m] = px[m]
    im = Image.fromarray(img, "P")
    im.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 3 * len(pal)))
    return im


def sheet(images, path, cols=8, pad=4):
    from PIL import Image
    images = [i for i in images if i is not None]
    if not images: return
    cw = max(i.width for i in images) + pad; ch = max(i.height for i in images) + pad
    rows = (len(images) + cols - 1) // cols
    S = Image.new("RGB", (cols * cw, rows * ch), (40, 0, 60))
    for k, im in enumerate(images):
        S.paste(im.convert("RGB"), ((k % cols) * cw, (k // cols) * ch))
    S.save(path)


def main():
    from collections import Counter
    cmd, path = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    if cmd == "info":
        x = DSP(path, int(rest[0], 0) if rest else 0); x.decode_all(); g = x.groups()
        print("kind", x.kind, "offs", [hex(o) for o in x.offs], "sizes", x.sizes, "tiles", len(x.tiles))
        print("stats", x.stats())
        print("dims", Counter((t.wb, t.h) for t in x.tiles).most_common(10))
        print("flag", Counter(t.flag for t in x.tiles), "overrun", Counter(t.over for t in x.tiles).most_common(5))
        print("groups", len(g), "sec1 tail", x.sec1_tail, "max tile ref", max(pt.tile for s, h, gg in g for pt in gg))
        print("part flags", Counter(hex(pt.flags) for s, h, gg in g for pt in gg).most_common(8))
    elif cmd == "render":
        out = rest[0]; base = int(rest[1], 0) if len(rest) > 1 else 0; mx = int(rest[2]) if len(rest) > 2 else 64
        x = DSP(path, base); x.decode_all(); g = x.groups()
        step = max(1, len(g) // mx)
        sheet([render_group(x, gg) for s, h, gg in g[::step][:mx]], out)
        print("wrote", out, min(mx, len(g)), "of", len(g))
    elif cmd == "tiles":
        from PIL import Image
        x = DSP(path, int(rest[1], 0) if len(rest) > 1 else 0); x.decode_all(); ims = []
        for t in x.tiles[:256]:
            im = Image.fromarray(tile_pixels(t), "P"); im.putpalette([c for rgb in GRAY for c in rgb] + [0] * 720); ims.append(im)
        sheet(ims, rest[0], cols=16, pad=2)


if __name__ == "__main__":
    main()
