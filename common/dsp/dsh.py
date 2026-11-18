"""DSH1: XVH1-class "strong" sprite codec for .DSP character files (MSHvSF kind 6, MvC kind 8).  Port of XvSF XVH1
(tools/nsp_huff.py): 4bpp pixels coded one at a time in raster order, canonical Huffman (max 12 bits), table
chosen by the causal neighbours (L, U, UL -> class via map1; class, UR -> table via map2; 15 outside the tile),
alphabet = 16 literal pixels + 30 copy-from-the-row-above runs (RUNS pixels).
Differences from XVH1:
  * magic 'DSH1'; the model sits at the start of the PIXEL section (DSP sec0), tile offsets stay relative to it,
    model layout: table offsets at +12, then map1, map2 right after it (one base register in the decoder)
  * the tile stream starts with ONE header byte: width code (pixels/16 - 1) << 4 | e, e = number of bytes the
    stock RLE decoder writes past nbytes for this tile (run overrun, odd literal: 0..15).  The tile is coded as
    nbytes + e bytes (the overrun bytes are a partial extra row), so the output equals the stock decoder's output
    byte for byte, including what it writes past nbytes.  Codes start at the next byte, MSB first.
  * the tile table (DSP sec2) is rewritten: offsets only (bits 0-21)
Tiles in `rle` keep their stock RLE streams, stored after the DSH1 part (size field at +4 covers only the DSH1 part,
so the dispatch sends them to the RLE path) - the hot-tier mechanism of dsm.py (--hot N).

sec0 layout: +0 u32 'DSH1'  +4 u32 size of the DSH1 part  +8 u16 classes  +10 u16 tables
             +12 u16 tofs[tables] (sec0 offset of each table record)  M = 12 + 2 * tables: u8 map1[4096]
             (L<<8 | U<<4 | UL -> class)  M + 4096: u8 map2[16 * classes] (class<<4 | UR -> table)  records: u8 cnt[maxlen] .. cnt[1] (number of
             codes of each length, maxlen = the table's longest code), then the symbols in canonical order; tofs
             points at the first symbol (cnt[l] is at tofs - l)   tile streams
Decoder: common/dsp/dshdec.S (MIPS, linked at 0x801fe200), entered from the dispatch in common/dsp/dsmdec.S.
MvC (kind 8 files, tiles of any even byte width 2..120): the width code in the tile header is W/4 - 1 ('0' = 3 i.e.
16 px, '10' = 7 i.e. 32 px, '11' + 6 bits) instead of W/16 - 1; decoder built with -DMVC, link address a parameter
(default 0x801fd800, max 2048 bytes).  Everything else is the same.

    python dsh.py encode GAME [ids hex..] [--hot N] [-k K] [-c C] [-j procs]  -> games/GAME/work/dsp/dsh[_hotN]/<label>.DSP + stats.json
    python dsh.py build mshvsf      -> games/mshvsf/work/dsp/dsh/dshdec.bin (raw binary linked at 0x801fe200)
    python dsh.py build mvc [addr]  -> games/mvc/work/dsp/dsh/dshdec.bin (-DMVC, linked at addr, default 0x801fd800)
"""
import os, sys, struct, json, time
import numpy as np
import numba as nb
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(ROOT, "work", "nbcache"))
import dsp as D
import dsm as DM
import nsp_huff as XH                       # parse2 / acc_hist / enc kernels (XvSF XVH1 encoder)
from nsp_codec import cluster, canon, RUNS, NR

MAGIC = 0x31485344                          # 'DSH1'
MAXLEN = int(os.environ.get('DSH_MAXLEN', '12'))
NS = 16 + NR
R16 = RUNS.astype(np.int64)
O_TOFS = 12
Q = 16                                      # second-level context values (UR)
RAW = int(os.environ.get('DSH_RAW', '1'))
REFINE = int(os.environ.get('DSH_REFINE', '20'))
MAXW = 240                                  # pixels: row buffer rb[0..W+3] in scratchpad 0x300-0x3ff


def written(sec0, t):
    """the bytes the stock RLE decoder writes for tile t: nbytes + overrun (runs, odd literal extra byte).
    sec0 should extend past the pixel section (an odd literal at its very end stores the next file byte)"""
    out = bytearray(); p = t.off; n = t.n; extra = 0
    while len(out) < n:
        b = sec0[p]; p += 1
        if b & 0xF0:
            out += bytes([(b & 15) * 0x11]) * ((b >> 4) + 1); extra = 0
        else:
            c = (b & 15) + 1
            out += sec0[p:p + c]; p += c
            extra = c & 1
    if extra: out.append(sec0[p])
    return bytes(out)


def tile_ctx(raw, wb):
    """per-pixel S, c12 = L<<8|U<<4|UL, q = UR (15 outside the tile), raster order; raw may end in a partial row"""
    n = len(raw); h = -(-n // wb)
    a = np.zeros(h * wb, np.uint8); a[:n] = np.frombuffer(raw, np.uint8)
    a = a.reshape(h, wb)
    px = np.empty((h, wb * 2), np.int32); px[:, 0::2] = a & 15; px[:, 1::2] = a >> 4
    P = np.full((h + 1, wb * 2 + 2), 15, np.int32); P[1:, 1:-1] = px
    L = P[1:, :-2]; U = P[:-1, 1:-1]; UL = P[:-1, :-2]; UR = P[:-1, 2:]
    k = 2 * n
    return px.ravel()[:k].copy(), ((L << 8) | (U << 4) | UL).ravel()[:k].astype(np.int32), UR.ravel()[:k].astype(np.int32)


def header(W, e, rep, wm=0):
    """tile header bits -> (value, nbits): width code wc = W/16 - 1: '0' wc 0, '10' wc 1, '11' + 4 bits wc
    (wm = 1, MvC: wc = W/4 - 1: '0' wc 3, '10' wc 7, '11' + 6 bits wc);
    then '10' no overrun, '0' + 4 bits e: e copies of the last byte, '11' + 4 bits e: e coded bytes"""
    if wm:
        assert W % 4 == 0 and 4 <= W <= 256
        wc = W // 4 - 1
        v, l = ((0, 1) if wc == 3 else (2, 2) if wc == 7 else ((3 << 6) | wc, 8))
    else:
        assert W % 16 == 0
        wc = W // 16 - 1
        v, l = ((0, 1) if wc == 0 else (2, 2) if wc == 1 else ((3 << 4) | wc, 6))
    v2, l2 = ((2, 2) if e == 0 else (e, 5) if rep else ((3 << 4) | e, 6))
    return (v << l2) | v2, l + l2


@nb.njit
def enc_tile(S, hv, hl, tail, tab, lens, codes, RUNS, choice, out):
    """header bits, the symbols, then the tail bytes (8 bits each: raw overrun bytes)"""
    n = len(S); i = 0; p = 0
    acc = hv; nb_ = hl
    while i < n:
        t = tab[i]; c = choice[i]
        if c == 0:
            sym = S[i]; i += 1
        else:
            sym = 16 + c - 1; i += RUNS[c - 1]
        l = lens[t, sym]
        acc = (acc << l) | codes[t, sym]; nb_ += l
        while nb_ >= 8:
            out[p] = (acc >> (nb_ - 8)) & 255; p += 1; nb_ -= 8
        acc &= (1 << nb_) - 1
    for k in range(len(tail)):
        acc = (acc << 8) | tail[k]
        out[p] = (acc >> nb_) & 255; p += 1
        acc &= (1 << nb_) - 1
    if nb_:
        out[p] = (acc << (8 - nb_)) & 255; p += 1
    return p


@nb.njit
def ref_decode(mem, src, n, model, RUNS, out, wm=0):
    """Model of the MIPS decoder (common/dsp/dshdec.S): decodes nbytes + e bytes (e from the header byte).
    wm = 1: MvC width code (-DMVC).  -> (bytes written, source bytes consumed)"""
    rb = np.full(260, 15, np.int64)
    src0 = src
    m1 = model + 12 + 2 * (np.int64(mem[model + 10]) | (np.int64(mem[model + 11]) << 8))
    buf = 0; nbits = 0
    # header: 1..6 bits width code, 2..6 bits overrun
    v = 0; k = 0
    while True:
        if nbits == 0:
            buf = np.int64(mem[src]); src += 1; nbits = 8
        nbits -= 1; v = v * 2 + ((buf >> nbits) & 1); k += 1
        if wm:
            if (k == 1 and v == 0) or (k == 2 and v == 2):
                wc = 3 + 4 * (v >> 1); break
            if k == 8:
                wc = v & 63; break
        else:
            if (k == 1 and v == 0) or (k == 2 and v == 2):
                wc = v >> 1; break
            if k == 6:
                wc = v & 15; break
    W = (wc + 1) * (4 if wm else 16)
    v = 0; k = 0; rep = 0; e = 0
    while True:
        if nbits == 0:
            buf = np.int64(mem[src]); src += 1; nbits = 8
        nbits -= 1; v = v * 2 + ((buf >> nbits) & 1); k += 1
        if k == 2 and v == 2:
            e = 0; break
        if k == 5 and (v >> 4) == 0:
            e = v & 15; rep = 1; break
        if k == 6:
            e = v & 15; break
    if rep == 0 and not RAW:
        n = n + e
    x = 0; L = 15; UL = 15; lo = 0; o = 0; run = 0
    while o < n:
        U = rb[x]
        if run == 0:
            c1 = np.int64(mem[m1 + ((L << 8) | (U << 4) | UL)])
            t = np.int64(mem[m1 + 4096 + ((c1 << 4) | rb[x + 1])])
            sp = model + (np.int64(mem[model + 12 + 2 * t]) | (np.int64(mem[model + 13 + 2 * t]) << 8))
            rec = sp - 1
            d = 0
            while True:
                if nbits == 0:
                    buf = np.int64(mem[src]); src += 1; nbits = 8
                nbits -= 1
                d = d * 2 + ((buf >> nbits) & 1)
                c = np.int64(mem[rec]); rec -= 1
                if d < c:
                    break
                d -= c; sp += c
            sym = np.int64(mem[sp + d])
            if sym < 16:
                p = sym
            else:
                run = RUNS[sym - 16] - 1
                p = U
        else:
            run -= 1
            p = U
        rb[x] = p
        if x & 1:
            out[o] = lo | (p << 4); o += 1
        else:
            lo = p
        x += 1
        if x == W:
            x = 0; L = 15; UL = 15
        else:
            L = p; UL = U
    if rep:
        for k in range(e):
            out[n + k] = out[n - 1]
        n += e
    elif RAW:
        for k in range(e):
            v = 0
            for j in range(8):
                if nbits == 0:
                    buf = np.int64(mem[src]); src += 1; nbits = 8
                nbits -= 1; v = v * 2 + ((buf >> nbits) & 1)
            out[n + k] = v
        n += e
    return n, src - src0


def refine(hist1, map1, map2, lens, iters=REFINE):
    """alternating re-assignment on the real coded bits: raw context -> class (given the tables of every
    (class, UR)), (class, UR) -> table, then new code lengths.  -> map1, map2, lens"""
    from nsp_codec import hufflens
    nc1 = int(map1.max()) + 1; K = lens.shape[0]
    h1 = hist1.reshape(4096, -1).astype(np.float64)
    used = np.nonzero(h1.sum(1))[0]
    def total(map1, map2, lens):
        th = np.zeros((K, NS), np.int64)
        np.add.at(th, map2[(map1[:, None] * Q + np.arange(Q)[None, :])].ravel(), hist1.reshape(-1, NS))
        return int((th * lens).sum()), th
    best, _ = total(map1, map2, lens)
    for it in range(iters):
        L = lens.astype(np.float64); L[L == 0] = 24.0
        Lk = L[map2.reshape(nc1, Q)].reshape(nc1, -1)            # [class, Q * NS]
        m1 = map1.copy(); m1[used] = (h1[used] @ Lk.T).argmin(1)
        hist2 = np.zeros((nc1, Q, NS), np.int64); np.add.at(hist2, m1, hist1)
        m2 = (hist2.reshape(-1, NS).astype(np.float64) @ L.T).argmin(1).astype(np.int32)
        th = np.zeros((K, NS), np.int64); np.add.at(th, m2[(m1[:, None] * Q + np.arange(Q)[None, :])].ravel(), hist1.reshape(-1, NS))
        ln = np.stack([hufflens(th[k], MAXLEN) if th[k].any() else lens[k] for k in range(K)])
        tot, _ = total(m1, m2, ln)
        if tot >= best: break
        best = tot; map1, map2, lens = m1.astype(np.int32), m2, ln
    return map1, map2, lens


def build_model(data, K=256, C1=256, passes=3):
    """data: [(S, c12, q, W)] -> model bytes, lens, codes, tabs, choices"""
    map1 = np.zeros(4096, np.int32); map2 = np.zeros(Q, np.int32)
    lens = np.full((1, NS), 3, np.uint8)
    choices = [np.zeros(len(d[0]), np.int32) for d in data]
    tabs = [np.zeros(len(d[0]), np.int32) for d in data]
    nc1 = 1
    for p in range(passes + 1):
        hist1 = np.zeros((4096, Q, NS), np.int64)
        for (S, c12, q, W), ch, tb in zip(data, choices, tabs):
            XH.parse2(S, W, tb, lens, R16, ch, 0)
            XH.acc_hist(S, c12, q, ch, R16, hist1)
        if p == passes: break
        if C1 > 1:
            map1, _ = cluster(hist1.reshape(4096, Q * NS), C1, iters=8, limit=15)
        nc1 = int(map1.max()) + 1
        hist2 = np.zeros((nc1, Q, NS), np.int64)
        np.add.at(hist2, map1, hist1)
        map2, lens = cluster(hist2.reshape(nc1 * Q, NS), K, limit=MAXLEN)
        if REFINE: map1, map2, lens = refine(hist1, map1, map2, lens)
        for (S, c12, q, W), tb in zip(data, tabs):
            tb[:] = map2[map1[c12] * Q + q]
    ntab = lens.shape[0]
    th = np.zeros((ntab, NS), np.int64)
    np.add.at(th, map2[(map1[:, None] * Q + np.arange(Q)[None, :])].ravel(), hist1.reshape(-1, NS))
    assert not ((th > 0) & (lens == 0)).any(), "symbol without code"
    codes, first, cnt, offs, ss = canon(lens)
    assert ntab <= 256 and nc1 <= 256 and lens.max() <= MAXLEN
    o_recs = O_TOFS + 2 * ntab + 4096 + nc1 * Q
    recs = bytearray(); tofs = [0] * ntab
    for k in range(ntab):
        ml = int(lens[k].max())
        recs += bytes(int(cnt[k, l]) for l in range(ml, 0, -1))     # cnt[ml] .. cnt[1], then the symbols
        tofs[k] = o_recs + len(recs)
        recs += bytes(int(s) for s in ss[k, :int((lens[k] > 0).sum())])
    model = struct.pack("<IIHH", MAGIC, 0, nc1, ntab) + struct.pack("<%dH" % ntab, *tofs) + bytes(int(x) for x in map1) \
        + bytes(int(x) for x in map2) + recs
    assert len(model) < 65536
    return bytes(model), lens, codes, tabs, choices, ntab, nc1


def encode(x, K=256, C1=256, rle=(), passes=6):
    """x: dsp.DSP (kind 6: MSHvSF, kind 8: MvC width code). -> (new DSP bytes, stats)"""
    t0 = time.time()
    assert x.kind in (6, 8)
    wm = int(x.kind == 8)
    x.decode_all(); T = x.tiles; rle = set(rle)
    s0x = x.d[0x14:]                                    # sec0 + what follows (odd literal at the section end)
    wr = {t.idx: written(s0x, t) for t in T}
    uniq = {}; order = []
    for t in T:
        k = (t.wb, t.n, wr[t.idx])                        # n too: same bytes written, different overrun (MvC)
        if t.idx not in rle and k not in uniq: uniq[k] = len(order); order.append(t)
    assert all(t.wb * 2 <= MAXW and t.wb % 2 == 0 and len(wr[t.idx]) - t.n <= 15 for t in order)
    hdr = []; data = []; tails = []
    for t in order:
        w = wr[t.idx]; e = len(w) - t.n
        rep = e > 0 and w[t.n:] == w[t.n - 1:t.n] * e
        hdr.append(header(t.wb * 2, e, rep, wm))
        tails.append(np.frombuffer(w[t.n:] if (RAW and not rep) else b"", np.uint8).astype(np.int64))
        data.append(tile_ctx(w[:t.n] if (rep or RAW) else w, t.wb) + (t.wb * 2,))
    model, lens, codes, tabs, choices, ntab, nc1 = build_model(data, K, C1, passes)
    out = np.zeros(1 << 17, np.uint8)
    sec0 = bytearray(model); uoff = []
    for (hv, hl), tl, (S, c12, q, W), ch, tb in zip(hdr, tails, data, choices, tabs):
        m = enc_tile(S, hv, hl, tl, tb, lens, codes, R16, ch, out)
        uoff.append(len(sec0)); sec0 += out[:m].tobytes()
    sec0 += b"\0" * (4 + (-len(sec0) % 4))
    struct.pack_into("<I", sec0, 4, len(sec0))
    dsh_end = len(sec0)
    roff = {}; done = {}
    for t in T:
        if t.idx in rle:
            st = (s0x if wm else x.sec[0])[t.off:t.off + t.clen + 1]   # +1: an odd literal reads one byte past the stream
            # (MSHvSF: as before, byte-identical outputs; MvC: also when the stream ends at the section end)
            if st not in done: done[st] = len(sec0); sec0 += st
            roff[t.idx] = done[st]
    sec0 += b"\0" * (-len(sec0) % 4)
    offs = {t.idx: (roff[t.idx] if t.idx in rle else uoff[uniq[(t.wb, t.n, wr[t.idx])]]) for t in T}
    return DM.assemble(x, sec0, offs), dict(
        old=len(x.d), new=None, old_pix=x.sizes[0], new_pix=len(sec0), model=len(model), tables=ntab, classes=nc1,
        dsh_part=dsh_end, rle_tiles=len(rle), tiles=len(T), uniq=len(order), raw=sum(t.n for t in T),
        secs=time.time() - t0)


def verify(new, orig):
    """decode every tile of `new` (DSH1 part: ref_decode incl. the overrun bytes, behind it: RLE) -> mismatches"""
    y = D.DSP(new); orig.decode_all()
    s0 = y.sec[0]; mem = np.frombuffer(s0 + b"\0" * 16, np.uint8)
    assert struct.unpack_from("<I", s0, 0)[0] == MAGIC
    end = struct.unpack_from("<I", s0, 4)[0]
    out = np.zeros(1 << 17, np.uint8); bad = 0
    for t, u in zip(orig.tiles, y.tiles):
        assert (u.wb, u.h) == (t.wb, t.h)
        want = written(orig.d[0x14:], t)
        if u.off >= end:
            got = written(y.d[0x14:], u)
        else:
            m, used = ref_decode(mem, u.off, t.n, 0, R16, out, int(y.kind == 8)); got = out[:m].tobytes()
            assert u.off + used <= end
        bad += got != want
    assert y.sec[1][:len(orig.sec[1])] == orig.sec[1] and y.sec[3] == orig.sec[3]
    return bad


SEARCH = [(128, 192), (128, 224), (160, 224), (160, 256), (192, 224), (192, 256)]     # (tables, classes) tried per file
DSH_ADDR, DSH_MAX = 0x801fe200, 2048                # fixed load address / size of the decoder (battle loader)
DSH_ADDR_GAME = {"mshvsf": 0x801fe200, "mvc": 0x801fd800}   # default link address per game (MvC: a parameter)


def decoder(game="mshvsf", addr=None):
    """assemble common/dsp/dshdec.S (MvC: -DMVC) at addr (default DSH_ADDR_GAME[game]) -> (bytes, {symbol: address});
    checks size and load-delay hazards"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dlib", os.path.join(ROOT, "tools", "speed", "decode", "dlib.py"))
    dl = importlib.util.module_from_spec(spec); spec.loader.exec_module(dl)
    addr = DSH_ADDR_GAME[game] if addr is None else addr
    assert addr & 3 == 0
    code, sym = dl.assemble(os.path.join(HERE, os.environ.get("DSH_SRC", "dshdec.S")), addr,      # DSH_SRC=dsxdec.S: LUT variant (dsx.py) outdir=os.path.join(ROOT, "work", "dsp_obj"),
                            defs=(("MVC",) if game == "mvc" else ()))
    assert len(code) <= DSH_MAX, "decoder %d bytes > %d" % (len(code), DSH_MAX)
    assert sym["dsh_dec"] == addr
    bad = dl.hazards(code, addr)
    assert not bad, "load-delay hazards: " + "; ".join(bad)
    return code, sym


def _job(a):
    game, cid, K, C1, outdir, cap = a
    b, base, label = D.char_dsp(game, cid)
    x = D.DSP(b, base)
    rle = DM.hot_tiles(game, label, x, cap)
    if cap and rle is None: return dict(label=label, skipped=True)
    best = None
    for k, c in ([(K, C1)] if K else SEARCH):          # per file: the (tables, classes) that gives the smallest file
        new, st = encode(x, k, c, rle=rle or ())
        if best is None or len(new) < len(best[0]): best = (new, st)
    new, st = best
    assert verify(new, x) == 0
    st.update(new=len(new), id=cid, label=label)
    open(os.path.join(outdir, label + ".DSP"), "wb").write(new)
    return st


def main():
    a = sys.argv[1:]
    K = C1 = None; cap = 0; nproc = 4
    if "-k" in a: i = a.index("-k"); K = int(a[i + 1]); del a[i:i + 2]
    if "-c" in a: i = a.index("-c"); C1 = int(a[i + 1]); del a[i:i + 2]
    if K or C1: K = K or 192; C1 = C1 or 256
    if "-j" in a: i = a.index("-j"); nproc = int(a[i + 1]); del a[i:i + 2]
    if "--hot" in a: i = a.index("--hot"); cap = int(a[i + 1]) * 1024; del a[i:i + 2]
    cmd, game = a[0], a[1]
    ids = ([int(v, 16) for v in a[2:]] or D.char_ids(game)) if cmd == "encode" else []
    outdir = os.path.join(ROOT, "games", game, "work", "dsp", "dsh" + ("_hot%d" % (cap // 1024) if cap else ""))
    os.makedirs(outdir, exist_ok=True)
    sp = os.path.join(outdir, "stats.json")
    if cmd == "build":
        addr = int(a[2], 16) if len(a) > 2 else None
        code, sym = decoder(game, addr); addr = sym["dsh_dec"]
        p = os.path.join(ROOT, "games", game, "work", "dsp", "dsh", "dshdec.bin")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(code)
        print("%s: %d bytes at 0x%08x-0x%08x (max %d), no load-delay hazards" % (p, len(code), addr, addr + len(code), DSH_MAX))
        return
    if cmd == "encode":
        from multiprocessing import Pool
        stats = json.load(open(sp)) if os.path.exists(sp) else {}
        with Pool(min(nproc, len(ids))) as p:
            for st in p.imap_unordered(_job, [(game, c, K, C1, outdir, cap) for c in ids]):
                if st.get("skipped"): continue
                stats[st["label"]] = st
                print("%s old %7d new %7d  pix %7d -> %7d (%.3f)  model %5d  tables %d classes %d  rle tiles %d  %.0fs" % (
                    st["label"], st["old"], st["new"], st["old_pix"], st["new_pix"], st["new_pix"] / st["old_pix"], st["model"],
                    st["tables"], st["classes"], st["rle_tiles"], st["secs"]), flush=True)
        json.dump(stats, open(sp, "w"), indent=1)


if __name__ == "__main__":
    main()
