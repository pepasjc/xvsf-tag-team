"""Relocation of Marvel Super Heroes vs. Street Fighter (SLUS-00793) character files DAT/PLxx_10.A0.

Every character is on the disc twice: PLxx_10.A0 (P1 slot, file loaded at 0x800bbfe4, code section at 0x800bc000)
and PLxx_20.A0 (P2 slot, file loaded at 0x801448e4).  The two links differ only in the relocated words, so diffing
them gives the complete relocation table (as tools/reloc.py does for XvSF), and the file can be loaded at ANY
4-aligned address (except a few forbidden residues, see safe()).

A0 file:  u32 3, then (offset, size) of 3 sections:
    sec1  code + data (resident)                        offset 0x1c
    sec2  kind-6 sprite set (stashed in SPU RAM by the game for main characters) - registered as set slot+8
    sec3  sound bank (uploaded to SPU, then scratch)
Relocations exist only in sec1 and (pointer words) sec2.

Relocation kinds (word index i, delta d = new file base - 0x800bbfe4):
    PTR  32-bit pointer                     w += d
    J26  j / jal into the overlay           26-bit field += d >> 2
    LO   lo16 user (addiu, lw, sw ...)      low half += d  (the matching lui absorbs the carry)
    HI   lui                                high half = (target + d + 0x8000) >> 16, target = lui<<16 + s16 lo of
                                            (one of) its lo16 users; a lui without users is dead (target lo = 0)

    python reloc.py verify            _10 -> _20, _20 -> _10 exact (except padding noise); table model == relocate()
    python reloc.py stats             counts per character
    python reloc.py safe              forbidden base residues per character (lui shared by lo16s of different carry)
    python reloc.py emit C BASE OUT   write PLxx_10 relocated so that the FILE starts at BASE
"""
import os, struct, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, ".."))
FILES = os.path.join(GAME, "work", "loader", "files")      # extracted by mkdisc.py extract
B10, B20 = 0x800bbfe4, 0x801448e4                           # file load addresses of the two links
NCHAR = 0x17
LO_OPS = {0x09: "addiu", 0x20: "lb", 0x21: "lh", 0x23: "lw", 0x24: "lbu", 0x25: "lhu",
          0x28: "sb", 0x29: "sh", 0x2B: "sw", 0x22: "lwl", 0x26: "lwr", 0x2A: "swl", 0x2E: "swr"}


def sext(v):
    return v - 0x10000 if v & 0x8000 else v


def path(c, s):
    return os.path.join(FILES, f"PL{c:02X}_{s}.A0")


def sections(b):
    n, = struct.unpack_from("<I", b)
    assert n == 3
    return [struct.unpack_from("<2I", b, 4 + 8 * i) for i in range(3)]


class Reloc:
    def __init__(self, c, a=None, b=None):
        self.char = c
        self.a = a if a is not None else open(path(c, "10"), "rb").read()
        self.b = b if b is not None else open(path(c, "20"), "rb").read()
        assert len(self.a) == len(self.b)
        self.sec = sections(self.a)
        self.end = self.sec[1][0] + self.sec[1][1]          # header + sec1 + sec2
        n = self.n = self.end // 4
        A = self.A = struct.unpack_from(f"<{n}I", self.a)
        B = self.B = struct.unpack_from(f"<{n}I", self.b)
        assert self.a[self.end:] == self.b[self.end:], "sec3 differs"
        D = B20 - B10
        self.ptr, self.j26, self.hi, self.lo, self.noise = [], [], [], [], []
        for i in range(n):
            x, y = A[i], B[i]
            if x == y:
                continue
            op = x >> 26
            if (y - x) & 0xFFFFFFFF == D and B10 <= x < B10 + 0x200000:
                self.ptr.append(i)
            elif op in (2, 3) and (y >> 26) == op and ((y - x) & 0x3FFFFFF) == D >> 2:
                self.j26.append(i)
            elif op == 0x0F and (y >> 16) == (x >> 16) and ((y - x) & 0xFFFF) in (D >> 16, (D >> 16) + 1):
                self.hi.append(i)
            elif op in LO_OPS and (y >> 16) == (x >> 16) and ((y - x) & 0xFFFF) == (D & 0xFFFF):
                self.lo.append(i)
            else:
                self.noise.append(i)        # padding that differs between the links (verify checks it)
        self._pair()

    def _good(self, h, l):
        A, B = self.A, self.B
        ta = ((A[h] & 0xFFFF) << 16) + sext(A[l] & 0xFFFF)
        tb = ((B[h] & 0xFFFF) << 16) + sext(B[l] & 0xFFFF)
        return tb - ta == B20 - B10

    def _pair(self):
        """For every lui, its lo16 users: same register, the two links agree on the full address (this fixes the
        carry).  Searched forward then backward over a wide window (lui and lo16 can sit in different blocks);
        the nearest one gives the lui's target, all of them count for the carry check (forbidden())."""
        A = self.A
        hiset, loset = set(self.hi), set(self.lo)
        self.hi_t, self.hi_los = {}, collections.defaultdict(list)
        self.unpaired = []
        # 1. every lo16 -> the nearest preceding lui of its base register that gives the same address in both links
        #    (then a short look-ahead: lo16 in a delay slot / block placed before its lui)
        for l in self.lo:
            rs = (A[l] >> 21) & 31
            found = None
            for rng in (range(l - 1, max(-1, l - 4096), -1), range(l + 1, min(self.n, l + 64))):
                for h in rng:
                    if h in hiset and ((A[h] >> 16) & 31) == rs and self._good(h, l):
                        found = h
                        break
                if found is not None:
                    break
            if found is None:
                self.unpaired.append(l)
            else:
                self.hi_los[found].append(l)
        # 2. a lui no lo16 chose (its users are reached through another path): the nearest consistent lo16 within
        #    64 words either way; none = dead lui (value overwritten before use), target low half 0
        for h in self.hi:
            if not self.hi_los[h]:
                rt = (A[h] >> 16) & 31
                for k in range(1, 64):
                    for l in (h + k, h - k):
                        if l in loset and ((A[l] >> 21) & 31) == rt and self._good(h, l):
                            self.hi_los[h].append(l)
                    if self.hi_los[h]:
                        break
            if not self.hi_los[h] and h > 0:
                # lui in a branch delay slot: its user is at the branch target
                p = A[h - 1]; op = p >> 26
                t = None
                if op in (1, 4, 5, 6, 7) or (op & 0x3C) == 0x14:
                    t = h + sext(p & 0xFFFF)
                elif op in (2, 3):
                    t = ((p & 0x3FFFFFF) * 4 - (B10 & 0x0FFFFFFF)) // 4
                if t is not None:
                    for l in range(t, min(self.n, t + 32)):
                        if l in loset and ((A[l] >> 21) & 31) == rt and self._good(h, l):
                            self.hi_los[h].append(l)
                            break
            if self.hi_los[h]:
                self.hi_t[h] = self.target(h, min(self.hi_los[h], key=lambda l: (abs(l - h), l < h)))
        self.orphan = [h for h in self.hi if not self.hi_los[h]]

    def target(self, h, l, W=None):
        W = W or self.A
        return ((W[h] & 0xFFFF) << 16) + sext(W[l] & 0xFFFF)

    def forbidden(self):
        """[(lo, hi)) intervals of (base - B10) mod 0x10000 where a lui's lo16 users need different high halves"""
        iv = []
        for h, los in self.hi_los.items():
            ts = sorted({self.target(h, l) + 0x8000 for l in los})
            if ts and ts[0] != ts[-1]:
                iv.append(((-ts[-1]) & 0xFFFF, (-ts[0]) & 0xFFFF))
        return sorted(set(iv))

    def safe(self, base):
        if base & 3 or self.unpaired:
            return False
        r = (base - B10) & 0xFFFF
        return not any((a <= r < b) if a <= b else (r >= a or r < b) for a, b in self.forbidden())

    def relocate(self, base, src=0):
        S = (self.A, self.B)[src]
        W = list(S)
        d = base - (B10, B20)[src]
        for i in self.ptr:
            W[i] = (S[i] + d) & 0xFFFFFFFF
        for i in self.j26:
            W[i] = (S[i] & 0xFC000000) | ((S[i] + (d >> 2)) & 0x3FFFFFF)
        for l in self.lo:
            W[l] = (S[l] & 0xFFFF0000) | ((S[l] + d) & 0xFFFF)
        for h in self.hi:
            lo = self.hi_t.get(h, 0) & 0xFFFF
            if src == 1 and h in self.hi_t:
                lo = self.target(h, min(self.hi_los[h], key=lambda l: (abs(l - h), l < h)), self.B) & 0xFFFF
            t = ((S[h] & 0xFFFF) << 16) + sext(lo) + d
            W[h] = (S[h] & 0xFFFF0000) | (((t + 0x8000) >> 16) & 0xFFFF)
        return struct.pack(f"<{self.n}I", *W) + (self.a, self.b)[src][self.end:]

    def counts(self):
        return dict(size=len(self.a), reloc_end=self.end, PTR=len(self.ptr), J26=len(self.j26), HI=len(self.hi),
                    LO=len(self.lo), noise=len(self.noise), unpaired=len(self.unpaired), dead_lui=len(self.orphan),
                    forbidden=len(self.forbidden()))

    def table(self):
        """Loader table: u16 word indices from the file start, in-place, any order:
             PTR.. 0xffff  J26.. 0xffff  LO.. 0xffff  (HI index, target low half).. 0xffff
           Word indices fit u16 (relocated part < 256 KB)."""
        assert self.n < 0xFFFF
        out = list(self.ptr) + [0xFFFF] + list(self.j26) + [0xFFFF] + list(self.lo) + [0xFFFF]
        for h in self.hi:
            out += [h, self.hi_t.get(h, 0) & 0xFFFF]
        out.append(0xFFFF)
        return struct.pack(f"<{len(out)}H", *out)


def apply_table(img, tab, base):
    """Python model of the MIPS relocation pass (tagload.c reloc()): img = PLxx_10 bytes, file placed at base."""
    W = list(struct.unpack_from(f"<{len(img) // 4}I", img))
    T = struct.unpack_from(f"<{len(tab) // 2}H", tab)
    d = base - B10
    p = 0
    for k in range(4):
        while T[p] != 0xFFFF:
            i = T[p]; p += 1
            if k == 0:
                W[i] = (W[i] + d) & 0xFFFFFFFF
            elif k == 1:
                W[i] = (W[i] & 0xFC000000) | ((W[i] + (d >> 2)) & 0x3FFFFFF)
            elif k == 2:
                W[i] = (W[i] & 0xFFFF0000) | ((W[i] + d) & 0xFFFF)
            else:
                lo = T[p]; p += 1
                t = ((W[i] & 0xFFFF) << 16) + sext(lo) + d
                W[i] = (W[i] & 0xFFFF0000) | (((t + 0x8000) >> 16) & 0xFFFF)
        p += 1
    return struct.pack(f"<{len(W)}I", *W) + img[len(W) * 4:]


_cache = {}


def get(c):
    if c not in _cache:
        _cache[c] = Reloc(c)
    return _cache[c]


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "verify"
    if cmd == "verify":
        ok = True
        for c in range(NCHAR):
            r = get(c)
            f = r.relocate(B20, 0)
            g = r.relocate(B10, 1)
            nz = {i * 4 for i in r.noise}
            dn = {i for i in range(0, r.end, 4) if f[i:i + 4] != r.b[i:i + 4]}
            dm = {i for i in range(0, r.end, 4) if g[i:i + 4] != r.a[i:i + 4]}
            good = dn <= nz and dm <= nz and not r.unpaired
            for base in (0x80123454, 0x800d0008, B10, 0x80170000 - 4):
                if r.safe(base):
                    good &= apply_table(r.a, r.table(), base) == r.relocate(base)
            ok &= good
            print(f"PL{c:02X} {'OK ' if good else 'BAD'} diff {len(dn)}/{len(dm)} {r.counts()} table {len(r.table())}")
        print("ALL OK" if ok else "FAILURES")
    elif cmd == "stats":
        for c in range(NCHAR):
            print(f"PL{c:02X}", get(c).counts(), len(get(c).table()))
    elif cmd == "safe":
        for c in range(NCHAR):
            r = get(c)
            print(f"PL{c:02X} dead lui {len(r.orphan)} forbidden {[(hex(a), hex(b)) for a, b in r.forbidden()]}")
    elif cmd == "emit":
        c, base, out = int(argv[2], 0), int(argv[3], 16), argv[4]
        open(out, "wb").write(get(c).relocate(base))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
