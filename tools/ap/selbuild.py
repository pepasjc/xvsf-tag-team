"""Character select screen: restore the small character animations (SP_SEL0.NSP + frame ids inside SELECT.BIN).

SELECT.BIN holds 8-byte animation records (word w0, word duration|0x8000 end, long frame id into SP_SEL0; 4 more bytes
after an end record).  Each character animation there is a copy of one body animation of the fight overlay, record for
record, with the same sprites the port kept.  This tool pairs every such animation with the body animation (same
durations, same sprite images), takes the arcade sprite of each record from the body pairing and appends the missing
sprites to SP_SEL0.  Output: SP_SEL0.NSP and SELECT.AP8 (see SPEC.md).
"""
import os, sys, struct, hashlib, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aplib
from aplib import NSP, tile_pixels, parse_part

BASE = 0x135d8            # file offset in SELECT.BIN of the animation data (object +0x44 = 0x800ab5d8, overlay at 0x80098000)


def _paint(items):
    x0 = min(i[0] for i in items); y0 = min(i[1] for i in items); x1 = max(i[0] + i[2].shape[1] for i in items); y1 = max(i[1] + i[2].shape[0] for i in items)
    img = np.full((y1 - y0, x1 - x0), 15, dtype=np.uint8)
    for x, y, px in reversed(items):
        reg = img[y - y0:y - y0 + px.shape[0], x - x0:x - x0 + px.shape[1]]; m = px != 15; reg[m] = px[m]
    return x0, y0, img


def _fl(px, lo):
    if lo & 0x20: px = px[:, ::-1]
    if lo & 0x40: px = px[::-1, :]
    return px


def _h(p):
    return hashlib.md5(struct.pack("<hhHH", p[0], p[1], *p[2].shape) + p[2].tobytes()).digest()


def group_parts(n, lo):
    p = lo; g = []
    while True:
        q = parse_part(n.sec[0], p); g.append(q); p += q.size
        if q.flags & 0x80: return g


def ps1_hash(n, lo):
    return _h(_paint([(q.x, q.y, _fl(tile_pixels(n.tiles[q.tile]), q.flags)) for q in group_parts(n, lo)]))


def arc_hash(ctx, s, bank):
    return _h(_paint([(x, y, _fl(ctx.block(c, nx, ny, bank), lo)) for c, nx, ny, lo, x, y in ctx.arc_parts(s)]))


def runs(S, n):
    gs = set(dict(n.groups()))

    def ok(f): return (f & 0xffff) in gs and 0 < (f >> 16) < n.sizes[3]
    a = BASE; out = []
    while a + 8 <= len(S):
        w0, w1, f = struct.unpack_from("<HHI", S, a)
        if ok(f) and (w1 & 0x7fff) < 256:
            run = []
            while a + 8 <= len(S):
                w0, w1, f = struct.unpack_from("<HHI", S, a)
                if not (ok(f) and (w1 & 0x7fff) < 256): break
                run.append((a, w1 & 0xff, f)); a += 8
                if w1 >> 15: a += 4; break
            out.append(run)
        else: a += 4
    return out


def build(ctx, ps1):
    n = NSP(os.path.join(ps1, "A", "A2", "SP_SEL0.NSP")); n.decode_all()
    S = open(os.path.join(ps1, "P", "P4", "SELECT.BIN"), "rb").read()
    rr = [r for r in runs(S, n) if r[0][0] - BASE < 0x1900]
    selh = {}
    for r in rr:
        for a, d, f in r:
            if f & 0xffff not in selh: selh[f & 0xffff] = ps1_hash(n, f & 0xffff)
    # body animations of every character: per record (hash of the stock sprite, duration, arcade sprite)
    whole = collections.defaultdict(list)
    body = collections.defaultdict(list)             # first (hash, dur) -> [(ch, [(hash, dur, arcade sprite)])]
    for ch in range(18):
        try: pb, al, un = aplib.pairs_all(ctx, ch)
        except Exception: continue
        m = NSP(os.path.join(ps1, "A", "A0", f"SP_PL{ch:02X}.NSP")); m.decode_all(); mg = set(dict(m.groups())); hc = {}; seq = []
        for x, y in al:
            lo = pb.frameid(y.frame) & 0xffff
            if lo not in hc: hc[lo] = ps1_hash(m, lo) if lo in mg else None
            seq.append((hc[lo], y.dur, x.spr, y.end))
        i = 0
        while i < len(seq):                          # split at end records
            j = i
            while not seq[j][3] and j + 1 < len(seq): j += 1
            a = seq[i:j + 1]
            for k in range(len(a)): body[(a[k][0], a[k][1])].append((ch, a, k)); body[a[k][0]].append((ch, a, k))
            whole[tuple(x[1] for x in a)].append((ch, a))
            i = j + 1
    s0 = bytearray(n.sec[0]); s1 = bytearray(n.sec[1]); s2 = bytearray(n.sec[2]); s3 = bytearray(n.sec[3])
    bank = {}; tilemap = {}; newid = {}; patches = []; rep = collections.OrderedDict(); skipped = collections.Counter()
    hits = []
    for r in rr:
        key = (selh[r[0][2] & 0xffff], r[0][1]); hit = None
        for ch, a, k in body.get(key, []):
            if k + len(r) <= len(a) and all(selh[f & 0xffff] == a[k + i][0] and d == a[k + i][1] for i, (ad, d, f) in enumerate(r)): hit = (ch, a[k:k + len(r)]); break
        if hit is None and len(r) >= 3:               # same sprites record for record, other durations (select-screen timing)
            for ch, a, k in body.get(key[0], []):
                if k + len(r) <= len(a) and all(selh[f & 0xffff] == a[k + i][0] for i, (ad, d, f) in enumerate(r)): hit = (ch, a[k:k + len(r)]); break
        if hit is None and len(r) >= 3:               # the select screen's own, further reduced copy of a whole body animation
            c = [(ch, a) for ch, a in whole.get(tuple(d for ad, d, f in r), []) if {selh[f & 0xffff] for ad, d, f in r} <= {x[0] for x in a}]
            if len({id(a) for ch, a in c}) >= 1 and len({ch for ch, a in c}) == 1: hit = c[0]
        hits.append(hit)
    def cost(i):
        if hits[i] is None: return 0
        ch, a = hits[i]; blocks = set()
        for (ad, d, f), x in zip(rr[i], a):
            if ctx.valid_def(x[2]):
                for c, nx, ny, lo, xx, yy in ctx.arc_parts(x[2]): blocks.add((ch, (c, nx, ny)))
        return blocks
    best = {}                                         # the longest animation of each character is its idle on the cursor: those first
    for i, h in enumerate(hits):
        if h is not None and (h[0] not in best or len(rr[i]) > len(rr[best[h[0]]])): best[h[0]] = i
    first = sorted(best.values(), key=lambda i: len(cost(i)))
    order = first + sorted((i for i in range(len(rr)) if i not in first), key=lambda i: len(cost(i)) if hits[i] else 0)      # then cheapest first: 4096-tile budget
    for h_ in hits:                                    # tile bank of each character, from any sprite the port kept
        if h_ is None or h_[0] in bank: continue
        for bk in (0, 0x10000, 0x20000, 0x30000):
            if any(ctx.valid_def(x[2]) and arc_hash(ctx, x[2], bk) == x[0] for x in h_[1]): bank[h_[0]] = bk; break
    for i_ in order:
        r = rr[i_]; hit = hits[i_]
        if hit is None: rep[r[0][0]] = ("no body animation matched", len(r), 0, 0); continue
        ch, a = hit
        if ch not in bank:
            for bk in (0, 0x10000, 0x20000, 0x30000):
                if any(ctx.valid_def(x[2]) and arc_hash(ctx, x[2], bk) == x[0] for x in a): bank[ch] = bk; break
        if ch not in bank: rep[r[0][0]] = ("character %d: no kept sprite to find the tile bank" % ch, len(r), 0, 0); continue
        bk = bank[ch]; done = left = 0
        if len(s1) // 4 + len([b for b in cost(i_) if b not in tilemap]) > 4096 - 0:
            rep[r[0][0]] = (aplib.NAMES[ch], len(r), len({f & 0xffff for ad, d, f in r}), len({x[2] for x in a}), 0, 'animation skipped: tile budget'); continue
        for (ad, d, f), (h, dd, s, e) in zip(r, a):
            if not ctx.valid_def(s): left += 1; continue
            if arc_hash(ctx, s, bk) == selh[f & 0xffff]: continue        # the select screen already shows the arcade sprite here
            if (ch, s) not in newid:
                ap = ctx.arc_parts(s); keys = list(dict.fromkeys((c, nx, ny) for c, nx, ny, lo, x, y in ap))
                need = sum(1 for k_ in keys if (ch, k_) not in tilemap); pk = aplib.pack([(nx + 1, ny + 1) for c, nx, ny in keys])
                if pk is None or len(s1) // 4 + need > 4096 or len(s0) + 7 * len(ap) > 0xfff0 or len(s3) + 10 + len(ap) > 0xfff0:
                    skipped["tile limit" if len(s1) // 4 + need > 4096 else "other limit"] += 1; newid[(ch, s)] = None
                else:
                    W, H, pos = pk; place = dict(zip(keys, pos)); lo_ = len(s0)
                    for i, (c, nx, ny, lo, x, y) in enumerate(ap):
                        if (ch, (c, nx, ny)) not in tilemap:
                            tilemap[(ch, (c, nx, ny))] = len(s1) // 4
                            s1.extend(struct.pack("<I", len(s2) | (nx << 24) | (ny << 28))); s2.extend(aplib.rle_encode(aplib.ps1_bytes(ctx.block(c, nx, ny, bk))))
                        s0.extend(aplib.enc_part((lo & 0x7f) | (0x80 if i == len(ap) - 1 else 0), tilemap[(ch, (c, nx, ny))], x, y))
                    A = len(s3) + 6
                    s3.extend(struct.pack("<HHH", A, 0, 0xffff) + struct.pack("<HBB", A - 8, (H - 1) << 4 | (W - 1), 0xff) + bytes(place[(c, nx, ny)][1] << 4 | place[(c, nx, ny)][0] for c, nx, ny, lo, x, y in ap))
                    newid[(ch, s)] = ((A - 6) << 16) | lo_
            if newid[(ch, s)] is None: left += 1
            else: patches.append((ad + 4, newid[(ch, s)])); done += 1
        rep[r[0][0]] = (aplib.NAMES[ch], len(r), len({f & 0xffff for ad, d, f in r}), len({x[2] for x in a}), done, left)
    for sec in (s0, s2, s3): sec.extend(bytes(-len(sec) % 4))
    hdr = struct.pack("<4I", 16, 16 + len(s0), 16 + len(s0) + len(s1), 16 + len(s0) + len(s1) + len(s2))
    nsp = hdr + bytes(s0) + bytes(s1) + bytes(s2) + bytes(s3)
    # check: every new frame renders exactly as the arcade definition
    tmp = os.path.join(os.environ.get("TEMP", "."), "_sel_check_%d.nsp" % os.getpid()); open(tmp, "wb").write(nsp); c = NSP(tmp); c.decode_all(); bad = 0
    for (ch, s), fid in newid.items():
        if fid is not None and ps1_hash(c, fid & 0xffff) != arc_hash(ctx, s, bank[ch]): bad += 1
    os.remove(tmp)
    ap8 = struct.pack("<4sII", b"AS8\x01", len(S), len(patches)) + hashlib.sha1(S).digest()[:16] + b"".join(struct.pack("<II", o, f) for o, f in patches)
    return dict(nsp=nsp, ap8=ap8, patches=patches, report=rep, skipped=dict(skipped), new=sum(1 for v in newid.values() if v is not None), bad=bad,
                sec=[len(s0), len(s1), len(s2), len(s3)], stock=n.sizes, tiles=len(s1) // 4)


if __name__ == "__main__":
    import pickle
    prg, T, chtab = pickle.load(open(sys.argv[1], "rb")); ctx = aplib.Ctx(prg, T, sys.argv[2], chtab); out = sys.argv[3]
    r = build(ctx, sys.argv[2])
    open(os.path.join(out, "SP_SEL0.NSP"), "wb").write(r["nsp"]); open(os.path.join(out, "SELECT.AP8"), "wb").write(r["ap8"])
    print("SP_SEL0 sections", r["sec"], "stock", r["stock"], "tiles", r["tiles"], "new sprites", r["new"], "skipped", r["skipped"], "frame-id patches", len(r["patches"]), "bad", r["bad"], "file", len(r["nsp"]))
    for k, v in sorted(r["report"].items()): print(" +%04x" % (k - BASE), v)
