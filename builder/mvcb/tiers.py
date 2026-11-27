"""Recipes for the MvC sprite tier files: what the builder ships instead of the files (which are made of the game's
pixels).

A tier file is a kind-8 DSP (header, sec0 pixels, sec1 frame groups, sec2 tile table, sec3 animation records).  Its
recipe holds only OUR part and references:
  * the codec model (the code tables / context maps / probabilities our encoder chose; DSH1, DSM1, DSR1),
  * per coded tile, where its content comes from: the tile of the same index in the base DSP (the stock file or the
    half-res effects file the builder made from it), zeros (frames our cut tiers removed), or another tile of the base,
  * the other sections as byte diffs against the base DSP (copy runs at any offset + our literal bytes),
  * the layout numbers (padding, tiles kept as stock RLE streams).
build() re-emits every tile stream with the encoder's own emission step (mvcb/codecs.py) and assembles the file.

    describe(T, sources, base)  -> recipe (JSON-able), raises when T is not reproducible from the sources
    build(recipe, sources)      -> bytes
"""
import hashlib, struct
from mvcb import codecs as C

MINRUN = 8


# ------------------------------------------------------------------------------------------------ byte diffs
class Index:
    """8-byte windows of the source buffers -> first positions (greedy longest-match diff)"""

    def __init__(self, sources):
        self.src = sources; self.idx = {}
        for name, b in sources.items():
            d = self.idx
            for i in range(0, len(b) - 7):
                k = b[i:i + 8]
                if k not in d: d[k] = [(name, i)]
                elif len(d[k]) < 8: d[k].append((name, i))

    def diff(self, t):
        t = bytes(t); out = []; lit = bytearray(); p = 0; n = len(t)
        while p < n:
            best = None
            if p + 8 <= n:
                for name, o in self.idx.get(t[p:p + 8], ()):
                    s = self.src[name]; k = 8
                    while p + k < n and o + k < len(s) and t[p + k] == s[o + k]: k += 1
                    if best is None or k > best[2]: best = (name, o, k)
            if best is None or best[2] < MINRUN:
                lit.append(t[p]); p += 1; continue
            if lit: out.append(lit.hex()); lit = bytearray()
            out.append(list(best)); p += best[2]
        if lit: out.append(lit.hex())
        assert undiff(out, self.src) == t
        return out


def undiff(segs, sources):
    out = bytearray()
    for s in segs:
        if isinstance(s, str): out += bytes.fromhex(s)
        else:
            b = sources[s[0]][s[1]:s[1] + s[2]]
            if len(b) != s[2]: raise ValueError("diff: %s too short" % s[0])
            out += b
    return bytes(out)


def literal_bytes(segs): return sum(len(s) // 2 for s in segs if isinstance(s, str))


# ------------------------------------------------------------------------------------------------ frame groups (sec1)
# Our frame cuts rewrite a group IN PLACE (same byte span): the 4 header bytes after the part count stay, the parts
# become those of another group of the base (same values, coordinates possibly in wider modes), zero bytes after them.
# Recipe per rewritten group: [group, source group, modes (hex nibble per part: xm << 2 | ym), header hex or ""].
def _s16(v): return v - 65536 if v & 0x8000 else v


def parse_part(d, p):
    r = d[p:p + 8] + bytes(8)
    v = r[1] | r[2] << 8; xm = (v >> 12) & 3; ym = v >> 14
    sm = lambda b, m: -b if m == 2 else ((b - 256 if b & 0x80 else b) if m == 0 else b)
    if xm == 3 and ym == 3: x, y, n = _s16(r[4] | r[5] << 8), _s16(r[6] | r[7] << 8), 8
    elif xm == 3: x, y, n = _s16(r[4] | r[5] << 8), sm(r[6], ym), 7
    elif ym == 3: x, y, n = sm(r[4], xm), _s16(r[5] | r[6] << 8), 7
    else: x, y, n = sm(r[4], xm), sm(r[5], ym), 6
    return (r[0], v & 0xFFF, r[3], x, y), (xm, ym), n


def part_bytes(val, xm, ym):
    flags, tile, b3, x, y = val
    v = tile | (xm << 12) | (ym << 14)
    def one(q, m):
        if m == 3: return struct.pack("<h", q)
        if m == 2: return bytes([(-q) & 255])
        if m == 1: return bytes([q & 255])
        return struct.pack("<b", q)
    return bytes([flags, v & 255, v >> 8, b3]) + one(x, xm) + one(y, ym)


def groups(s1):
    """the base's groups: [(start, end, header, [values])] (sequential parse of a stock sec1)"""
    p = 0; out = []
    while p + 6 <= len(s1):
        cnt = s1[p] | s1[p + 1] << 8; st = p; p += 6; vals = []
        for k in range(cnt):
            v, m, n = parse_part(s1, p); vals.append(v); p += n
        if p > len(s1): break
        out.append([st, p, s1[st + 2:st + 6], tuple(vals)])
    for i in range(len(out) - 1): out[i][1] = out[i + 1][0]
    return out


def sec1_groups(b1, t1):
    if len(b1) != len(t1): return None
    G = groups(b1)
    if not G: return None
    end = G[-1][1]
    if t1[end:] != b1[end:] or t1[:G[0][0]] != b1[:G[0][0]]: return None
    byval = {}
    for j, g in enumerate(G): byval.setdefault(g[3], j)
    ops = []
    for j, (st, en, hdr, vals) in enumerate(G):
        span = t1[st:en]
        if span == b1[st:en]: continue
        cnt = span[0] | span[1] << 8; p = 6; tv = []; modes = ""
        for k in range(cnt):
            if p >= len(span): return None
            v, m, n = parse_part(span, p); tv.append(v); modes += "%x" % (m[0] << 2 | m[1]); p += n
        if p > len(span) or any(span[p:]): return None
        k = byval.get(tuple(tv))
        if k is None: return None
        ops.append([j, k, modes, "" if span[2:6] == hdr else span[2:6].hex()])
    assert sec1_build(b1, ops) == t1
    return ops


def sec1_build(b1, ops):
    G = groups(b1); s = bytearray(b1)
    for j, k, modes, hdr in ops:
        st, en, h, _ = G[j]; vals = G[k][3]
        body = b"".join(part_bytes(v, int(m, 16) >> 2, int(m, 16) & 3) for v, m in zip(vals, modes))
        span = struct.pack("<H", len(vals)) + (bytes.fromhex(hdr) if hdr else h) + body
        assert len(span) <= en - st, "group %d: rewritten parts do not fit" % j
        s[st:en] = span + bytes(en - st - len(span))
    return bytes(s)


# ------------------------------------------------------------------------------------------------ tile contents
_CC = {}
_EC = {}


def contents(codec, x):
    """{tile idx: content} of the base DSP x (DSPX): DSH1 = written bytes (with the stock decoder's overrun), else raw.
    (2026-11-26) memoised per (codec, base bytes): many tiers share a base; callers get a copy of the dict"""
    k = (codec, hashlib.sha1(bytes(x.d)).digest(), len(x.tiles))
    if k not in _CC:
        if len(_CC) >= 48: _CC.pop(next(iter(_CC)))
        _CC[k] = _contents(codec, x)
    return dict(_CC[k])


def _contents(codec, x):
    s0x = x.d[0x14:]
    if codec == "DSH1":
        return {t.idx: C.rle_written(s0x, t.off, t.n)[0] for t in x.tiles}
    return {t.idx: C.rle_raw(s0x, t.off, t.n) for t in x.tiles}


def _key(codec, t, c): return (t.wb, t.n, c) if codec == "DSH1" else (t.wb, c)


def describe(T, sources, base, codec_check=True):
    """T: the tier file bytes; sources {name: bytes} (DSP files; base = the name of the DSP the tier was encoded from)"""
    x = C.DSPX(T); s0 = x.sec[0]
    cod = C.codec(s0)
    B = C.DSPX(sources[base])
    r = dict(codec=cod, base=base, ntiles=len(x.tiles))
    ix = Index(sources)
    if cod == "RLE":
        r.update(sec0=ix.diff(s0), offs=[t.off for t in x.tiles])
    else:
        model, M = C.MODEL[cod](s0)
        size = M["size"]
        dec = C.DECODE[cod](s0, x.tiles, size)
        bc = contents(cod, B)
        bt = {t.idx: t for t in B.tiles}
        byc = {}
        for t in B.tiles:
            byc.setdefault(_key(cod, t, bc[t.idx]), t.idx)
        ops = []
        for t in x.tiles:
            if t.idx not in dec: ops.append(None); continue
            c = dec[t.idx]
            if t.idx in bc and bc[t.idx] == c and bt[t.idx].wb == t.wb: ops.append(0)
            elif not any(c): ops.append(["z", len(c)])
            elif _key(cod, t, c) in byc: ops.append(["t", byc[_key(cod, t, c)]])
            else:
                raise ValueError("tile %d (%d x %d): content not found in the base %s" % (t.idx, t.wb, t.h, base))
        r.update(model=model.hex())
        # emitted part: streams in first-occurrence order of the unique contents
        streams, L = _emit(cod, M, x.tiles, dec, model)
        if s0[:L] != streams:
            j = next(i for i in range(min(L, len(streams))) if s0[i] != streams[i])
            raise ValueError("re-emitted streams differ from the tier file at byte %d (of %d)" % (j, L))
        rle = [(t.off - size) if t.idx not in dec else None for t in x.tiles]
        reg, roff = region_rule(B, x.tiles, rle)
        if reg + bytes(-len(reg) % 4) == s0[size:] and all(o is None or o == roff[i] for i, o in enumerate(rle)):
            region = "rule"; rle = [None if o is None else 1 for o in rle]
        else: region = ix.diff(s0[size:])
        r.update(ops=ops, pad=s0[L:size].hex(), region=region, rle=rle)
    # tile table without the offsets
    def strip(y): return b"".join(bytes(3) + t.ent[3:] for t in y.tiles) + y.tail2
    tsrc = {"T:" + base: strip(B)}
    r["sec2"] = Index(tsrc).diff(strip(x))
    g = sec1_groups(B.sec[1], x.sec[1])
    if g is not None: r["sec1g"] = g
    else: r["sec1"] = ix.diff(x.sec[1])
    r["sec3"] = ix.diff(x.sec[3])
    out = build(r, sources)
    assert out == T, "recipe does not rebuild the tier file"
    return r


def region_rule(B, tiles, rle):
    """the tiles kept as stock RLE: their streams from the base (+1 byte: an odd literal reads one past the stream),
    deduplicated, in tile order (dsh.encode / dsm.encode) -> (bytes, {idx: offset in the region})"""
    s0x = B.d[0x14:]; out = bytearray(); done = {}; roff = {}
    for t in tiles:
        if rle[t.idx] is None: continue
        bt = B.tiles[t.idx]
        st = s0x[bt.off:bt.off + C.rle_written(s0x, bt.off, bt.n)[1] + 1]
        if st not in done: done[st] = len(out); out += st
        roff[t.idx] = done[st]
    return bytes(out), roff


def _emit(cod, M, tiles, cont, model):
    """sec0 head: model + the unique tiles' streams -> (bytes, length); offsets in M['_off'] by tile idx"""
    seen = {}; order = []; offs = {}
    for t in tiles:
        if t.idx not in cont: continue
        c = cont[t.idx]; k = _key(cod, t, c)
        if k not in seen: seen[k] = len(order); order.append((t.wb, t.n, c))
        offs[t.idx] = seen[k]
    # (2026-11-26) a tile's stream depends only on (codec, model, pen, wb, n, content): tiers of one character share
    # most tiles, so the streams are memoised across build() calls and only the new ones are encoded
    pen = M.get("pen", 0) if cod == "DSM1" else None
    ck = (cod, bytes(model), pen)
    if ck not in _EC:
        if len(_EC) >= 64: _EC.pop(next(iter(_EC)))
        _EC[ck] = {}
    memo = _EC[ck]
    need = [o for o in order if o not in memo]
    if need:
        got = C.BATCH[cod](M, need, pen) if cod == "DSM1" else C.BATCH[cod](M, need)
        for o, st in zip(need, got): memo[o] = st
    streams = [memo[o] for o in order]
    sec0 = bytearray(model); at = []
    for st in streams: at.append(len(sec0)); sec0 += st
    M["_off"] = {i: at[j] for i, j in offs.items()}
    return bytes(sec0), len(sec0)


def build(r, sources):
    B = C.DSPX(sources[r["base"]])
    bt = {t.idx: t for t in B.tiles}
    def strip(y): return b"".join(bytes(3) + t.ent[3:] for t in y.tiles) + y.tail2
    s2 = bytearray(undiff(r["sec2"], {"T:" + r["base"]: strip(B)}))
    n = r["ntiles"]
    tiles = []
    for i in range(n):
        e = s2[5 * i:5 * i + 5]; t = C.Tile(); t.idx = i; t.flag = e[3] >> 7; t.wb = e[3] & 0x7F
        t.h = e[4] & 0x7F if t.flag else e[4]; tiles.append(t)
    if r["codec"] == "RLE":
        sec0 = undiff(r["sec0"], sources); offs = r["offs"]
    else:
        model = bytes.fromhex(r["model"])
        M = C.MODEL[r["codec"]](model + bytes(64))[1]
        bc = None; cont = {}
        for t, op in zip(tiles, r["ops"]):
            if op is None: continue
            if op == 0 or (isinstance(op, list) and op[0] == "t"):
                if bc is None: bc = contents(r["codec"], B)
                cont[t.idx] = bc[t.idx if op == 0 else op[1]]
            else: cont[t.idx] = bytes(op[1])
        head, L = _emit(r["codec"], M, tiles, cont, model)
        sec0 = bytearray(head) + bytes.fromhex(r["pad"])
        size = len(sec0)
        struct.pack_into("<I", sec0, 4, size)
        if r["region"] == "rule":
            reg, roff = region_rule(B, tiles, r["rle"])
            sec0 += reg + bytes(-len(reg) % 4)
            offs = [M["_off"][t.idx] if r["rle"][t.idx] is None else size + roff[t.idx] for t in tiles]
        else:
            sec0 += undiff(r["region"], sources)
            offs = [M["_off"][t.idx] if r["rle"][t.idx] is None else size + r["rle"][t.idx] for t in tiles]
    for i, o in enumerate(offs):
        s2[5 * i:5 * i + 3] = bytes((o & 255, o >> 8 & 255, o >> 16))
    sec1 = sec1_build(B.sec[1], r["sec1g"]) if "sec1g" in r else undiff(r["sec1"], sources)
    sec3 = undiff(r["sec3"], sources)
    o1 = 0x14 + len(sec0); o2 = o1 + len(sec1); o3 = o2 + len(s2)
    return struct.pack("<5I", 8, 0x14, o1, o2, o3) + bytes(sec0) + sec1 + bytes(s2) + sec3


def sha(b): return hashlib.sha1(b).hexdigest()
