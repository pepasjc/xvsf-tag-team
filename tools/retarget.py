"""Re-target assembled US patches ([(address, bytes)]) to another region's executable with
tools/regionmap.py.  The patch modules keep US addresses as their source of truth; for the US
disc this module is not used at all (the US build is unchanged by construction).

Every absolute reference inside a patch is found and mapped, or the build stops:
    * the patch address itself          -> RegionMap.code (matched code on both sides)
    * j / jal targets                   -> inside one of our own code blobs: rebased with the blob;
                                           else RegionMap.entry (call-site evidence) / code
    * lui + 16-bit offset pairs         -> full address rebuilt, mapped (blob: rebased; data: RegionMap.data,
                                           falling back to entry for code addresses), written back with the
                                           %hi carry; all users of one lui must agree on the new high half
    * an offset whose lui is in the ORIGINAL code before a small in-place patch (e.g. `lw v0,0x21bc(v0)`
      written over `lb v0,0x278c(v0)`): the lui is looked up in the US executable, the address mapped,
      and the other executable must have the right high half at the matching place
    * data words that look like pointers
Patches of 32 bytes or more are "blobs" (new code in dead ranges); smaller ones are in-place "sites".
`report` lists every decision with its evidence.
"""
import struct, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import regionmap as rm
from regionmap import Unmapped

BASE = rm.BASE
WRITES_RT = {0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26}
STORES = {0x28, 0x29, 0x2a, 0x2b, 0x2e}
IBASE = rm.IBASE
sx = lambda v: v - 0x10000 if v & 0x8000 else v
addrlike = lambda hi: 0x8000 <= hi <= 0x8020


def writes(w, reg):
    op = w >> 26
    if op == 0: return ((w >> 11) & 31) == reg and (w & 0x3F) not in (8,)
    if op in WRITES_RT: return ((w >> 16) & 31) == reg
    if op == 3: return reg == 31
    return False


class Retarget:
    def __init__(self, region, patches, extra_blobs=()):
        """extra_blobs: [(us_addr, size, region_addr)] of code that is placed separately (the loader)"""
        self.r = rm.get(region)
        self.patches = self._merge([(a, bytes(d)) for a, d in patches])
        self.report = []
        self.blobmap = [(a, n, j) for a, n, j in extra_blobs]
        for a, d in self.patches:
            if len(d) >= 32:
                j, how = self.r.code(a, need=1)
                # the whole range must be the same (dead) code on both sides
                for o in range(0, len(d), 4):
                    jj, _ = self.r.code(a + o, need=1)
                    if jj != j + o: raise Unmapped(f"blob {a:08x}: range is not contiguous in the other executable at +{o:x}")
                self.blobmap.append((a, len(d), j))
                self.report.append(f"blob  {a:08x} +{len(d):3d} -> {j:08x}   ({how})")
        self.U = self.r.U; self.J = self.r.J

    @staticmethod
    def _merge(pl):
        """in-place patches that touch neighbouring words belong together (a lui and its offset are
        sometimes written as two entries); later entries win where they overlap"""
        blobs = [(a, d) for a, d in pl if len(d) >= 32]
        mem = {}
        for a, d in pl:
            if len(d) < 32:
                for i, b in enumerate(d): mem[a + i] = b
        sites = []
        for x in sorted(mem):
            if sites and sites[-1][0] + len(sites[-1][1]) == x: sites[-1][1].append(mem[x])
            else: sites.append([x, bytearray([mem[x]])])
        for a, d in sites: assert a % 4 == 0 and len(d) % 4 == 0, f"site {a:08x} not word aligned"
        return blobs + [(a, bytes(d)) for a, d in sites]

    # ---- reference mapping
    def ref(self, A, kind, where):
        for a, n, j in self.blobmap:
            if a <= A < a + n: return j + (A - a), "own code"
        if kind == "j":
            return self.r.entry(A)
        try: return self.r.data(A)
        except Unmapped as e1:
            try: return self.r.entry(A)
            except Unmapped: raise Unmapped(f"{where}: {e1}")

    def _pairs(self, W, i):
        """lo users of the lui at W[i] inside the same patch"""
        rt = (W[i] >> 16) & 31; users = []
        for k in range(i + 1, len(W)):
            w = W[k]; op = w >> 26
            if op in IBASE and ((w >> 21) & 31) == rt:
                users.append(k)
                if ((w >> 16) & 31) == rt and op not in STORES: break
                continue
            if op == 0 and (w & 0x3F) in (0x20, 0x21) and ((w >> 11) & 31) == rt and rt in ((w >> 21) & 31, (w >> 16) & 31):
                continue                                        # addu reg, reg, index: still "address + index"
            if writes(w, rt): break
            if op in (2, 3) or (op == 0 and (w & 0x3F) in (8, 9)):
                # the delay slot still executes with the register
                if k + 1 < len(W):
                    w2 = W[k + 1]
                    if (w2 >> 26) in IBASE and ((w2 >> 21) & 31) == rt: users.append(k + 1)
                break
        return users

    def _words(self, addr, data, site):
        n = len(data) // 4
        W = list(struct.unpack(f"<{n}I", data[:n * 4])); out = list(W); done = set()
        tail = data[n * 4:]
        for i, w in enumerate(W):
            if i in done: continue
            op = w >> 26; here = f"{addr + 4 * i:08x}"
            if op in (2, 3):
                T = 0x80000000 | (w & 0x3FFFFFF) << 2
                j, how = self.ref(T, "j", here)
                out[i] = (w & 0xFC000000) | (j >> 2 & 0x3FFFFFF)
                self.report.append(f"  {here} {'jal' if op == 3 else 'j  '} {T:08x} -> {j:08x}   ({how})")
            elif op == 15 and addrlike(w & 0xFFFF):
                users = self._pairs(W, i)
                if not users and site:
                    # the user may be ORIGINAL code right after the patch
                    rt = (w >> 16) & 31; p = (addr - BASE) // 4 + n; ok = False
                    for q in range(p, p + 8):
                        u = self.U[q]
                        if (u >> 26) in IBASE and ((u >> 21) & 31) == rt:
                            ori = (u >> 26) == 0x0d
                            A = ((w & 0xFFFF) << 16 | (u & 0xFFFF)) if ori else (((w & 0xFFFF) << 16) + sx(u & 0xFFFF)) & 0xFFFFFFFF
                            j, how = self.ref(A, "d", here)
                            jq, _ = self.r.code(BASE + 4 * q, need=1)
                            if (self.J[(jq - BASE) // 4] & 0xFFFF) != (j & 0xFFFF):
                                raise Unmapped(f"{here}: lui pairs with the original offset at {BASE + 4 * q:08x}, which would have to change for {j:08x}")
                            out[i] = (w & 0xFFFF0000) | ((j >> 16) if ori else ((j + 0x8000) >> 16) & 0xFFFF)
                            self.report.append(f"  {here} lui for the original offset at {BASE + 4 * q:08x}: {A:08x} -> {j:08x}   ({how})")
                            ok = True; break
                        if writes(u, rt): break
                    if ok: continue
                if not users:
                    raise Unmapped(f"{here}: lui 0x{w & 0xFFFF:04x} without an offset user inside the patch - needs a manual rule")
                his = set()
                for k in users:
                    w2 = W[k]; ori = (w2 >> 26) == 0x0d
                    A = ((w & 0xFFFF) << 16 | (w2 & 0xFFFF)) if ori else (((w & 0xFFFF) << 16) + sx(w2 & 0xFFFF)) & 0xFFFFFFFF
                    j, how = self.ref(A, "d", here)
                    hi = (j >> 16) if ori else ((j + 0x8000) >> 16) & 0xFFFF
                    his.add(hi); out[k] = (w2 & 0xFFFF0000) | (j & 0xFFFF); done.add(k)
                    self.report.append(f"  {here} lui+{'ori' if ori else 'lo '} {A:08x} -> {j:08x}   ({how})")
                if len(his) != 1: raise Unmapped(f"{here}: the users of one lui need different high halves {sorted(hex(h) for h in his)}")
                out[i] = (w & 0xFFFF0000) | his.pop()
            elif site and op in IBASE and ((w >> 21) & 31) not in (0, 28, 29, 30):
                rs = (w >> 21) & 31
                # was the base register loaded by a lui in the ORIGINAL code just before this patch?
                p = (addr - BASE) // 4 + i - 1; src = None
                # inside the patch first
                for k in range(i - 1, -1, -1):
                    if writes(W[k], rs): src = ("patch", k); break
                    p -= 1
                if src is None:
                    for _ in range(16):
                        u = self.U[p]
                        if (u >> 26) == 15 and ((u >> 16) & 31) == rs and addrlike(u & 0xFFFF): src = ("orig", p); break
                        if writes(u, rs) or (u >> 26) in (1, 2, 3, 4, 5, 6, 7) or (u == 0x03E00008): break
                        p -= 1
                if src and src[0] == "orig":
                    u = self.U[src[1]]; ori = op == 0x0d
                    A = ((u & 0xFFFF) << 16 | (w & 0xFFFF)) if ori else (((u & 0xFFFF) << 16) + sx(w & 0xFFFF)) & 0xFFFFFFFF
                    j, how = self.ref(A, "d", here)
                    hi = (j >> 16) if ori else ((j + 0x8000) >> 16) & 0xFFFF
                    jl, _ = self.r.code(BASE + 4 * src[1], need=1)
                    got = self.J[(jl - BASE) // 4] & 0xFFFF
                    if got != hi: raise Unmapped(f"{here}: offset relies on the original lui at {BASE + 4 * src[1]:08x}; the other executable has 0x{got:04x} there, needed 0x{hi:04x} for {j:08x}")
                    out[i] = (w & 0xFFFF0000) | (j & 0xFFFF)
                    self.report.append(f"  {here} offset on original lui: {A:08x} -> {j:08x}   ({how})")
            elif 0x80010000 <= w < 0x80100000 and not w & 3:
                j, how = self.ref(w, "d", here)
                out[i] = j
                self.report.append(f"  {here} pointer word {w:08x} -> {j:08x}   ({how})")
        return struct.pack(f"<{n}I", *out) + tail

    def run(self):
        res = []
        for a, d in self.patches:
            if len(d) >= 32:
                j = next(jb for ua, n, jb in self.blobmap if ua == a and n == len(d))
                res.append((j, self._words(a, d, False)))
            else:
                try:
                    j, how = self.r.code(a)
                    for o in range(0, len(d), 4):
                        jj, _ = self.r.code(a + o, need=1)
                        if jj != j + o: raise Unmapped(f"site {a:08x}: not contiguous in the other executable")
                except Unmapped:
                    # a data table: its address must be referenced by matched code (or sit between such references)
                    j, how = self.r.data(a)
                    for o in range(0, len(d), 4):
                        if self.r.data(a + o)[0] != j + o: raise Unmapped(f"data site {a:08x}: not contiguous in the other executable")
                    how = "data: " + how
                self.report.append(f"site  {a:08x} +{len(d):3d} -> {j:08x}   ({how})")
                res.append((j, self._words(a, d, True)))
        return res


def us_patches():
    """the patch list of the US build, in build order (tools/mktagdisc.py), without the loader"""
    import nsppatch, tagpatch, palpatch, aipatch, hudpatch, roundpatch, bgmpatch, padpatch, diffpatch, balpatch
    pl = list(nsppatch.patches()) + list(tagpatch.patches()) + list(palpatch.patches()) + list(aipatch.patches()) + list(hudpatch.patches())
    pl += list(roundpatch.patches()) + list(bgmpatch.patches()) + list(padpatch.patches()) + list(diffpatch.rank_patches()) + list(balpatch.patches())
    return pl


if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else "jp"
    rt = Retarget(region, us_patches())
    try:
        out = rt.run()
    finally:
        print("\n".join(rt.report))
    print(f"{len(out)} patches re-targeted for {region}")
