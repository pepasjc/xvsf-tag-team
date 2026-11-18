"""Arcade -> PS1 frame restoration library (X-Men vs. Street Fighter, 8 MB build).

Nothing in this file is derived from the arcade ROMs: every table is located in, and read from, the user's own set at run time.
See work/ap/SPEC.md for the formats.  Front end: build8.py.
"""
import os, sys, struct, collections, hashlib
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from nsp import NSP, tile_pixels, parse_part          # PS1 sprite file model (tools/nsp.py)

NAMES = ["Wolverine", "Cyclops", "Storm", "Rogue", "Gambit", "Sabretooth", "Juggernaut", "Magneto", "Apocalypse", "Ryu", "Ken", "Chun-Li",
         "Dhalsim", "Zangief", "M.Bison", "Akuma", "Charlie", "Cammy"]
MAXW, MAXH = 15, 15          # VRAM rectangle of one frame, 16-pixel cells
MAXRAW = 27392               # decoded bytes of one frame summed over its parts (largest stock frame)
MAXPARTS = 128
SHARED_CHARS = set()            # measured OK: {0, 5, 13, 17}; enable only when the loader installs the slot table
SHARED_OK = {0, 5, 13, 17}   # characters whose shared-slot (multi-instance effect) frames are restored: measured within 1 loop/60 of stock.
#                                 Not Storm (41.6/27 vs 50.2/31), Cyclops (specials 59.4/57 vs 60/60), Dhalsim (super 53.8/45 vs 57.6/53).  AP_SHARED=1: all.
# animations kept in their stock representation because the restored one measurably costs game speed: {character: [(group, index)]}
KEEP_STOCK = {            # measured with work/ap/rate_mv.py + bk_bisect2.py (4 alignments): the phase named loses more than 1 loop per 60 vblanks with the animation restored
    1: [(22, 0)],                                                        # Cyclops qcf+P
    2: [(1, 6), (1, 7), (22, 4), (22, 21), (22, 23)],     # Storm air qcf/qcb, qcb+PP super; (22, 4) = lightning-super pose: 45.2 vs stock 48.8 average on the built disc (not seen in the RAM-poke harness)
    3: [(21, 6)],                                                        # Rogue qcb+K, qcb+KK
    5: [(21, 8)],                                                        # Sabretooth qcf+P
    6: [(0, 1), (1, 1), (1, 3), (1, 6), (1, 7), (1, 8), (2, 2), (2, 3), (12, 0), (22, 3), (22, 4), (24, 1), (23, 0)],   # Juggernaut dash, jumps, hcb/hcf, supers
    7: [(1, 6), (3, 0), (10, 2), (5, 0), (14, 8), (23, 17)],             # Magneto super jump, hcb/hcf, rdp, qcf+KK and rdp supers
}


def s16(v): return v - 65536 if v & 0x8000 else v
def s8(v): return v - 256 if v & 0x80 else v


class Rec:
    __slots__ = ("addr", "w0", "end", "dur", "spr", "tail", "info", "frame")


# ---------------------------------------------------------------- CPS2 graphics
def gfx_decode(read):
    """read(n) -> bytes of graphics ROM n in '13m'..'20m'.  -> uint8 [0x40000, 16, 16] colour indices"""
    out = np.zeros(0x2000000, dtype=np.uint8)
    for base, names in ((0, ("13m", "15m", "17m", "19m")), (0x1000000, ("14m", "16m", "18m", "20m"))):
        for k, n in enumerate(names):
            d = np.frombuffer(read(n), dtype=np.uint8)
            out[base + 2 * k + 0:base + 0x1000000:8] = d[0::2]
            out[base + 2 * k + 1:base + 0x1000000:8] = d[1::2]
    q = out.view(np.uint64).copy()

    def unsh(a):
        n = len(a)
        if n == 2: return a
        h = n // 2; l = unsh(a[:h]); r = unsh(a[h:])
        return np.concatenate([l[:h // 2], r[:h // 2], l[h // 2:], r[h // 2:]])
    bank = 0x200000 // 8
    for i in range(0, len(q), bank): q[i:i + bank] = unsh(q[i:i + bank])
    g = q.view(np.uint8).reshape(-1, 16, 2, 4)
    bits = np.unpackbits(g, axis=3).reshape(-1, 16, 2, 4, 8)
    px = (bits[:, :, :, 3] << 3) | (bits[:, :, :, 2] << 2) | (bits[:, :, :, 1] << 1) | bits[:, :, :, 0]
    return px.reshape(-1, 16, 16).astype(np.uint8)


# ---------------------------------------------------------------- context
class Ctx:
    """D: arcade 68k program image from 0 (big-endian bytes); tiles: gfx_decode result; ps1: directory with the PS1 disc files"""

    def __init__(self, D, tiles, ps1, chtab=None):
        self.D = D; self.T = tiles; self.ps1 = ps1
        self.chtab = chtab if chtab is not None else find_chtab(D)

    def be16(self, a): return struct.unpack_from(">H", self.D, a)[0]
    def be32(self, a): return struct.unpack_from(">I", self.D, a)[0]

    # ---- arcade sprite definitions
    def arc_def(self, a):
        """variant 2: word 2, word cell count, word n-1, long pos, n x (word code, byte ny<<4|nx, byte attr low)
        variant 0: word 0, word n, word attr (shared), long pos, n x word code"""
        D = self.D; h0 = self.be16(a); h1 = self.be16(a + 2)
        if h0 == 0:
            at = self.be16(a + 4)
            return h0, h1, [(self.be16(a + 10 + 2 * i), (at >> 8) & 15, at >> 12, at & 0xff) for i in range(h1)], self.be32(a + 6)
        n = self.be16(a + 4) + 1
        return h0, h1, [(self.be16(a + 10 + 4 * i), D[a + 12 + 4 * i] & 15, D[a + 12 + 4 * i] >> 4, D[a + 13 + 4 * i]) for i in range(n)], self.be32(a + 6)

    def valid_def(self, s):
        D = self.D
        try:
            if not 0x100000 <= s < len(D) - 32: return False
            h0 = self.be16(s)
            if h0 == 0:
                n = self.be16(s + 2); at = self.be16(s + 4); pos = self.be32(s + 6)
                return 1 <= n <= 128 and (at & 0xff80) == 0 and 0x100000 <= pos < len(D) - 8 and self.be16(pos) in (0, 2)
            if h0 != 2: return False
            n = self.be16(s + 4) + 1; pos = self.be32(s + 6)
            if not (1 <= n <= 128 and 0x100000 <= pos < len(D) - 8 and self.be16(pos) in (0, 2)): return False
            c = 0
            for i in range(n):
                at = D[s + 12 + 4 * i]
                if D[s + 13 + 4 * i] & 0x80: return False
                c += ((at & 15) + 1) * ((at >> 4) + 1)
            return c == self.be16(s + 2)
        except Exception:
            return False

    def arc_parts(self, a):
        """-> [(code, nx, ny, attrlo, x, y)]; position table: word type (2 byte deltas, 0 word deltas), x0, y0, deltas from the previous part"""
        D = self.D; h0, h1, ent, pos = self.arc_def(a); ty = self.be16(pos)
        x = s16(self.be16(pos + 2)); y = s16(self.be16(pos + 4)); out = []
        for i, (c, nx, ny, lo) in enumerate(ent):
            if i:
                if ty == 2: x += s8(D[pos + 4 + 2 * i]); y += s8(D[pos + 5 + 2 * i])
                else: x += s16(self.be16(pos + 2 + 4 * i)); y += s16(self.be16(pos + 4 + 4 * i))
            out.append((c, nx, ny, lo, x, y))
        return out

    def block(self, code, nx, ny, bank):
        out = np.zeros((16 * (ny + 1), 16 * (nx + 1)), dtype=np.uint8)
        for j in range(ny + 1):
            for i in range(nx + 1):
                c = (code & ~0xf) + ((code + i) & 0xf) + 0x10 * j + bank
                out[16 * j:16 * j + 16, 16 * i:16 * i + 16] = self.T[c & 0x3ffff]
        return out

    # ---- arcade animation tables
    def arc_groups(self, T):
        n = self.be16(T) // 2; g = [self.be16(T + 2 * i) for i in range(n)]; out = []
        for k in range(n):
            if g[k] == 0: out.append([]); continue
            nxt = min([x for x in g if x > g[k]] + [10 ** 9])
            if nxt == 10 ** 9:
                lim = min(T + gg + o for gg in g if gg for o in
                          [x for x in (self.be16(T + gg + 2 * j) for j in range(((min([y for y in g if y > gg] + [gg + 2]) - gg) // 2))) if x])
                m = (lim - (T + g[k])) // 2
            else: m = (nxt - g[k]) // 2
            out.append([(T + g[k] + self.be16(T + g[k] + 2 * j)) if self.be16(T + g[k] + 2 * j) else None for j in range(m)])
        return out

    def arec(self, a):
        x = Rec(); x.addr = a; x.w0 = self.be16(a); w1 = self.be16(a + 2); x.end = w1 >> 15; x.dur = w1 & 0xff; x.spr = self.be32(a + 4); x.tail = self.D[a + 8:a + 16]
        return x

    def arc_walk(self, a, limit=400):
        out = []
        while len(out) < limit:
            r = self.arec(a); out.append(r); a += 16
            if r.end: break
        return out


def find_chtab(D):
    """the table of 19 longs -> per-character animation tables (each starts with a word table whose first entry is 2 * 28 groups)"""
    for a in range(0x80000, 0x100000 - 76, 2):
        v = struct.unpack_from(">19I", D, a)
        if not all(0x90000 <= x < 0x100000 and not x & 1 for x in v): continue
        if list(v[:18]) != sorted(v[:18]): continue
        if all(D[x] == 0 and 0x20 <= D[x + 1] <= 0x60 and not D[x + 1] & 1 for x in v): return a
    raise ValueError("animation pointer table not found in the program ROMs")


class PS1Blob:
    """animation data of a character overlay (P/P0/PLxx_10.BIN): header 4 x u32 offsets (tables, records, frame ids, info records)"""

    def __init__(self, ctx, ch):
        self.ch = ch
        P = self.P = open(os.path.join(ctx.ps1, "P", "P0", f"PL{ch:02X}_10.BIN"), "rb").read()
        T = ctx.be32(ctx.chtab + 4 * ch); first = ctx.D[T + 1:T + 2] + ctx.D[T:T + 1]
        i = -1
        while True:
            i = P.find(bytes.fromhex("10000000"), i + 1)
            if i < 0: raise ValueError("animation data not found in the overlay of character %d" % ch)
            if i % 4 == 0 and P[i + 0x10:i + 0x12] == first:
                h = struct.unpack_from("<4I", P, i)
                if 0x10 < h[1] < h[2] < h[3] < len(P): break
        self.B = i; self.h = h

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
            r = Rec(); r.addr = a; w0 = self.u16(a); w1 = self.u16(a + 2); r.info = w0 & 0x1ff; r.dur = w0 >> 9; r.frame = w1 & 0xfff; r.end = w1 >> 15
            out.append(r); a += 4
            if r.end: break
        return out

    def frameid(self, i): return struct.unpack_from("<I", self.P, self.B + self.h[2] + 4 * i)[0]
    def nframes(self): return (self.h[3] - self.h[2]) // 4
    def inforec(self, i): return self.P[self.B + self.h[3] + 16 * i:self.B + self.h[3] + 16 * i + 16]


def pairs_all(ctx, ch):
    """every PS1 animation record with its arcade record -> (blob, [(arcade rec, ps1 rec)], unpaired count)"""
    pb = PS1Blob(ctx, ch); ag = ctx.arc_groups(ctx.be32(ctx.chtab + 4 * ch)); pg = pb.groups(); m = {}
    for k in range(len(ag)):
        for j, a in enumerate(ag[k]):
            if a is None or j >= len(pg[k]): continue
            ar = ctx.arc_walk(a); pr = pb.walk(pg[k][j])
            if len(ar) != len(pr): continue
            for x, y in zip(ar, pr): m[y.addr] = x.addr
    p = pb.B + pb.h[1]; end = pb.B + pb.h[2]; out = []; un = 0; cur = None
    while p < end:
        w0 = pb.u16(p); w1 = pb.u16(p + 2)
        y = Rec(); y.addr = p; y.info = w0 & 0x1ff; y.dur = w0 >> 9; y.frame = w1 & 0xfff; y.end = w1 >> 15
        if p in m: cur = m[p]
        x = ctx.arec(cur) if cur is not None else None
        ok = x is not None and x.end == y.end and (x.dur == y.dur or x.dur > 126 or x.dur == 0) and (p in m or pb.inforec(y.info)[8:12] == x.tail[0:4])
        if ok: out.append((x, y)); cur += 16 + (4 if y.end else 0)
        else: un += 1; cur = None
        p += 4 + (4 if y.end else 0)
    return pb, out, un


# ---------------------------------------------------------------- PS1 encoders
def ps1_bytes(px):
    return (px[:, 0::2] | (px[:, 1::2] << 4)).astype(np.uint8).tobytes()


def rle_encode(raw):
    """stock sprite RLE: token hi != 0: run of hi+1 bytes of value lo*0x11; token 0x0N: N+1 literal bytes"""
    out = bytearray(); n = len(raw); i = 0; lit = bytearray()

    def flush():
        nonlocal lit
        for k in range(0, len(lit), 16):
            c = lit[k:k + 16]; out.append(len(c) - 1); out.extend(c)
        lit = bytearray()
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


def enc_part(flags, tile, x, y):
    """part record of section 0 (5..7 bytes)"""
    def mode(v, isx, other3):
        if -128 <= v <= 127 and not (isx and other3): return 0, bytes([v & 255])
        if 0 <= v <= 255: return 1, bytes([v])
        if -255 <= v <= 0: return 2, bytes([-v])
        return 3, struct.pack("<h", v)
    ym, yb = mode(y, False, False)
    xm, xb = mode(x, True, ym == 3)
    return bytes([flags, tile & 255, (tile >> 8) | xm << 4 | ym << 6]) + xb + yb


def pack(blocks, maxw=MAXW, maxh=MAXH):
    best = None
    order = sorted(range(len(blocks)), key=lambda i: (-blocks[i][1], -blocks[i][0], i))
    for W in range(max(b[0] for b in blocks), maxw + 1):
        occ = np.zeros((64, W), dtype=bool); pos = [None] * len(blocks); H = 0
        for i in order:
            w, h = blocks[i]; done = False
            for y in range(0, 64 - h):
                for x in range(0, W - w + 1):
                    if not occ[y:y + h, x:x + w].any():
                        occ[y:y + h, x:x + w] = True; pos[i] = (x, y); H = max(H, y + h); done = True; break
                if done: break
        if H <= maxh and (best is None or W * H < best[0] * best[1]): best = (W, H, pos)
    return best


# ---------------------------------------------------------------- the converter
def merge_parts(ap):
    """join pairs of single-cell parts that touch (same flags) into one 2x1 or 1x2 tile -> [(codes, kind, nx, ny, lo, x, y)]"""
    out = [((c,), "", nx, ny, lo, x, y) for c, nx, ny, lo, x, y in ap]
    for kind, dx, dy in (("h", 16, 0), ("v", 0, 16)):
        used = set(); res = []; pos = {}
        for i, (cs, k, nx, ny, lo, x, y) in enumerate(out):
            if k == "" and nx == 0 and ny == 0: pos.setdefault((x, y, lo), i)
        for i, (cs, k, nx, ny, lo, x, y) in enumerate(out):
            if i in used: continue
            j = pos.get((x + dx, y + dy, lo)) if (k == "" and nx == 0 and ny == 0) else None
            if j is not None and j not in used and j != i and pos.get((x, y, lo)) == i:
                used.add(i); used.add(j); a, b = cs[0], out[j][0][0]
                if (kind == "h" and lo & 0x20) or (kind == "v" and lo & 0x40): a, b = b, a      # stored unflipped
                res.append(((a, b), kind, 1 if kind == "h" else 0, 1 if kind == "v" else 0, lo, x, y))
            else: res.append(out[i])
        out = res
    return out


def build(ctx, ch, merge=False, extra=None, extra_first=False):
    """extra(ctx, ch, env): optional hook called after the body pass with the working sections (dirbuild.add); its result is returned as r['direct'];
    extra_first: call it before the body pass, so that its sprites get the file's tile / section budget first"""
    pb, al, unpaired = pairs_all(ctx, ch)
    def pix(cs, kind, nx, ny):
        if kind == "": return ctx.block(cs[0], nx, ny, bank)
        a, b = ctx.block(cs[0], 0, 0, bank), ctx.block(cs[1], 0, 0, bank)
        return np.hstack([a, b]) if kind == "h" else np.vstack([a, b])
    n = NSP(os.path.join(ctx.ps1, "A", "A0", f"SP_PL{ch:02X}.NSP")); n.decode_all(); gr = dict(n.groups())
    s0 = bytearray(n.sec[0]); s1 = bytearray(n.sec[1]); s2 = bytearray(n.sec[2]); s3 = bytearray(n.sec[3]); stock3 = bytes(s3)
    inv = collections.defaultdict(set)
    for x, y in al: inv[pb.frameid(y.frame)].add(x.spr)
    bank = None; tilemap = {}; kept = {}

    def geo(g, ap):
        return len(g) == len(ap) and all((n.tiles[q.tile].w, n.tiles[q.tile].h, q.x, q.y, q.flags & 0x7f) == (16 * (nx + 1), 16 * (ny + 1), x, y, lo & 0x7f)
                                         for q, (c, nx, ny, lo, x, y) in zip(g, ap))

    def same(g, ap, bk):
        return all((tile_pixels(n.tiles[q.tile]) == ctx.block(c, nx, ny, bk)).all() for q, (c, nx, ny, lo, x, y) in zip(g, ap))
    for fid in sorted(inv):
        g = gr.get(fid & 0xffff)
        if g is None or (fid >> 16) + 6 > len(stock3): continue
        A = struct.unpack_from("<H", stock3, fid >> 16)[0]
        if A + 4 > len(stock3) or stock3[A + 3] != 0xff or stock3[A:A + 2] == b"\xff\xff": continue
        for s in sorted(inv[fid]):
            if s in kept or not ctx.valid_def(s): continue
            ap = ctx.arc_parts(s)
            if not geo(g, ap): continue
            if bank is None:
                for bk in (0, 0x10000, 0x20000, 0x30000):
                    if same(g, ap, bk): bank = bk; break
                if bank is None: continue
            if same(g, ap, bank):
                kept[s] = (fid & 0xffff, A)
                for q, (c, nx, ny, lo, x, y) in zip(g, ap): tilemap.setdefault(((c,), "", nx, ny), q.tile)
    if bank is None: raise ValueError("character %d: the PS1 sprite file and the arcade graphics do not match" % ch)
    stats = collections.Counter(); newid = {}; skipped = {}; maxrect = [0, 0]; maxraw = 0

    def frame_for(s):
        nonlocal maxraw
        if s in newid: return newid[s]
        if s in skipped: return None
        if not ctx.valid_def(s): skipped[s] = "not a sprite definition"; return None
        if len(s3) + 6 > 0xfff0: skipped[s] = "file limit: frame-record section full (64 KB)"; return None
        if s in kept:
            lo, A = kept[s]; stats["kept"] += 1
            hi = len(s3); s3.extend(struct.pack("<HHH", A, 0, 0xffff)); newid[s] = (hi << 16) | lo
            return newid[s]
        ap = ctx.arc_parts(s)
        mp = merge_parts(ap) if merge else [((c,), "", nx, ny, lo, x, y) for c, nx, ny, lo, x, y in ap]
        raw = sum((nx + 1) * (ny + 1) * 128 for cs, kd, nx, ny, al_, x, y in mp)
        keys = list(dict.fromkeys((cs, kd, nx, ny) for cs, kd, nx, ny, al_, x, y in mp))
        pk = pack([(nx + 1, ny + 1) for cs, kd, nx, ny in keys]) if len(mp) <= MAXPARTS and raw <= MAXRAW else None
        if pk is None:
            skipped[s] = "over limits: %d parts, %d bytes decoded, %d cells" % (len(mp), raw, sum((nx + 1) * (ny + 1) for cs, kd, nx, ny in keys)); return None
        # 16-bit / 12-bit fields of the stock format: a frame that does not fit keeps its stock representation
        need_t = sum(1 for k in keys if k not in tilemap); need_0 = 7 * len(mp); need_3 = 10 + len(mp)
        if len(s1) // 4 + need_t > 4096: skipped[s] = "file limit: 4096 tiles"; return None
        if len(s0) + need_0 > 0xfff0: skipped[s] = "file limit: part section full (64 KB)"; return None
        if len(s3) + need_3 > 0xfff0: skipped[s] = "file limit: frame-record section full (64 KB)"; return None
        W, H, pos = pk; place = dict(zip(keys, pos)); lo = len(s0); maxraw = max(maxraw, raw)
        for i, (cs, kd, nx, ny, al_, x, y) in enumerate(mp):
            key = (cs, kd, nx, ny)
            if key not in tilemap:
                r = ps1_bytes(pix(cs, kd, nx, ny)); tilemap[key] = len(s1) // 4
                s1.extend(struct.pack("<I", len(s2) | (nx << 24) | (ny << 28))); s2.extend(rle_encode(r)); stats["newtiles"] += 1
            s0.extend(enc_part((al_ & 0x7f) | (0x80 if i == len(mp) - 1 else 0), tilemap[key], x, y))
        if W * H > maxrect[0] * maxrect[1]: maxrect[:] = [W, H]
        A = len(s3) + 6
        s3.extend(struct.pack("<HHH", A, 0, 0xffff) + struct.pack("<HBB", A - 8, (H - 1) << 4 | (W - 1), slotbyte[0])
                  + bytes(place[(cs, kd, nx, ny)][1] << 4 | place[(cs, kd, nx, ny)][0] for cs, kd, nx, ny, al_, x, y in mp))
        newid[s] = ((A - 6) << 16) | lo; stats["new"] += 1
        return newid[s]
    def special(fid):
        # stock frame drawn through a shared VRAM slot (layout byte 3 != 0xff: one upload for every object showing it,
        # used for multi-instance effect objects) or the composite path: the record must keep that property
        hi = fid >> 16
        if hi + 6 > len(stock3): return True
        A = struct.unpack_from("<H", stock3, hi)[0]
        return A + 4 > len(stock3) or stock3[A + 3] != 0xff or stock3[A:A + 2] == bytes([255, 255])
    keep = set()                                     # records of the animations listed in KEEP_STOCK (speed policy)
    if KEEP_STOCK.get(ch):
        ag = ctx.arc_groups(ctx.be32(ctx.chtab + 4 * ch)); pg = pb.groups()
        for (k, j) in KEEP_STOCK[ch]:
            if k < len(pg) and j < len(pg[k]) and ag[k][j] is not None: keep.update(r.addr for r in pb.walk(pg[k][j]))
    budget = 0
    # shared VRAM slots (layout byte 3 = index into the set's slot table): restored frames of shared-slot records get new
    # indices above the stock ones; the loader must install a 255-entry table for the set (SPEC.md section 11)
    slotbyte = [0xff]; shid = {}
    used = [stock3[struct.unpack_from("<H", stock3, f >> 16)[0] + 3] for f in {pb.frameid(i) for i in range(pb.nframes())}
            if (f >> 16) + 6 <= len(stock3) and struct.unpack_from("<H", stock3, f >> 16)[0] + 4 <= len(stock3)]
    nextslot = [max([b for b in used if b != 0xff] + [-1]) + 1]

    def shared_for(s, fid0):
        if s in shid: return shid[s]
        if not (ch in SHARED_CHARS or os.environ.get("AP_SHARED")) or not ctx.valid_def(s): return None
        A0 = struct.unpack_from("<H", stock3, fid0 >> 16)[0]
        if stock3[A0:A0 + 2] == bytes([255, 255]) or (fid0 & 0xffff) not in gr: return None       # composite path: not handled
        ap = ctx.arc_parts(s); g = gr[fid0 & 0xffff]
        if geo(g, ap) and same(g, ap, bank): shid[s] = None; return None                          # the port kept this sprite
        if nextslot[0] > 254: return None
        save = newid.pop(s, None); k = kept.pop(s, None); slotbyte[0] = nextslot[0]
        f = frame_for(s); slotbyte[0] = 0xff; newid.pop(s, None)
        if save is not None: newid[s] = save
        if k is not None: kept[s] = k
        if f is not None: nextslot[0] += 1; skipped.pop(s, None)
        shid[s] = f
        return f
    direct = extra(ctx, ch, dict(n=n, pb=pb, s0=s0, s1=s1, s2=s2, s3=s3, stock3=stock3, tilemap=tilemap, bank=bank)) if extra and extra_first else None
    sub2 = [pb.frameid(i) for i in range(pb.nframes())]; idx = {}; recpatch = []; unchanged = 0; shared = 0; shared_ids = set()
    for x, y in al:
        if y.addr in keep: budget += 1; unchanged += 1; continue
        if special(pb.frameid(y.frame)):
            fid = shared_for(x.spr, pb.frameid(y.frame)) if (pb.frameid(y.frame) >> 16) + 6 <= len(stock3) else None
            if fid is None: shared += 1; unchanged += 1; shared_ids.add(pb.frameid(y.frame)); continue
            if fid not in idx: idx[fid] = len(sub2); sub2.append(fid)
            recpatch.append((y.addr - pb.B, idx[fid])); continue
        fid = frame_for(x.spr)
        if fid is None: unchanged += 1; continue
        if fid not in idx: idx[fid] = len(sub2); sub2.append(fid)
        recpatch.append((y.addr - pb.B, idx[fid]))
    done = set()
    for x, y in al:                                   # prefetch hint = the frame that follows in the script
        fid = newid.get(x.spr)
        if fid is None or fid in done: continue
        nx_ = ctx.be32(x.addr + 16) if x.end else x.addr + 16
        nf = newid.get(ctx.be32(nx_ + 4)) if 0 < nx_ < len(ctx.D) - 8 else None
        if nf is not None and nf != fid: done.add(fid); struct.pack_into("<H", s3, (fid >> 16) + 4, nf & 0xffff)
    if extra and not extra_first: direct = extra(ctx, ch, dict(n=n, pb=pb, s0=s0, s1=s1, s2=s2, s3=s3, stock3=stock3, tilemap=tilemap, bank=bank))
    s0.extend(bytes(-len(s0) % 4)); s2.extend(bytes(-len(s2) % 4)); s3.extend(bytes(-len(s3) % 4))      # sections 4-byte aligned in the file, as stock
    over = [k for k, v in dict(sec0=len(s0) >= 0x10000, sec3=len(s3) >= 0x10000, tiles=len(s1) // 4 > 4096, frames=len(sub2) > 4096).items() if v]
    hdr = struct.pack("<4I", 16, 16 + len(s0), 16 + len(s0) + len(s1), 16 + len(s0) + len(s1) + len(s2))
    return dict(ch=ch, merged=merge, bank=bank, nsp=hdr + bytes(s0) + bytes(s1) + bytes(s2) + bytes(s3), sec=[len(s0), len(s1), len(s2), len(s3)], stock=n.sizes, sub2=sub2,
                recpatch=sorted(set(recpatch)), blob_file_off=pb.B, old_nframes=pb.nframes(), maxrect=maxrect, maxraw=maxraw, over=over, ntiles=len(s1) // 4,
                stats=dict(stats), budget=budget, shared_new={k: v for k, v in shid.items() if v is not None}, slots=nextslot[0], shared=shared, shared_ids=sorted(shared_ids), records=len(al) + unpaired, unpaired=unpaired, unchanged=unchanged, newid=newid, skipped=skipped,
                arc_sprites=len({x.spr for x, y in al}), stock_sprites=len({pb.frameid(y.frame) & 0xffff for x, y in al}),
                overlay_sha1=hashlib.sha1(pb.P).hexdigest(), blob_head=pb.P[pb.B:pb.B + 16], direct=direct)


def check(ctx, r, tmpdir):
    """every frame of the result against the arcade definition, pixel for pixel -> (frames, bad)"""
    tmp = os.path.join(tmpdir, "_check.nsp"); open(tmp, "wb").write(r["nsp"])
    n = NSP(tmp); n.decode_all(); bad = 0; s3 = n.sec[3]
    for s, fid, sh in [(s, f, False) for s, f in r["newid"].items()] + [(s, f, True) for s, f in r.get("shared_new", {}).items()]:
        ap = ctx.arc_parts(s); p = fid & 0xffff; g = []
        while True:
            q = parse_part(n.sec[0], p); g.append(q); p += q.size
            if q.flags & 0x80: break
        A, B, C = struct.unpack_from("<HHH", s3, fid >> 16); size = s3[A + 2]; W = (size & 15) + 1; H = (size >> 4) + 1; occ = {}
        ok = B == 0 and (s3[A + 3] != 0xff) == sh and s3[A:A + 2] != bytes([255, 255])

        def paint(items):
            x0 = min(i[0] for i in items); y0 = min(i[1] for i in items); x1 = max(i[0] + i[2].shape[1] for i in items); y1 = max(i[1] + i[2].shape[0] for i in items)
            img = np.full((y1 - y0, x1 - x0), 15, dtype=np.uint8)
            for x, y, px in reversed(items):
                reg = img[y - y0:y - y0 + px.shape[0], x - x0:x - x0 + px.shape[1]]; m = px != 15; reg[m] = px[m]
            return x0, y0, img

        def fl(px, lo):
            if lo & 0x20: px = px[:, ::-1]
            if lo & 0x40: px = px[::-1, :]
            return px
        ia = paint([(x, y, fl(ctx.block(c, nx, ny, r["bank"]), lo)) for c, nx, ny, lo, x, y in ap])
        ip = paint([(q.x, q.y, fl(tile_pixels(n.tiles[q.tile]), q.flags)) for q in g])
        ok = ok and ia[0] == ip[0] and ia[1] == ip[1] and ia[2].shape == ip[2].shape and bool((ia[2] == ip[2]).all())
        ok = ok and {q.flags & 0x1f for q in g} == {lo & 0x1f for c, nx, ny, lo, x, y in ap}
        for i, q in enumerate(g):
            t = n.tiles[q.tile]; b = s3[A + 4 + i]
            for yy in range(b >> 4, (b >> 4) + t.h // 16):
                for xx in range(b & 15, (b & 15) + t.w // 16):
                    ok = ok and occ.get((xx, yy), q.tile) == q.tile and xx < W and yy < H; occ[(xx, yy)] = q.tile
        bad += not ok
    os.remove(tmp)
    return len(r["newid"]) + len(r.get("shared_new", {})), bad


def ap8(r):
    """the per-character patch file (SPEC.md section 3)"""
    out = struct.pack("<4sBBHIIII", b"AP8\x01", r["ch"], 0, 0, r["blob_file_off"], r["old_nframes"], len(r["sub2"]), len(r["recpatch"]))
    out += r["blob_head"]
    out += struct.pack("<%dI" % len(r["sub2"]), *r["sub2"])
    out += b"".join(struct.pack("<HH", rel, idx) for rel, idx in r["recpatch"])
    return out
