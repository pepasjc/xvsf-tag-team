"""XVM1: the default sprite codec - byte symbols like XVF1, but tables chosen by a clustered
(left pixel, byte above) context and a compact model (6-bit primary LUT + canonical fallback).

Codec (per tile, random access, static per-file model):
  the tile is a linear array of 4bpp-packed BYTES.  Symbols (canonical Huffman, max 12 bits):
      0..255   literal byte
      256+r    copy RUNS[r] bytes from the row above (row 0: the row above is all 0xFF)
      286+r    repeat the previous output byte RUNS[r] times (0xFF before the first byte)
      316      escape: the next 8 bits are a literal byte (literals too rare to get a code)
  No symbol crosses the end of row 0.
  Table = map[(P >> 4) << 8 | U]   P = previous output byte (0xFF at the start), U = byte above
  (0xFF in row 0); 4096-byte map -> K tables (K <= 64 by default).
  Tile stream: byte aligned, bits MSB first; 4 bits width code (bytes/8-1), then the codes.

sec2 layout:
  +0     u32 'XVM1'   +4 u32 sec2 size   +8 u16 offset of the fallback records   +10 u16 K
  +12    u16 RUNS[32]
  +76    u8  map[4096]
  +4172  s16 lut[K][64]         index = next 6 bits
  ...    fallback records, 32 bytes per table: for code length 7..12: u16 lim, s16 adj
             lim = first code longer than this length, left-justified to 12 bits
             entry address = sec2 + adj + 2 * (next `length` bits)
  ...    long-code entry lists (s16)
  ...    tile streams
  entry:  literal  len | byte << 4
          run      0x8000 | len | r << 4 | 0x2000 if "repeat previous byte"
          escape   0x9000 | len            (len <= 8)
          long     0xC000                  (LUT only: use the fallback records)

  python nsp_mid.py encode [ids hex...] [-k K] [-p penalty] [-o dir]  -> build/nspm/SP_PLxx.NSP + stats.json
  python nsp_mid.py file IN.NSP OUT.NSP            re-encode any .NSP (e.g. SP_EFF1.NSP)
  python nsp_mid.py verify [ids hex...]
  python nsp_mid.py table
"""
import sys, os, json, struct, time
import numpy as np
import numba as nb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nsp import NSP, rle_decode
from nsp_codec import hufflens, canon, RUNS, NR, A0, ROOT

OUTDIR = os.path.join(ROOT, "build", "nspm")
MAGIC = 0x314D5658            # 'XVM1'
KB = 6                        # primary LUT bits
LIMIT = 12
ESC = 256 + 2 * NR; NS = ESC + 1
R = RUNS.astype(np.int64)
O_RUNS, O_MAP, O_LUT = 12, 76, 76 + 4096


@nb.njit
def parse(S, W, tab, lens, RUNS, choice, pen):
    """Optimal parse.  Costs in 1/4 bit; `pen` (quarter bits) is added to every run symbol to
    trade size for decode speed."""
    n = len(S); NRr = len(RUNS)
    up = np.zeros(n + 1, np.int32); rep = np.zeros(n + 1, np.int32); eq = np.zeros(n + 1, np.int32)
    for i in range(n - 1, -1, -1):
        u = S[i - W] if i >= W else 255
        up[i] = up[i + 1] + 1 if (S[i] == u and i != W - 1) else (1 if S[i] == u else 0)
        eq[i] = eq[i + 1] + 1 if (i + 1 < n and S[i + 1] == S[i] and i != W - 1) else 1
    for i in range(n):
        pv = S[i - 1] if i else 255
        rep[i] = eq[i] if S[i] == pv else 0
    cost = np.zeros(n + 1, np.int64)
    for i in range(n - 1, -1, -1):
        t = tab[i]
        l = lens[t, S[i]]
        if l == 0: l = lens[t, 256 + 2 * NRr] + 8
        best = cost[i + 1] + 4 * l; bc = 0
        for r in range(NRr):
            if RUNS[r] > up[i]: break
            l = lens[t, 256 + r]
            if l == 0: continue
            c = cost[i + RUNS[r]] + 4 * l + pen
            if c < best: best = c; bc = 1 + r
        for r in range(NRr):
            if RUNS[r] > rep[i]: break
            l = lens[t, 256 + NRr + r]
            if l == 0: continue
            c = cost[i + RUNS[r]] + 4 * l + pen
            if c < best: best = c; bc = 1 + NRr + r
        cost[i] = best; choice[i] = bc


@nb.njit
def acc(S, ctx, choice, RUNS, hist):
    n = len(S); i = 0
    while i < n:
        c = choice[i]
        if c == 0: hist[ctx[i], S[i]] += 1; i += 1
        else: hist[ctx[i], 255 + c] += 1; i += RUNS[(c - 1) % len(RUNS)]


@nb.njit
def emit(S, W, tab, choice, RUNS, lens, codes, out):
    """MSB-first stream: width nibble then codes.  Returns bytes written."""
    n = len(S); i = 0; p = 0; NRr = len(RUNS)
    acc_ = (W >> 3) - 1; nb_ = 4
    while i < n:
        t = tab[i]; c = choice[i]; raw = -1
        if c == 0:
            sym = S[i]; i += 1
            if lens[t, sym] == 0: raw = sym; sym = 256 + 2 * NRr
        else:
            sym = 255 + c; i += RUNS[(c - 1) % NRr]
        l = lens[t, sym]
        acc_ = (acc_ << l) | codes[t, sym]; nb_ += l
        if raw >= 0:
            acc_ = (acc_ << 8) | raw; nb_ += 8
        while nb_ >= 8:
            out[p] = (acc_ >> (nb_ - 8)) & 255; p += 1; nb_ -= 8
        acc_ &= (1 << nb_) - 1
    if nb_:
        out[p] = (acc_ << (8 - nb_)) & 255; p += 1
    return p


@nb.njit
def ref_decode(mem, src, n, model, out):
    """Exact model of the MIPS decoder xvm_dec (tools/nspdec/nspdec.S): same bit buffer discipline
    (32-bit MSB-first buffer, c = bits available - 16, 16-bit refills), same table walks."""
    M = 0xFFFFFFFF
    fbo = model + (np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8))
    buf = (np.int64(mem[src]) << 24) | (np.int64(mem[src + 1]) << 16) | (np.int64(mem[src + 2]) << 8) | np.int64(mem[src + 3])
    src0 = src; src += 4
    W = ((buf >> 28) + 1) << 3
    buf = (buf << 4) & M
    c = 12
    P = 255; ph = 15 << 8
    o = 0
    while o < n:
        U = np.int64(out[o - W]) if o >= W else 255
        t = np.int64(mem[model + 76 + (ph | U)])
        a = model + 4172 + (t << 7) + ((buf >> 25) & 0x7e)
        e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        if (e & 0xC000) == 0xC000:                         # code longer than 6 bits
            w = buf >> 20
            p = fbo + (t << 5); sh = 5
            while True:
                lim = np.int64(mem[p]) | (np.int64(mem[p + 1]) << 8)
                if w < lim: break
                p += 4; sh -= 1
            adj = np.int64(mem[p + 2]) | (np.int64(mem[p + 3]) << 8)
            if adj & 0x8000: adj -= 0x10000
            a = model + adj + ((w >> sh) << 1)
            e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        l = e & 15
        buf = (buf << l) & M; c -= l
        if e & 0x8000:
            if e & 0x1000:                                 # escape: 8 raw bits
                P = buf >> 24
                buf = (buf << 8) & M; c -= 8
                out[o] = P; o += 1
            else:
                a = model + 12 + ((e >> 3) & 0x3e)
                r = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
                if e & 0x2000:
                    for k in range(r):
                        out[o] = P; o += 1
                else:
                    for k in range(r):
                        out[o] = out[o - W] if o >= W else 255
                        o += 1
                    P = np.int64(out[o - 1])
        else:
            P = (e >> 4) & 255
            out[o] = P; o += 1
        ph = (P >> 4) << 8
        if c < 0:
            v = (np.int64(mem[src]) << 8) | np.int64(mem[src + 1])
            buf = (buf | (v << (-c))) & M
            src += 2; c += 16
    return src - src0


def tile_ctx(raw, wb):
    a = np.frombuffer(raw, np.uint8).astype(np.int32); n = len(a)
    P = np.concatenate([[255], a[:-1]])
    U = np.concatenate([np.full(wb, 255), a[:-wb]]) if n > wb else np.full(n, 255)
    return a, ((P >> 4) << 8 | U).astype(np.int32)


def tab_lens(h, model_bits=int(os.environ.get("XVM_MB", "16"))):
    """Code lengths for one table.  Literals that are too rare to pay for their 2-byte long-code
    entry are left to the escape (decided once from the unpruned code, against a notional
    16-bit escape, so the choice cannot feed back on itself); escape code <= 8 bits."""
    h = h.copy(); h[ESC] = 0
    hh = h.copy(); hh[ESC] = 1
    l0 = hufflens(hh, LIMIT).astype(np.int64)
    keep = h > 0
    sav = h[:256] * (16 - l0[:256])
    keep[:256] &= ~((l0[:256] > KB) & (sav < model_bits))
    hh = np.where(keep, h, 0); hh[ESC] = max(1, int(h[:256][~keep[:256]].sum()))
    l = hufflens(hh, LIMIT)
    while l[ESC] > 8:
        hh[ESC] *= 2; l = hufflens(hh, LIMIT)
    return l


def cluster(hist, K, iters=8):
    nctx = hist.shape[0]; tot = hist.sum(1); used = np.nonzero(tot)[0]
    order = used[np.argsort(-tot[used])]
    tmap = np.zeros(nctx, np.int32)
    if K >= len(used):
        tmap[used] = np.arange(len(used)); K = max(1, len(used))
    else:
        tmap[:] = K - 1; tmap[order[:K - 1]] = np.arange(K - 1)
    H = hist[used].astype(np.float64)
    for it in range(iters + 1):
        th = np.zeros((K, NS), np.int64); np.add.at(th, tmap[used], hist[used])
        lens = np.stack([tab_lens(th[k]) for k in range(K)])
        if it == iters: break
        L = lens.astype(np.float64)
        esc = L[:, ESC:ESC + 1] + 8
        Lc = np.where(L > 0, L, 0); Lc[:, :256] = np.where(L[:, :256] > 0, L[:, :256], esc)
        Lc[:, 256:ESC] = np.where(L[:, 256:ESC] > 0, L[:, 256:ESC], 40)
        cost = H @ Lc.T
        new = cost.argmin(1).astype(np.int32)
        present = np.zeros(K, bool); present[new] = True
        if not present.all():
            cur = cost[np.arange(len(used)), new]; worst = np.argsort(-cur); wi = 0
            for k in np.nonzero(~present)[0]: new[worst[wi]] = k; wi += 1
        if (new == tmap[used]).all(): break
        tmap[used] = new
    return tmap, lens


def entry(sym, l):
    if sym < 256: return l | sym << 4
    if sym < 256 + NR: return 0x8000 | l | (sym - 256) << 4
    if sym < ESC: return 0xA000 | l | (sym - 256 - NR) << 4
    return 0x9000 | l


def make_model(tmap, lens):
    K = lens.shape[0]
    codes, first, cnt, offs, ss = canon(lens)
    lut = np.zeros((K, 1 << KB), np.int64)
    fb = np.zeros((K, 8, 2), np.int64)
    o_fb = O_LUT + K * (2 << KB)
    o_long = o_fb + K * 32
    longs = []
    for t in range(K):
        nlong = 0
        for l in range(1, LIMIT + 1):
            syms = np.nonzero(lens[t] == l)[0]
            f = int(first[t, l])
            if l <= KB:
                for s in syms:
                    c = int(codes[t, s])
                    for j in range(1 << (KB - l)): lut[t, (c << (KB - l)) | j] = entry(int(s), l)
            else:
                for s in syms:
                    c = int(codes[t, s])
                    lut[t, c >> (l - KB)] = 0xC000
                    longs.append(entry(int(s), l))
                adj = o_long + 2 * (len(longs) - len(syms)) - 2 * f
                assert -32768 <= adj < 32768
                fb[t, l - KB - 1] = ((f + len(syms)) << (LIMIT - l), adj & 0xFFFF)
        fb[t, LIMIT - KB - 1, 0] = max(fb[t, LIMIT - KB - 1, 0], 4096)     # the walk always stops here
    runs = [int(x) for x in RUNS] + [0, 0]
    m = struct.pack("<IIHH", MAGIC, 0, o_fb, K) + struct.pack("<32H", *runs) + bytes(int(x) for x in tmap)
    m += struct.pack("<%dH" % lut.size, *[int(x) for x in lut.ravel()])
    m += struct.pack("<%dH" % fb.size, *[int(x) for x in fb.ravel()])
    m += struct.pack("<%dH" % len(longs), *longs)
    assert len(m) == o_long + 2 * len(longs) and len(m) < 32768
    return m, codes


def encode_file(path, K=64, pen=0, passes=4, rle=(), fast=()):
    """-> (new file bytes, stats).  `rle` = tile indices kept as their ORIGINAL RLE streams (for tiles
    that are decoded in bursts): they are stored after the XVM1 part of sec2, and the size field in
    the XVM1 header covers only the XVM1 part, so the decoder's range test sends them to the game's
    own RLE routine - no decoder change, old XVM1 files stay valid."""
    t0 = time.time()
    n = NSP(path); n.decode_all()
    assert n.offs[0] == 16 and all(o % 4 == 0 for o in n.offs)
    T = n.tiles
    assert all((t.word >> 22) & 3 == 0 for t in T)
    rle = set(rle); fast = set(fast) - rle             # fast = tiles for the XVG1 region (nsp_fast2.py)
    uniq = {}; order = []
    for t in T:
        k = (t.wb, t.raw)
        if t.idx not in rle and t.idx not in fast and k not in uniq: uniq[k] = len(order); order.append(t)
    data = [tile_ctx(t.raw, t.wb) + (t.wb,) for t in order]
    tmap = np.zeros(4096, np.int32)
    lens = np.zeros((1, NS), np.uint8); lens[0, :256] = 7; lens[0, 256:ESC] = 6; lens[0, ESC] = 8
    ch = [np.zeros(len(d[0]), np.int32) for d in data]
    for p in range(passes + 1):
        hist = np.zeros((4096, NS), np.int64)
        for (S, c, W), cc in zip(data, ch):
            parse(S, W, tmap[c], lens, R, cc, pen); acc(S, c, cc, R, hist)
        if p == passes: break
        tmap, lens = cluster(hist, K)
    th = np.zeros((lens.shape[0], NS), np.int64); np.add.at(th, tmap, hist)
    assert not ((th[:, 256:ESC] > 0) & (lens[:, 256:ESC] == 0)).any() and (lens[:, ESC] > 0).all() and (lens[:, ESC] <= 8).all()
    model, codes = make_model(tmap, lens)
    out = np.zeros(1 << 17, np.uint8)
    sec2 = bytearray(model); uoff = []
    for (S, c, W), cc in zip(data, ch):
        m = emit(S, W, tmap[c], cc, R, lens, codes, out)
        uoff.append(len(sec2)); sec2 += out[:m].tobytes()
    sec2 += b"\0" * (4 + (-len(sec2) % 4))                 # the decoder reads up to 4 bytes ahead
    struct.pack_into("<I", sec2, 4, len(sec2))             # end of the XVM1 part
    xvm_end = len(sec2)
    foff = {}; finfo = dict(ntab=0, S=0, model=0); fast_len = 0
    if fast:
        import nsp_fast2
        fu = {}; fl = []
        for t in T:
            if t.idx in fast and (t.wb, t.raw) not in fu: fu[(t.wb, t.raw)] = len(fl); fl.append((t.raw, t.wb))
        reg, offs, finfo = nsp_fast2.encode_region(fl)
        for t in T:
            if t.idx in fast: foff[t.idx] = xvm_end + offs[fu[(t.wb, t.raw)]]
        sec2 += reg; fast_len = len(reg)
    roff = {}; rdone = {}
    for t in T:
        if t.idx in rle:
            st_ = n.sec[2][t.off:t.off + t.clen]
            if st_ not in rdone: rdone[st_] = len(sec2); sec2 += st_
            roff[t.idx] = rdone[st_]
    sec2 += b"\0" * (-len(sec2) % 4)
    assert len(sec2) < (1 << 22)
    sec1 = bytearray(n.sec[1])
    for t in T:
        off = roff[t.idx] if t.idx in rle else foff[t.idx] if t.idx in fast else uoff[uniq[(t.wb, t.raw)]]
        struct.pack_into("<I", sec1, t.idx * 4, (t.word & ~0x3FFFFF) | off)
    o1, o2 = n.offs[1], n.offs[2]; o3 = o2 + len(sec2)
    new = struct.pack("<4I", 16, o1, o2, o3) + n.sec[0] + bytes(sec1) + bytes(sec2) + n.sec[3]
    assert verify_bytes(new, n) == 0, "round trip failed"
    raw = sum(len(t.raw) for t in T)
    st = dict(old=len(n.d), new=len(new), old_sec2=n.sizes[2], new_sec2=len(sec2), model=len(model), tables=int(lens.shape[0]),
              rle_tiles=len(rle), rle_raw=sum(len(t.raw) for t in T if t.idx in rle), rle_stream=len(sec2) - xvm_end - fast_len,
              fast_tiles=len(fast), fast_raw=sum(len(t.raw) for t in T if t.idx in fast), fast_region=fast_len, fast_model=finfo["model"], fast_tables=finfo["ntab"],
              streams=len(sec2) - len(model), tiles=len(T), uniq=len(order), other=len(new) - len(sec2), raw=raw,
              lit=int(hist[:, :256].sum()), upruns=int(hist[:, 256:256 + NR].sum()), repruns=int(hist[:, 256 + NR:ESC].sum()),
              esc=int((th[:, :256] * (lens[:, :256] == 0)).sum()), longsyms=int((th * (lens > KB)).sum()), secs=time.time() - t0)
    return new, st


def verify_bytes(new, orig):
    mem = np.frombuffer(new + b"\0" * 8, np.uint8)
    o1, o2, o3 = struct.unpack_from("<3I", new, 4)
    assert struct.unpack_from("<I", new, o2)[0] == MAGIC
    xvm_end = struct.unpack_from("<I", new, o2 + 4)[0]
    import nsp_fast2
    fast_end = xvm_end
    if o2 + xvm_end + 8 <= o3 and struct.unpack_from("<I", new, o2 + xvm_end)[0] == nsp_fast2.MAGIC:
        fast_end = xvm_end + struct.unpack_from("<I", new, o2 + xvm_end + 4)[0]
    out = np.zeros(1 << 16, np.uint8); bad = 0
    orig.decode_all()
    for t in orig.tiles:
        w = struct.unpack_from("<I", new, o1 + 4 * t.idx)[0]
        assert w >> 22 == t.word >> 22
        nbytes = t.wb * t.h
        if fast_end > (w & 0x3FFFFF) >= xvm_end:           # XVG1 fast region
            used = nsp_fast2.ref_decode(mem, o2 + (w & 0x3FFFFF), nbytes, o2 + xvm_end, out)
            if out[:nbytes].tobytes() != t.raw: bad += 1
            assert (w & 0x3FFFFF) + used <= fast_end
            continue
        if (w & 0x3FFFFF) >= xvm_end:                      # behind both: original RLE stream
            got, used, over = rle_decode(new, o2 + (w & 0x3FFFFF), nbytes)
            if got != t.raw: bad += 1
            assert o2 + (w & 0x3FFFFF) + used <= o3
            continue
        used = ref_decode(mem, o2 + (w & 0x3FFFFF), nbytes, o2, out)
        if out[:nbytes].tobytes() != t.raw: bad += 1
        assert (w & 0x3FFFFF) + used <= xvm_end
    return bad


def _job(a):
    cid, K, pen, outdir = a[:4]
    new, st = encode_file(os.path.join(A0, "SP_PL%02X.NSP" % cid), K, pen, rle=a[4] if len(a) > 4 else (), fast=a[5] if len(a) > 5 else ())
    st["id"] = cid
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "SP_PL%02X.NSP" % cid), "wb").write(new)
    return st


def main():
    args = sys.argv[1:]
    K = 64; pen = 0; outdir = OUTDIR
    for flag in ("-k", "-p", "-o"):
        if flag in args:
            i = args.index(flag); v = args[i + 1]; del args[i:i + 2]
            if flag == "-k": K = int(v)
            elif flag == "-p": pen = int(v)
            else: outdir = os.path.join(ROOT, "build", v)
    cmd = args[0]
    sp = os.path.join(outdir, "stats.json")
    if cmd == "file":
        new, st = encode_file(args[1], K, pen)
        open(args[2], "wb").write(new)
        print(json.dumps(st))
        return
    ids = [int(x, 16) for x in args[1:]] or list(range(0x13))
    if cmd == "encode":
        from multiprocessing import Pool
        os.makedirs(outdir, exist_ok=True)
        stats = json.load(open(sp)) if os.path.exists(sp) else {}
        with Pool(min(7, len(ids))) as p:
            for st in p.imap_unordered(_job, [(c, K, pen, outdir) for c in ids]):
                stats["%02X" % st["id"]] = st
                print("PL%02X old %7d new %7d  streams %7d model %5d (%d tables)  per out byte: lit %.3f up %.3f rep %.3f esc %.4f long %.3f  %.0fs" % (
                    st["id"], st["old"], st["new"], st["streams"], st["model"], st["tables"], st["lit"] / st["raw"], st["upruns"] / st["raw"],
                    st["repruns"] / st["raw"], st["esc"] / st["raw"], st["longsyms"] / st["raw"], st["secs"]), flush=True)
        json.dump(stats, open(sp, "w"), indent=1)
    elif cmd == "verify":
        tot = 0
        for c in ids:
            new = open(os.path.join(outdir, "SP_PL%02X.NSP" % c), "rb").read()
            o = NSP(os.path.join(A0, "SP_PL%02X.NSP" % c))
            bad = verify_bytes(new, o); tot += bad
            assert new[16:struct.unpack_from("<I", new, 4)[0]] == o.sec[0] and new[struct.unpack_from("<I", new, 12)[0]:] == o.sec[3]
            print("PL%02X tiles %5d mismatching %d  (sec0/sec3 identical)" % (c, len(o.tiles), bad), flush=True)
        print("TOTAL mismatching tiles:", tot)
    elif cmd == "table":
        stats = json.load(open(sp))
        print("char   old file  new file   streams  model  non-px")
        for k in sorted(stats):
            s = stats[k]
            print("PL%s  %8d  %8d  %7d  %6d  %6d" % (k, s["old"], s["new"], s["streams"], s["model"], s["other"]))
        n = len(stats); Sm = lambda f: sum(s[f] for s in stats.values())
        print("avg   %8d  %8d  %7d  %6d  %6d" % (Sm("old") // n, Sm("new") // n, Sm("streams") // n, Sm("model") // n, Sm("other") // n))


if __name__ == "__main__":
    main()
