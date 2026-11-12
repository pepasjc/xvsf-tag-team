"""Common effects, second builder (work/ap/SPEC.md section 17): SP_EFF1.NSP + EFF1.AE8 for sprite set 0x26.

Pairing: dirbuild.pair (same durations, kept sprites pixel-identical: "pixel" pairs), then the animation SEQUENCE.  The EXE
holds the effect animations in the order of the arcade program; where the arcade has several variants of an effect (five
angles of the projectile ring, four bubble sizes, four directions of the dark burst, upward / sideways flames ...) the port
kept the sprites of ONE variant and made the others from it (plain copies, or copies warped by a modifier stream):
  * a run of consecutive PS1 animations with the same sprites and durations, one of them pixel-paired, is matched in
    order with the run of consecutive arcade animations of the same durations around its partner when both runs have
    the same length;
  * unpaired PS1 animations between two matched neighbours are matched in order with the arcade animations between
    the neighbours' partners when count, record counts and durations agree.
  An animation matched this way whose sprites are not those of its arcade animation is a "sequence" pair: no pixel
  proof, the evidence is the order (SPEC 17).  Sequence pairs are restored only for the families in VARIANTS.
Record kinds:
  * plain dynamic frame: gets the arcade frame (pixel pairs: always; sequence pairs: family in VARIANTS).
  * shared-slot frame (layout byte 3 != 0xff, one VRAM upload for all objects showing it): with the family in SHARED it
    gets a new shared frame with a slot index above the stock ones (24 stock entries).  The loader must then install a
    255-entry slot table for set 0x26 (SPEC 11); the manifest says `slot_table`.
  * modifier frame (frame record with a per-part vertex-offset stream: the port drew a cut frame by warping a kept
    sprite): with the family in MODIFIER (pixel pairs) or VARIANTS (sequence pairs) it gets the arcade frame, unwarped.
  * KEEP: families left entirely in their stock form (measured speed).
Nothing here is derived from either game.

    python eff2build.py --arcade SET.zip [PARENT.zip] --disc xvsf.bin --out NEWDIR [--shared a,b|all|none] [--modifier ..] [--variants ..] [--keep ..]
    (development: --ctx ctx.pkl --ps1 DIR_WITH_DISC_FILES --anims cache.pkl --exe SLUS_006.27)
"""
import os, sys, struct, hashlib, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aplib, dirbuild
from aplib import NSP
from dirbuild import _h, ps1_image, arc_image, group_parts

SET = 0x26
STOCK_SLOTS = 24                       # entries of the stock shared-slot table of set 0x26 (0x8005c65c + 4 x 0x26): new indices start here
EXE_BASE = 0x80010000 - 0x800          # RAM address of EXE file offset 0
# effect families: name -> EXE file offsets of the first record of every animation of the family (paired ones and their copies)
FAMILIES = collections.OrderedDict([
    ("muzzle_ring", [0x822fc, 0x82348, 0x82394, 0x823e0, 0x8242c]),      # ring at the start of a projectile (object type 0x24, subtypes 5-9)
    ("cyclops_ring", [0x82478, 0x82494]),                                 # type 0x24, subtypes 10, 11
    ("streak_burst", [0x824b0]),                                          # super start
    ("dust_lines", [0x8255c, 0x82588, 0x825b4, 0x825e0, 0x8260c]),        # dash / push-back ground dust, type 0x30
    ("dust_cloud", [0x82638, 0x826ac]),                                   # type 0x64 (slams)
    ("launch_ring", [0x82720]),                                           # type 0x24, subtype 12
    ("ring_in", [0x8277c]),
    ("star_sparkle", [0x827d8, 0x82834]),                                 # life-bar regeneration sparkle, type 0xac
    ("burst_ring", [0x828a4]),                                            # type 0x88, subtype 0
    ("debris", [0x828f8]),                                                # type 0x88, subtype 2 (throws, slams)
    ("dizzy_swoosh", [0x8291c, 0x82960]),                                 # type 0x4c
    ("chicks", [0x829d4, 0x82a18, 0x82a5c]),                             # dizzy birds; not paired (their sprites match no arcade animation of the same shape)
    ("bubbles", [0x82aa0, 0x82afc, 0x82b58, 0x82bb4]),                    # type 0x40 (cold hit), four variants
    ("flame_wisps", [0x82c10, 0x82c44, 0x82c60, 0x82ca4, 0x82cc0, 0x82cf4, 0x82d10, 0x82d54]),      # types 0x44 (fire hit) and 0xa0
    ("electric_arcs", [0x82d70, 0x82da4, 0x82dd8, 0x82e0c, 0x82e40]),     # type 0x48 (electric hit)
    ("dark_burst", [0x82e74, 0x82ee8, 0x82f5c, 0x82fd0]),                 # type 0x80 (Gambit's cards) and copies
])
# defaults = the measured release configuration (work/ap/SPEC.md section 17; harness work/ap/s3/erate.py, rule: every scenario within
# 1 main-loop iteration per 60 vblanks of stock, average and worst sliding window, mean of 4 alignments).  Stock -> restored:
KEEP = ["streak_burst",       # both players' supers 53.1/33 -> 51.3/37 (measured by the first builder, effbuild.py)
        "launch_ring",        # Storm's ice super (two rings on screen with the ice) 54.8/46.5 -> 53.9/43.5, with the 3 plain records alone
        "ring_in", "burst_ring",   # no game event found that shows them; forced, 6 instances: 55.9/50.8 -> 51.3/43.5
        "dust_cloud",         # Gambit's throw 60.0/60.0 -> 59.8/58.5
        "flame_wisps",        # Akuma's qcb+PP super 48.2/32.8 -> 46.0/30.8 (pixel pairs alone: also Bison's super 49.2/32.5 -> 47.8/31.8)
        "electric_arcs"]      # Storm's air super 50.1/31.8 -> 49.9/30.5 (worst window 1.25 lower)
SHARED = ["dust_lines", "cyclops_ring", "muzzle_ring", "dark_burst"]
MODIFIER = ["debris"]
VARIANTS = ["bubbles", "dark_burst", "dizzy_swoosh"]      # not muzzle_ring: the four other angles cost 1.0 / 2.0 in Ryu's super (52.2/40.0 -> 51.2/38.0)


class _Img:
    def __init__(self, P): self.P = P; self.B = 0; self.h = (0, 0, 0, 0)


def build(ctx, ps1, exe, keep=None, shared=None, modifier=None, variants=None):
    keep = KEEP if keep is None else keep; shared = SHARED if shared is None else shared; modifier = MODIFIER if modifier is None else modifier
    variants = VARIANTS if variants is None else variants
    fam_of = {o: f for f, L in FAMILIES.items() for o in L}
    n = NSP(os.path.join(ps1, "A", "A2", "SP_EFF1.NSP")); n.decode_all(); P = open(exe, "rb").read()
    s0, s1, s2, s3 = [bytearray(x) for x in n.sec]; stock3 = bytes(n.sec[3])
    paired, unpaired = dirbuild.pair(ctx, n, P, (0, 0))
    hp = {}; ha = {}

    def ph(lo):
        if lo not in hp: hp[lo] = _h(ps1_image(n, lo))
        return hp[lo]

    def ah(s, bk):
        if (s, bk) not in ha: ha[(s, bk)] = _h(arc_image(ctx, s, bk))
        return ha[(s, bk)]

    def kind(fid):
        A, B, C = struct.unpack_from("<HHH", stock3, fid >> 16)
        if A + 4 > len(stock3) or stock3[A:A + 2] == b"\xff\xff": return "composite"
        if stock3[A + 3] != 0xff: return "shared"
        return "modifier" if B else "plain"

    def frec(fid): return struct.unpack_from("<HHH", stock3, fid >> 16)
    # sequence matching (see the module text) -> units: (records, arcade records, bank, arcade loop target, "pixel" | "sequence")
    AA = dirbuild.arc_anims(ctx); aidx = {a[0][0][0]: i for i, a in enumerate(AA)}
    ps = sorted([p[0] for p in paired] + [u[0] for u in unpaired], key=lambda r: r[0][0])
    anchor = {p[0][0][0]: (aidx[p[2][0][0]], p[3]) for p in paired}
    sig = lambda recs: (tuple(r[2] for r in recs), tuple(r[4] & 0xffff for r in recs)); dsig = lambda i: tuple(r[2] for r in AA[i][0])
    m = {}; i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and sig(ps[j + 1]) == sig(ps[i]): j += 1
        run = ps[i:j + 1]; anc = [anchor[r[0][0]] for r in run if r[0][0] in anchor]
        if len(run) > 1 and anc:
            a0, bk = anc[0]; lo = hi = a0
            while lo > 0 and dsig(lo - 1) == dsig(a0): lo -= 1
            while hi + 1 < len(AA) and dsig(hi + 1) == dsig(a0): hi += 1
            if hi - lo + 1 == len(run):
                for k, r in enumerate(run): m[r[0][0]] = (lo + k, bk)
        for r in run:
            if r[0][0] not in m and r[0][0] in anchor: m[r[0][0]] = anchor[r[0][0]]
        i = j + 1
    i = 0
    while i < len(ps):
        if ps[i][0][0] in m: i += 1; continue
        j = i
        while j + 1 < len(ps) and ps[j + 1][0][0] not in m: j += 1
        if i > 0 and j + 1 < len(ps):
            a, b = m[ps[i - 1][0][0]][0], m[ps[j + 1][0][0]][0]
            if b - a - 1 == j - i + 1 and all(dsig(a + 1 + k) == tuple(r[2] for r in ps[i + k]) for k in range(j - i + 1)):
                for k in range(j - i + 1): m[ps[i + k][0][0]] = (a + 1 + k, m[ps[j + 1][0][0]][1])
        i = j + 1
    assert len({v[0] for v in m.values()}) == len(m), "two PS1 animations matched with one arcade animation"
    units = []; left_un = []
    for recs in ps:
        if recs[0][0] not in m: left_un.append(recs); continue
        ai, bk = m[recs[0][0]]; A_ = AA[ai][0]; aset = {ah(x[4], bk) for x in A_}
        pixel = any(ph(r[4] & 0xffff) == ah(x[4], bk) for r, x in zip(recs, A_)) and all(ph(r[4] & 0xffff) in aset for r in recs)
        units.append((recs, A_, bk, AA[ai][1], "pixel" if pixel else "sequence"))
    for u in units: assert u[0][0][0] in fam_of, "animation +%05x is in no family" % u[0][0][0]
    used = [stock3[frec(r[4])[0] + 3] for u in units for r in u[0]] + [stock3[frec(r[4])[0] + 3] for recs in left_un for r in recs]
    nextslot = max(max([b for b in used if b != 0xff] + [-1]) + 1, STOCK_SLOTS); stock_slots = nextslot
    tilemap = {}; stats = collections.Counter(); maxraw = 0; maxrect = [0, 0]; why = {}
    sprite = {}                                 # (arcade sprite, bank, shared?) -> (sec0 offset, layout offset) or None
    for recs, A_, bk, la, how in units:         # plain sprites the port kept: reuse the stock parts and layout
        byimg = {}
        for r in recs:
            if kind(r[4]) == "plain": byimg.setdefault(ph(r[4] & 0xffff), (r[4] & 0xffff, frec(r[4])[0]))
        for x in A_:
            if ah(x[4], bk) in byimg: sprite.setdefault((x[4], bk, False), byimg[ah(x[4], bk)])

    def newsprite(s, bk, sh):
        nonlocal maxraw, nextslot
        if (s, bk, sh) in sprite: return sprite[(s, bk, sh)]
        ap = ctx.arc_parts(s); raw = sum((nx + 1) * (ny + 1) * 128 for c, nx, ny, lo, x, y in ap)
        tk = lambda c, nx, ny: ((c,), "bank%x" % bk, nx, ny)
        keys = list(dict.fromkeys(tk(c, nx, ny) for c, nx, ny, lo, x, y in ap))
        pk = aplib.pack([(k[2] + 1, k[3] + 1) for k in keys]) if len(ap) <= aplib.MAXPARTS and raw <= aplib.MAXRAW else None
        res = None
        if pk is None: why[(s, bk)] = "over limits: %d parts, %d bytes decoded" % (len(ap), raw)
        elif len(s1) // 4 + sum(1 for k in keys if k not in tilemap) > 4096: why[(s, bk)] = "file limit: 4096 tiles"
        elif len(s0) + 7 * len(ap) > 0xfff0: why[(s, bk)] = "file limit: part section full (64 KB)"
        elif len(s3) + 4 + len(ap) + 6 > 0xfff0: why[(s, bk)] = "file limit: frame-record section full (64 KB)"
        elif sh and nextslot > 254: why[(s, bk)] = "no shared slot index left"
        else:
            W, H, pos = pk; place = dict(zip(keys, pos)); maxraw = max(maxraw, raw)
            if W * H > maxrect[0] * maxrect[1]: maxrect[:] = [W, H]
            if (s, bk, not sh) in sprite and sprite[(s, bk, not sh)] is not None and sprite[(s, bk, not sh)][0] >= len(n.sec[0]): lo_ = sprite[(s, bk, not sh)][0]      # parts already appended for the other kind
            else:
                lo_ = len(s0)
                for i, (c, nx, ny, lo, x, y) in enumerate(ap):
                    k = tk(c, nx, ny)
                    if k not in tilemap:
                        tilemap[k] = len(s1) // 4; stats["newtiles"] += 1
                        s1.extend(struct.pack("<I", len(s2) | (nx << 24) | (ny << 28))); s2.extend(aplib.rle_encode(aplib.ps1_bytes(ctx.block(c, nx, ny, bk))))
                    s0.extend(aplib.enc_part((lo & 0x7f) | (0x80 if i == len(ap) - 1 else 0), tilemap[k], x, y))
                stats["new"] += 1
            A = len(s3); slot = 0xff
            if sh: slot = nextslot; nextslot += 1; stats["new_shared"] += 1
            s3.extend(struct.pack("<HBB", 0, (H - 1) << 4 | (W - 1), slot) + bytes(place[tk(c, nx, ny)][1] << 4 | place[tk(c, nx, ny)][0] for c, nx, ny, lo, x, y in ap))
            res = (lo_, A)
        sprite[(s, bk, sh)] = res
        return res
    frecs = {}; patches = []; report = []; made = {}
    for recs, A_, bk, la, how in units:
        fam = fam_of[recs[0][0]]; N = len(recs)
        row = dict(offset=recs[0][0], ram=EXE_BASE + recs[0][0], family=fam, arcade=A_[0][0], pairing=how, records=N, sprites_stock=len({r[4] & 0xffff for r in recs}), sprites_arcade=len({x[4] for x in A_}),
                   kinds="".join(kind(r[4])[0].upper() for r in recs))
        ncut = sum(ph(r[4] & 0xffff) != ah(x[4], bk) for r, x in zip(recs, A_))
        if fam in keep:
            report.append(dict(row, restored=0, left={"kept stock: measured speed (KEEP)": ncut})); continue
        if how == "sequence" and fam not in variants:
            report.append(dict(row, restored=0, left={"sequence-paired variant, family not in VARIANTS": ncut})); continue
        loop_i = next((i for i, x in enumerate(A_) if x[0] == la), None)
        mode = []                                # per record: None (leave), "plain", "shared"
        for r, x in zip(recs, A_):
            k = kind(r[4]); cut = ph(r[4] & 0xffff) != ah(x[4], bk)
            if k == "plain": mode.append("plain")
            elif k == "modifier": mode.append("plain" if (how == "sequence" or fam in modifier and cut) else None)
            elif k == "shared": mode.append("shared" if fam in shared and (cut or how == "sequence" and frec(r[4])[1]) else None)
            else: mode.append(None)
        done = 0; left = collections.Counter()
        for i, (r, x) in enumerate(zip(recs, A_)):
            k = kind(r[4]); cut = ph(r[4] & 0xffff) != ah(x[4], bk)
            if mode[i] is None:
                if cut or how == "sequence" and frec(r[4])[1]: left["stock frame uses a %s" % ("shared VRAM slot" if k == "shared" else k)] += 1
                continue
            sp = newsprite(x[4], bk, mode[i] == "shared")
            if sp is None:
                if cut: left[why[(x[4], bk)]] += 1
                continue
            lo_, A = sp
            if mode[i] == "shared": C = 0xffff
            else:
                j = i; C = lo_                               # prefetch hint: the next different sprite of the script (as stock)
                for _ in range(N):
                    j = j + 1 if j + 1 < N else loop_i
                    if j is None: break
                    if A_[j][4] != x[4]:
                        nx_ = newsprite(A_[j][4], bk, False) if mode[j] == "plain" else None
                        C = nx_[0] if nx_ is not None else (recs[j][4] & 0xffff)
                        break
            old = frec(r[4])
            if lo_ == (r[4] & 0xffff) and old == (A, 0, C): continue      # stock record already says exactly this
            if (lo_, A, C) not in frecs:
                if len(s3) + 6 > 0xfff0:
                    if cut: left["file limit: frame-record section full (64 KB)"] += 1
                    continue
                frecs[(lo_, A, C)] = len(s3); s3.extend(struct.pack("<HHH", A, 0, C))
            fid = frecs[(lo_, A, C)] << 16 | lo_
            patches.append((r[0] + 4, r[4], fid)); made[fid] = (x[4], bk)
            if cut or frec(r[4])[1]: done += 1
        report.append(dict(row, restored=done, left=dict(left)))
    for recs in left_un:
        report.append(dict(offset=recs[0][0], ram=EXE_BASE + recs[0][0], family=fam_of.get(recs[0][0]), arcade=None, pairing=None, records=len(recs), kinds="".join(kind(r[4])[0].upper() for r in recs), sprites_stock=len({r[4] & 0xffff for r in recs}), sprites_arcade=None, restored=0,
                           left={"no arcade animation matched": len(recs)}))
    for k in (0, 2, 3): [s0, s1, s2, s3][k].extend(bytes(-len([s0, s1, s2, s3][k]) % 4))
    s = [s0, s1, s2, s3]
    hdr = struct.pack("<4I", 16, 16 + len(s0), 16 + len(s0) + len(s1), 16 + len(s0) + len(s1) + len(s2))
    nsp = hdr + b"".join(bytes(x) for x in s)
    p = sorted(set(patches)); assert len({a for a, o, f in p}) == len(p)
    ae8 = struct.pack("<4sBBHII16s", b"AE8\x01", SET, 1 if nextslot > stock_slots else 0, nextslot if nextslot > stock_slots else 0, len(P), len(p), hashlib.sha1(P).digest()[:16]) + b"".join(struct.pack("<III", EXE_BASE + o, old, new) for o, old, new in p)
    return dict(nsp=nsp, ae8=ae8, made=made, report=sorted(report, key=lambda d: d["offset"]), sec=[len(x) for x in s], stock=n.sizes, tiles=len(s1) // 4, patches=p,
                exe_sha1=hashlib.sha1(P).hexdigest(), expect={r[0]: (x[4], bk) for recs, A_, bk, la, how in units for r, x in zip(recs, A_)}, stats=dict(stats), maxraw=maxraw, maxrect=maxrect, slots=nextslot, stock_slots=stock_slots, keep=list(keep), shared=list(shared), modifier=list(modifier), variants=list(variants))


def check(ctx, r, tmpdir):
    """every patched frame id of the result against the arcade definition, pixel for pixel, and its records -> (frames, bad)"""
    tmp = os.path.join(tmpdir, "_echeck.nsp"); open(tmp, "wb").write(r["nsp"]); n = NSP(tmp); n.decode_all(); s3 = n.sec[3]; bad = 0; slots = set()
    for fid, (s, bk) in r["made"].items():
        hi = fid >> 16; lo = fid & 0xffff; ok = hi + 6 <= len(s3)
        if ok:
            A, B, C = struct.unpack_from("<HHH", s3, hi); g = group_parts(n.sec[0], lo)
            ok = B == 0 and s3[A:A + 2] != b"\xff\xff" and A + 4 + len(g) <= len(s3) and (s3[A + 3] == 0xff or r["stock_slots"] <= s3[A + 3] < 255)
            if ok:
                if s3[A + 3] != 0xff: slots.add(s3[A + 3])
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
    return len(r["made"]), bad, len(slots)


def main(argv=None):
    import argparse, pickle, shutil
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arcade", nargs="+"); ap.add_argument("--disc"); ap.add_argument("--out", required=True)
    ap.add_argument("--ctx"); ap.add_argument("--ps1"); ap.add_argument("--anims"); ap.add_argument("--exe")
    ap.add_argument("--shared"); ap.add_argument("--modifier"); ap.add_argument("--variants"); ap.add_argument("--keep"); ap.add_argument("--only", help="keep every family but these (measurement builds)")
    a = ap.parse_args(argv)

    def fams(v, dflt):
        if v is None: return dflt
        L = [] if v in ("", "none") else (list(FAMILIES) if v == "all" else v.split(","))
        for f in L:
            if f not in FAMILIES: raise SystemExit("unknown family %s (known: %s)" % (f, ", ".join(FAMILIES)))
        return L
    if os.path.exists(os.path.join(a.out, "manifest.json")) and not os.path.exists(os.path.join(a.out, "EFF1.AE8")):
        print("ERROR: --out holds another content set; give a new directory"); return 2
    os.makedirs(a.out, exist_ok=True); work = os.path.join(a.out, "_work"); os.makedirs(work, exist_ok=True)
    if a.ctx:
        prg, T, chtab = pickle.load(open(a.ctx, "rb")); ps1 = a.ps1; ctx = aplib.Ctx(prg, T, ps1, chtab); exe = a.exe
        if a.anims: ctx._dir_anims = pickle.load(open(a.anims, "rb"))
    else:
        import build8
        try:
            setname, prg, roms = build8.read_arcade(a.arcade); d = build8.Disc(a.disc); idx = {nm: (lba, sz) for nm, lba, sz in d.walk()}
            ps1 = os.path.join(work, "ps1"); os.makedirs(os.path.join(ps1, "A", "A2"), exist_ok=True)
            open(os.path.join(ps1, "A", "A2", "SP_EFF1.NSP"), "wb").write(d.read(*idx["A/A2/SP_EFF1.NSP"]))
            exe = os.path.join(work, build8.PS1_EXE); open(exe, "wb").write(d.read(*idx[build8.PS1_EXE]))
        except (build8.Fail, KeyError) as ex: print("ERROR:", ex); return 2
        ctx = aplib.Ctx(prg, aplib.gfx_decode(lambda nm: roms[nm]), ps1, aplib.find_chtab(prg))
    if a.only: a.keep = ",".join(f for f in FAMILIES if f not in a.only.split(","))
    r = build(ctx, ps1, exe, fams(a.keep, None), fams(a.shared, None), fams(a.modifier, None), fams(a.variants, None)); tot, bad, nslots = check(ctx, r, work)
    stock = open(os.path.join(ps1, "A", "A2", "SP_EFF1.NSP"), "rb").read(); o = struct.unpack_from("<4I", stock, 0) + (len(stock),); o2 = struct.unpack_from("<4I", r["nsp"], 0)
    prefix = all(r["nsp"][o2[k]:o2[k] + (o[k + 1] - o[k]) - 4] == stock[o[k]:o[k + 1] - 4] for k in range(4))
    if bad or not prefix or r["tiles"] > 4096 or r["sec"][0] >= 0x10000 or r["sec"][3] >= 0x10000 or struct.unpack_from("<I", r["nsp"], o2[2])[0] == struct.unpack_from("<I", b"NSPC", 0)[0]:
        print("ERROR: self-check failed (%d bad frames, stock prefix %s)" % (bad, prefix)); return 2
    open(os.path.join(a.out, "SP_EFF1.NSP"), "wb").write(r["nsp"]); open(os.path.join(a.out, "EFF1.AE8"), "wb").write(r["ae8"])
    man = dict(format="AE8 1", set=SET, nsp="SP_EFF1.NSP", nsp_size=len(r["nsp"]), nsp_sha1=hashlib.sha1(r["nsp"]).hexdigest(), sections=r["sec"], sections_stock=r["stock"], tiles=r["tiles"],
               ae8="EFF1.AE8", ae8_size=len(r["ae8"]), ae8_sha1=hashlib.sha1(r["ae8"]).hexdigest(), patches=len(r["patches"]), exe_sha1=r["exe_sha1"], exe_size=struct.unpack_from("<I", r["ae8"], 8)[0],
               sprites_new=r["stats"].get("new", 0), shared_frames_new=r["stats"].get("new_shared", 0), max_rect=r["maxrect"], max_frame_bytes=r["maxraw"], checked=tot,
               slot_table=r["slots"] > r["stock_slots"], slot_indices=r["slots"], slot_indices_stock=r["stock_slots"],
               families_kept_stock=r["keep"], families_shared=r["shared"], families_modifier=r["modifier"], families_variants=r["variants"], families={k: ["%05x" % o for o in v] for k, v in FAMILIES.items()}, animations=r["report"])
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1, sort_keys=True)
    shutil.rmtree(work, ignore_errors=True)
    print("SP_EFF1 sections", r["sec"], "stock", r["stock"], "tiles", r["tiles"], "file", len(r["nsp"]), "| new sprites", r["stats"].get("new", 0), "| new shared frames", r["stats"].get("new_shared", 0),
          "slot indices", r["slots"], "(stock %d)" % r["stock_slots"], "| EFF1.AE8", len(r["patches"]), "patches | checked", tot)
    for x in r["report"]:
        print(" +%05x %-13s records %2d arcade %s%s sprites %s -> %s | restored %2d, left %s" % (x["offset"], x["family"], x["records"], "%06x" % x["arcade"] if x["arcade"] else "  -   ",
              " (%s, %s)" % (x["pairing"], x["kinds"]) if x.get("pairing") else "", x["sprites_stock"], x["sprites_arcade"], x["restored"], x["left"] or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
