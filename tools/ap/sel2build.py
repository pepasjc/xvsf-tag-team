"""Character select screen, second sprite set: the animations that did not fit SP_SEL0 (4,096 tile indices per file).

Input: the arcade set, the PS1 disc files and a finished content directory (its SP_SEL0.NSP + SELECT.AP8 are used as they
are).  Output: SP_SEL2.NSP (a sprite file built from nothing but the sprites of the animations listed below, for a
sprite set id the game never loads) and SELECT2.AP8 (frame ids for every record of those animations, the list of
animation ranges that belong to the second set, the call sites to redirect and a position-independent stub that picks
the set when an animation is started).  Formats: work/ap/SPEC.md section 15.  Nothing here is derived from either game.

    python sel2build.py --arcade SET.zip [PARENT.zip] --disc xvsf.bin --base DIR --out NEWDIR
    (development: --ctx ctx.pkl --ps1 DIR_WITH_DISC_FILES --anims cache.pkl instead of --arcade / --disc)
"""
import os, sys, struct, hashlib, collections, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aplib, dirbuild
from aplib import NSP, tile_pixels, parse_part

BASE = 0x135d8            # file offset in SELECT.BIN of the animation data (object +0x44 = 0x800ab5d8; SELECT.BIN loads at 0x80098000)
LOAD = 0x80098000
PLAYER = 0x80030dd4       # animation start routine (a0 = object, a1 = record)
SET1, SET2 = 0x27, 0x39   # SP_SEL0's set; the second set: no file of the game has this id (file index 0x5a + set = a VS screen file)


def anims(S, n):
    """SELECT.BIN animation area, parsed record by record from its start: 8-byte records, 4 more bytes (loop offset) after an end
    record.  -> [(records [(file offset, w0, duration, end, frame id)], loop offset)] up to the first word that is not a frame id"""
    gs = set(dict(n.groups())); a = BASE; out = []; cur = []
    while a + 12 <= len(S):
        w0, w1, f = struct.unpack_from("<HHI", S, a)
        if not ((f & 0xffff) in gs and 0 < (f >> 16) and (f >> 16) + 6 <= n.sizes[3]): break
        cur.append((a, w0, w1 & 0x7fff, w1 >> 15, f)); a += 8
        if w1 >> 15: out.append((cur, struct.unpack_from("<h", S, a)[0])); cur = []; a += 4
    return out


def img_hash(n, lo): return dirbuild._h(dirbuild.ps1_image(n, lo))


def pair(ctx, n, S):
    """every animation of two or more records against the arcade animations (both record sizes): same record count and durations,
    every sprite the port kept is a sprite of the arcade animation (rule 'strict'), or at least one kept sprite sits on its own
    record and every candidate with these durations shows the same images (rule 'agree').
    -> [(records, loop, arcade records or None, bank, rule or reason)]"""
    AA = dirbuild.arc_anims(ctx); bykey = collections.defaultdict(list)
    for j, (a, alp) in enumerate(AA):
        bykey[tuple(r[2] for r in a)].append(j); bykey[tuple(r[2] for r in a[:-1]) + (None,)].append(j)
    idle = set()                                    # arcade animations of group 0 of a character table (standing / neutral)
    for ch in range(19):
        try: idle.update(a for a in ctx.arc_groups(ctx.be32(ctx.chtab + 4 * ch))[0] if a)
        except Exception: pass
    hp = {}; ha = {}

    def ph(lo):
        if lo not in hp: hp[lo] = img_hash(n, lo)
        return hp[lo]

    def ah(s, bk):
        if (s, bk) not in ha: ha[(s, bk)] = dirbuild._h(dirbuild.arc_image(ctx, s, bk))
        return ha[(s, bk)]

    def choose(c, rule):
        """c: [(records in place, image sequence, arcade records, bank)] -> (arcade records, bank, rule) or (None, None, reason)"""
        if len({x[1] for x in c}) == 1: return c[0][2], c[0][3], rule
        c = sorted(c, key=lambda x: -x[0])
        if c[0][0] > c[1][0]: return c[0][2], c[0][3], rule + ", most records in place"
        top = [x for x in c if x[0] == c[0][0]]; g0 = [x for x in top if x[2][0][0] in idle]
        if g0 and len({x[1] for x in g0}) == 1: return g0[0][2], g0[0][3], rule + ", the one of animation group 0"
        return None, None, "ambiguous: %d arcade animations fit" % len({x[1] for x in top})
    out = []
    for recs, lp in anims(S, n):
        if len(recs) < 2: out.append((recs, lp, None, None, "single record")); continue
        durs = tuple(r[2] for r in recs); strict = []; loose = []
        if durs[-1] >= 0xfff: durs = durs[:-1] + (None,)                 # the select screen holds its last record
        for j in bykey.get(durs, []):
            A = AA[j][0]
            for bk in (0, 0x10000, 0x20000, 0x30000):
                seq = tuple(ah(x[4], bk) for x in A); eq = sum(ph(r[4] & 0xffff) == h for r, h in zip(recs, seq))
                if not eq: continue
                (strict if all(ph(r[4] & 0xffff) in seq for r in recs) else loose).append((eq, seq, A, bk))
        res = None
        for rule, c in (("strict", strict), ("agree", loose)):
            if c: res = choose(c, rule); break
        if res is None: res = (None, None, "no arcade animation with these durations and a kept sprite in place")
        out.append((recs, lp, res[0], res[1], res[2]))
    # second method (selbuild's): the animation is a copy of a fight body animation - a run of its records with the same kept
    # sprites whatever the durations, or the whole animation with the same durations and no other kept sprite; the body pairing
    # of aplib gives the arcade record of each.  Covers kept sprites the port redrew (no arcade sprite is pixel-identical).
    if any(A is None and len(recs) > 1 for recs, lp, A, bk, why in out):
        body = collections.defaultdict(list); whole = collections.defaultdict(list)
        for ch in range(19):
            try: pb, al, un = aplib.pairs_all(ctx, ch)
            except Exception: continue
            m = NSP(os.path.join(ctx.ps1, "A", "A0", f"SP_PL{ch:02X}.NSP")); m.decode_all(); mg = set(dict(m.groups())); hc = {}; seq = []
            for x, y in al:
                lo = pb.frameid(y.frame) & 0xffff
                if lo not in hc: hc[lo] = img_hash(m, lo) if lo in mg else None
                seq.append((hc[lo], x.spr, y.end, x.addr, y.dur))
            bank = next((b for b in (0, 0x10000, 0x20000, 0x30000) if sum(ctx.valid_def(x[1]) and ah(x[1], b) == x[0] for x in seq[:400]) >= 3), None)
            if bank is None: continue
            i = 0
            while i < len(seq):
                j = i
                while not seq[j][2] and j + 1 < len(seq): j += 1
                a = seq[i:j + 1]
                for k in range(len(a)): body[a[k][0]].append((a, k, bank))
                whole[tuple(x[4] for x in a)].append((a, bank))
                i = j + 1
        for t, (recs, lp, A, bk, why) in enumerate(out):
            if A is not None or len(recs) < 2: continue
            hs = [ph(r[4] & 0xffff) for r in recs]
            c = [(a, b) for a, b in whole.get(tuple(r[2] for r in recs), []) if set(hs) <= {x[0] for x in a}]      # the whole animation first
            if not c:
                for a, k, b in body.get(hs[0], []):
                    if k + len(recs) <= len(a) and all(a[k + i][0] == h for i, h in enumerate(hs)): c.append((a[k:k + len(recs)], b))
            c = [(sum(x[0] == h for x, h in zip(a, hs)), tuple(ah(x[1], b) for x in a), [(x[3], 0, x[4], x[2], x[1]) for x in a], b) for a, b in c if all(ctx.valid_def(x[1]) for x in a)]
            if c:
                r = choose(c, "body animation")
                out[t] = (recs, lp, r[0], r[1], r[2] if r[0] is not None else why + "; body animations: " + r[2])
    return out


# ---------------------------------------------------------------- the stub (original code, position independent)
def _i(op, rs, rt, imm): return struct.pack("<I", op << 26 | rs << 21 | rt << 16 | (imm & 0xffff))
def _r(rs, rt, rd, fn): return struct.pack("<I", rs << 21 | rt << 16 | rd << 11 | fn)
A0, A1, T0, T1, T2, T3, T4, T5, T6, T7, T8, T9, RA, ZERO = 4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31, 0


def stub(ranges, set2=SET2, set1=SET1, base=LOAD + BASE, player=PLAYER):
    """Called in place of the animation start routine (a0 = object, a1 = record).  When the object's animation base (+0x44) is the
    select screen's and the record lies in one of `ranges` (offsets from that base, [lo, hi)), the object's sprite set (+0x6c)
    becomes set2; an object left on set2 by an earlier call goes back to set1.  Then the routine itself runs.  Uses t0-t9 only;
    no absolute address of its own: copy it to any 4-byte aligned address and point the call sites at its first word."""
    tab = b"".join(struct.pack("<HH", lo, hi) for lo, hi in sorted(ranges)) + struct.pack("<HH", 0xffff, 0xffff)
    n = len(tab) // 4
    c = [_i(0x23, A0, T0, 0x44),                       # lw    t0, 0x44(a0)
         _i(0x0f, 0, T1, base >> 16),                  # lui   t1, base.hi
         _i(0x0d, T1, T1, base & 0xffff),              # ori   t1, t1, base.lo
         None,                                         # bne   t0, t1, out
         _r(A1, T1, T2, 0x23),                         # subu  t2, a1, t1          (delay slot)
         _i(0x24, A0, T3, 0x6c),                       # lbu   t3, 0x6c(a0)
         _i(0x0d, ZERO, T4, set2),                     # ori   t4, zero, set2
         _i(0x05, T3, T4, 2),                          # bne   t3, t4, +2
         _i(0x0d, ZERO, T5, set1),                     # ori   t5, zero, set1      (delay slot)
         _i(0x28, A0, T5, 0x6c),                       # sb    t5, 0x6c(a0)
         _i(0x0b, T2, T3, 0x7fff),                     # sltiu t3, t2, 0x7fff
         None,                                         # beq   t3, zero, out
         _r(RA, ZERO, T9, 0x21),                       # addu  t9, ra, zero        (delay slot)
         _i(0x01, ZERO, 0x11, n + 1),                  # bgezal zero, past the table: ra = address of the table
         bytes(4)]                                     # nop
    c += [tab[4 * i:4 * i + 4] for i in range(n)]
    c += [_r(RA, ZERO, T6, 0x21),                      # addu  t6, ra, zero
          _r(T9, ZERO, RA, 0x21),                      # addu  ra, t9, zero
          _i(0x25, T6, T7, 0),                         # loop: lhu t7, 0(t6)
          _i(0x25, T6, T8, 2),                         # lhu   t8, 2(t6)
          _r(T2, T7, T3, 0x2b),                        # sltu  t3, t2, t7          below this range: no later one can match (sorted)
          None,                                        # bne   t3, zero, out
          _r(T2, T8, T3, 0x2b),                        # sltu  t3, t2, t8          (delay slot)
          _i(0x04, T3, ZERO, -6),                      # beq   t3, zero, loop
          _i(0x09, T6, T6, 4),                         # addiu t6, t6, 4           (delay slot)
          _i(0x28, A0, T4, 0x6c),                      # sb    t4, 0x6c(a0)
          struct.pack("<I", 0x08000000 | (player >> 2 & 0x3ffffff)),      # out: j player
          bytes(4)]                                    # nop
    out = len(c) - 2
    for k, op, rs, rt in ((3, 0x05, T0, T1), (11, 0x04, T3, ZERO), (15 + n + 5, 0x05, T3, ZERO)): c[k] = _i(op, rs, rt, out - (k + 1))
    return b"".join(c)


# ---------------------------------------------------------------- the second sprite file
def build(ctx, ps1, basedir, set2=SET2):
    """-> dict(nsp, ap8, report, ...).  ps1: directory with the disc files; basedir: content directory whose SP_SEL0.NSP and
    SELECT.AP8 stay as they are (their state is what the second set is measured against)"""
    n = NSP(os.path.join(ps1, "A", "A2", "SP_SEL0.NSP")); n.decode_all()
    S = open(os.path.join(ps1, "P", "P4", "SELECT.BIN"), "rb").read()
    nbp = os.path.join(basedir, "SP_SEL0.NSP"); nb = NSP(nbp); nb.decode_all(); a8 = open(os.path.join(basedir, "SELECT.AP8"), "rb").read()
    if a8[:4] != b"AS8\x01" or struct.unpack_from("<I", a8, 4)[0] != len(S) or a8[12:28] != hashlib.sha1(S).digest()[:16]:
        raise ValueError("the base directory's SELECT.AP8 is not for this SELECT.BIN")
    Sb = bytearray(S); used1 = set(dict(n.groups()))                       # sec0 offsets of sprites in the first file
    for i in range(struct.unpack_from("<I", a8, 8)[0]):
        off, fid = struct.unpack_from("<II", a8, 28 + 8 * i); struct.pack_into("<I", Sb, off, fid); used1.add(fid & 0xffff)
    P = pair(ctx, n, S)
    hb = {}

    def cur(r):                                                             # image the base content shows on this record
        f = struct.unpack_from("<I", Sb, r[0] + 4)[0] & 0xffff
        if f not in hb: hb[f] = img_hash(nb, f)
        return hb[f]
    s0 = bytearray(); s1 = bytearray(); s2 = bytearray(); s3 = bytearray(b"\x04\x00")
    tilemap = {}; sprite = {}; frec = {}; patches = []; ranges = []; report = []; made = {}; maxraw = 0; maxrect = [0, 0]

    def newsprite(s, bk):
        nonlocal maxraw
        if (s, bk) in sprite: return sprite[(s, bk)]
        res = None
        if ctx.valid_def(s):
            ap = ctx.arc_parts(s); raw = sum((nx + 1) * (ny + 1) * 128 for c, nx, ny, lo, x, y in ap)
            keys = list(dict.fromkeys((bk, c, nx, ny) for c, nx, ny, lo, x, y in ap))
            pk = aplib.pack([(k[2] + 1, k[3] + 1) for k in keys]) if len(ap) <= aplib.MAXPARTS and raw <= aplib.MAXRAW else None
            if pk is not None and len(s1) // 4 + sum(1 for k in keys if k not in tilemap) <= 4096 and len(s0) + 7 * len(ap) + 8 <= 0xfff0 and len(s3) + 10 + len(ap) <= 0xfff0:
                W, H, pos = pk; place = dict(zip(keys, pos))
                while len(s0) in used1: s0.append(0)                        # no sprite of this file starts where one of the first file does
                lo_ = len(s0); maxraw = max(maxraw, raw)
                if W * H > maxrect[0] * maxrect[1]: maxrect[:] = [W, H]
                for i, (c, nx, ny, lo, x, y) in enumerate(ap):
                    k = (bk, c, nx, ny)
                    if k not in tilemap:
                        tilemap[k] = len(s1) // 4
                        s1.extend(struct.pack("<I", len(s2) | (nx << 24) | (ny << 28))); s2.extend(aplib.rle_encode(aplib.ps1_bytes(ctx.block(c, nx, ny, bk))))
                    s0.extend(aplib.enc_part((lo & 0x7f) | (0x80 if i == len(ap) - 1 else 0), tilemap[k], x, y))
                A = len(s3)
                s3.extend(struct.pack("<HBB", 0, (H - 1) << 4 | (W - 1), 0xff) + bytes(place[(bk, c, nx, ny)][1] << 4 | place[(bk, c, nx, ny)][0] for c, nx, ny, lo, x, y in ap))
                res = (lo_, A)
        sprite[(s, bk)] = res
        return res
    for recs, lp, A_, bk, why in P:
        k = recs[0][0] - BASE; N = len(recs)
        row = dict(offset=k, records=N, sprites_stock=len({r[4] & 0xffff for r in recs}))
        if A_ is None:
            if N > 1: row.update(set=SET1, note="not paired: " + why); report.append(row)
            continue
        ah = [dirbuild._h(dirbuild.arc_image(ctx, x[4], bk)) for x in A_]
        cut0 = sum(img_hash(n, r[4] & 0xffff) != h for r, h in zip(recs, ah)); cut1 = sum(cur(r) != h for r, h in zip(recs, ah))
        row.update(arcade=A_[0][0], rule=why, sprites_arcade=len({x[4] for x in A_}), cut_records_stock=cut0, cut_records_base=cut1)
        loop_i = (lp - k) // 8 if (lp - k) % 8 == 0 and 0 <= lp - k < 8 * N else None
        if cut1 == 0: row.update(set=SET1, note="complete in the first file"); report.append(row); continue
        if loop_i is None: row.update(set=SET1, note="left as it is: the loop leaves the animation"); report.append(row); continue
        mark = (len(s0), len(s1), len(s2), len(s3), dict(tilemap), dict(sprite), dict(frec))
        sp = [newsprite(x[4], bk) for x in A_]
        if any(x is None for x in sp):                                      # all or nothing: an animation never mixes the two sets
            del s0[mark[0]:], s1[mark[1]:], s2[mark[2]:], s3[mark[3]:]; tilemap.clear(); tilemap.update(mark[4]); sprite.clear(); sprite.update(mark[5]); frec.clear(); frec.update(mark[6])
            row.update(set=SET1, note="left as it is: a sprite is over the limits or the second file is full"); report.append(row); continue
        for i, (r, x) in enumerate(zip(recs, A_)):
            j = i; C = 0xffff                                               # pre-decode hint: the next different sprite of the script (as stock)
            for _ in range(N):
                j = j + 1 if j + 1 < N else loop_i
                if A_[j][4] != x[4]: C = sp[j][0]; break
            lo_, A = sp[i]
            if (lo_, A, C) not in frec: frec[(lo_, A, C)] = len(s3); s3.extend(struct.pack("<HHH", A, 0, C))
            fid = frec[(lo_, A, C)] << 16 | lo_; patches.append((r[0] + 4, fid)); made[fid] = (x[4], bk)
        ranges.append((k, k + 8 * N)); row.update(set=set2, note="second file"); report.append(row)
    for sec in (s0, s2, s3): sec.extend(bytes(-len(sec) % 4))
    hdr = struct.pack("<4I", 16, 16 + len(s0), 16 + len(s0) + len(s1), 16 + len(s0) + len(s1) + len(s2))
    nsp = hdr + bytes(s0) + bytes(s1) + bytes(s2) + bytes(s3)
    merged = []
    for lo, hi in sorted(ranges):
        if merged and merged[-1][1] == lo: merged[-1] = (merged[-1][0], hi)
        else: merged.append((lo, hi))
    jal = struct.pack("<I", 0x0c000000 | (PLAYER >> 2 & 0x3ffffff)); sites = [o for o in range(0, len(S) - 3, 4) if S[o:o + 4] == jal]
    code = stub(merged, set2)
    ap8 = struct.pack("<4sI16sBBHIIII", b"AS8\x02", len(S), hashlib.sha1(S).digest()[:16], set2, SET1, 0, len(patches), len(merged), len(sites), len(code))
    ap8 += b"".join(struct.pack("<II", o, f) for o, f in patches) + b"".join(struct.pack("<HH", lo, hi) for lo, hi in merged)
    ap8 += b"".join(struct.pack("<I", o) for o in sites) + code
    return dict(nsp=nsp, ap8=ap8, patches=patches, ranges=merged, sites=sites, stub=code, report=report, made=made, sec=[len(s0), len(s1), len(s2), len(s3)],
                tiles=len(s1) // 4, sprites=sum(1 for v in sprite.values() if v), maxraw=maxraw, maxrect=maxrect, used1=used1, select_size=len(S), set=set2)


def check(ctx, r, tmpdir):
    """the built file from its bytes: every patched frame against the arcade sprite, pixel for pixel; layouts; limits -> (frames, bad, notes)"""
    tmp = os.path.join(tmpdir, "_sel2check_%d.nsp" % os.getpid()); open(tmp, "wb").write(r["nsp"]); n = NSP(tmp); n.decode_all(); os.remove(tmp)
    s3 = n.sec[3]; bad = 0; notes = []; starts = {f & 0xffff for f in r["made"]}
    if len(n.tiles) > 4096 or len(n.sec[0]) >= 0x10000 or len(s3) >= 0x10000: notes.append("over a file limit")
    if n.sec[2][:4] in (b"XVM1", b"XVH1", b"XVF1"): notes.append("tile data starts with a codec magic")
    if s3[0] != 4: notes.append("frame section type")
    if starts & r["used1"]: notes.append("sprite offsets shared with the first file")
    for fid, (s, bk) in r["made"].items():
        hi = fid >> 16; lo = fid & 0xffff; A, B, C = struct.unpack_from("<HHH", s3, hi); g = dirbuild.group_parts(n.sec[0], lo)
        ok = B == 0 and s3[A:A + 2] != b"\xff\xff" and s3[A + 3] == 0xff and (C == 0xffff or C in starts) and A + 4 + len(g) <= len(s3)
        a = dirbuild.arc_image(ctx, s, bk); p = dirbuild.ps1_image(n, lo)
        ok = ok and a[0] == p[0] and a[1] == p[1] and a[2].shape == p[2].shape and bool((a[2] == p[2]).all())
        W = (s3[A + 2] & 15) + 1; H = (s3[A + 2] >> 4) + 1; occ = {}
        for i, q in enumerate(g):
            t = n.tiles[q.tile]; b = s3[A + 4 + i]
            for yy in range(b >> 4, (b >> 4) + t.h // 16):
                for xx in range(b & 15, (b & 15) + t.w // 16):
                    ok = ok and occ.get((xx, yy), q.tile) == q.tile and xx < W and yy < H; occ[(xx, yy)] = q.tile
        bad += not ok
    covered = set()
    for lo, hi in r["ranges"]: covered.update(range(lo, hi, 4))
    if {o - 4 - BASE for o, f in r["patches"]} - covered: notes.append("patched record outside the ranges")
    if any(x["set"] != r["set"] and covered & set(range(x["offset"], x["offset"] + 8 * x["records"], 4)) for x in r["report"]): notes.append("a first-set animation inside a range")
    if len({o for o, f in r["patches"]}) * 8 != sum(hi - lo for lo, hi in r["ranges"]): notes.append("a record of a second-set animation has no frame id")
    return len(r["made"]), bad, notes


def main(argv=None):
    import argparse, pickle, shutil
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arcade", nargs="+"); ap.add_argument("--disc"); ap.add_argument("--base", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--ctx"); ap.add_argument("--ps1"); ap.add_argument("--anims")
    a = ap.parse_args(argv)
    if os.path.abspath(a.base) == os.path.abspath(a.out): print("ERROR: --out must be a new directory"); return 2
    os.makedirs(a.out, exist_ok=True); work = os.path.join(a.out, "_work"); os.makedirs(work, exist_ok=True)
    if a.ctx:
        prg, T, chtab = pickle.load(open(a.ctx, "rb")); ps1 = a.ps1; ctx = aplib.Ctx(prg, T, ps1, chtab)
        if a.anims: ctx._dir_anims = pickle.load(open(a.anims, "rb"))
    else:
        import build8
        try:
            setname, prg, roms = build8.read_arcade(a.arcade); ps1 = build8.read_ps1(a.disc, work, list(range(18)))
        except build8.Fail as ex: print("ERROR:", ex); return 2
        ctx = aplib.Ctx(prg, aplib.gfx_decode(lambda nm: roms[nm]), ps1, aplib.find_chtab(prg))
    r = build(ctx, ps1, a.base); tot, bad, notes = check(ctx, r, work)
    if bad or notes: print("ERROR: self-check failed: %d bad frames %s" % (bad, notes)); return 2
    for fn in os.listdir(a.base):                                          # the new directory = the base content, unchanged, plus the two files
        if os.path.isfile(os.path.join(a.base, fn)): shutil.copyfile(os.path.join(a.base, fn), os.path.join(a.out, fn))
    open(os.path.join(a.out, "SP_SEL2.NSP"), "wb").write(r["nsp"]); open(os.path.join(a.out, "SELECT2.AP8"), "wb").write(r["ap8"])
    man = json.load(open(os.path.join(a.out, "manifest.json")))
    man["select2"] = dict(nsp="SP_SEL2.NSP", nsp_size=len(r["nsp"]), nsp_sha1=hashlib.sha1(r["nsp"]).hexdigest(), sections=r["sec"], tiles=r["tiles"], sprites=r["sprites"],
                          ap8="SELECT2.AP8", ap8_size=len(r["ap8"]), ap8_sha1=hashlib.sha1(r["ap8"]).hexdigest(), set=r["set"], patches=len(r["patches"]),
                          ranges=[list(x) for x in r["ranges"]], sites=len(r["sites"]), stub_bytes=len(r["stub"]), max_rect=r["maxrect"], max_frame_bytes=r["maxraw"], checked=tot,
                          base=os.path.basename(os.path.abspath(a.base)), animations=r["report"])
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1, sort_keys=True)
    shutil.rmtree(work, ignore_errors=True)
    print("SP_SEL2 sections", r["sec"], "tiles", r["tiles"], "sprites", r["sprites"], "file", len(r["nsp"]), "| SELECT2.AP8", len(r["ap8"]), "bytes:", len(r["patches"]), "frame ids,",
          len(r["ranges"]), "ranges,", len(r["sites"]), "call sites, stub", len(r["stub"]), "bytes | checked", tot, "frames")
    for x in r["report"]:
        print(" +%04x records %2d set %02x  %s" % (x["offset"], x["records"], x["set"], ("arcade %06x, sprites %d -> %d, cut records %d (stock) %d (base) | " % (
            x["arcade"], x["sprites_stock"], x["sprites_arcade"], x["cut_records_stock"], x["cut_records_base"]) if "arcade" in x else "") + x["note"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
