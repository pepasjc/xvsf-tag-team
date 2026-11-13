"""Strong tier of 1.1 ("nsph4"): the XVH1 file plus the most decoded tiles (play volume per extra byte, data/hot_tiles.json)
as their stock RLE streams behind the XVH1 part; the XVH1 size field covers only the XVH1 part, so the decoder's range
test sends those tiles to the RLE decoder.  Extra bytes per character <= min(CAP, base - strong - MARGIN).
Same result as work/speed/decode/strongrle.py (the reference)."""
import struct, collections
CAP, MARGIN = 4096, 2048


def encode(xvh, n, hot, base_size, cap=CAP, margin=MARGIN):
    """xvh = XVH1 file bytes, n = decoded stock nspfile.NSP, hot = {tile index (str): bytes decoded}"""
    x = bytes(xvh)
    cap = max(0, min(cap, base_size - len(x) - margin))
    o1, o2, o3 = struct.unpack_from("<3I", x, 4); size = struct.unpack_from("<I", x, o2 + 4)[0]
    nt = (o2 - o1) // 4
    offs = [struct.unpack_from("<I", x, o1 + 4 * i)[0] & 0x3fffff for i in range(nt)]
    u = sorted(set(offs)) + [size]; nxt = {a: b for a, b in zip(u, u[1:])}
    model_end = min(offs)
    share = collections.Counter(offs)
    hlen = [(nxt[o] - o) / share[o] for o in offs]
    soff = [int(v) for v in n.off]; clen = [int(v) for v in n.clen]; raw = [int(v) for v in n.nbytes]
    group = collections.defaultdict(list)
    for i in range(nt): group[soff[i]].append(i)
    vol = collections.Counter()
    for t, b in hot.items():
        g = group[soff[int(t)]]
        for u_ in g: vol[u_] += b / len(g)
    rle = set(); used = 0.0
    for t in sorted(vol, key=lambda t: -vol[t] / max(1.0, clen[t] - hlen[t])):
        e = max(0.0, clen[t] - hlen[t])
        if used + e > cap: continue
        rle.add(t); used += e
    s2 = x[o2:o3]; st2 = n.sec[2]
    keep = sorted(set(o for i, o in enumerate(offs) if i not in rle))
    new2 = bytearray(s2[:model_end]); remap = {}
    for o in keep:
        remap[o] = len(new2); new2 += s2[o:nxt[o]]
    new2 += b"\0" * (4 + (-len(new2) % 4))
    struct.pack_into("<I", new2, 4, len(new2))
    rdone = {}; roff = {}
    for t in sorted(rle):
        stm = st2[soff[t]:soff[t] + clen[t]]
        if stm not in rdone: rdone[stm] = len(new2); new2 += stm
        roff[t] = rdone[stm]
    new2 += b"\0" * (-len(new2) % 4)
    sec1 = bytearray(x[o1:o2])
    for i in range(nt):
        w = struct.unpack_from("<I", sec1, 4 * i)[0]
        struct.pack_into("<I", sec1, 4 * i, (w & ~0x3FFFFF) | (roff[i] if i in rle else remap[offs[i]]))
    return struct.pack("<4I", 16, o1, o2, o2 + len(new2)) + x[16:o1] + bytes(sec1) + bytes(new2) + x[o3:]
