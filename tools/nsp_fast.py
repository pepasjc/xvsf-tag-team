"""XVF1: speed-first re-encoding of X-Men vs. Street Fighter character .NSP pixel sections (sec2).
(XVH1 in nsp_huff.py is the size-first variant.)

Codec (per tile, random access, static per-file model, LUT decoded):
  the tile is a linear array of 4bpp-packed BYTES (2 pixels).  Symbols, canonical Huffman, max
  8+S bits (S = 2..4, chosen per file):
      0..255        literal byte
      256+r         copy RUNS[r] bytes from the row above (dst - width); never used in row 0
      286+r         repeat the previous output byte RUNS[r] times (0xFF before the first byte)
  The code table (16 of them) is selected by the HIGH nibble (= right pixel) of the previous
  output byte in linear order (0xFF before the first byte).
  Tile stream: byte aligned, bits packed LSB first; 4 bits width code (bytes/8-1), then codes
  (each code is emitted first-bit-first, i.e. bit-reversed canonical code).

sec2 layout:
  +0     u32 'XVF1'      +4 u32 sec2 size      +8 u16 ((1<<S)-1)<<1      +10 u16 0
  +12    u16 RUNS[32]
  +76    s16 lut[16][256]      primary LUT, index = next 8 stream bits
  +8268  s16 sub-tables, 1<<S entries each, index = the following S bits
  ...    tile streams (sec1 offsets relative to sec2 start)
  LUT entry:  literal  len | byte<<5                       (len = bits consumed, 1..8)
              run      0x8000 | len | r<<5 | 0x2000 if "repeat previous byte"
              long     0xC000 | (sub-table byte offset / 2)   (consumes 8 bits, then the sub entry)

  python nsp_fast.py encode [ids hex...]   -> build/nspf/SP_PLxx.NSP + stats.json
  python nsp_fast.py verify [ids hex...]
  python nsp_fast.py table
"""
import sys, os, json, struct, time
import numpy as np
import numba as nb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nsp import NSP
from nsp_codec import hufflens, canon, RUNS, NR, A0, ROOT

OUTDIR = os.path.join(ROOT, "build", "nspf")
MAGIC = 0x31465658            # 'XVF1'
K = 8
NS = 256 + 2 * NR
RUNS16 = RUNS.astype(np.int64)
O_RUNS, O_LUT = 12, 76
O_SUB = O_LUT + 16 * 512


@nb.njit
def parse(S, W, lens, RUNS, choice):
    n = len(S)
    up = np.zeros(n + 1, np.int32); rep = np.zeros(n + 1, np.int32)
    for i in range(n - 1, -1, -1):
        up[i] = up[i + 1] + 1 if (i >= W and S[i] == S[i - W]) else 0
    # rep[i]: number of bytes from i on equal to the byte before i
    eq = np.zeros(n + 1, np.int32)
    for i in range(n - 1, -1, -1):
        eq[i] = eq[i + 1] + 1 if (i + 1 < n and S[i + 1] == S[i]) else 1
    for i in range(n):
        pv = S[i - 1] if i else 255
        rep[i] = eq[i] if S[i] == pv else 0
    cost = np.zeros(n + 1, np.int64)
    for i in range(n - 1, -1, -1):
        t = (S[i - 1] >> 4) if i else 15
        l = lens[t, S[i]]
        if l == 0: l = 30
        best = cost[i + 1] + l; bc = 0
        for r in range(len(RUNS)):
            if RUNS[r] > up[i]: break
            l = lens[t, 256 + r]
            if l == 0: l = 30
            c = cost[i + RUNS[r]] + l
            if c < best: best = c; bc = 1 + r
        for r in range(len(RUNS)):
            if RUNS[r] > rep[i]: break
            l = lens[t, 256 + len(RUNS) + r]
            if l == 0: l = 30
            c = cost[i + RUNS[r]] + l
            if c < best: best = c; bc = 1 + len(RUNS) + r
        cost[i] = best; choice[i] = bc


@nb.njit
def walk(S, choice, RUNS, hist, lens, rcodes, out):
    """Accumulate hist; if out has room, also emit the stream (LSB first). Returns bytes written."""
    n = len(S); i = 0; p = 0
    acc = 0; nb_ = 0
    emit = len(out) > 0
    while i < n:
        t = (S[i - 1] >> 4) if i else 15
        c = choice[i]
        if c == 0:
            sym = S[i]; i += 1
        else:
            sym = 255 + c; i += RUNS[(c - 1) % len(RUNS)]
        hist[t, sym] += 1
        if emit:
            acc |= rcodes[t, sym] << nb_; nb_ += lens[t, sym]
            while nb_ >= 8:
                out[p] = acc & 255; p += 1; acc >>= 8; nb_ -= 8
    if emit and nb_:
        out[p] = acc & 255; p += 1
    return p


@nb.njit
def ref_decode(mem, src, n, model, out):
    """Exact model of the MIPS decoder xvf_dec in tools/nspdec/nspdec.S (same buffer discipline:
    buf holds the unread bits shifted left by one, c = bits available - 16, 16-bit refills)."""
    M = 0xFFFFFFFF
    lut = model + 76
    submask = np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8)
    w = np.int64(mem[src]) | (np.int64(mem[src + 1]) << 8) | (np.int64(mem[src + 2]) << 16) | (np.int64(mem[src + 3]) << 24)
    src0 = src; src += 4
    W = ((w & 15) + 1) << 3
    buf = (w >> 3) & 0xFFFFFFFE
    c = 12
    last = 255
    tbl = lut + 15 * 512
    o = 0
    while o < n:
        a = tbl + (buf & 0x1fe)
        e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        if e & 0x4000 and e & 0x8000:                      # long code: 8 bits, then the sub-table
            buf >>= 8; c -= 8
            a = lut + 8192 + ((e & 0x3fff) << 1) + (buf & submask)
            e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        l = e & 31
        buf >>= l; c -= l
        if e & 0x8000:
            a = lut - 64 + ((e & 0x3e0) >> 4)
            r = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
            if e & 0x2000:
                for k in range(r):
                    out[o] = last; o += 1
            else:
                for k in range(r):
                    out[o] = out[o - W]; o += 1
                last = np.int64(out[o - 1])
                tbl = lut + ((last >> 4) << 9)
        else:
            last = (e >> 5) & 255
            tbl = lut + (e & 0x1e00)
            out[o] = last; o += 1
        if c < 0:
            v = np.int64(mem[src]) | (np.int64(mem[src + 1]) << 8)
            buf = (buf | (v << (c + 17))) & M
            src += 2; c += 16
    return src - src0


def bitrev(c, l):
    r = 0
    for _ in range(l):
        r = (r << 1) | (c & 1); c >>= 1
    return r


def make_model(lens, codes, S):
    """-> (model bytes without header fixups, rcodes)"""
    lut = np.zeros((16, 256), np.int64)
    subs = []
    rcodes = np.zeros(lens.shape, np.int64)
    for t in range(16):
        submap = {}
        for sym in range(NS):
            l = int(lens[t, sym])
            if not l: continue
            rc = bitrev(int(codes[t, sym]), l); rcodes[t, sym] = rc
            if sym < 256: ent = lambda ll: ll | sym << 5
            elif sym < 256 + NR: ent = lambda ll: 0x8000 | ll | (sym - 256) << 5
            else: ent = lambda ll: 0xA000 | ll | (sym - 256 - NR) << 5
            if l <= K:
                for j in range(1 << (K - l)): lut[t, rc | j << l] = ent(l)
            else:
                assert l - K <= S
                p = rc & 255
                if p not in submap:
                    submap[p] = len(subs); subs.append(np.zeros(1 << S, np.int64))
                    off = submap[p] << S                       # byte offset / 2
                    assert off < 0x4000
                    lut[t, p] = 0xC000 | off
                st = subs[submap[p]]; hi = rc >> 8; ll = l - K
                for j in range(1 << (S - ll)): st[hi | j << ll] = ent(ll)
    runs = list(int(x) for x in RUNS) + [0, 0]
    m = struct.pack("<IIHH", MAGIC, 0, ((1 << S) - 1) << 1, 0) + struct.pack("<32H", *runs)
    m += struct.pack("<4096H", *[int(x) for x in lut.ravel()])
    for st in subs: m += struct.pack("<%dH" % (1 << S), *[int(x) for x in st])
    return m, rcodes


def build(cid, passes=6):
    t0 = time.time()
    n = NSP(os.path.join(A0, "SP_PL%02X.NSP" % cid)); n.decode_all()
    assert n.offs[0] == 16 and all(o % 4 == 0 for o in n.offs)
    T = n.tiles
    uniq = {}; order = []
    for t in T:
        k = (t.wb, t.raw)
        if k not in uniq: uniq[k] = len(order); order.append(t)
    data = [(np.frombuffer(t.raw, np.uint8).astype(np.int32), t.wb) for t in order]
    best = None
    for S in (2, 3, 4):
        limit = K + S
        lens = np.zeros((16, NS), np.uint8); lens[:, :256] = 7; lens[:, 256:] = 6
        choices = [np.zeros(len(d[0]), np.int32) for d in data]
        none = np.zeros(0, np.uint8); zc = np.zeros((16, NS), np.int64)
        for p in range(passes + 1):
            hist = np.zeros((16, NS), np.int64)
            for (Sy, W), ch in zip(data, choices):
                parse(Sy, W, lens, RUNS16, ch)
                walk(Sy, ch, RUNS16, hist, lens, zc, none)
            if p == passes: break
            lens = np.stack([hufflens(hist[t], limit) for t in range(16)])
        assert not ((hist > 0) & (lens == 0)).any()
        codes = canon(lens)[0]
        model, rcodes = make_model(lens, codes, S)
        out = np.zeros(1 << 17, np.uint8); h2 = np.zeros((16, NS), np.int64)
        sec2 = bytearray(model); uoff = []
        for (Sy, W), ch in zip(data, choices):
            # header nibble + codes: prepend the width code by emitting it as 4 raw bits
            m = walk_hdr(Sy, W, ch, RUNS16, lens, rcodes, out)
            uoff.append(len(sec2)); sec2 += out[:m].tobytes()
        sec2 += b"\0" * (4 + (-len(sec2) % 4))                # slack: the decoder reads up to 4 bytes ahead
        if best is None or len(sec2) < len(best[0]): best = (sec2, uoff, S, len(model), hist)
    sec2, uoff, S, mlen, hist = best
    struct.pack_into("<I", sec2, 4, len(sec2))
    sec1 = bytearray(n.sec[1])
    for t in T:
        struct.pack_into("<I", sec1, t.idx * 4, (t.word & ~0x3FFFFF) | uoff[uniq[(t.wb, t.raw)]])
    o1, o2 = n.offs[1], n.offs[2]; o3 = o2 + len(sec2)
    new = struct.pack("<4I", 16, o1, o2, o3) + n.sec[0] + bytes(sec1) + bytes(sec2) + n.sec[3]
    assert verify_bytes(new, n) == 0, "round trip failed"
    nsym = int(hist.sum()); raw = sum(len(t.raw) for t in T)
    st = dict(id=cid, old=len(n.d), new=len(new), old_sec2=n.sizes[2], new_sec2=len(sec2), model=mlen, S=S,
              streams=len(sec2) - mlen, tiles=len(T), uniq=len(order), other=len(new) - len(sec2), raw=raw,
              lit=int(hist[:, :256].sum()), upruns=int(hist[:, 256:256 + NR].sum()), repruns=int(hist[:, 256 + NR:].sum()),
              secs=time.time() - t0)
    return new, st


@nb.njit
def walk_hdr(S, W, choice, RUNS, lens, rcodes, out):
    n = len(S); i = 0; p = 0
    acc = (W >> 3) - 1; nb_ = 4
    while i < n:
        t = (S[i - 1] >> 4) if i else 15
        c = choice[i]
        if c == 0:
            sym = S[i]; i += 1
        else:
            sym = 255 + c; i += RUNS[(c - 1) % len(RUNS)]
        acc |= rcodes[t, sym] << nb_; nb_ += lens[t, sym]
        while nb_ >= 8:
            out[p] = acc & 255; p += 1; acc >>= 8; nb_ -= 8
    if nb_:
        out[p] = acc & 255; p += 1
    return p


def verify_bytes(new, orig):
    mem = np.frombuffer(new + b"\0" * 8, np.uint8)
    o1, o2, o3 = struct.unpack_from("<3I", new, 4)
    assert struct.unpack_from("<I", new, o2)[0] == MAGIC
    out = np.zeros(1 << 16, np.uint8); bad = 0
    orig.decode_all()
    for t in orig.tiles:
        w = struct.unpack_from("<I", new, o1 + 4 * t.idx)[0]
        assert w >> 22 == t.word >> 22
        nbytes = t.wb * t.h
        used = ref_decode(mem, o2 + (w & 0x3FFFFF), nbytes, o2, out)
        if out[:nbytes].tobytes() != t.raw: bad += 1
        assert o2 + (w & 0x3FFFFF) + used <= o3 + 4
    return bad


def _job(cid):
    new, st = build(cid)
    os.makedirs(OUTDIR, exist_ok=True)
    open(os.path.join(OUTDIR, "SP_PL%02X.NSP" % cid), "wb").write(new)
    return st


def main():
    args = sys.argv[1:]; cmd = args[0]
    ids = [int(x, 16) for x in args[1:]] or list(range(0x13))
    sp = os.path.join(OUTDIR, "stats.json")
    if cmd == "encode":
        from multiprocessing import Pool
        os.makedirs(OUTDIR, exist_ok=True)
        stats = json.load(open(sp)) if os.path.exists(sp) else {}
        with Pool(min(6, len(ids))) as p:
            for st in p.imap_unordered(_job, ids):
                stats["%02X" % st["id"]] = st
                print("PL%02X old %7d new %7d  streams %7d model %5d (S=%d)  per out byte: lit %.3f up %.3f rep %.3f  %.0fs" % (
                    st["id"], st["old"], st["new"], st["streams"], st["model"], st["S"], st["lit"] / st["raw"], st["upruns"] / st["raw"],
                    st["repruns"] / st["raw"], st["secs"]), flush=True)
        json.dump(stats, open(sp, "w"), indent=1)
    elif cmd == "verify":
        tot = 0
        for c in ids:
            new = open(os.path.join(OUTDIR, "SP_PL%02X.NSP" % c), "rb").read()
            o = NSP(os.path.join(A0, "SP_PL%02X.NSP" % c))
            bad = verify_bytes(new, o); tot += bad
            assert new[16:struct.unpack_from("<I", new, 4)[0]] == o.sec[0] and new[struct.unpack_from("<I", new, 12)[0]:] == o.sec[3]
            print("PL%02X tiles %5d mismatching %d  (sec0/sec3 identical)" % (c, len(o.tiles), bad), flush=True)
        print("TOTAL mismatching tiles:", tot)
    elif cmd == "table":
        stats = json.load(open(sp))
        print("char   old file  new file   streams  model+LUT  non-px")
        for k in sorted(stats):
            s = stats[k]
            print("PL%s  %8d  %8d  %7d  %6d  %6d" % (k, s["old"], s["new"], s["streams"], s["model"], s["other"]))
        n = len(stats); Sm = lambda f: sum(s[f] for s in stats.values())
        print("avg   %8d  %8d  %7d  %6d  %6d" % (Sm("old") // n, Sm("new") // n, Sm("streams") // n, Sm("model") // n, Sm("other") // n))


if __name__ == "__main__":
    main()
