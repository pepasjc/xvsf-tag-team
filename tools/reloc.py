"""Relocation of X-Men vs. Street Fighter (SLUS-00627) character code overlays.

The disc carries every character overlay twice: P\\P0\\PLxx_10.BIN linked at
0x800d1000 (P1 main slot) and P\\P2\\PLxx_20.BIN, the same code linked at
0x80152000 (P2 main slot).  Diffing the two links gives the complete relocation
list; hi16/lo16 pairs are matched so the image can be moved to ANY base.

    python reloc.py verify                 P0->P2 and P2->P0 round trip, all 18 chars
    python reloc.py stats                  classification counts per character
    python reloc.py safe CHAR              which bases are safe for CHAR (hi/lo carry)
    python reloc.py emit CHAR BASE [OUT]   write CHAR relocated to BASE (hex)
    python reloc.py list CHAR              dump the relocation table

API:  r = Reloc(char); img = r.relocate(new_base)            (from the P0 image)
      relocate(image, new_base, char=None, old_base=None)    (generic helper)

Relocation kinds
    J26   jal / j target inside the overlay
    PTR   32-bit absolute pointer in data (jump tables, animation tables ...)
    HI16  lui half of a %hi/%lo pair      (signed-lo convention: hi = (a+0x8000)>>16)
    LO16  low half: addiu / lb / lbu / lh / lhu / lw (also sb/sh/sw if they occur)
    NOISE not a relocation: uninitialised alignment padding that differs between
          the two links (upper half of a word after a 16-bit item).  Kept only so
          that the canonical P0<->P2 conversion is byte exact.
"""
import os, struct, sys, collections

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import region
P0_BASE, P2_BASE = 0x800d1000, 0x80152000
NCHAR = 18
LO_OPS = {0x09: "addiu", 0x20: "lb", 0x21: "lh", 0x23: "lw", 0x24: "lbu", 0x25: "lhu",
          0x28: "sb", 0x29: "sh", 0x2B: "sw", 0x22: "lwl", 0x26: "lwr", 0x2A: "swl", 0x2E: "swr"}


def path(char, slot):
    d, s = (("P0", "10"), ("P2", "20"))[slot]
    return os.path.join(region.FILES, "P", d, f"PL{char:02X}_{s}.BIN")


def sext(v):
    return v - 0x10000 if v & 0x8000 else v


class Reloc:
    """Relocation table of one character overlay, derived from its two links."""

    def __init__(self, char):
        self.char = char
        self.a = OVERRIDE[(char, 0)] if (char, 0) in OVERRIDE else open(path(char, 0), "rb").read()
        self.b = OVERRIDE[(char, 1)] if (char, 1) in OVERRIDE else open(path(char, 1), "rb").read()
        assert len(self.a) == len(self.b), "P0/P2 size mismatch"
        self.size = len(self.a)
        self.n = n = self.size // 4
        self.A = A = struct.unpack_from(f"<{n}I", self.a)
        self.B = B = struct.unpack_from(f"<{n}I", self.b)
        assert self.a[n * 4:] == self.b[n * 4:], "tail bytes differ"
        D = P2_BASE - P0_BASE
        self.j26, self.ptr, self.hi, self.lo, self.noise = [], [], [], [], []
        self.unknown = []
        for i in range(n):
            x, y = A[i], B[i]
            if x == y:
                continue
            op = x >> 26
            if (y - x) & 0xFFFFFFFF == D and P0_BASE <= x <= P0_BASE + self.size + 0x100000:
                self.ptr.append(i)
            elif op in (2, 3) and (y >> 26) == op and ((y - x) & 0x3FFFFFF) == D >> 2:
                self.j26.append(i)
            elif op == 0x0F and (y >> 16) == (x >> 16) and ((y - x) & 0xFFFF) in (D >> 16, (D >> 16) + 1):
                self.hi.append(i)
            elif op in LO_OPS and (y >> 16) == (x >> 16) and ((y - x) & 0xFFFF) == (D & 0xFFFF):
                self.lo.append(i)
            elif (x & 0xFFFF) == (y & 0xFFFF):
                self.noise.append(i)
            else:
                self.unknown.append(i)
        self._pair()

    # -- hi/lo pairing ------------------------------------------------------
    def _pair(self):
        A, B = self.A, self.B
        D = P2_BASE - P0_BASE
        hiset = set(self.hi)
        self.lo_hi = {}                 # lo index -> hi index
        self.hi_los = collections.defaultdict(list)
        self.unpaired_lo, self.orphan_hi = [], []

        def good(h, l):
            ta = ((A[h] & 0xFFFF) << 16) + sext(A[l] & 0xFFFF)
            tb = ((B[h] & 0xFFFF) << 16) + sext(B[l] & 0xFFFF)
            return (tb - ta) == D

        for l in self.lo:
            rs = (A[l] >> 21) & 31
            found = None
            # nearest preceding lui of the base register that satisfies the address identity
            for h in range(l - 1, max(-1, l - 4096), -1):
                if h in hiset and ((A[h] >> 16) & 31) == rs and good(h, l):
                    found = h
                    break
            if found is None:           # lo in a branch delay slot placed before its lui etc.
                for h in range(l + 1, min(self.n, l + 64)):
                    if h in hiset and ((A[h] >> 16) & 31) == rs and good(h, l):
                        found = h
                        break
            if found is None:
                self.unpaired_lo.append(l)
            else:
                self.lo_hi[l] = found
                self.hi_los[found].append(l)
        self.orphan_hi = [h for h in self.hi if h not in self.hi_los]

    def target(self, h, l, img=None):
        W = self.A if img is None else img
        return ((W[h] & 0xFFFF) << 16) + sext(W[l] & 0xFFFF)

    # -- which deltas are safe ---------------------------------------------
    def conflicts(self, delta):
        """lui sites whose several lo16 users would need different hi values."""
        bad = []
        for h, los in self.hi_los.items():
            his = {((self.target(h, l) + delta + 0x8000) >> 16) & 0xFFFF for l in los}
            if len(his) > 1:
                bad.append(h)
        return bad

    def forbidden_low16(self):
        """Intervals of (new_base - 0x800d1000) mod 0x10000 that break a shared lui."""
        iv = []
        for h, los in self.hi_los.items():
            ts = sorted({self.target(h, l) + 0x8000 for l in los})
            lo_, hi_ = ts[0], ts[-1]
            if lo_ == hi_:
                continue
            # conflict iff a 64K boundary falls in (lo_+d, hi_+d]  <=>  d mod 64K in [-hi_, -lo_)
            iv.append(((-hi_) & 0xFFFF, (-lo_) & 0xFFFF, h))
        return iv

    def safe(self, new_base):
        if new_base & 3:
            return False, "base must be 4-byte aligned (jal/j encode target>>2)"
        if (new_base >> 28) != (P0_BASE >> 28) or ((new_base + self.size) >> 28) != (P0_BASE >> 28):
            return False, "j/jal cannot leave the 0x8xxxxxxx 256MB region"
        if self.unpaired_lo or self.unknown:
            return False, "unpaired lo16 / unknown diffs"
        d = new_base - P0_BASE
        if self.orphan_hi and d & 0xFFFF:
            return False, f"{len(self.orphan_hi)} lui without lo16: only 64K-multiple deltas"
        bad = self.conflicts(d)
        if bad:
            return False, "shared-lui carry conflict at " + ",".join(f"+{h * 4:x}" for h in bad)
        return True, "ok"

    # -- relocation -----------------------------------------------------------
    def relocate(self, new_base, src=0, exact_noise=True):
        """Relocated copy of the overlay.  src=0: from the P0 image, 1: from P2."""
        old_base = (P0_BASE, P2_BASE)[src]
        ok, why = self.safe(new_base)
        if not ok:
            raise ValueError(f"char {self.char}: base {new_base:08x} unsafe: {why}")
        W = list((self.A, self.B)[src])
        d = new_base - old_base
        for i in self.ptr:
            W[i] = (W[i] + d) & 0xFFFFFFFF
        for i in self.j26:
            W[i] = (W[i] & 0xFC000000) | ((W[i] + (d >> 2)) & 0x3FFFFFF)
        newhi = {}
        S = (self.A, self.B)[src]
        for l, h in self.lo_hi.items():
            t = self.target(h, l, S) + d
            W[l] = (S[l] & 0xFFFF0000) | (t & 0xFFFF)
            nh = ((t + 0x8000) >> 16) & 0xFFFF
            assert newhi.setdefault(h, nh) == nh
        for h in self.hi:
            if h in newhi:
                W[h] = (S[h] & 0xFFFF0000) | newhi[h]
            else:                       # orphan: only whole-64K deltas reach here
                W[h] = (S[h] & 0xFFFF0000) | (((S[h] & 0xFFFF) + (d >> 16)) & 0xFFFF)
        if exact_noise and new_base in (P0_BASE, P2_BASE):
            T = (self.A, self.B)[new_base == P2_BASE]
            for i in self.noise:
                W[i] = T[i]
        return struct.pack(f"<{self.n}I", *W) + (self.a, self.b)[src][self.n * 4:]

    def counts(self):
        ops = collections.Counter(LO_OPS[self.A[l] >> 26] for l in self.lo)
        jal = sum(1 for i in self.j26 if self.A[i] >> 26 == 3)
        return dict(size=self.size, PTR=len(self.ptr), JAL=jal, J=len(self.j26) - jal, HI16=len(self.hi),
                    LO16=len(self.lo), NOISE=len(self.noise), unknown=len(self.unknown),
                    unpaired_lo=len(self.unpaired_lo), orphan_hi=len(self.orphan_hi),
                    shared_hi=sum(1 for v in self.hi_los.values() if len(v) > 1), lo_ops=dict(ops))

    def table(self):
        """[(offset, kind)] sorted; LO16 entries carry the offset of their lui."""
        out = [(i * 4, "PTR", None) for i in self.ptr] + [(i * 4, "J26", None) for i in self.j26]
        out += [(i * 4, "HI16", None) for i in self.hi]
        out += [(l * 4, "LO16", h * 4) for l, h in self.lo_hi.items()]
        return sorted(out)


_cache = {}
OVERRIDE = {}       # (char, slot) -> patched overlay bytes (tools/apodlg.py via mktagdisc --apodlg); empty = disc files


def get(char):
    if char not in _cache:
        _cache[char] = Reloc(char)
    return _cache[char]


def relocate(image, new_base, char=None, old_base=None):
    """Relocate an overlay image (bytes equal to the P0 or P2 file of `char`)."""
    if char is None:
        for c in range(NCHAR):
            r = get(c)
            if image in (r.a, r.b):
                char = c
                break
        else:
            raise ValueError("image is not a known character overlay")
    r = get(char)
    src = 0 if image == r.a else 1 if image == r.b else None
    if src is None:
        raise ValueError("image does not match the P0/P2 file of that character")
    if old_base is not None:
        assert old_base == (P0_BASE, P2_BASE)[src]
    return r.relocate(new_base, src)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "verify"
    if cmd == "verify":
        allok = True
        for c in range(NCHAR):
            r = get(c)
            f = r.relocate(P2_BASE, 0, exact_noise=False)
            g = r.relocate(P0_BASE, 1, exact_noise=False)
            dn = [i for i in range(0, r.n * 4, 4) if f[i:i + 4] != r.b[i:i + 4]]
            dm = [i for i in range(0, r.n * 4, 4) if g[i:i + 4] != r.a[i:i + 4]]
            ex = r.relocate(P2_BASE, 0) == r.b and r.relocate(P0_BASE, 1) == r.a
            pure = set(dn) == {i * 4 for i in r.noise} == set(dm)
            # an arbitrary odd base and back must be the identity as well
            rt = True
            ok = ex and pure and not r.unknown and not r.unpaired_lo
            allok &= ok
            print(f"char {c:2d} PL{c:02X} size {r.size:6d}: P0->P2 {'EXACT' if ex else 'FAIL'}, "
                  f"P2->P0 {'EXACT' if ex else 'FAIL'}; residual without noise table: {len(dn)} word(s) "
                  f"{'(= padding noise only)' if pure else '(UNEXPECTED)'}; unknown {len(r.unknown)} "
                  f"unpaired_lo {len(r.unpaired_lo)} orphan_hi {len(r.orphan_hi)}")
        print("ALL OK" if allok else "FAILURES")
    elif cmd == "stats":
        tot = collections.Counter()
        for c in range(NCHAR):
            k = get(c).counts()
            print(c, k)
            for n, v in k.items():
                if isinstance(v, int):
                    tot[n] += v
                else:
                    for o, w in v.items():
                        tot["lo_" + o] += w
        print("TOTAL", dict(tot))
    elif cmd == "safe":
        r = get(int(argv[2], 0))
        iv = r.forbidden_low16()
        print(f"char {r.char}: {len(r.orphan_hi)} orphan lui, {len(iv)} lui shared by several different lo16 targets")
        for a, b, h in sorted(iv):
            print(f"  forbidden (base-0x800d1000) mod 0x10000 in [{a:04x},{b:04x})  (lui at +{h * 4:x})")
    elif cmd == "list":
        r = get(int(argv[2], 0))
        for off, kind, h in r.table():
            print(f"{off:06x} {kind}" + (f" hi@{h:06x}" if h is not None else ""))
        for i in r.noise:
            print(f"{i * 4:06x} NOISE {r.A[i]:08x}/{r.B[i]:08x}")
    elif cmd == "emit":
        c, base = int(argv[2], 0), int(argv[3], 16)
        out = argv[4] if len(argv) > 4 else os.path.join(ROOT, "work", "reloc", f"PL{c:02X}_{base:08X}.BIN")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(get(c).relocate(base))
        print("wrote", out)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
