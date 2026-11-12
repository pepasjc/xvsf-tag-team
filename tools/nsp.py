"""X-Men vs. Street Fighter (PS1, SLUS-00627) character sprite file (.NSP) parser/decoder.

Format (verified against the game code, see notes in each function):
  header: 4 x u32 LE section offsets (sec0..sec3)
  sec0: sprite-part records, variable length 5..7 bytes (parser 0x80057be4)
  sec1: u32 per tile: bits0-21 offset into sec2, bit23 flag, bits24-27 = bytes-wide/8-1,
        bits28-31 = rows/16-1 (parser 0x80057f48)
  sec2: per-tile byte-RLE of 4bpp packed pixel bytes (decoder 0x8001b5b0)
  sec3: animation/frame tables (not pixel data)

CLI:
  python nsp.py info FILE
  python nsp.py render FILE [outdir] [maxgroups]   -> PNG contact sheet of assembled part groups
  python nsp.py tiles FILE out.png                 -> tile atlas (first 256 tiles)
"""
import struct, sys, os, math


def rle_decode(src, pos, n):
    """Exact model of 0x8001b5b0(src, dst, n).
    Returns (bytes[n], consumed source bytes, overrun bytes past n)."""
    out = bytearray()
    p = pos
    while len(out) < n:
        b = src[p]; p += 1
        if b & 0xF0:                      # run: (hi+1) bytes of value lo*0x11
            out += bytes([(b & 0xF) * 0x11]) * ((b >> 4) + 1)
        else:                             # literal: (lo+1) raw bytes
            c = (b & 0xF) + 1
            out += src[p:p + c]; p += c
    return bytes(out[:n]), p - pos, len(out) - n


class Tile:
    __slots__ = ("idx", "off", "flag", "wb", "h", "raw", "clen", "over", "word")

    @property
    def w(self):
        return self.wb * 2          # pixels


class Part:
    __slots__ = ("flags", "tile", "x", "y", "size", "xm", "ym")


def _s8(v): return v - 256 if v & 0x80 else v
def _s16(v): return v - 65536 if v & 0x8000 else v


def parse_part(d, p):
    """Model of 0x80057be4. Returns Part (size = 5..7)."""
    r = d[p:p + 7] + b"\0" * 7
    pt = Part(); pt.flags = r[0]
    pt.tile = (r[1] | r[2] << 8) & 0xFFF
    xm = (r[2] >> 4) & 3; ym = r[2] >> 6
    pt.xm, pt.ym = xm, ym

    def small(v, m, plain=False):
        if m == 2: return -v
        if m == 0 and not plain: return _s8(v)
        return v
    if xm == 3 and ym == 3:
        pt.x = _s16(r[3] | r[4] << 8); pt.y = _s16(r[5] | r[6] << 8); pt.size = 7
    elif xm == 3:
        pt.x = _s16(r[3] | r[4] << 8); pt.y = small(r[5], ym); pt.size = 6
    elif ym == 3:
        pt.x = small(r[3], xm, plain=True); pt.y = _s16(r[4] | r[5] << 8); pt.size = 6
    else:
        pt.x = small(r[3], xm); pt.y = small(r[4], ym); pt.size = 5
    return pt


class NSP:
    def __init__(self, path):
        self.path = path
        d = self.d = open(path, "rb").read()
        self.offs = list(struct.unpack_from("<4I", d, 0))
        o = self.offs + [len(d)]
        self.sec = [d[o[i]:o[i + 1]] for i in range(4)]
        self.sizes = [len(s) for s in self.sec]
        s1 = self.sec[1]
        self.tiles = []
        for i in range(len(s1) // 4):
            w = struct.unpack_from("<I", s1, i * 4)[0]
            t = Tile(); t.idx = i; t.word = w
            t.off = w & 0x3FFFFF; t.flag = (w >> 23) & 1
            t.wb = ((w >> 24 & 15) + 1) * 8
            t.h = ((w >> 28) + 1) * 16
            t.raw = None; t.clen = 0; t.over = 0
            self.tiles.append(t)

    def decode_all(self):
        s2 = self.sec[2]
        for t in self.tiles:
            if t.raw is None:
                t.raw, t.clen, t.over = rle_decode(s2, t.off, t.wb * t.h)
        return self.tiles

    def groups(self):
        """sec0 walked sequentially; a group ends at a part with flags&0x80."""
        s0 = self.sec[0]; p = 0; g = []; out = []; start = 0
        while p + 5 <= len(s0):
            pt = parse_part(s0, p)
            if p + pt.size > len(s0): break
            g.append(pt); p += pt.size
            if pt.flags & 0x80:
                out.append((start, g)); g = []; start = p
        self.sec0_tail = len(s0) - start
        return out


def tile_pixels(t):
    """raw 4bpp packed (low nibble = left pixel, PS1 order) -> HxW uint8 index array."""
    import numpy as np
    a = np.frombuffer(t.raw, dtype=np.uint8).reshape(t.h, t.wb)
    px = np.empty((t.h, t.wb * 2), dtype=np.uint8)
    px[:, 0::2] = a & 15; px[:, 1::2] = a >> 4
    return px


GRAY = [(i * 16, i * 16, i * 16) for i in range(15)] + [(40, 0, 60)]
TRANSP = 15    # palette slot 15 is the transparent one in character sprites (observed)
FLIPX = 0x20   # part flag bits: 0x20 -> scratch+0x6c, 0x40 -> +0x6d in 0x80056340 (h/v flip)
FLIPY = 0x40


def render_group(nsp, g, pal=GRAY):
    import numpy as np
    from PIL import Image
    boxes = [(pt, nsp.tiles[pt.tile]) for pt in g if pt.tile < len(nsp.tiles)]
    if not boxes: return None
    x0 = min(pt.x for pt, t in boxes); y0 = min(pt.y for pt, t in boxes)
    x1 = max(pt.x + t.w for pt, t in boxes); y1 = max(pt.y + t.h for pt, t in boxes)
    if x1 - x0 > 1024 or y1 - y0 > 1024: return None
    img = np.full((y1 - y0, x1 - x0), TRANSP, dtype=np.uint8)
    for pt, t in reversed(boxes):
        px = tile_pixels(t)
        if pt.flags & FLIPX: px = px[:, ::-1]
        if pt.flags & FLIPY: px = px[::-1, :]
        reg = img[pt.y - y0:pt.y - y0 + t.h, pt.x - x0:pt.x - x0 + t.w]
        m = px != TRANSP
        reg[m] = px[m]
    im = Image.fromarray(img, "P")
    im.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 48))
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
    cmd = sys.argv[1]; n = NSP(sys.argv[2])
    if cmd == "info":
        n.decode_all()
        print("offsets", [hex(x) for x in n.offs], "sizes", n.sizes)
        print("tiles", len(n.tiles), "raw bytes", sum(len(t.raw) for t in n.tiles))
        print("dims (w px,h)", Counter((t.w, t.h) for t in n.tiles).most_common())
        print("flag", Counter(t.flag for t in n.tiles), "bit22", Counter(t.word >> 22 & 1 for t in n.tiles))
        print("overrun", Counter(t.over for t in n.tiles))
        g = n.groups()
        print("groups", len(g), "tail", n.sec0_tail)
        print("part flags", Counter(hex(pt.flags) for s, gg in g for pt in gg).most_common())
        print("max tile ref", max(pt.tile for s, gg in g for pt in gg))
        print("parts per group", Counter(len(gg) for s, gg in g).most_common(12))
    elif cmd == "render":
        out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "nsp_check")
        mx = int(sys.argv[4]) if len(sys.argv) > 4 else 64
        os.makedirs(out, exist_ok=True)
        n.decode_all(); g = n.groups()
        base = os.path.splitext(os.path.basename(n.path))[0]
        step = max(1, len(g) // mx)
        sel = g[::step][:mx]
        sheet([render_group(n, gg) for s, gg in sel], os.path.join(out, base + "_frames.png"))
        print("wrote", base, len(sel), "of", len(g))
    elif cmd == "tiles":
        n.decode_all()
        from PIL import Image
        ims = []
        for t in n.tiles[:256]:
            im = Image.fromarray(tile_pixels(t), "P")
            im.putpalette([c for rgb in GRAY for c in rgb] + [0] * 720); ims.append(im)
        sheet(ims, sys.argv[3], cols=16, pad=2)


if __name__ == "__main__":
    main()
