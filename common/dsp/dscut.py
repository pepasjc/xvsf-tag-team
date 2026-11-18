"""Animation-frame cut tiers for MvC (last-resort size lever): DSA1 / DSH1 files of a character DSP in which the N
heaviest frames (sec1 groups) show a neighbour frame instead, so their own tiles are no longer needed.

Method (no animation-record rewrite; sec1 / sec2 / sec3 keep their byte lengths, sec3 is never touched):
  * exclusive bytes of a group = RLE stream bytes of the tiles that ONLY this group references (streams shared with
    a tile used elsewhere do not count); groups are ranked by it
  * the top N groups (skipping ones whose neighbour does not fit) are rewritten IN PLACE: same byte span, the 4 header
    bytes after nparts kept, nparts = the neighbour's, the neighbour's part records copied (previous group in sec1
    order, else the next; a neighbour that is itself being cut is avoided).  Spare bytes in the span are absorbed by
    re-encoding coordinates in the 16-bit mode (part record 6 -> 7 -> 8 bytes, same values; parser model
    dsp.parse_part = MvC 0x8008c6a8); bytes that cannot be absorbed stay unused (zero) after the last part
  * tiles referenced by no group any more (but referenced before) get all-zero pixels; tiles never referenced by any
    group stay as they are (other code may use them)
  * the result is a modified STOCK DSP ("cut stock", RLE; freed tiles share one zero stream per size) that is then
    encoded with dsa.py / dsh.py exactly like the normal tiers.  Tests compare against the stock decoder on it.

    python dscut.py GAME N [ids]        -> games/G/work/dsp/cut<N>_stock/<label>.DSP + cuts.json (cut stock files)
    python dscut.py GAME N enc [ids]    -> dsa_cut<N>/, dsh_cut<N>/ (<label>.DSP, stats.json, cuts.json)
"""
import os, sys, struct, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import dsp as D
import dsm as M


def part_bytes(pt, xm, ym):
    """serialise a part record with x / y modes (xm / ym: 0..2 as stored, or 3 = s16)"""
    v = pt.tile | (xm << 12) | (ym << 14)
    out = bytes([pt.flags, v & 255, v >> 8, pt.b3])
    def one(val, m):
        if m == 3: return struct.pack("<h", val)
        if m == 2: return bytes([(-val) & 255])
        if m == 1: return bytes([val & 255])
        return struct.pack("<b", val)
    return out + one(pt.x, xm) + one(pt.y, ym)


def fill_parts(parts, room):
    """parts records filling exactly `room` bytes where possible -> (bytes, unused bytes)"""
    modes = [[p.xm, p.ym] for p in parts]
    sz = lambda: sum(6 + (m[0] == 3) + (m[1] == 3) for m in modes)
    for m in modes:
        for a in (0, 1):
            if sz() < room and m[a] != 3: m[a] = 3
    b = b"".join(part_bytes(p, *m) for p, m in zip(parts, modes))
    for p, m in zip(parts, modes):
        q = D.parse_part(part_bytes(p, *m), 0)
        assert (q.x, q.y, q.tile, q.flags, q.b3) == (p.x, p.y, p.tile, p.flags, p.b3)
    return b, room - len(b)


def cut(x, n, hot=None, keep=None, first=None):
    """x: dsp.DSP (stock).  -> (cut stock DSP bytes, [cut records]).
    hot: set of tile indices decoded in play (hot.py); when given, a frame group that uses any of them is never cut
    (only frames never seen in the fight runs - supers / rare moves - are cut, not walk / stand / normals)."""
    x.decode_all(); g = x.groups(); s1 = bytearray(x.sec[1])
    starts = [s for s, h, gg in g]; ends = starts[1:] + [len(s1) - x.sec1_tail]
    users = {}
    for i, (s, h, gg) in enumerate(g):
        for p in gg:
            if p.tile < len(x.tiles): users.setdefault(p.tile, set()).add(i)
    stream_users = {}
    for t in x.tiles:
        stream_users.setdefault((t.off, t.clen), set()).update(users.get(t.idx, {-1}))   # -1: no group (keep)
    excl = []
    for i in range(len(g)):
        tot = sum(k[1] + 1 for k, us in stream_users.items() if us == {i})
        excl.append(tot)
    order = sorted(range(len(g)), key=lambda i: -excl[i])
    if hot is not None:
        order = [i for i in order if not any(p.tile in hot for p in g[i][2])]
    if keep:                                             # protected frame groups (by sec1 offset): never cut
        order = [i for i in order if g[i][0] not in keep]
    if first:                                            # these groups (sec1 offsets) are cut first, heaviest first
        order = [i for i in order if g[i][0] in first] + [i for i in order if g[i][0] not in first]
    chosen = []; recs = []
    for i in order:
        if len(chosen) >= n or excl[i] == 0: break
        span = ends[i] - starts[i]
        for j in ([i - 1, i + 1] if i > 0 else [i + 1]):
            if not (0 <= j < len(g)) or j in chosen: continue
            nb = g[j][2]
            if 6 + sum(p.size for p in nb) > span: continue
            body, unused = fill_parts(nb, span - 6)
            s1[starts[i]:starts[i] + 2] = struct.pack("<H", len(nb))
            s1[starts[i] + 6:ends[i]] = body + bytes(unused)
            chosen.append(i)
            recs.append(dict(group=i, sec1=starts[i], excl_rle_bytes=excl[i], neighbour=j, unused=unused))
            break
    # parse back: every group equals its target content
    for r in recs:
        cnt = struct.unpack_from("<H", s1, r["sec1"])[0]; p = r["sec1"] + 6; got = []
        for k in range(cnt):
            pt = D.parse_part(bytes(s1), p); got.append((pt.flags, pt.tile, pt.x, pt.y, pt.b3)); p += pt.size
        want = [(pt.flags, pt.tile, pt.x, pt.y, pt.b3) for pt in g[r["neighbour"]][2]]
        assert got == want and p <= ends[r["group"]]
    # tiles freed by the cut
    still = set()
    for i, (s, h, gg) in enumerate(g):
        src = g[[r["neighbour"] for r in recs if r["group"] == i][0]][2] if i in chosen else gg
        for p in src: still.add(p.tile)
    freed = [t for t in x.tiles if t.idx in users and t.idx not in still]
    sec0 = bytearray(x.sec[0]); offs = {t.idx: t.off for t in x.tiles}; zs = {}
    for t in freed:
        if t.n not in zs:
            zs[t.n] = len(sec0); sec0 += D.rle_encode(bytes(t.n)) + b"\0"
        offs[t.idx] = zs[t.n]
    sec0 += b"\0" * (-len(sec0) % 4)
    y = D.DSP(x.d); y.sec = list(x.sec); y.sec[1] = bytes(s1)
    new = M.assemble(y, sec0, offs)
    z = D.DSP(new)
    assert [len(s) for s in z.sec[1:]] == [len(s) for s in x.sec[1:]] and z.sec[3] == x.sec[3]
    for r in recs: r["freed_tiles"] = sum(1 for t in freed if users[t.idx] & {r["group"]})
    return new, recs, len(freed)


def hot_tiles(game, label):
    """DSCUT_COLD=1: the tiles decoded in the fight runs (games/G/work/dsp/hot/<label>.json); None = rank all frames"""
    if os.environ.get("DSCUT_COLD") != "1": return None
    p = os.path.join(ROOT, "games", game, "work", "dsp", "hot", label + ".json")
    return {int(k) for k, v in json.load(open(p)).items() if v > 0}


def anim_groups(game, cid):
    """DSCUT_ANIM=dir: <dir>/<id>.json from games/mvc/tools/fxhalf/animlog.py -> (keep = 'move' groups: stand / walk /
    dash / crouch / jump / block / tag, never cut; first = 'intro' + 'win' groups not in 'move', when DSCUT_INTRO=1)"""
    d = os.environ.get("DSCUT_ANIM")
    if not d: return None, None
    p = os.path.join(d, "%02X.json" % cid)
    if not os.path.exists(p): return None, None
    j = json.load(open(p))
    keep = set(j.get("move", []))
    first = (set(j.get("intro", [])) | set(j.get("win", []))) - keep if os.environ.get("DSCUT_INTRO") == "1" else None
    return keep, first


def _stock(game, cid, n):
    b, base, l = D.char_dsp(game, cid); x = D.DSP(b, base)
    keep, first = anim_groups(game, cid)
    new, recs, nf = cut(x, n, hot_tiles(game, l), keep, first)
    return l, x, new, recs, nf


def _enc(a):
    game, cid, n = a
    import dsa as A, dsh as H
    l, x, new, recs, nf = _stock(game, cid, n)
    y = D.DSP(new)
    out = {}
    da, sa = A.encode(y); assert A.verify(da, y) == 0
    best = None
    for k, c in H.SEARCH:
        dh, sh = H.encode(D.DSP(new), k, c)
        if best is None or len(dh) < len(best[0]): best = (dh, sh)
    dh, sh = best; assert H.verify(dh, D.DSP(new)) == 0
    for tier, data, st in (("dsa", da, sa), ("dsh", dh, sh)):
        st = dict(st); st.update(new=len(data), id=cid, label=l, cut_groups=len(recs), freed_tiles=nf)
        d = os.path.join(ROOT, "games", game, "work", "dsp", "%s_cut%d" % (tier, n)); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, l + ".DSP"), "wb").write(data)
        out[tier] = st
    return l, recs, out


def main():
    a = sys.argv[1:]
    game, n = a[0], int(a[1]); enc = len(a) > 2 and a[2] == "enc"
    ids = [int(v, 16) for v in a[(3 if enc else 2):]] or D.char_ids(game)
    base = os.path.join(ROOT, "games", game, "work", "dsp")
    if not enc:
        d = os.path.join(base, "cut%d_stock" % n); os.makedirs(d, exist_ok=True); cuts = {}
        for c in ids:
            l, x, new, recs, nf = _stock(game, c, n)
            open(os.path.join(d, l + ".DSP"), "wb").write(new); cuts[l] = recs
            print(l, "cut", len(recs), "groups, freed tiles", nf, "excl RLE bytes", sum(r["excl_rle_bytes"] for r in recs), flush=True)
        json.dump(cuts, open(os.path.join(d, "cuts.json"), "w"), indent=1)
        return
    from multiprocessing import Pool
    stats = {"dsa": {}, "dsh": {}}; cuts = {}
    with Pool(int(os.environ.get("NPROC", "4"))) as p:
        for l, recs, out in p.imap_unordered(_enc, [(game, c, n) for c in ids]):
            cuts[l] = recs
            for t, st in out.items(): stats[t][l] = st
            print(l, "cut", len(recs), "dsa", out["dsa"]["new"], "dsh", out["dsh"]["new"], flush=True)
    for t in ("dsa", "dsh"):
        d = os.path.join(base, "%s_cut%d" % (t, n))
        for name, obj in (("stats.json", stats[t]), ("cuts.json", cuts)):
            p_ = os.path.join(d, name); old = json.load(open(p_)) if os.path.exists(p_) else {}
            old.update(obj); json.dump(old, open(p_, "w"), indent=1)


if __name__ == "__main__":
    main()
