"""DSX: DSH1 files with a 4-bit lookup table per Huffman table.  Same magic 'DSH1' and dispatch route; the classes field
(+8) gets bit 15 set.  Decoder common/dsp/dsxdec.S decodes BOTH formats (plain DSH1 bit-serially from level 1 with a
16-bit refill, DSX via the LUT), so one build can mix DSH1 and DSX tiers (mktag.py tier names dsx*).

Model layout:  +0 'DSH1' +4 size +8 classes +10 tables T  +12 tofs[T]  LUT array 16 * T  map1[4096]  map2[16 * classes]
records.  LUT of table t at map1 - 16 * (t + 1) (entry for the next 4 code bits: symbol | (length - 1) << 6 for codes
of <= 4 bits, 0xff = longer); record = K4 S4 cnt[12] .. cnt[1] symbols[nsym] (tofs[t] -> symbols), K4 = sum cnt[k]
<< (4 - k), S4 = sum cnt[k] (k <= 4).  map1 / map2 / the tile streams are unchanged; everything after the model moves
by delta (a multiple of 4): the +4 size field and every tile offset (sec2) are rewritten.
Decoder output is byte-identical (dsmtest.py mvc dsh with DSH_SRC=dsxdec.S DSMDIR=<converted dir>).

    python dsx.py conv GAME SRCDIR DSTDIR [ids..]     e.g. conv mvc games/mvc/work/dsp/dsh games/mvc/work/dsp/dsx
                                                       (directories relative to the repository root, or absolute)
"""
import os, sys, struct, glob, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import dsp as D
import dsm as DM

MAGIC = 0x31485344
O_TOFS = 12
MAXLEN = 12


def records(s0):
    """-> classes, tables, tofs list, [(cnt[1..maxlen], symbols)], model end (offset after the last record)"""
    assert struct.unpack_from("<I", s0, 0)[0] == MAGIC
    classes, tables = struct.unpack_from("<HH", s0, 8)
    tofs = list(struct.unpack_from("<%dH" % tables, s0, O_TOFS))
    m1 = O_TOFS + 2 * tables
    rec_lo = m1 + 4096 + 16 * classes
    recs = []
    for t, o in enumerate(tofs):
        cnt = []; kraft = 0.0; n = 0
        for l in range(1, MAXLEN + 1):
            c = s0[o - l]; cnt.append(c); n += c; kraft += c / (1 << l)
            if kraft >= 1.0 - 1e-12: break
        recs.append((cnt, bytes(s0[o:o + n])))
    # records are contiguous in table order: check the maxlen found by the Kraft sum against that layout
    order = sorted(range(tables), key=lambda t: tofs[t])
    p = rec_lo
    for t in order:
        cnt, sym = recs[t]
        assert tofs[t] - len(cnt) >= p, ("record overlap", t)
        p = tofs[t] + len(sym)
    return classes, tables, tofs, recs, rec_lo, p


def lut(cnt, sym):
    """-> (LUT 16 bytes, K4, S4)"""
    k4 = sum(cnt[k - 1] << (4 - k) for k in range(1, min(4, len(cnt)) + 1))
    s4 = sum(cnt[:4])
    out = []
    for p in range(16):
        d = 0; sp = 0; e = 0xFF
        for l in range(1, 5):
            d = d * 2 + (p >> (4 - l) & 1)
            c = cnt[l - 1] if l <= len(cnt) else 0
            if d < c:
                e = sym[sp + d] | (l - 1) << 6; break
            d -= c; sp += c
        if e != 0xFF: assert sym[sp + d] < 63
        out.append(e)
    assert all((e == 0xFF) == (p >= k4) for p, e in enumerate(out)), (cnt, k4)
    assert k4 <= 16 and s4 <= 255
    return bytes(out), k4, s4


def convert(data):
    """DSH1 DSP bytes (kind 8 or 6) -> DSX bytes"""
    x = D.DSP(data)
    s0 = x.sec[0]
    classes, tables, tofs, recs, rec_lo, rec_hi = records(s0)
    dsh_size = struct.unpack_from("<I", s0, 4)[0]
    assert all(t.off >= rec_hi for t in x.tiles), "a tile stream inside the model"
    m1 = O_TOFS + 2 * tables
    model = bytearray(s0[:m1]) + bytes(16 * tables) + s0[m1:rec_lo]
    ntofs = [0] * tables
    for t in sorted(range(tables), key=lambda t: tofs[t]):
        cnt, sym = recs[t]
        lt, k4, s4 = lut(cnt, sym)
        lo = m1 + 16 * (tables - 1 - t)
        model[lo:lo + 16] = lt
        model += bytes((k4, s4)) + bytes(reversed(cnt + [0] * (MAXLEN - len(cnt)))) + sym
        ntofs[t] = len(model) - len(sym)
    model += bytes((-(len(model) - rec_hi)) % 4)              # delta multiple of 4: alignment of what follows kept
    delta = len(model) - rec_hi
    struct.pack_into("<%dH" % tables, model, O_TOFS, *ntofs)
    struct.pack_into("<H", model, 8, classes | 0x8000)       # format flag for dsxdec.S (dshdec.S ignores classes)
    assert len(model) < 0x10000
    sec0 = bytearray(model) + s0[rec_hi:]
    struct.pack_into("<I", sec0, 4, dsh_size + delta)
    offs = {t.idx: t.off + delta for t in x.tiles}
    out = DM.assemble(x, bytes(sec0), offs)
    y = D.DSP(out)
    assert y.sec[1] == x.sec[1] and y.sec[3] == x.sec[3]
    return out, delta


def conv_dir(game, src, dst, ids=None):
    src = src if os.path.isabs(src) else os.path.join(ROOT, src)
    dst = dst if os.path.isabs(dst) else os.path.join(ROOT, dst)
    os.makedirs(dst, exist_ok=True)
    st = {}
    for f in sorted(glob.glob(os.path.join(src, "PL*_10.DSP"))):
        l = os.path.basename(f)[:-4]
        if ids and int(l[2:4], 16) not in ids: continue
        out, delta = convert(open(f, "rb").read())
        open(os.path.join(dst, l + ".DSP"), "wb").write(out)
        st[l] = dict(delta=delta, size=len(out))
        print("%s %s +%d B" % (os.path.basename(dst), l, delta), flush=True)
    json.dump(st, open(os.path.join(dst, "dsx.json"), "w"), indent=1)
    return st


if __name__ == "__main__":
    if sys.argv[1] == "conv":
        conv_dir(sys.argv[2], sys.argv[3], sys.argv[4], [int(v, 16) for v in sys.argv[5:]] or None)


def verify_dir(game, src, dst, ids=None):
    """every tile: the LUT decoder (dsxdec.S) on the converted file vs the DSH1 decoder (dshdec.S) on the source file,
    output + 64 bytes (dsmtest Run harness, unicorn) -> mismatches"""
    os.environ.setdefault("DSA_AT", "0x801fd900")
    import dsmtest as T
    src = src if os.path.isabs(src) else os.path.join(ROOT, src)
    dst = dst if os.path.isabs(dst) else os.path.join(ROOT, dst)
    os.environ["DSH_SRC"] = "dshdec.S"; old = T.Run(game, True)
    os.environ["DSH_SRC"] = "dsxdec.S"; new = T.Run(game, True)
    tot = bad = 0
    for f in sorted(glob.glob(os.path.join(src, "PL*_10.DSP"))):
        l = os.path.basename(f)[:-4]
        if ids and int(l[2:4], 16) not in ids: continue
        a, b = open(f, "rb").read(), open(os.path.join(dst, l + ".DSP"), "rb").read()
        x, y = D.DSP(a), D.DSP(b)
        b0 = old.load(a); b1 = new.load(b); nb = 0
        for t, u in zip(x.tiles, y.tiles):
            assert (t.wb, t.h, t.flag) == (u.wb, u.h, u.flag)
            nb += 1; bad += old.call(b0 + t.off, t.n) != new.call(b1 + u.off, t.n)
        tot += nb
        print("%s %s tiles %5d mismatching so far %d" % (os.path.basename(dst), l, nb, bad), flush=True)
    print("TOTAL %s tiles %d mismatching %d" % (dst, tot, bad))
    return bad


def verify_plain(game, src, ids=None):
    """plain DSH1 files: dsxdec.S vs dshdec.S on the same file, every tile, output + 64 bytes -> mismatches"""
    os.environ.setdefault("DSA_AT", "0x801fd900")
    import dsmtest as T
    src = src if os.path.isabs(src) else os.path.join(ROOT, src)
    os.environ["DSH_SRC"] = "dshdec.S"; old = T.Run(game, True)
    os.environ["DSH_SRC"] = "dsxdec.S"; new = T.Run(game, True)
    tot = bad = 0
    for f in sorted(glob.glob(os.path.join(src, "PL*_10.DSP"))):
        l = os.path.basename(f)[:-4]
        if ids and int(l[2:4], 16) not in ids: continue
        a = open(f, "rb").read(); x = D.DSP(a)
        b0 = old.load(a); b1 = new.load(a); nb = 0
        for t in x.tiles:
            nb += 1; bad += old.call(b0 + t.off, t.n) != new.call(b1 + t.off, t.n)
        tot += nb
    print("TOTAL plain %s tiles %d mismatching %d" % (src, tot, bad))
    return bad


def build(game="mvc", addr=0x801fd400):
    """games/GAME/work/dsp/dsx/dsxdec.bin (position-independent; checked at two link addresses)"""
    os.environ["DSH_SRC"] = "dsxdec.S"
    import dsh as H
    a, _ = H.decoder(game, addr); b, _ = H.decoder(game, addr + 0x1000)
    assert a == b, "dsxdec.S is not position-independent"
    p = os.path.join(ROOT, "games", game, "work", "dsp", "dsx"); os.makedirs(p, exist_ok=True)
    open(os.path.join(p, "dsxdec.bin"), "wb").write(a)
    print("dsxdec.bin %d bytes" % len(a))
    return a


if __name__ == "__main__" and sys.argv[1] == "verify":
    sys.exit(1 if verify_dir(sys.argv[2], sys.argv[3], sys.argv[4], [int(v, 16) for v in sys.argv[5:]] or None) else 0)
if __name__ == "__main__" and sys.argv[1] == "plain":
    sys.exit(1 if verify_plain(sys.argv[2], sys.argv[3], [int(v, 16) for v in sys.argv[4:]] or None) else 0)
if __name__ == "__main__" and sys.argv[1] == "build":
    build(*(sys.argv[2:3] or ["mvc"]))
