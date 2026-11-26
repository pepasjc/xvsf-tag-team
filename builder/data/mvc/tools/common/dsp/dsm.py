"""DSM1: XVM1-class sprite codec for .DSP files (MSHvSF, MvC).  Same model as XvSF XVM1 (tools/nsp_mid.py):
byte symbols, canonical Huffman (max 12 bits), table chosen by a clustered (high nibble of the previous byte,
byte above) context, 6-bit primary LUT + canonical fallback, copy-from-above / repeat runs, escape.
Differences from XVM1:
  * magic 'DSM1'; the model sits at the start of the PIXEL section (DSP sec0) and tile offsets stay relative to it
  * a tile stream starts with one BYTE = row width in bytes (1..255; MvC tiles have any width), then the
    MSB-first code bits starting at the next byte
  * the tile table (DSP sec2) is rewritten: offsets only (kind 6: bits 0-21, kind 8: u24)
Tiles in `rle` keep their original RLE streams, stored after the DSM1 part (size field at +4 covers only the DSM1
part, so the dispatch sends them to the game's RLE decoder) - the "mid/fat" tier mechanism of XvSF.

sec0 layout: +0 u32 'DSM1' +4 u32 size of the DSM1 part +8 u16 fallback-record offset +10 u16 K
             +12 u16 RUNS[32]  +76 u8 map[4096]  +4172 s16 lut[K][64]  fallback records  long-code lists  streams

    python dsm.py encode GAME [ids hex..] [-k K]     -> games/GAME/work/dsp/dsm/<label>.DSP + stats.json
"""
import os, sys, struct, json, time
import numpy as np
import numba as nb
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(ROOT, "work", "nbcache"))
import dsp as D
import nsp_mid as XM                        # parse / acc / cluster / make_model (XvSF XVM1 encoder kernels)
from nsp_codec import RUNS, NR

MAGIC = 0x314D5344                          # 'DSM1'
R = RUNS.astype(np.int64)
ESC, NS, KB = XM.ESC, XM.NS, XM.KB


@nb.njit
def emit(S, W, tab, choice, RUNS, lens, codes, out):
    n = len(S); i = 0; p = 0; NRr = len(RUNS)
    out[0] = W; p = 1
    acc_ = 0; nb_ = 0
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
    """Exact model of the MIPS decoder dsm_dec (common/dsp/dsmdec.S): 32-bit MSB-first buffer, c = bits
    available - 16, 16-bit refills; returns source bytes consumed (incl. the width byte)."""
    M = 0xFFFFFFFF
    fbo = model + (np.int64(mem[model + 8]) | (np.int64(mem[model + 9]) << 8))
    W = np.int64(mem[src])
    buf = (np.int64(mem[src + 1]) << 24) | (np.int64(mem[src + 2]) << 16) | (np.int64(mem[src + 3]) << 8) | np.int64(mem[src + 4])
    src0 = src; src += 5
    c = 16
    P = 255; ph = 15 << 8
    o = 0
    while o < n:
        U = np.int64(out[o - W]) if o >= W else 255
        t = np.int64(mem[model + 76 + (ph | U)])
        a = model + 4172 + (t << 7) + ((buf >> 25) & 0x7e)
        e = np.int64(mem[a]) | (np.int64(mem[a + 1]) << 8)
        if (e & 0xC000) == 0xC000:
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
            if e & 0x1000:
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


def build_model(data, K=64, pen=0, passes=4):
    """data: [(S int32 array, ctx, W)] -> (model bytes, tmap, lens, codes, choices)"""
    tmap = np.zeros(4096, np.int32)
    lens = np.zeros((1, NS), np.uint8); lens[0, :256] = 7; lens[0, 256:ESC] = 6; lens[0, ESC] = 8
    ch = [np.zeros(len(d[0]), np.int32) for d in data]
    for p in range(passes + 1):
        hist = np.zeros((4096, NS), np.int64)
        for (S, c, W), cc in zip(data, ch):
            XM.parse(S, W, tmap[c], lens, R, cc, pen); XM.acc(S, c, cc, R, hist)
        if p == passes: break
        tmap, lens = XM.cluster(hist, K)
    th = np.zeros((lens.shape[0], NS), np.int64); np.add.at(th, tmap, hist)
    assert not ((th[:, 256:ESC] > 0) & (lens[:, 256:ESC] == 0)).any() and (lens[:, ESC] > 0).all() and (lens[:, ESC] <= 8).all()
    model, codes = XM.make_model(tmap, lens)
    model = bytearray(model); struct.pack_into("<I", model, 0, MAGIC)
    return bytes(model), tmap, lens, codes, ch, hist


def encode(x, K=64, pen=0, rle=(), passes=4):
    """x: dsp.DSP.  -> (new DSP bytes, stats)"""
    t0 = time.time()
    x.decode_all(); T = x.tiles; rle = set(rle)
    uniq = {}; order = []
    for t in T:
        k = (t.wb, t.raw)
        if t.idx not in rle and k not in uniq: uniq[k] = len(order); order.append(t)
    assert all(t.wb < 256 for t in order)
    data = [XM.tile_ctx(t.raw, t.wb) + (t.wb,) for t in order]
    model, tmap, lens, codes, ch, hist = build_model(data, K, pen, passes)
    out = np.zeros(1 << 17, np.uint8)
    sec0 = bytearray(model); uoff = []
    for (S, c, W), cc in zip(data, ch):
        m = emit(S, W, tmap[c], cc, R, lens, codes, out)
        uoff.append(len(sec0)); sec0 += out[:m].tobytes()
    sec0 += b"\0" * (4 + (-len(sec0) % 4))
    struct.pack_into("<I", sec0, 4, len(sec0))
    dsm_end = len(sec0)
    roff = {}; done = {}
    for t in T:
        if t.idx in rle:
            st = x.sec[0][t.off:t.off + t.clen + 1]          # +1: an odd literal reads one byte past the stream
            if st not in done: done[st] = len(sec0); sec0 += st
            roff[t.idx] = done[st]
    sec0 += b"\0" * (-len(sec0) % 4)
    return assemble(x, sec0, {t.idx: (roff[t.idx] if t.idx in rle else uoff[uniq[(t.wb, t.raw)]]) for t in T}), dict(
        old=len(x.d), new=None, old_pix=x.sizes[0], new_pix=len(sec0), model=len(model), tables=int(lens.shape[0]),
        dsm_part=dsm_end, rle_tiles=len(rle), tiles=len(T), uniq=len(order), raw=sum(t.n for t in T), secs=time.time() - t0)


def assemble(x, sec0, offs):
    """new file: header, new sec0, sec1, rewritten sec2 (tile table), sec3"""
    s2 = bytearray(x.sec[2])
    for t in x.tiles:
        o = offs[t.idx]
        if x.kind == 6:
            assert o < (1 << 22)
            struct.pack_into("<I", s2, 4 * t.idx, (t.word & ~0x3FFFFF) | o)
        else:
            assert o < (1 << 24)
            s2[5 * t.idx:5 * t.idx + 3] = bytes((o & 255, o >> 8 & 255, o >> 16))
    o1 = 0x14 + len(sec0); o2 = o1 + len(x.sec[1]); o3 = o2 + len(s2)
    pad1 = (-o2) % 4 if x.kind == 6 else 0                      # keep the u32 tile table aligned
    o2 += pad1; o3 += pad1
    sec1 = x.sec[1] + b"\0" * pad1
    return struct.pack("<5I", x.kind, 0x14, o1, o2, o3) + bytes(sec0) + sec1 + bytes(s2) + x.sec[3]


def verify(new, orig):
    """decode every tile of `new` with the models (DSM1 part: ref_decode, behind it: RLE) -> mismatching tiles"""
    y = D.DSP(new); orig.decode_all()
    s0 = y.sec[0]; mem = np.frombuffer(s0 + b"\0" * 16, np.uint8)
    assert struct.unpack_from("<I", s0, 0)[0] == MAGIC
    end = struct.unpack_from("<I", s0, 4)[0]
    out = np.zeros(1 << 17, np.uint8); bad = 0
    for t, u in zip(orig.tiles, y.tiles):
        assert (u.wb, u.h) == (t.wb, t.h)
        if u.off >= end:
            got = D.rle_decode(s0, u.off, t.n)[0]
        else:
            used = ref_decode(mem, u.off, t.n, 0, out); got = out[:t.n].tobytes()
            assert u.off + used <= end
        bad += got != t.raw
    assert y.sec[1][:len(orig.sec[1])] == orig.sec[1] and y.sec[3] == orig.sec[3]
    return bad


def hot_tiles(game, label, x, cap):
    """tiles to keep as stock RLE: most decoded bytes per stored RLE byte first, until `cap` bytes of RLE streams
    (play volume from games/G/work/dsp/hot/<label>.json, common/dsp/hot.py).  -> set of tile indices, or None"""
    p = os.path.join(ROOT, "games", game, "work", "dsp", "hot", label + ".json")
    if not cap or not os.path.exists(p): return None
    x.decode_all(); v = json.load(open(p))
    items = sorted(((vol / (x.tiles[int(k)].clen + 1), int(k)) for k, vol in v.items()), reverse=True)
    sel = set(); used = 0; seen = {}
    for r, k in items:
        t = x.tiles[k]; key = (t.off, t.clen)
        c = 0 if key in seen else t.clen + 1
        if used + c > cap: continue
        used += c; seen[key] = 1; sel.add(k)
    for t in x.tiles:                                  # every alias of a chosen stream too
        if (t.off, t.clen) in seen: sel.add(t.idx)
    return sel


def _job(a):
    game, cid, K, outdir = a[:4]; cap = a[4] if len(a) > 4 else 0
    b, base, label = D.char_dsp(game, cid)
    x = D.DSP(b, base)
    rle = hot_tiles(game, label, x, cap)
    if cap and rle is None: return dict(label=label, skipped=True)
    new, st = encode(x, K, rle=rle or ())
    assert verify(new, x) == 0
    st.update(new=len(new), id=cid, label=label)
    open(os.path.join(outdir, label + ".DSP"), "wb").write(new)
    return st


def main():
    a = sys.argv[1:]
    K = 64; cap = 0
    if "-k" in a: i = a.index("-k"); K = int(a[i + 1]); del a[i:i + 2]
    if "--hot" in a: i = a.index("--hot"); cap = int(a[i + 1]) * 1024; del a[i:i + 2]
    cmd, game = a[0], a[1]
    ids = [int(v, 16) for v in a[2:]] or D.char_ids(game)
    outdir = os.path.join(ROOT, "games", game, "work", "dsp", "dsm" + ("_hot%d" % (cap // 1024) if cap else ""))
    os.makedirs(outdir, exist_ok=True)
    sp = os.path.join(outdir, "stats.json")
    if cmd == "encode":
        from multiprocessing import Pool
        stats = json.load(open(sp)) if os.path.exists(sp) else {}
        with Pool(min(8, len(ids))) as p:
            for st in p.imap_unordered(_job, [(game, c, K, outdir, cap) for c in ids]):
                if st.get("skipped"): continue
                stats[st["label"]] = st
                print("%s old %7d new %7d  pix %7d -> %7d (%.3f)  model %5d  rle tiles %d  %.0fs" % (st["label"], st["old"], st["new"], st["old_pix"],
                      st["new_pix"], st["new_pix"] / st["old_pix"], st["model"], st["rle_tiles"], st["secs"]), flush=True)
        json.dump(stats, open(sp, "w"), indent=1)


if __name__ == "__main__":
    main()
