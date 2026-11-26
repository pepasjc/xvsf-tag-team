"""Assist frame cuts (asdip lead, rc4.6 --ascut): inside one animation of a special-partner assist (DAxx_11.A0 code
section, same animation blob as the characters: tools/cuts/animtab.py), a frame shows its NEIGHBOUR frame group of
that animation instead.  Done as the characters' --redcut / --wmhover: the frame-table entry's u16 sec1 offset of the
cut frame -> the neighbour's sec1 offset (sec3 / hit data untouched).  The same group on consecutive frames = the
player path's cached draw: no decode (assists draw through the player path, l5log site B).

Rules (the characters' cut rules, tools/cuts/cutrules.py + tools/fxhalf/cutcheck.py, applied per assist):
  never cut  (a) a group shown while an assist object's attack id (obj + 0x88) was non-zero (work/asdip/act, asact.py)
             (b) the peak / extension pose of every ATTACK animation (one that shows an active-hitbox group; the
                 characters' rule skips movement / damage animations): farthest beyond its first frame, ties 2 px
             (u) every group the scans never showed (no decode saving to buy there)
             (c) the first frame of every animation
             (2) the last frame of every animation (never replaced by an earlier frame)
             (3 v2) the largest-area and the farthest-reach frame of every animation with >= 2 distinct frames that
                 shows an effect frame (a group drawn by a child object of the assist, asact timeline)
  the replacement is the previous (else next) group in EVERY animation context of that frame index (same animation,
  nearest kept frame); no chains (a replacement is never cut, a cut never replaces); no two neighbours cut; every
  animation keeps >= 2 distinct frames (>= half for movement-free assists is not required); (1) mask IoU >= IOU
  (0.5) even for neighbours; (3b) the replacement has >= half the visible area; (redcut) the cut frame reaches at most
  EXT = 6 px beyond its replacement and vice versa (no beam / projectile / trail frame drawn as a frame without it,
  no frame without one drawn as a frame with it).
    python ascut.py plan [ids]      -> work/asdip/ascut.json {DAxx: [[frame index, table byte offset, old, new], ..]}
    python ascut.py check           independent re-check of ascut.json against the rules (the cutcheck gate) + report
    patch(a, code) -> code with the cuts (mktag --ascut)"""
import os, sys, json, struct
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "common", "dsp"))
import dsp as D
DATA = os.path.join(GAME, "work", "assist", "data")
OUT = os.path.join(GAME, "work", "asdip")
ACTS = [os.path.join(OUT, d) for d in ("act", "act2")]   # asact.py runs (two teams, both sides)
MAINOBJ = {0xbb90, 0xbca8}                         # *(main + 0x2f0) of P1 / P2 = the assist object itself


def act_files(a):
    return [os.path.join(d, n) for d in ACTS for n in ("DA%02X.json" % a, "DA%02X_p2.json" % a) if os.path.exists(os.path.join(d, n))]
IOU = float(os.environ.get("AC_IOU", "0.5"))
PEAK_TOL = 2
EXT = int(os.environ.get("AC_EXT", "6"))          # redcut.py's reach rule


def blob(code, ng=None):
    """animation blob of an assist code section: u32 off[4] = 16, records, frame table, info"""
    hits = []
    for B in range(0, len(code) - 16, 4):
        h = struct.unpack_from("<4I", code, B)
        if h[0] == 16 and h[0] < h[1] < h[2] < h[3] <= len(code) - B and (h[3] - h[2]) % 4 == 0: hits.append((B, h))
    assert len(hits) >= 1, "no blob"
    return hits[0]


class AsAnim:
    def __init__(self, a, code=None):
        self.a = a
        d = os.path.join(DATA, "DA%02X" % a)
        self.code = code if code is not None else open(os.path.join(d, "code.bin"), "rb").read()
        self.x = D.DSP(open(os.path.join(d, "rle.DSP"), "rb").read()); self.x.decode_all()
        self.gs = self.x.groups(); self.starts = [s for s, h, g in self.gs]
        st = {s: i for i, s in enumerate(self.starts)}
        b = self.code; B, h = blob(b); self.B, self.h = B, h
        u16 = lambda o: struct.unpack_from("<H", b, o)[0]
        self.ft = B + h[2]; self.nf = (h[3] - h[2]) // 4
        self.fso = [u16(self.ft + 4 * i) for i in range(self.nf)]
        self.frames = [st.get(o) for o in self.fso]
        T = B + h[0]; ncat = u16(T) // 2
        cats = [u16(T + 2 * i) for i in range(ncat)]
        ends = sorted(set(cats + [h[1] - h[0]]))
        self.anims = {}
        for k, co in enumerate(cats):
            nxt = min(e for e in ends if e > co); n = (nxt - co) // 2
            for j in range(n):
                off = u16(T + co + 2 * j)
                if B + h[1] + off >= B + h[2]: continue
                self.anims[(k, j)] = self.walk(off)

    def walk(self, off, limit=300):
        b = self.code; a = self.B + self.h[1] + off; out = []
        while len(out) < limit and a + 4 <= self.B + self.h[2]:
            w0, w1 = struct.unpack_from("<HH", b, a); a += 4
            f = (w0 & 0xff) | (w1 & 0x7000) >> 4
            out.append((f, w0 >> 8, self.frames[f] if f < len(self.frames) else None))
            if w1 & 0x8000: break
        return out

    def ctx(self):
        """per animation: collapsed [[group, {frame indices}]]"""
        out = {}
        for k, recs in self.anims.items():
            sq = []
            for f, d, g in recs:
                if g is None: continue
                if sq and sq[-1][0] == g: sq[-1][1].add(f)
                else: sq.append([g, {f}])
            out[k] = sq
        return out

    # ---- pictures
    def mask(self, g):
        if not hasattr(self, "_m"): self._m = {}
        if g in self._m: return self._m[g]
        boxes = [(pt, self.x.tiles[pt.tile]) for pt in self.gs[g][2] if pt.tile < len(self.x.tiles)]
        if not boxes: self._m[g] = None; return None
        x0 = min(pt.x for pt, t in boxes); y0 = min(pt.y for pt, t in boxes)
        x1 = max(pt.x + t.wb * 2 for pt, t in boxes); y1 = max(pt.y + t.h for pt, t in boxes)
        m = np.zeros((y1 - y0, x1 - x0), bool)
        for pt, t in boxes:
            px = D.tile_pixels(t) != D.TRANSP
            if pt.flags & 0x20: px = px[:, ::-1]
            if pt.flags & 0x40: px = px[::-1, :]
            m[pt.y - y0:pt.y - y0 + t.h, pt.x - x0:pt.x - x0 + t.wb * 2] |= px
        self._m[g] = (x0, y0, m)
        return self._m[g]

    def area(self, g):
        m = self.mask(g); return 0 if m is None else int(m[2].sum())

    def reach(self, g):
        m = self.mask(g)
        if m is None: return 0
        x0, y0, a = m
        return max(abs(x0), abs(x0 + a.shape[1]), abs(y0), abs(y0 + a.shape[0]))

    def extent(self, g):
        m = self.mask(g)
        if m is None: return None
        x0, y0, a = m
        return x0 + a.shape[1], x0, -y0

    def iou(self, i, j):
        a, b = self.mask(i), self.mask(j)
        if a is None or b is None: return 1.0 if a is None and b is None else 0.0
        X0 = min(a[0], b[0]); Y0 = min(a[1], b[1])
        X1 = max(a[0] + a[2].shape[1], b[0] + b[2].shape[1]); Y1 = max(a[1] + a[2].shape[0], b[1] + b[2].shape[0])
        A = np.zeros((Y1 - Y0, X1 - X0), bool); Bm = A.copy()
        A[a[1] - Y0:a[1] - Y0 + a[2].shape[0], a[0] - X0:a[0] - X0 + a[2].shape[1]] = a[2]
        Bm[b[1] - Y0:b[1] - Y0 + b[2].shape[0], b[0] - X0:b[0] - X0 + b[2].shape[1]] = b[2]
        u = (A | Bm).sum()
        return 1.0 if u == 0 else float((A & Bm).sum()) / u

    def dec_bytes(self, g):
        return sum(self.x.tiles[pt.tile].wb * self.x.tiles[pt.tile].h for pt in self.gs[g][2] if pt.tile < len(self.x.tiles))

    # ---- rules
    def protected(self):
        P = {}
        offs = self.starts; act = set(); seen = set(); eff = set()
        for p in act_files(self.a):
            j = json.load(open(p))
            act |= {offs.index(o) for o in j["active"] if o in offs}
            seen |= {offs.index(o) for o in j["seen"] if o in offs}
            for fr in j.get("timeline", []):
                for ob, g, at in fr:
                    if ob not in MAINOBJ and g in offs: eff.add(offs.index(g))   # drawn by a child object = effect
        self.act_ok = bool(act_files(self.a)); self.eff = eff
        for g in act: P.setdefault(g, set()).add("a:active hitbox")
        for g in range(len(self.gs)):
            if g not in seen: P.setdefault(g, set()).add("u:not seen in the scans")
        for k, sq in self.ctx().items():
            s = [g for g, fs in sq]
            if not s: continue
            P.setdefault(s[0], set()).add("c:first frame")
            P.setdefault(s[-1], set()).add("2:last frame")
            if len(set(s)) < 2: continue
            if set(s) & eff:                           # rule (3) v2: animations with effect frames (child objects)
                P.setdefault(max(set(s), key=lambda g: (self.area(g), -s.index(g))), set()).add("3:largest area")
                P.setdefault(max(set(s), key=lambda g: (self.reach(g), self.area(g), -s.index(g))), set()).add("3:farthest reach")
            if not set(s) & act: continue              # rule (b): attack animations (show an active-hitbox group)
            e0 = self.extent(s[0])
            if not e0: continue
            sc = {}
            for g in set(s):
                e = self.extent(g)
                if e: sc[g] = max(e[0] - e0[0], e0[1] - e[1], e[2] - e0[2])
            m = max(sc.values()) if sc else 0
            if m > 0:
                for g, v in sc.items():
                    if v >= m - PEAK_TOL: P.setdefault(g, set()).add("b:peak pose")
        return P

    def over(self, G, R):
        """px the cut frame reaches beyond its replacement in any direction (beams, trails, projectiles)"""
        a, b = self.mask(G), self.mask(R)
        if a is None or b is None: return 0 if a is None else 999
        return max(b[0] - a[0], b[1] - a[1], (a[0] + a[2].shape[1]) - (b[0] + b[2].shape[1]), (a[1] + a[2].shape[0]) - (b[1] + b[2].shape[0]))

    def vis(self, G, R):
        if self.over(G, R) > EXT: return "cut frame reaches %d px beyond its replacement" % self.over(G, R)
        if self.over(R, G) > EXT: return "replacement reaches %d px beyond the cut frame" % self.over(R, G)
        if self.iou(G, R) < IOU: return "IoU %.2f < %.2f" % (self.iou(G, R), IOU)
        if self.area(G) and self.area(R) * 2 < self.area(G): return "replacement under half the area"
        return None


def neighbours(A, ctx):
    """frame index -> (set of prev groups, set of next groups) intersected over every context of that frame index"""
    nb = {}
    for k, sq in ctx.items():
        for q, (G, fs) in enumerate(sq):
            pv = {sq[q - 1][0]} if q > 0 else set(); nx = {sq[q + 1][0]} if q + 1 < len(sq) else set()
            for f in fs:
                if f in nb: nb[f] = (nb[f][0] & pv, nb[f][1] & nx)
                else: nb[f] = (pv, nx)
    return nb


def floors_ok(A, ctx, red):
    for k, sq in ctx.items():
        b = len({G for G, fs in sq})
        hit = [any(f in red for f in fs) for G, fs in sq]
        if any(hit[q] and hit[q + 1] for q in range(len(sq) - 1)): return False
        for q, (G, fs) in enumerate(sq):              # a frame index with more records in one sequence: all or none
            pass
        aft = len({red.get(f, G) for G, fs in sq for f in fs})
        if b >= 2 and aft < 2: return False
    return True


def weights(a):
    """decode weight per group: how often it was shown NEW (group change) in the asact runs (both sides)"""
    w = {}
    for p in act_files(a):
        last = {}
        for fr in json.load(open(p)).get("timeline", []):
            for ob, g, at in fr:
                if last.get(ob) != g: w[g] = w.get(g, 0) + 1
                last[ob] = g
    return w


def plan(a):
    A = AsAnim(a); ctx = A.ctx(); P = A.protected(); nb = neighbours(A, ctx)
    W = weights(a)
    fr_of = {}
    for f, G in enumerate(A.frames):
        if G is not None: fr_of.setdefault(G, set()).add(f)
    used = {f for sq in ctx.values() for G, fs in sq for f in fs}
    cand = []
    for f in sorted(used):
        G = A.frames[f]
        if G is None or G in P or not W.get(A.starts[G]): continue      # only frames the scans drew new (decodes)
        pv, nx = nb[f]
        for R in sorted(pv) + sorted(nx - pv):
            if R == G or A.vis(G, R): continue
            cand.append((-(W.get(A.starts[G], 0) * A.dec_bytes(G)), -A.iou(G, R), f, G, R))
            break
    cand.sort()
    red = {}
    for _, _, f, G, R in cand:
        if f in red: continue
        if any(A.frames[g] == R for g in red) or R in {A.frames[g] for g in red}: continue     # replacement never cut
        if any(v == G for v in red.values()): continue                                         # a cut never replaces
        if any(red.get(f2) is not None for f2 in fr_of.get(R, ())): continue
        trial = dict(red); trial[f] = R
        if not floors_ok(A, ctx, trial): continue
        red = trial
    rows = [[f, A.ft + 4 * f, A.starts[A.frames[f]], A.starts[R]] for f, R in sorted(red.items())]
    tot = sum(W.get(A.starts[G], 0) * A.dec_bytes(G) for G in range(len(A.gs)))
    sav = sum(W.get(A.starts[A.frames[f]], 0) * A.dec_bytes(A.frames[f]) for f in red)
    return rows, dict(groups=len(A.gs), frames=A.nf, protected=len(P), cut=len(red), act=A.act_ok,
                      dec_share=round(sav / tot, 3) if tot else 0.0)


def check(a, rows):
    """independent re-check of one assist's cuts on the patched code -> list of FAIL strings"""
    A0 = AsAnim(a); P = A0.protected(); ctx = A0.ctx(); nb = neighbours(A0, ctx)
    code = patch(a, A0.code, rows)
    A1 = AsAnim(a, code)
    fails = []
    if not A0.act_ok: fails.append("no attack-box scan")
    red = {}
    for f in range(A0.nf):
        if A1.fso[f] != A0.fso[f]: red[f] = A1.frames[f]
    if set(red) != {r[0] for r in rows}: fails.append("patched frames differ from the plan")
    assert code[:A0.ft] == A0.code[:A0.ft] and code[A0.ft + 4 * A0.nf:] == A0.code[A0.ft + 4 * A0.nf:]
    for f in range(A0.nf):
        if code[A0.ft + 4 * f + 2:A0.ft + 4 * f + 4] != A0.code[A0.ft + 4 * f + 2:A0.ft + 4 * f + 4]: fails.append("sec3 word changed f%d" % f)
    for f, R in red.items():
        G = A0.frames[f]
        if R is None: fails.append("f%d -> no group" % f); continue
        if G in P: fails.append("f%d g%d protected (%s)" % (f, G, ",".join(sorted(P[G]))))
        pv, nx = nb.get(f, (set(), set()))
        if R not in pv | nx: fails.append("f%d g%d -> g%d not a neighbour in every animation" % (f, G, R))
        v = A0.vis(G, R)
        if v: fails.append("f%d g%d -> g%d %s" % (f, G, R, v))
        if R in {A0.frames[k] for k in red}: fails.append("f%d chain: replacement g%d is cut" % (f, R))
    if not floors_ok(A0, ctx, red): fails.append("floors (two neighbours cut / animation under 2 frames)")
    for k, sq in ctx.items():                          # the drawn sequence: every frame shows a group of the SAME animation
        gs = {G for G, fs in sq}
        for G, fs in sq:
            for f in fs:
                if red.get(f, G) not in gs: fails.append("anim %d.%d f%d shows a foreign group" % (k[0], k[1], f))
    return fails


def patch(a, code, rows=None):
    if rows is None: rows = json.load(open(os.path.join(OUT, "ascut.json")))["DA%02X" % a]
    b = bytearray(code)
    for f, o, old, new in rows:
        assert struct.unpack_from("<H", b, o)[0] == old, (a, f, o)
        struct.pack_into("<H", b, o, new)
    return bytes(b)


def reloc_words(a):
    """word indices the relocation table touches (the frame table must not be among them)"""
    T = open(os.path.join(DATA, "DA%02X" % a, "reloc.bin"), "rb").read()
    v = struct.unpack("<%dH" % (len(T) // 2), T); i = 0; out = set()
    for part in range(4):
        while v[i] != 0xffff:
            out.add(v[i]); i += 2 if part == 3 else 1
        i += 1
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if cmd == "plan":
        ids = [int(v, 16) for v in sys.argv[2:]] or list(range(0x16))
        p = os.path.join(OUT, "ascut.json"); allj = json.load(open(p)) if os.path.exists(p) else {}
        rep = {}
        for a in ids:
            rows, st = plan(a)
            A = AsAnim(a); rw = reloc_words(a)
            assert not any((A.ft + 4 * f) // 4 in rw for f in range(A.nf)), "frame table relocated"
            allj["DA%02X" % a] = rows; rep["DA%02X" % a] = st
            print("DA%02X groups %3d frames %3d protected %3d cut %2d decode share %.3f%s" % (
                a, st["groups"], st["frames"], st["protected"], st["cut"], st["dec_share"], "" if st["act"] else "  (NO ACT SCAN)"), flush=True)
        json.dump(dict(sorted(allj.items())), open(p, "w"), indent=1)
        json.dump(rep, open(os.path.join(OUT, "ascut_report.json"), "w"), indent=1)
    elif cmd == "check":
        j = json.load(open(os.path.join(OUT, "ascut.json"))); bad = 0
        for k in sorted(j):
            a = int(k[2:], 16); f = check(a, j[k]); bad += len(f)
            print("%s cuts %2d %s" % (k, len(j[k]), "OK" if not f else "FAIL " + "; ".join(f)))
        print("ASCUT CHECK %s (%d assists, %d cuts)" % ("ALL OK" if not bad else "FAIL %d" % bad, len(j), sum(len(v) for v in j.values())))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()


def sheet(path, ids=None):
    """contact sheet: per cut, the cut group (left, red frame) and what is drawn instead (right)"""
    from PIL import Image, ImageDraw
    j = json.load(open(os.path.join(OUT, "ascut.json"))); rows = []
    for k in sorted(j):
        a = int(k[2:], 16)
        if ids and a not in ids or not j[k]: continue
        A = AsAnim(a)
        for f, o, old, new in j[k]:
            rows.append((k, f, A, A.starts.index(old), A.starts.index(new)))
    def img(A, g, H=96):
        m = A.mask(g)
        if m is None: return Image.new("RGB", (8, H))
        x0, y0, a = m; im = Image.fromarray((a * 220).astype("uint8")).convert("RGB")
        s = min(1.0, H / im.height, 160 / im.width); return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
    W, H = 360, 120; cols = 4; n = len(rows)
    S = Image.new("RGB", (W * cols, H * ((n + cols - 1) // cols)), (40, 40, 48)); d = ImageDraw.Draw(S)
    for i, (k, f, A, G, R) in enumerate(rows):
        X, Y = (i % cols) * W, (i // cols) * H
        a, b = img(A, G), img(A, R)
        S.paste(a, (X + 4, Y + 16)); S.paste(b, (X + 180, Y + 16))
        d.text((X + 4, Y + 2), "%s f%d g%d -> g%d IoU %.2f" % (k, f, G, R, A.iou(G, R)), fill=(255, 255, 0))
    S.save(path)
