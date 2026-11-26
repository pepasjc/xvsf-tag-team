"""MvC achievements core (freeze worker, rc4 line 2026-11-20): the adapted set (../set.py) compiled into the compact
tables of core.c: templates (condition lists with per-achievement parameters), a 3-byte record per achievement, the
constant table, the memory references, Huffman-packed titles and the points.  The one achievement with hit counts /
ResetIf (112518) is not a template: core.c codes it by hand (asserted here against its memaddr text).

    python corec.py OUTDIR      -> OUTDIR/core_set.h, OUTDIR/set.txt (the rcheevos oracle's input, host/core_diff.c)
"""
import os, re, sys, heapq, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("mvc_ach_set", os.path.join(HERE, "..", "set.py"))
SET = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(SET)

SPECIAL = {112518: "R:0xH07b740!=0_N:0xH07bdf2=0_0xH07b82b=0.1._N:0xH07b82b=2_R:d0xH07b82b=1_N:0xH07b82b=1_"
                   "N:d0xH07b82b=0_R:0xH07bdf2=7_0xH07c16d<=1_0xH07b71c>=1_T:0xH07bdf2>=7_T:0xH07cf10=2"}
OPS = {"=": 0, "!=": 1, "<": 2, "<=": 3, ">": 4, ">=": 5}
COND = re.compile(r"^(d?)0x([HX])([0-9a-f]{6})(!=|<=|>=|=|<|>)(\d+)$")
V0 = SET.V                                   # derived bytes: set address V + i = core vars[i]


def parse(mem):
    out = []
    for c in mem.split("_"):
        m = COND.match(c)
        assert m, "not a pure condition: %r" % c
        d, sz, a, op, v = m.groups()
        out.append(((int(a, 16), sz == "X", d == "d"), OPS[op], int(v)))
    return out


def build():
    achs = SET.ACHS
    refs, consts, tpls, recs = [], [], [], []
    def ref(r):
        if r not in refs: refs.append(r)
        return refs.index(r)
    def const(v):
        if v not in consts: consts.append(v)
        return consts.index(v)
    groups = {}
    parsed = {}
    for a in achs:
        if a["id"] in SPECIAL:
            assert a["memaddr"] == SPECIAL[a["id"]], "112518 changed: recode core.c special()"
            continue
        p = parse(a["memaddr"]); parsed[a["id"]] = p
        groups.setdefault(tuple((r, op) for r, op, v in p), []).append(a["id"])
    tidx = {}
    for key, ids in groups.items():
        vals = list(zip(*[[v for _, _, v in parsed[i]] for i in ids]))     # per condition: the members' values
        var = [k for k, vs in enumerate(vals) if len(set(vs)) > 1]
        minus1 = {}                                                       # a value = an earlier parameter - 1
        for k in var[:]:
            j = next((j for j in var if j < k and j not in minus1 and all(x == y - 1 for x, y in zip(vals[k], vals[j]))), None)
            if j is not None: minus1[k] = j; var.remove(k)
        assert len(var) <= 2, (key, var)
        conds = []
        for k, ((r, op), vs) in enumerate(zip(key, vals)):
            ri = ref(r)
            if k in minus1:
                conds.append((ri, op, 5 + var.index(minus1[k]), 0))       # 5/6: param raw - 1
            elif k in var:
                pk = var.index(k)
                big = max(vs) > 255
                for v in vs: const(v) if big else None
                mode = (3 + pk) if big else (1 + pk)            # 1/2: param raw, 3/4: consts[param]
                conds.append((ri, op, mode, 0))
            else:
                conds.append((ri, op, 0, const(vs[0])))
        tidx[key] = len(tpls); tpls.append((conds, var, vals))
    for a in achs:
        if a["id"] in SPECIAL:
            recs.append((0xff, 0, 0)); continue
        p = parsed[a["id"]]; key = tuple((r, op) for r, op, v in p)
        conds, var, vals = tpls[tidx[key]]
        ps = []
        for pk, k in enumerate(var):
            v = p[k][2]
            ps.append(const(v) if conds[k][2] >= 3 else v)
        ps += [0] * (2 - len(ps))
        assert all(0 <= x < 256 for x in ps)
        recs.append((tidx[key],) + tuple(ps))
    assert len(refs) <= 32 and len(consts) <= 256 and len(tpls) < 255
    return achs, refs, consts, tpls, recs


# ---- titles: one phrase symbol + Huffman over symbols, a 0 symbol ends a title; byte nodes, no start table ------------
PHRASE = "HIT COMBINATION "
def sym_of(ch): return 0 if ch == "\0" else 1 if ch == "\1" else ord(ch) - 0x20 + 2
def ch_of(s): return "\0" if s == 0 else "\1" if s == 1 else chr(s - 2 + 0x20)


def huff(texts):
    from collections import Counter
    seq = "".join(t.replace(PHRASE, "\1") + "\0" for t in texts)
    assert all(0x20 <= ord(ch) < 0x7e or ch in "\0\1" for ch in seq)
    c = Counter(seq)
    h = [(n, i, ch) for i, (ch, n) in enumerate(sorted(c.items()))]
    heapq.heapify(h); k = len(h)
    while len(h) > 1:
        a = heapq.heappop(h); b = heapq.heappop(h)
        heapq.heappush(h, (a[0] + b[0], k, (a[2], b[2]))); k += 1
    tree = h[0][2]
    nodes = []                                   # node i = (left, right) bytes: < 0x80 node index, 0x80 | symbol = leaf
    def emit(t):
        if isinstance(t, str): return 0x80 | sym_of(t)
        i = len(nodes); nodes.append(None)
        nodes[i] = (emit(t[0]), emit(t[1])); return i
    emit(tree)
    assert len(nodes) < 0x80
    codes = {}
    def walk(t, s):
        if isinstance(t, str): codes[t] = s; return
        walk(t[0], s + "0"); walk(t[1], s + "1")
    walk(tree, "")
    bits = "".join(codes[ch] for ch in seq)
    data = bytes(int(bits[i:i + 8].ljust(8, "0")[::-1], 2) for i in range(0, len(bits), 8))   # LSB first
    return nodes, data


def decode(nodes, data, i):            # host check: title i, decoded as core.c does (skip i titles from bit 0)
    out, b, t = "", 0, 0
    while True:
        n = 0
        while True:
            n = nodes[n][data[b >> 3] >> (b & 7) & 1]; b += 1
            if n & 0x80: break
        s = n & 0x7f
        if s == 0:
            if t == i: return out
            t += 1; out = ""; continue
        out += PHRASE if s == 1 else ch_of(s)


def main(out):
    achs, refs, consts, tpls, recs = build()
    titles = [a["title"].upper() for a in achs]
    nodes, data = huff(titles)
    for i, t in enumerate(titles): assert decode(nodes, data, i) == t
    L = ["/* generated by corec.py from ../set.py - do not edit */",
         "#define NACH %d" % len(achs), "#define NTPL %d" % len(tpls), "#define NREF %d" % len(refs)]
    # refs (u16): derived byte: 0x8000 | delta << 14 | index; game byte: x32 << 13 | (address - 0x7b000)
    rw, dl = [], []
    for a, x, d in refs:
        if V0 <= a < V0 + 16: rw.append(0x8000 | d << 14 | (a - V0)); dl += [a - V0] if d else []
        else:
            assert not d and 0x7b000 <= a < 0x7d000
            rw.append(x << 13 | (a - 0x7b000))
    assert len(set(dl)) == 1, "core.c keeps one delta (the combo count)"
    L.append("#define DELTA_VAR %d" % dl[0])
    L.append("static const uint16_t c_ref[NREF] = { %s };" % ", ".join("0x%04x" % w for w in rw))
    L.append("static const uint32_t c_const[%d] = { %s };" % (len(consts), ", ".join("%du" % v for v in consts)))
    # templates: (ref, mask | mode << 3, const index) ... 0xff; mask bits: 4 lhs < rhs, 2 equal, 1 lhs > rhs
    MASK = {0: 2, 1: 5, 2: 4, 3: 6, 4: 1, 5: 3}
    tb, off = [], []
    for conds, var, vals in tpls:
        off.append(len(tb))
        for ri, op, mode, ci in conds: tb += [ri, MASK[op] | mode << 3, ci]
        tb.append(0xff)
    L.append("static const uint8_t c_tpl[%d] = { %s };" % (len(tb), ", ".join(str(x) for x in tb)))
    L.append("static const uint8_t c_toff[NTPL] = { %s };" % ", ".join(str(x) for x in off))
    assert max(off) < 256 and len(tpls) <= 16
    pv = sorted({a["points"] for a in achs}); assert len(pv) <= 16 and max(pv) < 100
    L.append("static const uint8_t c_ptab[%d] = { %s };" % (len(pv), ", ".join(str(x) for x in pv)))
    L.append("static const uint8_t c_rec[NACH][3] = { %s };" % ", ".join(
        "{%d,%d,%d}" % ((r[0] | pv.index(a["points"]) << 4) if r[0] != 0xff else (0xf0 & (pv.index(a["points"]) << 4)) | 0x0f, r[1], r[2])
        for r, a in zip(recs, achs)))
    L.append("static const uint8_t c_hnode[%d][2] = { %s };" % (len(nodes), ", ".join("{%d,%d}" % n for n in nodes)))
    L.append("static const uint8_t c_hdat[%d] = { %s };" % (len(data), ", ".join(str(x) for x in data)))
    L.append('static const char c_phrase[] = "%s";' % PHRASE)
    L.append("#define SPECIAL_IDX %d" % next(i for i, a in enumerate(achs) if a["id"] in SPECIAL))
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "core_set.h"), "w").write("\n".join(L) + "\n")
    open(os.path.join(out, "core_set.inc"), "w").write(".equ NACH, %d\n.equ SPECIAL_IDX, %d\n.equ DELTA_VAR, %d\n" % (
        len(achs), next(i for i, a in enumerate(achs) if a["id"] in SPECIAL), dl[0]))
    with open(os.path.join(out, "set.txt"), "w") as f:
        for a in achs: f.write("ach\t%d\t%d\t%s\t%s\n" % (a["id"], a["points"], a["memaddr"], a["title"]))
    print("core set: %d achievements, %d templates (%d B), %d refs, %d consts, titles %d B + %d nodes"
          % (len(achs), len(tpls), len(tb), len(refs), len(consts), len(data), len(nodes)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "gen"))
