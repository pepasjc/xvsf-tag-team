"""Compile an achievement set (rcheevos condition strings) into the tables of tools/ach/eval.h.

    from setc import compile_set
    info = compile_set(achs, out_c, out_txt, title_cols=.., desc_cols=.., desc_lines=..)

achs: list of dicts with id, title, desc, points, memaddr (rcheevos syntax).  set.txt (one
"ach  id  points  memaddr  title" line per achievement) feeds tools/ach/host/diff.c, which runs
the tables against stock rcheevos.  Anything eval.c does not implement raises an error.

Group layout: rcheevos 12.5 evaluates a group in a fixed order of parts (condset.c
rc_classify_conditions): chains ending in PauseIf, then ResetIf, then conditions with a hit
target, then the rest (Measured is refused).  The conditions are stored in that order.
"""
import re
import textwrap

SIZE = {"H": 0, " ": 1, "": 1, "W": 2, "X": 3, **{c: 0 for c in "MNOPQRSTLUK"}}
PART = {"H": 0, " ": 0, "": 0, "W": 0, "X": 0, **{c: 1 + i for i, c in enumerate("MNOPQRST")}, "L": 9, "U": 10, "K": 11}
# flag letter -> eval.h CT_*
FLAGS = {None: 0, "A": 1, "B": 2, "N": 3, "O": 4, "Z": 5, "C": 6, "D": 7, "R": 8, "P": 9, "T": 10}
COMBINING = {3, 4, 5, 6, 7}
INDIRECT = {1, 2}
OPS = {None: 0, "=": 1, "!=": 2, "<": 3, "<=": 4, ">": 5, ">=": 6}
COND = re.compile(r"^(?:([A-Z]):)?(.+?)(?:(!=|<=|>=|=|<|>)(.+?))?(?:\.(\d+)\.)?$")
MEM = re.compile(r"^(d?)0x([ HMNOPQRSTLUKWX]?)([0-9a-fA-F]+)$")


def split_groups(memaddr):
    """Groups are separated by 'S', which is also a size letter after '0x'."""
    out, cur = [], ""
    for i, ch in enumerate(memaddr):
        if ch == "S" and not (i > 0 and memaddr[i - 1] == "x"):
            out.append(cur); cur = ""
        else:
            cur += ch
    return out + [cur]


class Set:
    def __init__(self):
        self.mem, self.consts, self.conds, self.groups, self.achs = [], [], [], [], []

    def _operand(self, s, deps):
        m = MEM.match(s)
        if m:
            size, addr = m.group(2), int(m.group(3), 16)
            assert addr < 0x200000, hex(addr)
            ref = SIZE[size] << 24 | addr
            if ref not in self.mem:
                self.mem.append(ref)
            assert len(self.mem) <= 0x400
            i = self.mem.index(ref)
            deps.add(min(i, 31))
            return (2 if m.group(1) else 1) << 14 | PART[size] << 10 | i
        if re.fullmatch(r"[hH][0-9a-fA-F]+", s):
            v = int(s[1:], 16)
        elif re.fullmatch(r"-?\d+", s):
            v = int(s) & 0xFFFFFFFF
        else:
            raise ValueError(f"operand not supported: {s}")
        if v not in self.consts:
            self.consts.append(v)
        assert len(self.consts) < 0x4000
        return self.consts.index(v)

    def add(self, memaddr):
        first = len(self.groups)
        deps, pure, stable = set(), True, True
        for g in split_groups(memaddr):
            parsed = []
            for c in g.split("_") if g else []:
                m = COND.match(c)
                if not m:
                    raise ValueError(c)
                flag, lhs, op, rhs, hits = m.groups()
                if flag not in FLAGS:
                    raise ValueError(f"flag not supported: {c}")
                t = FLAGS[flag]
                if t in INDIRECT:
                    if op is not None:
                        raise ValueError(f"AddSource with an operator: {c}")
                elif op is None:
                    raise ValueError(f"no comparison: {c}")
                hits = int(hits or 0)
                if hits > 255:
                    raise ValueError(f"hit target over 255: {c}")
                if hits or t in (5, 6, 7, 8) or (t == 9 and hits):
                    pure = False
                if hits > 1 or t in (6, 7):          # AddHits / SubHits, or a count past 1: not idempotent
                    stable = False
                parsed.append((t, OPS[op], self._operand(lhs, deps), self._operand(rhs, deps) if rhs else 0, hits))
            # chains -> parts (rc_classify_conditions); AddSource stays in front of what it feeds
            parts, chain = [[], [], [], []], []
            for cond in parsed:
                chain.append(cond)
                t, h = cond[0], cond[4]
                if t in COMBINING or t in INDIRECT:
                    continue
                k = 0 if t == 9 else 1 if t == 8 else 2 if h else 3
                parts[k] += chain; chain = []
            parts[3] += chain
            if chain and chain[-1][0] in COMBINING | INDIRECT:
                raise ValueError(f"group ends in a combining condition: {g}")
            start = len(self.conds)
            for p in parts:
                self.conds += p
            self.groups.append((start, [len(p) for p in parts]))
        # pure 1: no state at all; 2: state, but re-testing unchanged memory changes nothing (hit targets <= 1, no
        # AddHits/SubHits; eval.c still tests it while WAITING); 0: tested every frame
        self.achs.append((first, len(self.groups) - first, 1 if pure else 2 if stable else 0, sum(1 << d for d in deps)))


def ascii(s):
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
         .replace("…", "...").replace("–", "-").replace("—", "-").replace("é", "e"))
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in " ".join(s.split()))


def texts(A, title_cols, desc_cols, desc_lines, upper):
    """Per achievement "title" NUL "line1\\nline2..." NUL, wrapped for the list."""
    out = []
    for a in A:
        t = ascii(a["title"]); d = ascii(a["desc"])
        if upper:
            t, d = t.upper(), d.upper()
        assert len(t) <= title_cols, (t, len(t))
        dl = textwrap.wrap(d, desc_cols)
        assert len(dl) <= desc_lines, (a["title"], dl)
        out += [t, "\n".join(dl)]
    return out


def pack_texts(strings, maxdict=128):
    """Word dictionary: bytes 0x80.. stand for its entries (phrases of whole words, each with
    the space after it). Greedy by bytes saved."""
    toks = [re.findall(r"[^ \n]+ ?|\n", s) for s in strings]
    dic = []
    while len(dic) < maxdict:
        gain = {}
        for t in toks:
            for i in range(len(t)):
                for n in range(1, 8):
                    if i + n > len(t):
                        break
                    ph = tuple(t[i:i + n])
                    if any(isinstance(x, int) for x in ph) or "\n" in ph:
                        continue
                    gain[ph] = gain.get(ph, 0) + 1
        best, score = None, 0
        for ph, cnt in gain.items():
            ln = sum(len(x) for x in ph)
            s = cnt * (ln - 1) - (ln + 1)
            if s > score:
                best, score = ph, s
        if not best:
            break
        k = len(dic)
        dic.append("".join(best))
        new = []
        for t in toks:
            o, i = [], 0
            while i < len(t):
                if tuple(t[i:i + len(best)]) == best:
                    o.append(k); i += len(best)
                else:
                    o.append(t[i]); i += 1
            new.append(o)
        toks = new
    packed = [b"".join(bytes((0x80 + x,)) if isinstance(x, int) else x.encode() for x in t) for t in toks]
    return dic, packed


def unpack(dic, b):
    return "".join(dic[c - 0x80] if c >= 0x80 else chr(c) for c in b)


def carray(ctype, name, vals, per=16):
    vals = list(vals)
    rows = [", ".join(vals[i:i + per]) for i in range(0, len(vals), per)] or ["0"]
    return f"const {ctype} {name}[] = {{\n\t" + ",\n\t".join(rows) + "\n};\n"


def compile_set(A, out_c, out_txt=None, title="", title_cols=34, desc_cols=36, desc_lines=4, upper=False):
    s = Set()
    for a in A:
        s.add(a["memaddr"])
    strings = texts(A, title_cols, desc_cols, desc_lines, upper)
    dic, packed = pack_texts(strings)
    assert all(unpack(dic, b) == t for b, t in zip(packed, strings))
    blob = bytearray()
    for b in packed:
        blob += b + b"\0"
    dblob = bytearray()
    for d in dic:
        dblob += d.encode() + b"\0"
    code = bytearray(); at = []
    for t, o, l, r, h in s.conds:
        at.append(len(code))
        code += bytes((t | o << 4, l & 255, l >> 8))
        if t not in INDIRECT:
            code += bytes((r & 255, r >> 8, h))
    assert len(code) < 0x10000 and len(blob) < 0x10000 and len(s.conds) < 0x10000
    with open(out_c, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"/* generated by tools/ach/setc.py: {ascii(title)} */\n")
        f.write('#include "eval.h"\n#include "meta.h"\n')
        f.write(f"const uint16_t ra_nmem = {len(s.mem)}, ra_ncond = {len(s.conds)}, ra_nach = {len(A)}, ra_nconst = {max(1, len(s.consts))}, ra_impure = {sum(p == 0 for _, _, p, _ in s.achs)};\n")
        f.write(carray("uint32_t", "ra_mem", (f"{m:#010x}" for m in s.mem), 8))
        f.write(carray("uint32_t", "ra_const", (f"{v}u" for v in s.consts or [0]), 10))
        f.write(carray("uint8_t", "ra_code", map(str, code), 24))
        f.write(carray("struct ra_group", "ra_group",
                       (f"{{{at[a] if sum(n) else 0},{a},{{{n[0]},{n[1]},{n[2]},{n[3]}}}}}" for a, n in s.groups), 6))
        f.write(carray("struct ra_ach", "ra_ach", (f"{{{a},{n},{p},{d:#x}u}}" for a, n, p, d in s.achs), 5))
        f.write(f"uint32_t ra_val[{len(s.mem)}], ra_dlt[{len(s.mem)}];\n")
        f.write(f"uint8_t ra_hit[{max(1, len(s.conds))}];\nuint8_t ra_st[{len(A)}], ra_hh[{len(A)}];\n")
        f.write(f"const uint16_t ra_total_points = {sum(a['points'] for a in A)};\n")
        f.write(carray("uint8_t", "ra_points", (str(a["points"]) for a in A), 20))
        f.write(carray("uint8_t", "ra_text", map(str, blob), 24))
        f.write(carray("char", "ra_dict", map(str, dblob), 24))
    if out_txt:
        with open(out_txt, "w", encoding="utf-8", newline="\n") as f:
            for a in A:
                f.write(f"ach\t{a['id']}\t{a['points']}\t{a['memaddr']}\t{ascii(a['title'])}\n")
    return dict(achievements=len(A), points=sum(a["points"] for a in A), memrefs=len(s.mem),
                conditions=len(s.conds), consts=len(s.consts), code=len(code), text=sum(map(len, strings)),
                packed=len(blob) + len(dblob), pure=sum(p == 1 for _, _, p, _ in s.achs), stable=sum(p == 2 for _, _, p, _ in s.achs))
