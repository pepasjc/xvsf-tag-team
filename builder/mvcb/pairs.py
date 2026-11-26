"""Store-once sprite pairs (mktag --share): the union A0 of a base character + the json of its user character
(games/mvc/tools/speed5/pairs.py build(), run on the half-res effects A0 files the builder made).

    build(ab, au, b, u) -> (union A0 bytes, json text)
"""
import json, struct
import dsp as D                                              # common/dsp


def a0_split(a):
    n, = struct.unpack_from("<I", a)
    return n, [struct.unpack_from("<2I", a, 4 + 8 * i) for i in range(n)]


def key(t, raw): return (t.wb, t.h, t.flag, bytes(raw))


def build(ab, au, b, u):
    nb, sb = a0_split(ab); nu, su = a0_split(au)
    assert nb == 3 and nu == 3
    db = D.DSP(ab[sb[1][0]:sb[1][0] + sb[1][1]]); du = D.DSP(au[su[1][0]:su[1][0] + su[1][1]])
    db.decode_all(); du.decode_all()
    have = {}
    for t in db.tiles: have.setdefault(key(t, t.raw), t.idx)
    sec0 = bytearray(db.sec[0]); sec2 = bytearray(db.sec[2][:len(db.tiles) * 5])
    remap = {}; extra = 0; streams = {}
    for t in du.tiles:
        k = key(t, t.raw)
        if k in have: remap[t.idx] = have[k]; continue
        so = (t.off, t.clen)
        if so not in streams:
            streams[so] = len(sec0)
            sec0 += du.sec[0][t.off:t.off + t.clen + 1]
        off = streams[so]
        e = bytes([off & 0xff, off >> 8 & 0xff, off >> 16 & 0x3f]) + t.ent[3:5]
        have[k] = len(sec2) // 5; remap[t.idx] = have[k]; sec2 += e; extra += 1
    assert len(sec2) // 5 <= 4096
    sec0 += bytes(-len(sec0) % 4)
    s1, s2, s3 = db.sec[1], bytes(sec2), db.sec[3]
    s2 += bytes(-len(s2) % 4)
    o1 = 0x14 + len(sec0); o2 = o1 + len(s1); o3 = o2 + len(s2)
    U = struct.pack("<5I", db.kind, 0x14, o1, o2, o3) + bytes(sec0) + s1 + s2 + s3
    U += bytes(-len(U) % 4)
    code = ab[sb[0][0]:sb[0][0] + sb[0][1]]; st = ab[sb[2][0]:sb[2][0] + sb[2][1]]
    h = 4 + 8 * 3
    A = struct.pack("<7I", 3, h, len(code), h + len(code), len(U), h + len(code) + len(U), len(st)) + code + U + st
    s1u = bytearray(du.sec[1])
    for start, hdr, g in du.groups():
        p = start + 6
        for pt in g:
            v = s1u[p + 1] | s1u[p + 2] << 8
            nv = (v & 0xf000) | remap[v & 0xfff]
            s1u[p + 1] = nv & 0xff; s1u[p + 2] = nv >> 8
            p += pt.size
    j = json.dumps(dict(base=b, user=u, base_tiles=len(db.tiles), user_tiles=len(du.tiles), extra=extra,
                        union_sec0=len(sec0), base_sec0=len(db.sec[0]), user_sec0=len(du.sec[0]),
                        user_sec1=bytes(s1u).hex(), user_sec3=du.sec[3].hex()))
    return A, j
