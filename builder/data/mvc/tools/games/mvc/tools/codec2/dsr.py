"""DSR1: DSA1 + run mode (CPU worker, 2026-11-19, research; tools/codec2).  Same range coder, node format and tile
framing as DSA1 (common/dsp/dsa.py); pixel coding per row, raster order, neighbours outside the tile = 15:

  not in a run:  leaf = walk(tree, from jump[L << 4 | U])        (prefix tests on L / U only are pre-walked)
                 e = bit(p_leaf[0])            e = 1: pixel = U, start a run (pos = 0)
                 else literal(leaf)
  in a run:      c = (U == UL) | (UR == U) << 1 | (U == 15) << 2 | pos << 3 | (URR == UR) << 5 | (UU == U) << 6 | (UUR == UR) << 7
                 bit(cont[c]) = 1: pixel = U, pos = min(pos + 1, 3)
                 else: run ends, pixel != U: leaf = walk(...), literal(leaf)
  literal:       if L != U: bit(lprob[leaf]) = 1 -> pixel = L
                 else / on 0: 4 nibble bits MSB first with p_leaf[1..15] (as DSA1)
  A run never crosses a row end.  bit(p): p = P(bit 0) * 256.

Pixel section (layout v3): +0 'DSR1' +4 u32 size of the DSR1 part  +8 u16 4 * nodes  +10 u16 leaves  +12 u16 entries  +14 0
+16 u8 cont[256]  +272 u16 entry[64] (node index)  +400 u8 jump[256] (entry index)  +656 u32 node[n] (DSA1 MIPS node words)  leaf records [leaves] x 17 B (p[0..15] as DSA1, then lprob),
padded to 4; tiles (u8 width in bytes, range-coder bytes).  Decoder base register = &node[0]: cont at -640, entry at -384, jump at -256.

    python dsr.py encode ids..   -> games/mvc/work/codec2/dsr/<label>.DSP + stats.json (verified tile by tile)
"""
import os, sys, struct, json, time
import numpy as np, numba as nb
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"C:\playground\xvsf"
sys.path.insert(0, os.path.join(ROOT, "common", "dsp")); sys.path.insert(0, HERE)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(ROOT, "work", "nbcache"))
import dsp as D, dsa as A, dsm as M
MAGIC = 0x31525344                       # 'DSR1'
OUT = os.path.join(ROOT, "games", "mvc", "work", "codec2", os.environ.get("DSR_OUT", "dsr"))


def qp(n0, n1):
    n = n0 + n1
    return int(min(max(round(n0 / n * 256), 1), 255)) if n else 128


def feats(t):
    if t < 40: return {t // 5}
    i, j = A.PAIRS[t - 40]; return {i, j}


def test(t, f):
    if t < 40:
        n, k = divmod(t, 5)
        return ((f[n] >> k) & 1) if k < 4 else int(f[n] == 15)
    i, j = A.PAIRS[t - 40]; return int(f[i] == f[j])


def jump_table(nodes, weight=None, maxent=64):
    """per (L << 4 | U): the first node whose test needs more than L / U (prefix pre-walked).  At most maxent distinct
    targets (layout v3: u8 jump -> u16 entry[64]); the lightest targets fall back to their parent on the path (an
    ancestor: still exact, one more node to walk)."""
    paths = []
    for v in range(256):
        f = [v >> 4, v & 15] + [None] * 6
        i = 0; path = [0]
        while not nodes[i][0] and feats(nodes[i][1]) <= {0, 1}:
            i = nodes[i][2] if test(nodes[i][1], f) else i + 1
            path.append(i)
        paths.append(path)
    w = weight if weight is not None else np.ones(256)
    while len(set(p[-1] for p in paths)) > maxent:
        tw = {}
        for v, p in enumerate(paths): tw[p[-1]] = tw.get(p[-1], 0) + w[v]
        worst = min((t for t in tw if t != 0), key=lambda t: tw[t])
        for p in paths:
            if p[-1] == worst and len(p) > 1: p.pop()
    return [p[-1] for p in paths]


def split(pxs, F, sym):
    """per pixel: x position, walked-full / symbol-only / in-run flags (decoder order)"""
    N = len(sym); xpos = np.zeros(N, np.int64); k = 0
    for p in pxs:
        H, W = p.shape; xpos[k:k + H * W] = np.tile(np.arange(W), H); k += H * W
    eq = sym == F[:, 1]
    prev = np.zeros(N, bool); prev[1:] = eq[:-1]; prev &= xpos > 0
    return xpos, eq, ~prev, prev & ~eq, prev


def cont_ctx(F, inrun, xpos, UUR):
    U, UL, UR, URR, UU = F[:, 1], F[:, 2], F[:, 3], F[:, 7], F[:, 5]
    N = len(U); pos = np.zeros(N, np.int64)
    for i in np.nonzero(inrun)[0]: pos[i] = min(pos[i - 1] + 1, 3) if inrun[i - 1] else 0
    return (U == UL) * 1 + (UR == U) * 2 + (U != 15) * 4 + pos * 8 + (URR == UR) * 32 + (UU == U) * 64 + (UUR == UR) * 128


def uur(pxs):
    """pixel (x+1, y-2) per pixel (15 outside the tile)"""
    out = []
    for p in pxs:
        H, W = p.shape; q = np.full((H, W), 15, np.int64)
        if H > 2 and W > 1: q[2:, :-1] = p[:-2, 1:]
        out.append(q.ravel())
    return np.concatenate(out)


def model(pxs):
    n = sum(p.size for p in pxs)
    F = np.zeros((n, A.NB), np.int64); sym = np.zeros(n, np.int64); k = 0
    for p in pxs: k = A.gather(p.astype(np.int64), p.shape[0], p.shape[1], F, sym, k)
    T = A.tests(F)
    xpos, eq, full, symonly, inrun = split(pxs, F, sym)
    walked = full | symonly
    nodes, _ = A.build_tree(T[walked], sym[walked], eq[walked], node_cost=int(os.environ.get('DSR_NODECOST', '32')),
                            maxdepth=int(os.environ.get('DSR_MAXDEPTH', '28')))
    nodes_arr = np.array([(0x8000 | a) if kind else (a | (r << 16)) for kind, a, r in nodes], np.int64)
    pairs = np.array(A.PAIRS, np.int64)
    lv = np.zeros(n, np.int64); A.tile_leaves(nodes_arr, F, pairs, lv)
    nl = sum(1 for nd in nodes if nd[0])
    L, U = F[:, 0], F[:, 1]
    pe = [qp(a, b) for a, b in zip(np.bincount(lv[full & ~eq], minlength=nl), np.bincount(lv[full & eq], minlength=nl))]
    lit = walked & ~eq; ask = lit & (L != U); hit = ask & (sym == L)
    lp = [qp(a, b) for a, b in zip(np.bincount(lv[ask & ~hit], minlength=nl), np.bincount(lv[hit], minlength=nl))]
    l4 = lit & ~hit
    probs = np.full((nl, 16), 128, np.int64); probs[:, 0] = pe
    n0 = np.zeros(nl * 16, np.int64); n1 = np.zeros(nl * 16, np.int64)
    for lev in range(4):
        node = (1 << lev) + (sym >> (4 - lev)) if lev else np.ones(n, np.int64)
        b = (sym >> (3 - lev)) & 1; key = lv * 16 + node
        n0 += np.bincount(key[l4 & (b == 0)], minlength=nl * 16); n1 += np.bincount(key[l4 & (b == 1)], minlength=nl * 16)
    for q in range(nl * 16):
        if q % 16: probs[q // 16, q % 16] = qp(n0[q], n1[q])
    cc = cont_ctx(F, inrun, xpos, uur(pxs))
    cont = [qp(a, b) for a, b in zip(np.bincount(cc[inrun & ~eq], minlength=256), np.bincount(cc[inrun & eq], minlength=256))]
    wt = np.bincount((F[walked, 0] * 16 + F[walked, 1]), minlength=256)
    return nodes, nodes_arr, jump_table(nodes, wt), cont, lp, probs


@nb.njit
def tile_decisions(px, nodes, pairs, jump, cont, lp, probs, outp, outb):
    """the (probability, bit) sequence of one tile in decoder order -> count"""
    Hh, W = px.shape; k = 0; f = np.zeros(8, np.int64)
    for y in range(Hh):
        inrun = False; pos = 0
        for x in range(W):
            f[0] = px[y, x - 1] if x > 0 else 15
            f[1] = px[y - 1, x] if y > 0 else 15
            f[2] = px[y - 1, x - 1] if (y > 0 and x > 0) else 15
            f[3] = px[y - 1, x + 1] if (y > 0 and x + 1 < W) else 15
            f[4] = px[y, x - 2] if x > 1 else 15
            f[5] = px[y - 2, x] if y > 1 else 15
            f[6] = px[y - 1, x - 2] if (y > 0 and x > 1) else 15
            f[7] = px[y - 1, x + 2] if (y > 0 and x + 2 < W) else 15
            s = px[y, x]
            if inrun:
                c = (1 if f[1] == f[2] else 0) | (2 if f[3] == f[1] else 0) | (4 if f[1] != 15 else 0) | (pos << 3) | (32 if f[7] == f[3] else 0) | (64 if f[5] == f[1] else 0) | (128 if (px[y - 2, x + 1] if (y > 1 and x + 1 < W) else 15) == f[3] else 0)
                if s == f[1]:
                    outp[k] = cont[c]; outb[k] = 1; k += 1
                    pos = min(pos + 1, 3); continue
                outp[k] = cont[c]; outb[k] = 0; k += 1
                inrun = False; known = True
            else:
                known = False
            i = jump[f[0] * 16 + f[1]]
            while True:
                nd = nodes[i]
                if nd & 0x8000: break
                t = nd & 0xFF
                if t < 40:
                    n = t // 5; kk = t % 5
                    r = ((f[n] >> kk) & 1) if kk < 4 else (1 if f[n] == 15 else 0)
                else:
                    r = 1 if f[pairs[t - 40, 0]] == f[pairs[t - 40, 1]] else 0
                i = (nd >> 16) if r else i + 1
            lf = nd & 0x7FFF
            if not known:
                outp[k] = probs[lf, 0]
                if s == f[1]:
                    outb[k] = 1; k += 1; inrun = True; pos = 0; continue
                outb[k] = 0; k += 1
            if f[0] != f[1]:
                outp[k] = lp[lf]
                if s == f[0]:
                    outb[k] = 1; k += 1; continue
                outb[k] = 0; k += 1
            idx = 1
            for sh in (3, 2, 1, 0):
                b = (s >> sh) & 1; outp[k] = probs[lf, idx]; outb[k] = b; k += 1; idx = idx * 2 + b
    return k


@nb.njit
def rc_encode(ps, bs, n, out):
    """LZMA-style range coder (= dsa.RC: bit + finish) over n decisions -> bytes written (incl. the leading 0)"""
    low = np.int64(0); rng = np.int64(0xFFFFFFFF); cache = np.int64(0); csize = np.int64(1); o = 0
    for i in range(n + 5):
        if i < n:
            bound = (rng >> 8) * ps[i]
            if bs[i] == 0: rng = bound
            else: low += bound; rng -= bound
            nsh = 0
            while rng < (1 << 24):
                rng = (rng << 8) & 0xFFFFFFFF; nsh += 1
        else:
            nsh = 1
        for _ in range(nsh):
            if low < 0xFF000000 or low >= (1 << 32):
                carry = low >> 32; temp = cache
                while True:
                    out[o] = (temp + carry) & 0xFF; o += 1; temp = 0xFF
                    csize -= 1
                    if csize == 0: break
                cache = (low >> 24) & 0xFF
            csize += 1
            low = (low & 0x00FFFFFF) << 8
    return o


@nb.njit
def ref_decode(mem, src, n, nodes, pairs, jump, cont, lp, probs, out):
    """exact model of the planned MIPS decoder -> bytes consumed"""
    wb = np.int64(mem[src]); W = wb * 2; H = (2 * n) // W
    p = src + 1; code = np.int64(0)
    for i in range(4): code = (code << 8) | np.int64(mem[p]); p += 1
    rng = np.int64(0xFFFFFFFF)
    px = np.full((H, W), 15, np.int64); f = np.zeros(8, np.int64)
    for y in range(H):
        inrun = False; pos = 0
        for x in range(W):
            f[0] = px[y, x - 1] if x > 0 else 15
            f[1] = px[y - 1, x] if y > 0 else 15
            f[2] = px[y - 1, x - 1] if (y > 0 and x > 0) else 15
            f[3] = px[y - 1, x + 1] if (y > 0 and x + 1 < W) else 15
            f[4] = px[y, x - 2] if x > 1 else 15
            f[5] = px[y - 2, x] if y > 1 else 15
            f[6] = px[y - 1, x - 2] if (y > 0 and x > 1) else 15
            f[7] = px[y - 1, x + 2] if (y > 0 and x + 2 < W) else 15
            known = False
            if inrun:
                c = (1 if f[1] == f[2] else 0) | (2 if f[3] == f[1] else 0) | (4 if f[1] != 15 else 0) | (pos << 3) | (32 if f[7] == f[3] else 0) | (64 if f[5] == f[1] else 0) | (128 if (px[y - 2, x + 1] if (y > 1 and x + 1 < W) else 15) == f[3] else 0)
                bound = (rng >> 8) * cont[c]
                if code < bound: b = 0; rng = bound
                else: b = 1; code -= bound; rng -= bound
                while rng < (1 << 24):
                    rng = (rng << 8) & 0xFFFFFFFF; code = ((code << 8) | np.int64(mem[p])) & 0xFFFFFFFF; p += 1
                if b == 1:
                    px[y, x] = f[1]; pos = min(pos + 1, 3); continue
                inrun = False; known = True
            i = jump[f[0] * 16 + f[1]]
            while True:
                nd = nodes[i]
                if nd & 0x8000: break
                t = nd & 0xFF
                if t < 40:
                    nn = t // 5; kk = t % 5
                    r = ((f[nn] >> kk) & 1) if kk < 4 else (1 if f[nn] == 15 else 0)
                else:
                    r = 1 if f[pairs[t - 40, 0]] == f[pairs[t - 40, 1]] else 0
                i = (nd >> 16) if r else i + 1
            lf = nd & 0x7FFF
            if not known:
                bound = (rng >> 8) * probs[lf, 0]
                if code < bound: b = 0; rng = bound
                else: b = 1; code -= bound; rng -= bound
                while rng < (1 << 24):
                    rng = (rng << 8) & 0xFFFFFFFF; code = ((code << 8) | np.int64(mem[p])) & 0xFFFFFFFF; p += 1
                if b == 1:
                    px[y, x] = f[1]; inrun = True; pos = 0; continue
            if f[0] != f[1]:
                bound = (rng >> 8) * lp[lf]
                if code < bound: b = 0; rng = bound
                else: b = 1; code -= bound; rng -= bound
                while rng < (1 << 24):
                    rng = (rng << 8) & 0xFFFFFFFF; code = ((code << 8) | np.int64(mem[p])) & 0xFFFFFFFF; p += 1
                if b == 1:
                    px[y, x] = f[0]; continue
            idx = 1
            while idx < 16:
                bound = (rng >> 8) * probs[lf, idx]
                if code < bound: b = 0; rng = bound
                else: b = 1; code -= bound; rng -= bound
                while rng < (1 << 24):
                    rng = (rng << 8) & 0xFFFFFFFF; code = ((code << 8) | np.int64(mem[p])) & 0xFFFFFFFF; p += 1
                idx = idx * 2 + b
            px[y, x] = idx - 16
    for k in range(n):
        out[k] = px[(2 * k) // W, (2 * k) % W] | (px[(2 * k) // W, (2 * k) % W + 1] << 4)
    return p - src


def mips_node(kind, a, r):
    if kind:
        assert 17 * a < 0x8000
        return 0x8000 | 17 * a                   # leaf word = 0x8000 | record offset (17 B records)
    if a < 40:
        n_, k_ = divmod(a, 5)
        return (4 * n_ + k_) | (r << 16) if k_ < 4 else (4 * n_) | (1 << 10) | (r << 16)
    i_, j_ = A.PAIRS[a - 40]
    return (4 * i_) | ((4 * j_) << 5) | (2 << 10) | (r << 16)


def encode(x, prep=None):
    t0 = time.time()
    x.decode_all()
    if prep: prep(x)                             # e.g. encode_cutfix: unreferenced tiles zeroed
    uniq = {}; order = []
    for t in x.tiles:
        k = (t.wb, t.raw)
        if k not in uniq: uniq[k] = len(order); order.append(t)
    pxs = [D.tile_pixels(t).astype(np.int64) for t in order]
    nodes, nodes_arr, jump, cont, lp, probs = model(pxs)
    pairs = np.array(A.PAIRS, np.int64)
    nl = probs.shape[0]
    rec = b"".join(bytes(int(v) for v in probs[l]) + bytes([lp[l]]) for l in range(nl))
    ents = sorted(set(jump)); assert len(ents) <= 64
    head = struct.pack("<IIHHHH", MAGIC, 0, 4 * len(nodes), nl, len(ents), 0) + bytes(cont)         + struct.pack("<64H", *([4 * e_ for e_ in ents] + [0] * (64 - len(ents)))) + bytes(2 * ents.index(j) for j in jump)
    assert len(head) == 656
    head += struct.pack("<%dI" % len(nodes), *[mips_node(*nd) for nd in nodes]) + rec
    head += bytes(1) * (-len(head) % 4)
    sec0 = bytearray(head); uoff = []
    ja, ca, la = np.array(jump, np.int64), np.array(cont, np.int64), np.array(lp, np.int64)
    bp = np.zeros(1 << 18, np.int64); bb = np.zeros(1 << 18, np.int64); ob = np.zeros(1 << 17, np.int64)
    for t, p in zip(order, pxs):
        nd = tile_decisions(p, nodes_arr, pairs, ja, ca, la, probs, bp, bb)
        nbyte = rc_encode(bp, bb, nd, ob)
        st = bytes(int(v) for v in ob[:nbyte]); assert st[0] == 0
        uoff.append(len(sec0)); sec0.append(t.wb); sec0 += st[1:]
    sec0 += b"\0" * (8 + (-len(sec0) % 4))
    struct.pack_into("<I", sec0, 4, len(sec0))
    new = M.assemble(x, bytes(sec0), {t.idx: uoff[uniq[(t.wb, t.raw)]] for t in x.tiles})
    # verify every tile with the reference decoder
    mem = np.frombuffer(bytes(sec0) + b"\0" * 16, np.uint8); out = np.zeros(1 << 16, np.uint8); bad = 0
    for t, off in zip(order, uoff):
        ref_decode(mem, off, t.n, nodes_arr, pairs, ja, ca, la, probs, out); bad += out[:t.n].tobytes() != t.raw
    return new, dict(old=len(x.d), new=len(new), old_pix=x.sizes[0], new_pix=len(sec0), model=len(head), nodes=len(nodes),
                     leaves=nl, tiles=len(x.tiles), uniq=len(order), bad=bad, secs=round(time.time() - t0, 1))


if __name__ == "__main__" and sys.argv[1] == "encode":
    os.makedirs(OUT, exist_ok=True)
    sp = os.path.join(OUT, "stats.json"); stats = json.load(open(sp)) if os.path.exists(sp) else {}
    for s in sys.argv[2:]:
        b, base, label = D.char_dsp("mvc", int(s, 16))
        x = D.DSP(b, base)
        new, st = encode(x); st["label"] = label
        open(os.path.join(OUT, label + ".DSP"), "wb").write(new)
        stats[label] = st; json.dump(stats, open(sp, "w"), indent=1)
        print(label, st, flush=True)


def encode_tier(cid, src, outdir, fxroot):
    """option-B tier: src 'fx' = the fx tree's PLxx_10.A0 DSP (-> dsr), 'cutN' = its cutN_stock/PLxx_10.DSP (-> dsr_cutN)"""
    dspw = os.path.join(fxroot, "games", "mvc", "work", "dsp")
    if src == "fx":
        b = open(os.path.join(dspw, "files", "PL%02X_10.A0" % cid), "rb").read()
        x = D.DSP(b, struct.unpack_from("<I", b, 12)[0])
    else:
        x = D.DSP(open(os.path.join(dspw, src + "_stock", "PL%02X_10.DSP" % cid), "rb").read())
    new, st = encode(x)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "PL%02X_10.DSP" % cid), "wb").write(new)
    return st


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "tier":
    # python dsr.py tier SRC OUTDIR FXROOT ids..
    src, outdir, fxroot = sys.argv[2], sys.argv[3], sys.argv[4]
    for s in sys.argv[5:]:
        st = encode_tier(int(s, 16), src, outdir, fxroot); print(src, s, st, flush=True)



def encode_cutfix(cid, n, outdir, fxroot):
    """dsr_cutN with EXACTLY the gated dsa_cutN frame cuts: the fx stock DSP (fxroot files/PLxx_10.A0) with dsa_cutN's sec1
    (same length, dscut rewrites in place) and the tiles no group references zeroed (as dscut does); then encode()."""
    sys.path.insert(0, os.path.join(ROOT, "games", "mvc", "tools", "speed5")); import supercut2 as SC
    dspw = os.path.join(fxroot, "games", "mvc", "work", "dsp")
    b = open(os.path.join(dspw, "files", "PL%02X_10.A0" % cid), "rb").read(); base = struct.unpack_from("<I", b, 12)[0]
    dsp_ = bytearray(b[base:]); y = D.DSP(bytes(dsp_))
    ac = D.DSP(open(os.path.join(dspw, "dsa_cut%d" % n, "PL%02X_10.DSP" % cid), "rb").read())
    o1 = 0x14 + len(y.sec[0]) if False else y.offs[1]
    assert len(ac.sec[1]) == len(y.sec[1]), "sec1 length differs"
    dsp_[o1:o1 + len(y.sec[1])] = ac.sec[1]
    x = D.DSP(bytes(dsp_))
    st, en = SC.layout("%02X" % cid)
    s1 = bytearray(x.sec[1]); ref = set()
    for s_ in st:
        for p_ in SC.parse_at(s1, s_): ref.add(p_.tile)
    def prep(xx):
        for t in xx.tiles:
            if t.idx not in ref: t.raw = bytes(len(t.raw))
    new, st_ = encode(x, prep)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "PL%02X_10.DSP" % cid), "wb").write(new)
    st_["unreferenced_zeroed"] = sum(1 for t in x.tiles if t.idx not in ref)
    return st_


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "cutfix":
    # python dsr.py cutfix N OUTDIR FXROOT ids..
    n, outdir, fxroot = int(sys.argv[2]), sys.argv[3], sys.argv[4]
    for s_ in sys.argv[5:]:
        st_ = encode_cutfix(int(s_, 16), n, outdir, fxroot); print("cut%d" % n, s_, st_, flush=True)
