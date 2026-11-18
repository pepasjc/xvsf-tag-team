"""Address map between the US executable (SLUS-00627) and another region's executable of
X-Men vs. Street Fighter (Japan: SLPS-01284), built from the two files by signature matching.
It refuses to guess: every answer carries its evidence, anything else raises Unmapped.

How
  1. Both images are turned into token streams with the relocatable fields masked: j/jal targets,
     lui of an address-like value (0x8000..0x8020), the 16-bit offset of an instruction whose base
     register was loaded by such a lui within the previous 8 instructions, and data words that look
     like pointers (0x80010000..0x80100000).  Everything else must be bit-identical.
  2. k-grams (K = 6 tokens) that occur exactly once in BOTH streams are anchors; each anchor is
     extended in both directions while the tokens stay equal.  That gives matched runs; a US
     position that two different anchors want to map to different places is marked ambiguous.
  3. Data addresses: wherever a lui+offset pair, a j/jal target or a pointer word sits at matched
     positions, the two full values form a (US, other) pair.  A US value seen with two different
     partners is ambiguous.

Queries
  code(a)   -> (addr, run)        a lies in a matched run of `run` tokens (bit-identical modulo the masks)
  data(a)   -> (addr, how)        how = "seen N" (N independent references agree, none disagrees) or
                                  "interp" (not referenced itself; the nearest referenced addresses
                                  below and above both have the same delta, and are < 0x1000 away)
  any(a)    -> code(a) if a is in a matched run, else data(a)

    python regionmap.py jp                 statistics
    python regionmap.py jp ADDR...         map addresses (hex)
"""
import os, struct, sys, bisect, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BASE, HDR, K = 0x80010000, 0x800, 6
EXE = {"us": os.path.join(ROOT, "disc", "files", "SLUS_006.27"),
       "jp": os.path.join(ROOT, "work", "jap", "files", "SLPS_012.84")}
LOADS = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2a, 0x2b, 0x2e}
IBASE = LOADS | {0x09, 0x0d}


class Unmapped(Exception):
    pass


def words(path):
    d = open(path, "rb").read()[HDR:]
    return struct.unpack(f"<{len(d) // 4}I", d[:len(d) // 4 * 4])


def tokens(W):
    T = []
    n = len(W)
    for i, w in enumerate(W):
        op = w >> 26
        if op in (2, 3):
            T.append(-1 - op)                                   # j / jal, target masked
        elif op == 15 and 0x8000 <= (w & 0xFFFF) <= 0x8020:
            T.append(-0x100 - ((w >> 16) & 31))                 # lui rt, <address high>
        elif op in IBASE:
            rs = (w >> 21) & 31
            masked = False
            if rs:
                for k in range(1, 9):
                    if i - k < 0: break
                    p = W[i - k]
                    if (p >> 26) == 15 and ((p >> 16) & 31) == rs and 0x8000 <= (p & 0xFFFF) <= 0x8020:
                        masked = True; break
            T.append(-0x10000 - (w >> 16) if masked else w)     # offset masked
        elif 0x80010000 <= w < 0x80100000 and not w & 3:
            T.append(-5)                                        # pointer-like data word
        else:
            T.append(w)
    return T


class RegionMap:
    def __init__(self, region="jp"):
        self.region = region
        self.U = words(EXE["us"]); self.J = words(EXE[region])
        self.TU = tokens(self.U); self.TJ = tokens(self.J)
        self._align()
        self._datamap()

    # ---- code alignment
    def _align(self):
        TU, TJ = self.TU, self.TJ
        def grams(T):
            g = collections.defaultdict(list)
            for i in range(len(T) - K + 1):
                key = tuple(T[i:i + K])
                if all(x == 0 for x in key): continue           # zero padding
                g[key].append(i)
            return g
        gu, gj = grams(TU), grams(TJ)
        self.m = m = [-1] * len(TU)                             # US word index -> other word index
        self.amb = set()
        # pass 1: every position covered by a k-gram that is unique in both images
        for key, pu in gu.items():
            if len(pu) != 1: continue
            pj = gj.get(key)
            if not pj or len(pj) != 1: continue
            for t in range(K):
                a, b = pu[0] + t, pj[0] + t
                if m[a] == -1: m[a] = b
                elif m[a] != b: self.amb.add(a)
        for a in self.amb: m[a] = -2
        # pass 2: fill the gaps between anchored positions from both sides; where the two sides want
        # different things for the same position (e.g. a common prologue between two functions that
        # sit in a different order), the position stays unmapped (ambiguous)
        n = len(TU); i = 0
        while i < n:
            if m[i] >= 0: i += 1; continue
            g0 = i
            while i < n and m[i] < 0: i += 1
            g1 = i                                              # gap [g0, g1)
            le = g0
            if g0 > 0 and m[g0 - 1] >= 0:
                d = m[g0 - 1] - (g0 - 1)
                while le < g1 and 0 <= le + d < len(TJ) and TU[le] == TJ[le + d] and m[le] != -2: le += 1
                dl = d
            rs_ = g1
            if g1 < n and m[g1] >= 0:
                d = m[g1] - g1
                while rs_ > g0 and 0 <= rs_ - 1 + d < len(TJ) and TU[rs_ - 1] == TJ[rs_ - 1 + d] and m[rs_ - 1] != -2: rs_ -= 1
                dr = d
            if le > g0 and rs_ < g1 and dl == dr:
                for k in range(g0, le): m[k] = k + dl
                for k in range(max(rs_, le), g1): m[k] = k + dr
            else:
                lo_end = min(le, rs_) if rs_ < g1 else le       # the left side keeps what the right side does not claim
                hi_start = max(le, rs_) if le > g0 else rs_
                for k in range(g0, lo_end): m[k] = k + dl
                for k in range(hi_start, g1): m[k] = k + dr
                for k in range(lo_end, hi_start):
                    if le > g0 and rs_ < g1 and rs_ <= k < le: m[k] = -2; self.amb.add(k)
        # run lengths
        self.run = run = [0] * len(TU)
        i = 0
        while i < len(TU):
            if m[i] < 0: i += 1; continue
            j = i
            while j + 1 < len(TU) and m[j + 1] == m[j] + 1: j += 1
            for k in range(i, j + 1): run[k] = j - i + 1
            i = j + 1

    # ---- data pairs
    def _datamap(self):
        U, J, m = self.U, self.J, self.m
        pairs = collections.defaultdict(collections.Counter)
        jp = collections.defaultdict(collections.Counter)      # j / jal targets only
        sx = lambda v: v - 0x10000 if v & 0x8000 else v
        for i, w in enumerate(U):
            j = m[i]
            if j < 0: continue
            x = J[j]; op = w >> 26
            if op in (2, 3):
                jp[0x80000000 | (w & 0x3FFFFFF) << 2][0x80000000 | (x & 0x3FFFFFF) << 2] += 1
            elif op == 15 and 0x8000 <= (w & 0xFFFF) <= 0x8020:
                rt = (w >> 16) & 31
                for k in range(1, 9):
                    if i + k >= len(U) or m[i + k] != j + k: break
                    w2, x2 = U[i + k], J[j + k]; op2 = w2 >> 26
                    rs2, rt2 = (w2 >> 21) & 31, (w2 >> 16) & 31
                    if op2 in IBASE and rs2 == rt:
                        f = (lambda hi, lo: (hi << 16) | lo) if op2 == 0x0d else (lambda hi, lo: ((hi << 16) + sx(lo)) & 0xFFFFFFFF)
                        pairs[f(w & 0xFFFF, w2 & 0xFFFF)][f(x & 0xFFFF, x2 & 0xFFFF)] += 1
                        if rt2 == rt and op2 not in (0x28, 0x29, 0x2a, 0x2b, 0x2e): break   # register rewritten (address completed / loaded over)
                        continue
                    # the register stops holding "lui value" when anything else writes it, or control flow may leave
                    if op2 == 0:
                        if ((w2 >> 11) & 31) == rt or (w2 & 0x3F) in (8, 9): break          # rd write, jr / jalr
                    elif op2 in (2, 3): break
                    elif op2 in (1, 4, 5, 6, 7): break
                    elif rt2 == rt and op2 not in (0x28, 0x29, 0x2a, 0x2b, 0x2e): break
            elif 0x80010000 <= w < 0x80100000 and not w & 3 and self.TU[i] == -5:
                pairs[w][x] += 1
        self.seenj = {a: (next(iter(c)), sum(c.values())) for a, c in jp.items() if len(c) == 1}
        self.jamb = {a: dict(c) for a, c in jp.items() if len(c) > 1}
        self.seen = {}; self.damb = {}
        for a, c in pairs.items():
            if len(c) == 1: self.seen[a] = (next(iter(c)), sum(c.values()))
            else: self.damb[a] = dict(c)
        self.skeys = sorted(self.seen)

    # ---- queries
    def _support(self, i):
        """equal tokens before / after word i under its own delta (the position itself counts for both)"""
        d = self.m[i] - i; TU, TJ = self.TU, self.TJ
        b = 0
        while i - b >= 0 and 0 <= i - b + d < len(TJ) and TU[i - b] == TJ[i - b + d]: b += 1
        f = 0
        while i + f < len(TU) and i + f + d < len(TJ) and TU[i + f] == TJ[i + f + d]: f += 1
        return b, f

    def _fwd(self, a, j):
        i, k = (a - BASE) >> 2, (j - BASE) >> 2; f = 0
        while 0 <= i + f < len(self.TU) and 0 <= k + f < len(self.TJ) and self.TU[i + f] == self.TJ[k + f]: f += 1
        return f

    def code(self, a, need=4):
        """a position inside code (hook site): needs `need` equal tokens on BOTH sides"""
        i = (a - BASE) >> 2
        if not (0 <= i < len(self.m)) or a & 3: raise Unmapped(f"{a:08x}: not a word in the executable")
        if self.m[i] == -2: raise Unmapped(f"{a:08x}: ambiguous (the code before and after it would map it to different places)")
        if self.m[i] < 0: raise Unmapped(f"{a:08x}: no matching code/data in the {self.region} executable")
        b, f = self._support(i)
        if min(b, f) < need: raise Unmapped(f"{a:08x}: only {b} tokens before / {f} after match at {BASE + self.m[i] * 4:08x}")
        # a run of zero words (bss, padding) "matches" at any shift: positions inside one prove nothing
        lo, hi = max(0, i - K), min(len(self.TU), i + K + 1)
        if len({t for t in self.TU[lo:hi] if t != 0}) < 4: raise Unmapped(f"{a:08x}: inside a zero-filled area, the alignment proves nothing there")
        return BASE + self.m[i] * 4, f"{b} before / {f} after"

    def entry(self, a):
        """a function entry or jump target: the j/jal references decide, and the code must match
        K tokens forward from there; without references: code()"""
        if a in self.jamb: raise Unmapped(f"{a:08x}: call targets disagree {self.jamb[a]}")
        if a in self.seenj:
            j, n = self.seenj[a]; f = self._fwd(a, j)
            if f < K: raise Unmapped(f"{a:08x}: {n} calls say {j:08x} but only {f} tokens match there")
            return j, f"{n} call sites + {f} tokens forward"
        return self.code(a)

    def data(self, a):
        """the operand of a lui+offset pair or a pointer word (variables, tables, constants)"""
        if a in self.damb: raise Unmapped(f"{a:08x}: ambiguous data address {self.damb[a]}")
        if a in self.seen: return self.seen[a][0], f"seen {self.seen[a][1]}"
        i = (a - BASE) >> 2
        if 0 <= i < len(self.m) and self.m[i] >= 0:
            lo, hi = max(0, i - K), min(len(self.TU), i + K + 1)
            if len({t for t in self.TU[lo:hi] if t != 0}) >= 4:
                b, f = self._support(i)
                if b + f - 1 >= K: return BASE + self.m[i] * 4 + (a & 3), f"content {b} before / {f} after"
        k = bisect.bisect_left(self.skeys, a)
        lo = self.skeys[k - 1] if k else None; hi = self.skeys[k] if k < len(self.skeys) else None
        if lo is None or hi is None: raise Unmapped(f"{a:08x}: outside the referenced data")
        dl = self.seen[lo][0] - lo; dh = self.seen[hi][0] - hi
        if dl != dh or a - lo > 0x1000 or hi - a > 0x1000:
            raise Unmapped(f"{a:08x}: not referenced, neighbours {lo:08x} ({dl:+x}) / {hi:08x} ({dh:+x})")
        return a + dl, f"interp {lo:08x}..{hi:08x}"

    def any(self, a):
        for f in (self.entry, self.data):
            try: return f(a)
            except Unmapped as ex: last = ex
        raise last

    def stats(self):
        n = len(self.m); matched = sum(1 for x in self.m if x >= 0)
        nz = sum(1 for i in range(n) if self.U[i])
        code_end = (0x80098000 - BASE) >> 2
        mc = sum(1 for x in self.m[:code_end] if x >= 0)
        deltas = collections.Counter((self.m[i] - i) * 4 for i in range(n) if self.m[i] >= 0)
        return dict(words=n, nonzero=nz, matched=matched, matched_below_98000=mc, of=code_end, ambiguous=len(self.amb),
                    data_seen=len(self.seen), data_ambiguous=len(self.damb), deltas=deltas.most_common(12))


_cache = {}


def get(region="jp"):
    if region not in _cache: _cache[region] = RegionMap(region)
    return _cache[region]


if __name__ == "__main__":
    r = get(sys.argv[1] if len(sys.argv) > 1 else "jp")
    if len(sys.argv) > 2:
        for s in sys.argv[2:]:
            a = int(s, 16)
            try: j, how = r.any(a); print(f"{a:08x} -> {j:08x}  ({how})")
            except Unmapped as ex: print("UNMAPPED", ex)
    else:
        st = r.stats()
        print(f"{st['matched']} of {st['words']} words matched ({st['matched_below_98000']} of {st['of']} below 0x80098000), "
              f"{st['ambiguous']} ambiguous positions; data addresses seen {st['data_seen']}, ambiguous {st['data_ambiguous']}")
        print("address deltas of matched words (bytes: count):", [(f"{d:+x}", c) for d, c in st["deltas"]])
        for a, c in sorted(r.damb.items())[:40]: print(f"  ambiguous data {a:08x}: " + ", ".join(f"{k:08x} x{v}" for k, v in c.items()))
