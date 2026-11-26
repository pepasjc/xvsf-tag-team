"""All static sec3 reference candidates per character: every 4-aligned word in the A0 code part whose low u16 is a frame
group start (sec1 offset) and whose high u16 is a sec3 offset < len(sec3) that walks cleanly with that group's part count
(s3fmt.walk_engine).  Main frame table entries are tagged 'main'; others 'other' (inline animation streams, helper /
projectile tables).  Dynamic captures (work/sec3/cap_*.json) are checked against main | other.
    python s3refs.py [ids]  -> work/sec3/refs.json"""
import os, sys, struct, json, glob, collections
HERE = os.path.dirname(os.path.abspath(__file__)); GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "common", "dsp"), os.path.join(GAME, "tools", "cuts"), os.path.join(GAME, "tools"), HERE]
import dsp as D, s3fmt as F, animtab, reloc as R


def scan(c):
    a = animtab.Anim(c); b = a.b; s3 = a.dsp.sec[3]; S = R.sections(b)
    g = {s: len(gg) for s, hh, gg in a.dsp.groups()}
    ft0, ft1 = a.B + a.h[2], a.B + a.h[3]
    main, other = [], []
    lo, hi = S[0][0], S[0][0] + S[0][1]
    for i in range(ft0, ft1, 4):                     # main frame table (2-aligned possible: read with byte loads)
        so, o = struct.unpack_from("<HH", b, i)
        if o == 0xffff: continue
        e, re, it, st = F.walk_engine(s3, o, g[so]); assert st == "ok"
        main.append((i, so, o, g[so], re))

    def item(p):                                     # inline animation stream item (0x8003c3f4): {u32 group|sec3 << 16,
        if p < lo or p + 8 > hi or p % 4: return None   # u16 dur | 0x8000 jump, u16 -> obj+0x38} [+ u32 next pointer]
        so, o, d = struct.unpack_from("<HHH", b, p)
        if so not in g or (o != 0xffff and o >= len(s3)) or d & 0x7fff > 600: return None
        if o != 0xffff and F.walk_engine(s3, o, g[so])[3] != "ok": return None
        if d & 0x8000:
            q = struct.unpack_from("<I", b, p + 8)[0] - R.B10
            return (so, o, q if lo <= q < hi and q % 4 == 0 else -1)
        return (so, o, p + 8)
    r = R.get(c); tg = set()                         # stream starts = relocation targets (pointer words, lui/lo pairs)
    for i in r.ptr: tg.add(r.A[i] - R.B10)
    for h, ls in r.hi_los.items():
        for l in ls: tg.add(r.target(h, l) - R.B10)
    def item2(p, base):                              # format 2 (0x8003c340, obj+0x72 = 2): {u16 -> 0x38, u16 dur | 0x8000,
        if p < lo or p + 8 > hi or p % 2: return None  # u32 group|sec3 << 16 (byte loads)}; jump: s16 at +8, rel. obj+0x60
        x, d, so, o = struct.unpack_from("<HHHH", b, p)
        if so not in g or (o != 0xffff and o >= len(s3)) or d & 0x7fff > 600: return None
        if o != 0xffff and F.walk_engine(s3, o, g[so])[3] != "ok": return None
        if d & 0x8000:
            if p + 10 > hi: return None
            q = base + struct.unpack_from("<h", b, p + 8)[0]
            return (so, o, q if lo <= q < hi and q % 2 == 0 else -1)
        return (so, o, p + 8)
    seen = set(); heads = []
    def sweep(p, fmt):                               # consecutive items from p (a stream block), any entry offset inside
        out = []
        while True:
            it = item(p) if fmt == 1 else item2(p, p)
            if not it: return out
            out.append((p,) + it[:2])
            if fmt == 1: d = struct.unpack_from("<H", b, p + 4)[0]; p += 12 if d & 0x8000 else 8
            else: d = struct.unpack_from("<H", b, p + 2)[0]; p += 10 if d & 0x8000 else 8
    starts = set(t for t in tg if lo <= t < hi and not ft0 <= t < ft1)
    for p in sorted(starts):
        for fmt in (1, 2):
            run = sweep(p, fmt)
            if not run: continue
            heads.append((fmt, p, len(run)))
            for q, so, o in run:
                if (fmt, q) in seen: continue
                seen.add((fmt, q))
                if o != 0xffff: other.append((q, so, o, g[so], F.walk_engine(s3, o, g[so])[1]))
    D0 = max(i for i in range(7, r.n) if r.A[i] == 0x03e00008) * 4 + 8      # data part: after the last jr $ra (text)
    covered = {q for f_, q in seen}
    for fmt, step in ((1, 4), (2, 2)):              # blind blocks (>= 3 consecutive items) in the data part only
        p = D0 + (-D0 % step)
        while p < hi - 8:
            if (ft0 <= p < ft1) or p in covered: p += step; continue
            run = sweep(p, fmt)
            if len(run) >= 3:
                heads.append((fmt, p, len(run), "blind"))
                for q, so, o in run:
                    covered.add(q)
                    if o != 0xffff: other.append((q, so, o, g[so], F.walk_engine(s3, o, g[so])[1]))
                p = run[-1][0] + 8
            else: p += step
    scan.heads = heads
    return a, s3, g, main, other


def main_():
    ids = [int(v, 16) for v in sys.argv[1:]] or D.char_ids("mvc")
    dyn = collections.defaultdict(set)
    for f in glob.glob(os.path.join(ROOT, "work", "sec3", "cap_*.json")):
        for c, off, grp, nparts, cons, path, cell, n in json.load(open(f))["recs"]:
            if c.isdigit(): dyn[int(c)].add((off, nparts))
    out = {}
    for c in ids:
        try: a, s3, g, mn, ot = scan(c)
        except Exception as ex: continue
        if not s3: continue
        mo = {o for i, so, o, n, re in mn}
        oo = {o for i, so, o, n, re in ot} - mo
        cov = bytearray(len(s3))
        for i, so, o, n, re in mn + ot: cov[o:re] = b"\1" * (re - o)
        d = dyn.get(c, set())
        miss = sorted(x for x in d if x[0] not in mo | {o for i, so, o, n, re in ot})
        dyn_other = sorted({x[0] for x in d if x[0] in oo})
        holes = []; k = 0
        while k < len(s3):
            if cov[k]: k += 1; continue
            j = k
            while j < len(s3) and not cov[j]: j += 1
            if not (j - k == 1 and s3[k] == 0) and not (j == len(s3) and j - k < 4 and not any(s3[k:j])): holes.append((k, j))
            k = j
        out["%02x" % c] = dict(main=len(mo), other_offsets=len(oo), other_words=[(hex(i), so, o, n) for i, so, o, n, re in ot if o in oo][:200],
                              dyn=len(d), dyn_in_other=dyn_other, dyn_unexplained=miss, holes=holes)
        print("%02x main %3d other-only %3d (words %3d) | dyn refs %3d, via other %2d, unexplained %d | holes %s" % (
            c, len(mo), len(oo), sum(1 for x in ot if x[2] in oo), len(d), len(dyn_other), len(miss), holes[:5]))
    json.dump(out, open(os.path.join(ROOT, "work", "sec3", "refs.json"), "w"), indent=0)


if __name__ == "__main__":
    main_()
