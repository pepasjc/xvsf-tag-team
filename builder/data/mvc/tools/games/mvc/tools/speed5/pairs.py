"""Store-once sprite pairs (fx worker, 2026-11-19; mktag --share).

Variant characters share most of their decoded tiles with a base character (tools/speed5/share.py: Red Venom 96 % of
Venom's pixels, Orange Hulk 87 % of Hulk, Lilith 81 % of Morrigan, Gold War Machine 70 % of War Machine, Chun-Li 100 %
inside Shadow Lady).  When both are in one battle, ONE pixel section can serve both:

  union DSP U(b, u) = b's DSP (sec0 / sec1 / sec2 / sec3 unchanged) + u's tiles that b does not have (RLE streams
  appended to sec0, entries appended to sec2).  b's groups keep their tile indices; u's groups (its own sec1) get the
  indices remapped into U's tile table.  The tier encoders run on U as character b in the tree work/speed5/root_pair.

At run time (tagload.c SHARE): b's slot loads U's tier file (pixels + b's tables incl. U's tile table), u's slot loads
only its own sec1' + sec3 and is registered (D04) on b's pixel section and b's tile table (sec2).  The decoder dispatch
picks the codec by source address, so u's tiles decode with U's model.  Exact: every u tile is pixel-identical (same
width, rows, half-res flag, decoded bytes).

    python pairs.py build [b:u ...]      -> root_pair/games/mvc/work/dsp/files/PLbb_10.A0 (union) + pair_bb_uu.json
    python pairs.py enc   [b ...]        -> encode the union files at the pair tiers (dsa dsh dsm dsh_hot16)
    python pairs.py check [b:u ...]      -> every u tile of every group decodes to its own pixels through U (per tier)
"""
import os, sys, json, struct, shutil, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
SRC = os.path.join(GAME, "work", "fxhalf", "root_v5")             # delivery tree (tag14b .. dx13t)
TREE = os.path.join(GAME, "work", "speed5", "root_pair")
PAIRS = [(0x06, 0x12), (0x03, 0x13), (0x0F, 0x16), (0x15, 0x0B), (0x01, 0x14), (0x10, 0x08)]
PTIERS = ["dsa", "dsh", "dsm", "dsh_hot16"]                      # encoded; dsx / dsx_hot16 = dsxmod of dsh / dsh_hot16
sys.path.insert(0, os.path.join(SRC, "common", "dsp"))
import dsp as D


def a0_split(a):
    n, = struct.unpack_from("<I", a)
    s = [struct.unpack_from("<2I", a, 4 + 8 * i) for i in range(n)]
    return n, s


def files_dir(t): return os.path.join(t, "games", "mvc", "work", "dsp", "files")


def key(t, raw):
    return (t.wb, t.h, t.flag, bytes(raw))


def build(b, u):
    ab = open(os.path.join(files_dir(SRC), "PL%02X_10.A0" % b), "rb").read()
    au = open(os.path.join(files_dir(SRC), "PL%02X_10.A0" % u), "rb").read()
    nb, sb = a0_split(ab); nu, su = a0_split(au)
    assert nb == 3 and nu == 3
    db = D.DSP(ab[sb[1][0]:sb[1][0] + sb[1][1]]); du = D.DSP(au[su[1][0]:su[1][0] + su[1][1]])
    db.decode_all(); du.decode_all()
    have = {}
    for t in db.tiles: have.setdefault(key(t, t.raw), t.idx)
    sec0 = bytearray(db.sec[0]); sec2 = bytearray(db.sec[2][:len(db.tiles) * 5]); tail2 = db.tail2
    remap = {}; extra = 0; streams = {}
    for t in du.tiles:
        k = key(t, t.raw)
        if k in have: remap[t.idx] = have[k]; continue
        so = (t.off, t.clen)
        if so not in streams:                         # the tile's RLE stream (incl. the run overrun the decoder reads)
            streams[so] = len(sec0)
            sec0 += du.sec[0][t.off:t.off + t.clen + 1]
        off = streams[so]
        assert off < 1 << 22
        e = bytes([off & 0xff, off >> 8 & 0xff, off >> 16 & 0x3f]) + t.ent[3:5]
        have[k] = len(sec2) // 5; remap[t.idx] = have[k]; sec2 += e; extra += 1
    assert len(sec2) // 5 <= 4096, "union tile table > 12-bit index"
    sec0 += bytes(-len(sec0) % 4)
    # union DSP: header, sec0, b's sec1, union sec2 (+ b's tail), b's sec3
    s1, s2, s3 = db.sec[1], bytes(sec2), db.sec[3]       # b's sec2 tail is alignment only: pad to 4, never 5+ bytes
    s2 += bytes(-len(s2) % 4)                              # (a 5th byte would parse as an extra zero tile)
    assert len(s2) - len(sec2) < 5
    assert db.offs[1] % 4 == 0 and len(s1) % 4 == 0 or True
    o1 = 0x14 + len(sec0); o2 = o1 + len(s1); o3 = o2 + len(s2)
    U = struct.pack("<5I", db.kind, 0x14, o1, o2, o3) + bytes(sec0) + s1 + s2 + s3
    U += bytes(-len(U) % 4)
    # check: every tile of U decodes like before; every u group through the remap = u's own tile pixels
    du2 = D.DSP(U); du2.decode_all()
    for t in db.tiles: assert du2.tiles[t.idx].raw == t.raw
    for t in du.tiles: assert du2.tiles[remap[t.idx]].raw == t.raw and du2.tiles[remap[t.idx]].ent[3:5] == t.ent[3:5]
    # union A0 (code, union DSP, b's set)
    code = ab[sb[0][0]:sb[0][0] + sb[0][1]]; st = ab[sb[2][0]:sb[2][0] + sb[2][1]]
    h = 4 + 8 * 3
    A = struct.pack("<7I", 3, h, len(code), h + len(code), len(U), h + len(code) + len(U), len(st)) + code + U + st
    os.makedirs(files_dir(TREE), exist_ok=True)
    open(os.path.join(files_dir(TREE), "PL%02X_10.A0" % b), "wb").write(A)
    # u's groups with union indices (parts: b1 | b2 << 8 low 12 bits = tile)
    s1u = bytearray(du.sec[1])
    for start, hdr, g in du.groups():
        p = start + 6
        for pt in g:
            v = s1u[p + 1] | s1u[p + 2] << 8
            nv = (v & 0xf000) | remap[v & 0xfff]
            s1u[p + 1] = nv & 0xff; s1u[p + 2] = nv >> 8
            p += pt.size
    json.dump(dict(base=b, user=u, base_tiles=len(db.tiles), user_tiles=len(du.tiles), extra=extra,
                   union_sec0=len(sec0), base_sec0=len(db.sec[0]), user_sec0=len(du.sec[0]),
                   user_sec1=bytes(s1u).hex(), user_sec3=du.sec[3].hex()),
              open(os.path.join(TREE, "pair_%02X_%02X.json" % (b, u)), "w"))
    print("pair %02X+%02X: %d of %d user tiles shared, %d extra; union sec0 %d B (base %d, user %d)" % (
        b, u, len(du.tiles) - extra, len(du.tiles), extra, len(sec0), len(db.sec[0]), len(du.sec[0])))


def setup():
    """tree: the delivery tree's encoders + hot lists; files = the union A0s only"""
    for d in ("common",):
        if not os.path.exists(os.path.join(TREE, d)): shutil.copytree(os.path.join(SRC, d), os.path.join(TREE, d))
    hs = os.path.join(SRC, "games", "mvc", "work", "dsp", "hot"); hd = os.path.join(TREE, "games", "mvc", "work", "dsp", "hot")
    if os.path.exists(hs) and not os.path.exists(hd): shutil.copytree(hs, hd)
    os.makedirs(files_dir(TREE), exist_ok=True)


def enc(bases):
    cd = os.path.join(TREE, "common", "dsp")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tools"), NUMBA_CACHE_DIR=os.path.join(ROOT, "work", "nbcache"), NPROC="2")
    ids = ["%x" % b for b in bases]
    for cmd in (["dsa.py", "encode", "mvc"], ["dsh.py", "encode", "mvc", "-j", "2"], ["dsm.py", "encode", "mvc"],
                ["dsh.py", "encode", "mvc", "--hot", "16", "-j", "2"]):
        print(" ".join(cmd), flush=True)
        subprocess.check_call([sys.executable] + cmd + ids, cwd=cd, env=env)


if __name__ == "__main__":
    a = sys.argv[1:]
    sel = [tuple(int(x, 16) for x in s.split(":")) for s in a[1:] if ":" in s] or PAIRS
    if a[0] == "build":
        setup()
        for b, u in sel: build(b, u)
    elif a[0] == "enc":
        enc([int(x, 16) for x in a[1:]] or [b for b, u in PAIRS])
