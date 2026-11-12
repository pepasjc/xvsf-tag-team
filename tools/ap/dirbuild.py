"""Direct-frame-id animations of the fight overlays (projectiles, beams, helper objects): find, pair with the arcade, restore.

The fight overlay P/P0/PLxx_10.BIN holds, outside the body animation blob, animations made of 8-byte records
    u16 w0, u16 duration | 0x8000 end, u32 frame id          (+ s32 loop offset, relative to the object's +0x44 base, after an end record)
played by 0x80030dd4.  The arcade program holds the same animations as
    word w0, word duration | 0x8000 end, long sprite          (+ long loop pointer after an end record)
with the same record count and durations; the port repointed the records of the sprites it cut to a neighbouring kept
sprite.  This module pairs every PS1 animation with the arcade one (durations, then the images of the kept sprites, in
file order), appends the missing sprites to the character's sprite file (through aplib.build's `extra` hook) and emits
frame-id patches for the overlay (PLxx.AD8, SPEC.md section 12).  Nothing here is derived from either game.
"""
import os, sys, struct, hashlib, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aplib
from aplib import tile_pixels, parse_part

# direct animations kept in their stock form because the restored one measurably costs game speed (work/ap/rate_mv.py):
# {character: [offset of the animation's first record in P/P0/PLxx_10.BIN]}
KEEP_STOCK = {0: [0xeb18, 0xeb80],        # Wolverine, speed streaks of the barrage: hcb+P/K worst second 55.5 -> 52.8 with them, 55.5 without
              2: [0xdebc, 0xdc10]}        # Storm, dash wind (dash 57.2 -> 56.2) and one cape part (qcb+PP super worst second 41.8 -> 38.8)


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


def _h(p): return hashlib.md5(struct.pack("<hhHH", p[0], p[1], *p[2].shape) + p[2].tobytes()).digest()


def group_parts(s0, lo):
    p = lo; g = []
    while True:
        q = parse_part(s0, p); g.append(q); p += q.size
        if q.flags & 0x80: return g


def ps1_image(n, lo): return _paint([(q.x, q.y, _fl(tile_pixels(n.tiles[q.tile]), q.flags)) for q in group_parts(n.sec[0], lo)])
def arc_image(ctx, s, bank): return _paint([(x, y, _fl(ctx.block(c, nx, ny, bank), lo)) for c, nx, ny, lo, x, y in ctx.arc_parts(s)])


def ps1_anims(P, okfid, skip=(0, 0)):
    """every animation of 8-byte records in an overlay image -> [(records [(offset, w0, dur, end, fid)], loop offset)]"""
    out = []; a = 0
    while a + 12 <= len(P):
        if skip[0] <= a < skip[1]: a = (skip[1] + 3) & ~3; continue
        p = a; cur = []
        while p + 12 <= len(P):
            w0, w1, f = struct.unpack_from("<HHI", P, p)
            if (w1 & 0x7f00) or not okfid(f): cur = []; break
            cur.append((p, w0, w1 & 0xff, w1 >> 15, f)); p += 8
            if w1 >> 15:
                lp = struct.unpack_from("<i", P, p)[0]
                if not 0 <= lp < 0x8000 or lp % 4: cur = []
                break
        else: cur = []
        if cur: out.append((cur, lp)); a = p + 4
        else: a += 4
    return out


def arc_anims(ctx, lo=0x20000, hi=0x100000):
    """every animation in the arcade program, in both record sizes -> [(records [(address, w0, dur, end, sprite)], loop target address)]
    8-byte records (word w0, word duration | 0x8000 end, long sprite) and the 16-byte body records (same head + 8 bytes); a long
    loop pointer follows the end record"""
    if getattr(ctx, "_dir_anims", None) is not None: return ctx._dir_anims
    D = ctx.D; out = []; ok = {}

    def valid(s):
        if s not in ok: ok[s] = ctx.valid_def(s)
        return ok[s]
    for stride in (8, 16):
        a = lo
        while a < hi:
            p = a; cur = []
            if D[a + 2] & 0x7f:                       # duration word: high byte 0x00 or 0x80
                a += 2; continue
            while p + stride + 4 <= hi:
                w1 = ctx.be16(p + 2); s = ctx.be32(p + 4)
                if (w1 & 0x7f00) or not valid(s): cur = []; break
                cur.append((p, ctx.be16(p), w1 & 0xff, w1 >> 15, s)); p += stride
                if w1 >> 15:
                    lp = ctx.be32(p)                 # loop pointer: into this animation, or into another one (a record address in the program)
                    if not (lo <= lp < hi and lp % 2 == 0 and (a <= lp <= cur[-1][0] or (not ctx.be16(lp + 2) & 0x7f00 and valid(ctx.be32(lp + 4))))): cur = []
                    break
            if cur and len(cur) >= 2: out.append((cur, lp)); a = p + 4
            else: a += 2
    out.sort(key=lambda t: t[0][0][0])
    ctx._dir_anims = out
    return out


def pair(ctx, n, P, skip):
    """-> (paired [(ps1 records, loop, arcade records, bank, arcade loop target)], unpaired [(ps1 records, loop)])
    n: decoded stock NSP of the character, P: overlay image, skip: byte range of the body blob"""
    gs = set(dict(n.groups())); s3len = n.sizes[3]

    def okfid(f): return (f & 0xffff) in gs and 2 <= (f >> 16) and (f >> 16) + 6 <= s3len
    pa = [x for x in ps1_anims(P, okfid, skip) if len(x[0]) >= 2]
    AA = arc_anims(ctx); bykey = collections.defaultdict(list)
    for j, (a, alp) in enumerate(AA): bykey[tuple(r[2] for r in a)].append(j)
    hp = {}; ha = {}

    def ph(lo):
        if lo not in hp: hp[lo] = _h(ps1_image(n, lo))
        return hp[lo]

    def ah(s, bk):
        if (s, bk) not in ha: ha[(s, bk)] = _h(arc_image(ctx, s, bk))
        return ha[(s, bk)]
    cands = []
    for recs, lp in pa:
        c = []
        for j in bykey.get(tuple(r[2] for r in recs), []):
            A = AA[j][0]
            for bk in (0, 0x10000, 0x20000, 0x30000):
                eq = [ph(r[4] & 0xffff) == ah(x[4], bk) for r, x in zip(recs, A)]; aset = {ah(x[4], bk) for x in A}
                if any(eq) and all(ph(r[4] & 0xffff) in aset for r in recs):      # every sprite the port kept is a sprite of the arcade animation, one at least on its own record
                    c.append((j, bk)); break
        cands.append(c)
    # longest chain with increasing arcade index (both games keep the same order)
    best = {}                                  # (i, k) -> (length, previous)
    for i, c in enumerate(cands):
        for k, (j, bk) in enumerate(c):
            b = (1, None)
            for (i2, k2), (ln, pv) in best.items():
                if i2 < i and cands[i2][k2][0] < j and ln + 1 > b[0]: b = (ln + 1, (i2, k2))
            best[(i, k)] = b
    chain = {}
    if best:
        cur = max(best, key=lambda t: (best[t][0], -t[0]))
        while cur is not None: chain[cur[0]] = cands[cur[0]][cur[1]]; cur = best[cur][1]
    paired = [(pa[i][0], pa[i][1], AA[chain[i][0]][0], chain[i][1], AA[chain[i][0]][1]) for i in sorted(chain)]
    return paired, [pa[i] for i in range(len(pa)) if i not in chain]


def add(ctx, ch, env):
    """aplib.build `extra` hook: env = the builder's working state.  Appends the sprites and frame records the direct
    animations need and returns dict(patches [(overlay offset, stock frame id, new frame id)], report rows, ...)"""
    n = env["n"]; pb = env["pb"]; P = pb.P; s0, s1, s2, s3 = env["s0"], env["s1"], env["s2"], env["s3"]; stock3 = env["stock3"]
    tilemap = env["tilemap"]; body_bank = env["bank"]
    paired, unpaired = pair(ctx, n, P, (pb.B, pb.B + pb.h[3]))
    hp = {}

    def ph(lo):
        if lo not in hp: hp[lo] = _h(ps1_image(n, lo))
        return hp[lo]

    def kind(fid):
        A, B, C = struct.unpack_from("<HHH", stock3, fid >> 16)
        if A + 4 > len(stock3) or stock3[A:A + 2] == b"\xff\xff": return "composite"
        if stock3[A + 3] != 0xff: return "shared"
        return "modifier" if B else "plain"
    sprite = {}                                 # (arcade sprite, bank) -> (sec0 offset, layout offset) or None
    why = {}
    for recs, lp, A_, bk, la in paired:             # sprites the port kept: reuse the stock parts and layout
        byimg = {}
        for r in recs:
            if kind(r[4]) == "plain": byimg.setdefault(ph(r[4] & 0xffff), (r[4] & 0xffff, struct.unpack_from("<H", stock3, r[4] >> 16)[0]))
        for x in A_:
            h = _h(arc_image(ctx, x[4], bk))
            if h in byimg: sprite.setdefault((x[4], bk), byimg[h])
    stats = collections.Counter(); maxraw = 0; maxrect = [0, 0]

    def newsprite(s, bk):
        nonlocal maxraw
        if (s, bk) in sprite: return sprite[(s, bk)]
        ap = ctx.arc_parts(s); raw = sum((nx + 1) * (ny + 1) * 128 for c, nx, ny, lo, x, y in ap)
        tk = lambda c, nx, ny: ((c,), "", nx, ny) if bk == body_bank else ((c,), "bank%x" % bk, nx, ny)
        keys = list(dict.fromkeys(tk(c, nx, ny) for c, nx, ny, lo, x, y in ap))
        pk = aplib.pack([(k[2] + 1, k[3] + 1) for k in keys]) if len(ap) <= aplib.MAXPARTS and raw <= aplib.MAXRAW else None
        res = None
        if pk is None: why[(s, bk)] = "over limits: %d parts, %d bytes decoded" % (len(ap), raw)
        elif len(s1) // 4 + sum(1 for k in keys if k not in tilemap) > 4096: why[(s, bk)] = "file limit: 4096 tiles"
        elif len(s0) + 7 * len(ap) > 0xfff0: why[(s, bk)] = "file limit: part section full (64 KB)"
        elif len(s3) + 4 + len(ap) + 6 > 0xfff0: why[(s, bk)] = "file limit: frame-record section full (64 KB)"
        else:
            W, H, pos = pk; place = dict(zip(keys, pos)); lo_ = len(s0); maxraw = max(maxraw, raw)
            if W * H > maxrect[0] * maxrect[1]: maxrect[:] = [W, H]
            for i, (c, nx, ny, lo, x, y) in enumerate(ap):
                k = tk(c, nx, ny)
                if k not in tilemap:
                    tilemap[k] = len(s1) // 4; stats["newtiles"] += 1
                    s1.extend(struct.pack("<I", len(s2) | (nx << 24) | (ny << 28))); s2.extend(aplib.rle_encode(aplib.ps1_bytes(ctx.block(c, nx, ny, bk))))
                s0.extend(aplib.enc_part((lo & 0x7f) | (0x80 if i == len(ap) - 1 else 0), tilemap[k], x, y))
            A = len(s3)
            s3.extend(struct.pack("<HBB", 0, (H - 1) << 4 | (W - 1), 0xff) + bytes(place[tk(c, nx, ny)][1] << 4 | place[tk(c, nx, ny)][0] for c, nx, ny, lo, x, y in ap))
            res = (lo_, A); stats["new"] += 1
        sprite[(s, bk)] = res
        return res
    frec = {}; patches = []; report = []; made = {}
    keep = set(KEEP_STOCK.get(ch, ())) | {int(x, 16) for x in os.environ.get("AP_DKEEP", "").split(",") if x}
    for recs, lp, A_, bk, la in paired:
        if recs[0][0] in keep:
            report.append(dict(offset=recs[0][0], arcade=A_[0][0], records=len(recs), sprites_stock=len({r[4] & 0xffff for r in recs}), sprites_arcade=len({x[4] for x in A_}),
                               restored=0, left={"kept stock: measured speed (KEEP_STOCK)": sum(ph(r[4] & 0xffff) != _h(arc_image(ctx, x[4], bk)) for r, x in zip(recs, A_))}))
            continue
        N = len(recs)                                   # loop target as a record index: the arcade loop pointer
        loop_i = next((i for i, x in enumerate(A_) if x[0] == la), None)      # None: the script continues in another animation
        done = 0; left = collections.Counter()
        for i, (r, x) in enumerate(zip(recs, A_)):
            k = kind(r[4])
            cut = ph(r[4] & 0xffff) != _h(arc_image(ctx, x[4], bk))
            if k != "plain":
                if cut: left["stock frame uses a %s" % ("shared VRAM slot" if k == "shared" else k)] += 1
                continue
            sp = newsprite(x[4], bk)
            if sp is None:
                if cut: left[why[(x[4], bk)]] += 1
                continue
            j = i; C = sp[0]                              # prefetch hint: the next different sprite of the script (as stock)
            for _ in range(N):
                j = j + 1 if j + 1 < N else loop_i
                if j is None: break
                if A_[j][4] != x[4]:
                    nx_ = newsprite(A_[j][4], bk) if kind(recs[j][4]) == "plain" else None
                    C = nx_[0] if nx_ is not None else (recs[j][4] & 0xffff)
                    break
            lo_, A = sp
            old = struct.unpack_from("<HHH", stock3, r[4] >> 16)
            if lo_ == (r[4] & 0xffff) and old[0] == A and old[2] == C: continue      # stock record already says exactly this
            if (lo_, A, C) not in frec:
                if len(s3) + 6 > 0xfff0:
                    if cut: left["file limit: frame-record section full (64 KB)"] += 1
                    continue
                frec[(lo_, A, C)] = len(s3); s3.extend(struct.pack("<HHH", A, 0, C))
            fid = frec[(lo_, A, C)] << 16 | lo_
            patches.append((r[0] + 4, r[4], fid)); made[fid] = (x[4], bk)
            if cut: done += 1
        report.append(dict(offset=recs[0][0], arcade=A_[0][0], records=N, sprites_stock=len({r[4] & 0xffff for r in recs}), sprites_arcade=len({x[4] for x in A_}),
                           restored=done, left=dict(left)))
    for recs, lp in unpaired:
        report.append(dict(offset=recs[0][0], arcade=None, records=len(recs), sprites_stock=len({r[4] & 0xffff for r in recs}), sprites_arcade=None, restored=0,
                           left={"no arcade animation matched": len(recs)}))
    return dict(patches=patches, report=sorted(report, key=lambda d: d["offset"]), made=made, stats=dict(stats), maxraw=maxraw, maxrect=maxrect,
                overlay_size=len(P))


def check(ctx, r, tmpdir):
    """every patched frame id of the result against the arcade definition, pixel for pixel, and its records -> (frames, bad)"""
    from nsp import NSP
    d = r["direct"]; tmp = os.path.join(tmpdir, "_dcheck.nsp"); open(tmp, "wb").write(r["nsp"]); n = NSP(tmp); n.decode_all(); s3 = n.sec[3]; bad = 0
    gs = set(dict(n.groups())) | {f & 0xffff for f in d["made"]}        # sequential walk = the stock sprites; plus the appended ones
    for fid, (s, bk) in d["made"].items():
        hi = fid >> 16; lo = fid & 0xffff; ok = lo in gs and hi + 6 <= len(s3)
        if ok:
            A, B, C = struct.unpack_from("<HHH", s3, hi); g = group_parts(n.sec[0], lo)
            ok = B == 0 and s3[A:A + 2] != b"\xff\xff" and s3[A + 3] == 0xff and C in gs and A + 4 + len(g) <= len(s3)
            if ok:
                a = arc_image(ctx, s, bk); p = ps1_image(n, lo)
                ok = a[0] == p[0] and a[1] == p[1] and a[2].shape == p[2].shape and bool((a[2] == p[2]).all())
                W = (s3[A + 2] & 15) + 1; H = (s3[A + 2] >> 4) + 1; occ = {}
                for i, q in enumerate(g):
                    t = n.tiles[q.tile]; b = s3[A + 4 + i]
                    for yy in range(b >> 4, (b >> 4) + t.h // 16):
                        for xx in range(b & 15, (b & 15) + t.w // 16):
                            ok = ok and occ.get((xx, yy), q.tile) == q.tile and xx < W and yy < H; occ[(xx, yy)] = q.tile
        bad += not ok
    os.remove(tmp)
    return len(d["made"]), bad


def ad8(ch, d):
    """PLxx.AD8 (SPEC.md section 12): magic, character, overlay size, count, then {u32 overlay offset, u32 stock frame id, u32 new frame id}"""
    p = sorted(set(d["patches"]))
    return struct.pack("<4sBBHII", b"AD8\x01", ch, 0, 0, d["overlay_size"], len(p)) + b"".join(struct.pack("<III", *x) for x in p)
