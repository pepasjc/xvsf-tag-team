"""DSA1: strong sprite tier (built for MvC, works for any kind-6/8 DSP) - per-pixel binary range coding with a
per-file context TREE over 8 causal neighbours.

Pixel coding (raster order, 4bpp, neighbours outside the tile = 15):
  F = (L, U, UL, UR, LL, UU, ULL, URR)                (x-1 / y-1 / ... ; LL = x-2, UU = y-2, ULL = (x-2,y-1), URR = (x+2,y-1))
  leaf = walk(tree, F)                                 inner node: test(F) ? right : left (= next node)
  bit e = decode(leaf.p[0])          e = 1: pixel = U
  else  idx = 1; 4x: idx = 2*idx + decode(leaf.p[idx]);  pixel = idx - 16
Range decoder (LZMA style, 8-bit probabilities p = P(bit 0) * 256, 1..255):
  bound = (range >> 8) * p;  code < bound ? (bit 0, range = bound) : (bit 1, code -= bound, range -= bound)
  while range < 2^24: range <<= 8, code = code << 8 | next byte
Tests: id 0..39: n = id // 5, k = id % 5: k < 4 -> bit k of F[n]; k = 4 -> F[n] == 15;  id 40..67: F[i] == F[j] (pairs
in PAIRS order).

Pixel section (replaces DSP sec0):
  +0 u32 'DSA1'   +4 u32 size of the DSA1 part   +8 u16 node count   +10 u16 leaf count
  +12 u32 node[n]   inner: test | right_index << 16   leaf: 0x8000 | leaf_index
  ...  u8 leafprob[nleaf][16]
  ...  tile streams: u8 width in bytes, then range-coder bytes (the encoder's leading zero byte is dropped)
Tiles in `rle` stay stock RLE behind the DSA1 part (as DSM1).

    python dsa.py encode GAME [ids] [--hot KB]   -> games/GAME/work/dsp/dsa[_hotN]/<label>.DSP + stats.json
    python dsa.py build GAME [addr]               -> games/GAME/work/dsp/dsa/dsadec.bin (common/dsp/dsadec.S; position-
                                                     independent: the same bytes at any address, checked)
MIPS decoder: common/dsp/dsadec.S (hand-written, caller-saved registers only, no stack; dsadec.c = the C reference).
"""
import os, sys, struct, json, time
import numpy as np, numba as nb
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(ROOT, "work", "nbcache"))
import dsp as D
import dsm as M

MAGIC = 0x31415344                       # 'DSA1'
NB = 8
PAIRS = [(i, j) for i in range(NB) for j in range(i + 1, NB)]
NTEST = 40 + len(PAIRS)


@nb.njit
def gather(px, Hh, W, F, sym, k):
    for y in range(Hh):
        for x in range(W):
            F[k, 0] = px[y, x - 1] if x > 0 else 15
            F[k, 1] = px[y - 1, x] if y > 0 else 15
            F[k, 2] = px[y - 1, x - 1] if (y > 0 and x > 0) else 15
            F[k, 3] = px[y - 1, x + 1] if (y > 0 and x + 1 < W) else 15
            F[k, 4] = px[y, x - 2] if x > 1 else 15
            F[k, 5] = px[y - 2, x] if y > 1 else 15
            F[k, 6] = px[y - 1, x - 2] if (y > 0 and x > 1) else 15
            F[k, 7] = px[y - 1, x + 2] if (y > 0 and x + 2 < W) else 15
            sym[k] = px[y, x]; k += 1
    return k


def tests(F):
    cols = []
    for n in range(NB):
        for b in range(4): cols.append((F[:, n] >> b) & 1)
        cols.append(F[:, n] == 15)
    for i, j in PAIRS: cols.append(F[:, i] == F[:, j])
    return np.stack(cols, 1).astype(np.uint8)


def qp(n0, n1):
    n = n0 + n1
    return np.clip(np.round(np.where(n > 0, n0 / np.maximum(n, 1), 0.5) * 256), 1, 255)


def bits_bin(n0, n1):
    p = qp(n0, n1) / 256
    return -(n0 * np.log2(p) + n1 * np.log2(1 - p))


def leaf_bits(h):
    """h[17]: h[0..15] symbol counts of pixels != U, h[16] = count of pixels == U -> (bits, probs[16])"""
    neq = h[:16].sum()
    tot = bits_bin(h[16], neq)            # e = 1 when == U: p[0] = P(e = 0)
    probs = np.zeros(16, np.int64); probs[0] = qp(neq, h[16])
    tot = bits_bin(neq, h[16])
    for idx in range(1, 16):
        lev = idx.bit_length() - 1; sh = 4 - lev            # idx at depth lev covers symbols [(idx - 2^lev) << sh, +2^sh)
        base = (idx - (1 << lev)) << sh; half = 1 << (sh - 1)
        n0 = h[base:base + half].sum(); n1 = h[base + half:base + 2 * half].sum()
        probs[idx] = qp(n0, n1); tot += bits_bin(n0, n1)
    return float(tot), probs


def build_tree(T, sym, eq, node_cost=4 * 8, leaf_cost=16 * 8, maxdepth=28):
    """MDL greedy tree.  -> (nodes [(kind, a)], leaves [probs])  preorder: inner (test, right child index)"""
    col = np.where(eq, 16, sym)
    nodes = []; leaves = []
    def rec(idx, d):
        h = np.bincount(col[idx], minlength=17).astype(np.float64)
        here, probs = leaf_bits(h)
        best = None
        if d < maxdepth and len(idx) > 48:
            oh = np.zeros((len(idx), 17), np.float32); oh[np.arange(len(idx)), col[idx]] = 1
            H1 = T[idx].T.astype(np.float32) @ oh
            for k in range(T.shape[1]):
                h1 = H1[k].astype(np.float64); h0 = h - h1
                if h1.sum() == 0 or h0.sum() == 0: continue
                g = here - leaf_bits(h0)[0] - leaf_bits(h1)[0]
                if best is None or g > best[0]: best = (g, k)
        if best is not None and best[0] > node_cost + leaf_cost:
            me = len(nodes); nodes.append([0, best[1], 0])
            m = T[idx, best[1]] == 1
            rec(idx[~m], d + 1)                   # left = test false = next node
            nodes[me][2] = len(nodes)
            rec(idx[m], d + 1)
        else:
            nodes.append([1, len(leaves), 0]); leaves.append(probs)
    sys.setrecursionlimit(10000)
    rec(np.arange(len(sym)), 0)
    return nodes, leaves


# ------------------------------------------------------------------------------------------ range coder
class RC:
    def __init__(self):
        self.low = 0; self.range = 0xFFFFFFFF; self.cache = 0; self.csize = 1; self.out = bytearray()

    def shift(self):
        if self.low < 0xFF000000 or self.low >= (1 << 32):
            carry = self.low >> 32; temp = self.cache
            while True:
                self.out.append((temp + carry) & 0xFF); temp = 0xFF
                self.csize -= 1
                if self.csize == 0: break
            self.cache = (self.low >> 24) & 0xFF
        self.csize += 1
        self.low = (self.low & 0x00FFFFFF) << 8

    def bit(self, p, b):
        bound = (self.range >> 8) * p
        if b == 0: self.range = bound
        else: self.low += bound; self.range -= bound
        while self.range < (1 << 24):
            self.range = (self.range << 8) & 0xFFFFFFFF; self.shift()

    def finish(self):
        for _ in range(5): self.shift()
        assert self.out[0] == 0
        return bytes(self.out[1:])


@nb.njit
def walk_leaf(nodes, f, pairs):
    i = 0
    while True:
        nd = nodes[i]
        if nd & 0x8000: return nd & 0x7FFF
        t = nd & 0xFF
        if t < 40:
            n = t // 5; k = t % 5
            r = ((f[n] >> k) & 1) if k < 4 else (1 if f[n] == 15 else 0)
        else:
            r = 1 if f[pairs[t - 40, 0]] == f[pairs[t - 40, 1]] else 0
        i = (nd >> 16) if r else i + 1


@nb.njit
def tile_leaves(nodes, F, pairs, out):
    for k in range(len(F)): out[k] = walk_leaf(nodes, F[k], pairs)


def encode_tile(px, nodes_arr, probs, pairs):
    Hh, W = px.shape
    F = np.zeros((Hh * W, NB), np.int64); sym = np.zeros(Hh * W, np.int64)
    gather(px.astype(np.int64), Hh, W, F, sym, 0)
    lv = np.zeros(len(sym), np.int64); tile_leaves(nodes_arr, F, pairs, lv)
    rc = RC()
    for k in range(len(sym)):
        p = probs[lv[k]]; s = sym[k]
        if s == F[k, 1]: rc.bit(int(p[0]), 1); continue
        rc.bit(int(p[0]), 0)
        idx = 1
        for sh in (3, 2, 1, 0):
            b = (s >> sh) & 1; rc.bit(int(p[idx]), b); idx = idx * 2 + b
    return rc.finish()


@nb.njit
def ref_decode(mem, src, n, model, out, pairs):
    """exact model of the MIPS decoder (common/dsp/dsadec.c): returns bytes consumed"""
    nn = np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8)
    nodes = np.zeros(nn, np.int64)
    for i in range(nn):
        a = model + 12 + 4 * i
        w = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8) | (np.int64(mem[a + 2]) << 16) | (np.int64(mem[a + 3]) << 24)
        if w & 0x8000: nodes[i] = w
        else:                                   # back to the encoder's test id
            s1 = w & 31; s2 = (w >> 5) & 31; ty = (w >> 10) & 3
            if ty == 0: t = (s1 // 4) * 5 + s1 % 4
            elif ty == 1: t = (s1 // 4) * 5 + 4
            else:
                t = 0
                for q in range(len(pairs)):
                    if pairs[q, 0] == s1 // 4 and pairs[q, 1] == s2 // 4: t = 40 + q
            nodes[i] = t | (w & 0xFFFF0000)
    lp = model + 12 + 4 * nn
    wb = np.int64(mem[src]); W = wb * 2; H = (2 * n) // W
    p = src + 1
    code = 0
    for i in range(4): code = (code << 8) | np.int64(mem[p]); p += 1
    rng = 0xFFFFFFFF
    px = np.full((H, W), 15, np.int64)
    f = np.zeros(8, np.int64)
    for y in range(H):
        for x in range(W):
            f[0] = px[y, x - 1] if x > 0 else 15
            f[1] = px[y - 1, x] if y > 0 else 15
            f[2] = px[y - 1, x - 1] if (y > 0 and x > 0) else 15
            f[3] = px[y - 1, x + 1] if (y > 0 and x + 1 < W) else 15
            f[4] = px[y, x - 2] if x > 1 else 15
            f[5] = px[y - 2, x] if y > 1 else 15
            f[6] = px[y - 1, x - 2] if (y > 0 and x > 1) else 15
            f[7] = px[y - 1, x + 2] if (y > 0 and x + 2 < W) else 15
            lf = walk_leaf(nodes, f, pairs)
            pb = lp + 16 * lf
            idx = 0; v = 0; first = True
            while True:
                pr = np.int64(mem[pb + idx])
                bound = (rng >> 8) * pr
                if code < bound: b = 0; rng = bound
                else: b = 1; code -= bound; rng -= bound
                while rng < (1 << 24):
                    rng = (rng << 8) & 0xFFFFFFFF; code = ((code << 8) | np.int64(mem[p])) & 0xFFFFFFFF; p += 1
                if first:
                    first = False
                    if b == 1: v = f[1]; break
                    idx = 1
                else:
                    idx = idx * 2 + b
                    if idx >= 16: v = idx - 16; break
            px[y, x] = v
    for k in range(n):
        out[k] = px[(2 * k) // W, (2 * k) % W] | (px[(2 * k) // W, (2 * k) % W + 1] << 4)
    return p - src


def encode(x, rle=()):
    t0 = time.time()
    x.decode_all(); rle = set(rle)
    uniq = {}; order = []
    for t in x.tiles:
        k = (t.wb, t.raw)
        if t.idx not in rle and k not in uniq: uniq[k] = len(order); order.append(t)
    assert all(t.wb < 256 for t in order)
    pxs = [D.tile_pixels(t) for t in order]
    n = sum(p.size for p in pxs)
    F = np.zeros((n, NB), np.int64); sym = np.zeros(n, np.int64); k = 0
    for p in pxs: k = gather(p.astype(np.int64), p.shape[0], p.shape[1], F, sym, k)
    T = tests(F); eq = sym == F[:, 1]
    nodes, leaves = build_tree(T, sym, eq)
    nodes_arr = np.array([(0x8000 | a) if kind else (a | (r << 16)) for kind, a, r in nodes], np.int64)
    def mips_node(kind, a, r):
        """MIPS node word over V = sum F[n] << 4n:  type 0: (V >> s1) & 1;  1: ((V >> s1) & 15) == 15;
        2: ((V >> s1) ^ (V >> s2)) & 15 == 0;  bits 0-4 s1, 5-9 s2, 10-11 type, 16-31 right child; leaf 0x8000 | leaf"""
        if kind: return 0x8000 | a
        if a < 40:
            nn_, k_ = divmod(a, 5)
            return (4 * nn_ + k_) | (r << 16) if k_ < 4 else (4 * nn_) | (1 << 10) | (r << 16)
        i_, j_ = PAIRS[a - 40]
        return (4 * i_) | ((4 * j_) << 5) | (2 << 10) | (r << 16)
    mnodes = [mips_node(*nd) for nd in nodes]
    probs = np.array(leaves, np.int64)
    pairs = np.array(PAIRS, np.int64)
    model = struct.pack("<IIHH", MAGIC, 0, len(nodes), len(leaves)) + struct.pack("<%dI" % len(nodes), *mnodes) \
        + bytes(int(v) for v in probs.ravel())
    sec0 = bytearray(model); uoff = []
    for t, p in zip(order, pxs):
        uoff.append(len(sec0)); sec0.append(t.wb); sec0 += encode_tile(p, nodes_arr, probs, pairs)
    sec0 += b"\0" * (8 + (-len(sec0) % 4))
    struct.pack_into("<I", sec0, 4, len(sec0)); end = len(sec0)
    roff = {}; done = {}
    for t in x.tiles:
        if t.idx in rle:
            st = x.sec[0][t.off:t.off + t.clen + 1]
            if st not in done: done[st] = len(sec0); sec0 += st
            roff[t.idx] = done[st]
    sec0 += b"\0" * (-len(sec0) % 4)
    new = M.assemble(x, sec0, {t.idx: (roff[t.idx] if t.idx in rle else uoff[uniq[(t.wb, t.raw)]]) for t in x.tiles})
    return new, dict(old=len(x.d), new=len(new), old_pix=x.sizes[0], new_pix=len(sec0), model=len(model), nodes=len(nodes),
                     leaves=len(leaves), dsa_part=end, rle_tiles=len(rle), tiles=len(x.tiles), uniq=len(order), secs=time.time() - t0)


def verify(new, orig):
    y = D.DSP(new); orig.decode_all()
    s0 = y.sec[0]; mem = np.frombuffer(s0 + b"\0" * 16, np.uint8)
    end = struct.unpack_from("<I", s0, 4)[0]; out = np.zeros(1 << 16, np.uint8); bad = 0
    pairs = np.array(PAIRS, np.int64)
    for t, u in zip(orig.tiles, y.tiles):
        if u.off >= end: got = D.rle_decode(s0, u.off, t.n)[0]
        else:
            used = ref_decode(mem, u.off, t.n, 0, out, pairs); got = out[:t.n].tobytes()
            assert u.off + used <= end
        bad += got != t.raw
    return bad


DSA_MAX = 2048


def decoder(addr=0x801fd808):
    """assemble common/dsp/dsadec.S at addr -> (bytes, {symbol: address}); checks size, load-delay hazards, that the
    code is position-independent (identical bytes at another address) and that it touches no $sp / $s* / $gp"""
    import importlib.util, re, subprocess
    spec = importlib.util.spec_from_file_location("dlib", os.path.join(ROOT, "tools", "speed", "decode", "dlib.py"))
    dl = importlib.util.module_from_spec(spec); spec.loader.exec_module(dl)
    src = os.path.join(HERE, "dsadec.S"); od = os.path.join(ROOT, "work", "dsp_obj")
    code, sym = dl.assemble(src, addr, outdir=od)
    code2, _ = dl.assemble(src, addr ^ 0x00100000, outdir=od)
    assert code == code2, "dsadec.S is not position-independent"
    assert len(code) <= DSA_MAX and (sym["dsa_dec"] & 0xffffffff) == addr
    bad = dl.hazards(code, addr)
    assert not bad, "load-delay hazards: " + "; ".join(bad)
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    for i in md.disasm(code, addr):
        t = i.mnemonic + " " + i.op_str
        assert not re.search(r"[$](sp|s[0-8]|fp|gp|k[01])[^a-z0-9]|[$](sp|s[0-8]|fp|gp|k[01])$|^jal", t), t
    return code, sym


def _job(a):
    game, cid, outdir, cap = a
    b, base, label = D.char_dsp(game, cid)
    x = D.DSP(b, base)
    rle = M.hot_tiles(game, label, x, cap)
    if cap and rle is None: return dict(label=label, skipped=True)
    new, st = encode(x, rle or ())
    st["bad"] = verify(new, x)
    st.update(id=cid, label=label)
    open(os.path.join(outdir, label + ".DSP"), "wb").write(new)
    return st


def main():
    a = sys.argv[1:]; cap = 0
    if "--hot" in a: i = a.index("--hot"); cap = int(a[i + 1]) * 1024; del a[i:i + 2]
    cmd, game = a[0], a[1]
    if cmd == "build":
        addr = int(a[2], 16) if len(a) > 2 else 0x801fd808
        code, sym = decoder(addr)
        p = os.path.join(ROOT, "games", game, "work", "dsp", "dsa", "dsadec.bin")
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(code)
        print("%s: %d bytes (linked at 0x%08x, position-independent, no load-delay hazards)" % (p, len(code), addr))
        return
    ids = [int(v, 16) for v in a[2:]] or D.char_ids(game)
    outdir = os.path.join(ROOT, "games", game, "work", "dsp", "dsa" + ("_hot%d" % (cap // 1024) if cap else ""))
    os.makedirs(outdir, exist_ok=True)
    sp = os.path.join(outdir, "stats.json")
    stats = json.load(open(sp)) if os.path.exists(sp) else {}
    from multiprocessing import Pool
    with Pool(min(6, len(ids))) as p:
        for st in p.imap_unordered(_job, [(game, c, outdir, cap) for c in ids]):
            if st.get("skipped"): continue
            stats[st["label"]] = st
            print("%s old %7d new %7d  pix %7d -> %7d (%.3f)  model %5d (%d nodes, %d leaves)  bad %d  %.0fs" % (
                st["label"], st["old"], st["new"], st["old_pix"], st["new_pix"], st["new_pix"] / st["old_pix"], st["model"],
                st["nodes"], st["leaves"], st["bad"], st["secs"]), flush=True)
    json.dump(stats, open(sp, "w"), indent=1)


if __name__ == "__main__":
    main()
