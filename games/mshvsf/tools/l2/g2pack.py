"""L2-G (fx worker, rc4 lever L2): packed MvC frame-group section (DSP sec1), format "G2", lossless.

Stock sec1: groups back to back: u16 nparts, 4 header bytes, nparts part records (6-8 B, see common/dsp/dsp.py
parse_part), then a tail.  Groups are addressed by their byte offset (frame tables in the code part, u16).

G2 section (replaces sec1 in the DSP; the engine reaches it through the slot table 0x8009cf40 as before):
  +0   u32 magic 'G2PK'
  +4   u16 stock sec1 size, u16 number of groups
  +8   u16 offset of the anchor table, u16 offset of the group streams, u16 tail length, u16 0
  +16  tables: A[7] (flags, modes = xm | ym << 2) 2 B each, DT[7] s16 tile deltas, B3[31], X[31], Y[31] raw bytes (+1 pad)
  anchors: per 8 groups: u16 stock offset, u16 stream offset (relative to the streams start)
  streams: per group: u8 packed length (bytes after this byte; 0xff = escape: u16 length follows), u8 nparts,
           4 header bytes, then the bit stream (LSB first) of the parts, padded to a byte
  tail: the stock tail bytes
Part bit stream:
  A    3 bits: index 0-6 -> A[i]; 7 = escape: 8 bits flags, 2 bits xm, 2 bits ym
  tile 1 bit 0 = previous tile + 1 (first part: previous = 0); 1 + 3 bits: 0-6 = previous + DT[i], 7 = 12-bit literal
  b3   5 bits: 0-30 -> B3[i]; 31 = escape + 8 bits
  x    mode 3: 16 bits raw; else 5 bits: 0-30 -> X[i] (raw stored byte); 31 = escape + 8 bits
  y    same with Y
The unpacker rebuilds the exact stock bytes of a group (modes give the record layout).

    python g2pack.py test           all characters: pack, unpack every group, compare with the stock bytes
    python g2pack.py size [ids]     sizes per character
"""
import os, sys, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__)); GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "common", "dsp")]
import dsp as D
MAGIC = b"G2PK"
NA, ND, NB = 7, 7, 31
ANCH = 16                                # anchor every ANCH groups


def split(sec1, starts=None):
    """-> [(offset, nparts, header4, [part raw records])], tail bytes.  starts: the group offsets (from the uncut file
    of the same character: cut tiers set a group's nparts to 0 in place and leave its old part bytes unread)"""
    if starts is not None:
        out = []
        for p in starts:
            n = sec1[p] | sec1[p + 1] << 8; q = p + 6; parts = []
            for k in range(n):
                pt = D.parse_part(sec1, q); parts.append((pt, sec1[q:q + pt.size])); q += pt.size
            out.append((p, n, sec1[p + 2:p + 6], parts))
        return out, b""
    out = []; p = 0
    while p + 6 <= len(sec1):
        n = sec1[p] | sec1[p + 1] << 8; q = p + 6; parts = []
        for k in range(n):
            pt = D.parse_part(sec1, q); parts.append((pt, sec1[q:q + pt.size])); q += pt.size
        if q > len(sec1): break
        out.append((p, n, sec1[p + 2:p + 6], parts)); p = q
    return out, sec1[p:]


class Bits:
    def __init__(self): self.v = 0; self.n = 0
    def put(self, val, nb):
        assert 0 <= val < 1 << nb, (val, nb); self.v |= val << self.n; self.n += nb
    def bytes(self): return self.v.to_bytes((self.n + 7) // 8, "little")


def fields(rec):
    """raw part record -> (flags, xm, ym, tile, b3, xraw, yraw)"""
    v = rec[1] | rec[2] << 8; xm = (v >> 12) & 3; ym = v >> 14
    r = rec[4:]
    if xm == 3: xr = r[0] | r[1] << 8; r = r[2:]
    else: xr = r[0]; r = r[1:]
    yr = (r[0] | r[1] << 8) if ym == 3 else r[0]
    return rec[0], xm, ym, v & 0xFFF, rec[3], xr, yr


def build_record(fl, xm, ym, tile, b3, xr, yr):
    v = tile | xm << 12 | ym << 14
    out = bytes([fl, v & 0xff, v >> 8, b3])
    out += struct.pack("<H", xr) if xm == 3 else bytes([xr])
    out += struct.pack("<H", yr) if ym == 3 else bytes([yr])
    return out


def pack(sec1, starts=None):
    groups, tail = split(sec1, starts)
    cA, cD, cB, cX, cY = (collections.Counter() for _ in range(5))
    for off, n, hdr, parts in groups:
        pt = 0
        for p, rec in parts:
            fl, xm, ym, tile, b3, xr, yr = fields(rec)
            cA[(fl, xm | ym << 2)] += 1
            if tile - pt != 1: cD[tile - pt] += 1
            cB[b3] += 1
            if xm != 3: cX[xr] += 1
            if ym != 3: cY[yr] += 1
            pt = tile
    A = [k for k, _ in cA.most_common(NA)]; DT = [k for k, _ in cD.most_common(ND) if -32768 <= k < 32768]
    B3 = [k for k, _ in cB.most_common(NB)]; X = [k for k, _ in cX.most_common(NB)]; Y = [k for k, _ in cY.most_common(NB)]
    A += [(0, 0)] * (NA - len(A)); DT += [0x7fff] * (ND - len(DT))
    B3 += [0] * (NB - len(B3)); X += [0] * (NB - len(X)); Y += [0] * (NB - len(Y))
    iA = {k: i for i, k in enumerate(A)}; iD = {k: i for i, k in enumerate(DT) if k != 0x7fff}
    iB = {k: i for i, k in enumerate(B3[:len(cB)])}; iX = {k: i for i, k in enumerate(X[:len(cX)])}; iY = {k: i for i, k in enumerate(Y[:len(cY)])}
    tab = b"".join(bytes([f, m]) for f, m in A) + b"".join(struct.pack("<h", d) for d in DT) + bytes(B3) + bytes(X) + bytes(Y) + b"\0"
    streams = bytearray(); anchors = bytearray()
    for gi, (off, n, hdr, parts) in enumerate(groups):
        if gi % ANCH == 0: anchors += struct.pack("<HH", off, len(streams))
        b = Bits(); pt = 0
        for p, rec in parts:
            fl, xm, ym, tile, b3, xr, yr = fields(rec)
            m = xm | ym << 2
            if (fl, m) in iA: b.put(iA[(fl, m)], 3)
            else: b.put(7, 3); b.put(fl, 8); b.put(xm, 2); b.put(ym, 2)
            d = tile - pt
            if d == 1: b.put(0, 1)
            elif d in iD: b.put(1, 1); b.put(iD[d], 3)
            else: b.put(1, 1); b.put(7, 3); b.put(tile, 12)
            for val, idx, mode in ((b3, iB, 0), (xr, iX, xm), (yr, iY, ym)):
                if mode == 3: b.put(val, 16)
                elif val in idx: b.put(idx[val], 5)
                else: b.put(31, 5); b.put(val, 8)
            pt = tile
        assert n < 256
        body = (bytes([n]) if n < 127 else bytes([127, n])) + hdr + b.bytes()
        nxt = groups[gi + 1][0] if gi + 1 < len(groups) else None
        span = (nxt - off) if nxt is not None else 6 + sum(len(r) for p, r in parts)
        assert span >= 6 + sum(len(r) for p, r in parts)
        L = bytes([len(body)]) if len(body) < 255 else bytes([255]) + struct.pack("<H", len(body))
        S = bytes([span - 6]) if span - 6 < 255 else bytes([255]) + struct.pack("<H", span)
        streams += L + S + body
    hdr = MAGIC + struct.pack("<HH", len(sec1), len(groups))
    o_anch = 16 + len(tab); o_str = o_anch + len(anchors)
    hdr += struct.pack("<HHHH", o_anch, o_str, len(tail), 0)
    out = hdr + tab + anchors + bytes(streams) + tail
    out += bytes(-len(out) % 4)
    assert o_str + len(streams) < 0x10000
    return out


class Unpacker:
    """Python model of the MIPS unpacker: group(off) -> stock bytes"""
    def __init__(self, g):
        assert g[:4] == MAGIC
        self.g = g; self.size, self.ng = struct.unpack_from("<HH", g, 4)
        self.o_anch, self.o_str, self.tail = struct.unpack_from("<HHH", g, 8)
        t = 16
        self.A = [(g[t + 2 * i], g[t + 2 * i + 1]) for i in range(NA)]; t += 2 * NA
        self.DT = [struct.unpack_from("<h", g, t + 2 * i)[0] for i in range(ND)]; t += 2 * ND
        self.B3 = g[t:t + NB]; t += NB; self.X = g[t:t + NB]; t += NB; self.Y = g[t:t + NB]
        self.nanch = (self.ng + ANCH - 1) // ANCH

    def rec(self, p):
        """group record at p -> (body start, body length, stock span, next record)"""
        g = self.g; L = g[p]; p += 1
        if L == 255: L = g[p] | g[p + 1] << 8; p += 2
        S = g[p]; p += 1
        if S == 255: S = g[p] | g[p + 1] << 8; p += 2
        else: S += 6
        return p, L, S, p + L

    def find(self, off):
        """stream position of the group record at stock offset off: anchor binary search, then skip by spans"""
        lo, hi = 0, self.nanch - 1
        while lo < hi:
            m = (lo + hi + 1) // 2
            if struct.unpack_from("<H", self.g, self.o_anch + 4 * m)[0] <= off: lo = m
            else: hi = m - 1
        so, sp = struct.unpack_from("<HH", self.g, self.o_anch + 4 * lo)
        p = self.o_str + sp
        while so < off:
            b, L, S, p = self.rec(p); so += S
        assert so == off, ("offset not at a group start", off, so)
        return p

    def group(self, off):
        b, L, S, nx = self.rec(self.find(off))
        return self.decode(self.g[b:b + L])

    def decode(self, body):
        n = body[0]; h = 1
        if n == 127: n = body[1]; h = 2
        out = bytearray(struct.pack("<H", n) + body[h:h + 4])
        v = int.from_bytes(body[h + 4:], "little"); pos = 0
        def get(nb):
            nonlocal pos
            r = (v >> pos) & ((1 << nb) - 1); pos += nb; return r
        pt = 0
        for k in range(n):
            i = get(3)
            if i < 7: fl, m = self.A[i]; xm, ym = m & 3, m >> 2
            else: fl = get(8); xm = get(2); ym = get(2)
            if get(1) == 0: tile = pt + 1
            else:
                j = get(3); tile = get(12) if j == 7 else pt + self.DT[j]
            vals = []
            for tabl, mode in ((self.B3, 0), (self.X, xm), (self.Y, ym)):
                if mode == 3: vals.append(get(16))
                else:
                    j = get(5); vals.append(get(8) if j == 31 else tabl[j])
            out += build_record(fl, xm, ym, tile & 0xFFF, *vals); pt = tile & 0xFFF
        return bytes(out)



def char_sec1(c):
    data, base, label = D.char_dsp("mvc", c); x = D.DSP(data, base, label)
    return x.sec[1]


def test():
    tot_s = tot_p = 0
    for c in D.char_ids("mvc"):
        s1 = char_sec1(c); pk = pack(s1); u = Unpacker(pk)
        groups, tail = split(s1)
        for off, n, hdr, parts in groups:
            g = u.group(off); assert g == s1[off:off + len(g)] and len(g) == 6 + sum(len(r) for p, r in parts), (c, off)
        assert pk[len(pk) - (-len(pk) % 4) - len(tail):len(pk) - (-len(pk) % 4)] == tail if tail else True
        tot_s += len(s1); tot_p += len(pk)
        print("%02x sec1 %6d -> G2 %6d (-%4.1f%%)  groups %d  OK" % (c, len(s1), len(pk), 100 - 100.0 * len(pk) / len(s1), len(groups)), flush=True)
    print("all %d -> %d (-%.1f%%)" % (tot_s, tot_p, 100 - 100.0 * tot_p / tot_s))


if __name__ == "__main__":
    if sys.argv[1] == "test": test()


def pack_dsp(dsp, ref=None):
    """whole DSP (kind 8: header u32 kind, off[4]; sections 0-3) -> the same DSP with sec1 in G2 form.  ref = the
    character's stock DSP (group starts: cut tiers keep the offsets, nparts lowered in place).  sec1 starts 4-aligned
    (lw / lhu in g2get), sec2 / sec3 keep their alignment mod 4."""
    kind, o0, o1, o2, o3 = struct.unpack_from("<5I", dsp, 0)
    s1 = dsp[o1:o2]
    starts = None
    if ref is not None:
        r = D.DSP(ref, 0).sec[1]; assert len(r) == len(s1), "sec1 size differs from the reference"
        starts = [o for o, n, h, p in split(r)[0]]
    pk = pack(s1, starts)
    n1 = (o1 + 3) & ~3
    pad1 = bytes(n1 - o1)                                   # between sec0 and sec1
    n2 = n1 + len(pk); n2 += (o2 - n2) % 4                  # sec2 keeps o2 mod 4
    out = dsp[:o1] + pad1 + pk + bytes(n2 - n1 - len(pk))
    d = n2 - o2
    out += dsp[o2:]
    out = bytearray(out); struct.pack_into("<4I", out, 4, o0, n1, n2, o3 + d)
    return bytes(out)
