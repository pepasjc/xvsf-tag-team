"""Find unreferenced code ranges in SLUS_006.27 (candidates for patch space).

A range [start, end) is reported when
  * start is a function prologue (addiu sp,sp,-N) preceded by a function end (jr ra + delay slot / padding),
  * NO address inside it is the target of a jal / j / conditional branch from outside the range,
    equals a data word, or is built by a lui+addiu/ori pair, anywhere in the EXE or in any overlay
    (P/P0..P4: character, reduced, stage, select, opdemo code).
Static only: confirm with a break-fill boot+fight test (work/deadtest.py) before using a range.

    python deadcode.py [minsize=256]
"""
import glob, os, struct, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EXE = open(os.path.join(ROOT, "disc/files/SLUS_006.27"), "rb").read()
TADDR, TSIZE = struct.unpack_from("<2I", EXE, 0x18)
LO, HI = 0x80010000, TADDR + TSIZE


def words(b):
    n = len(b) // 4
    return struct.unpack_from(f"<{n}I", b)


def refs_from(W, base, own):
    """yield referenced absolute addresses (only those in LO..HI)"""
    n = len(W)
    for i, w in enumerate(W):
        op = w >> 26
        if LO <= w < HI:
            yield w, base + i * 4, "word"
        if op in (2, 3):
            t = 0x80000000 | ((w & 0x3FFFFFF) << 2)
            if LO <= t < HI:
                yield t, base + i * 4, "j"
        elif own and (op in (4, 5, 6, 7) or (op == 1 and ((w >> 16) & 31) in (0, 1, 16, 17))):
            imm = w & 0xFFFF
            imm -= 0x10000 if imm & 0x8000 else 0
            yield base + i * 4 + 4 + imm * 4, base + i * 4, "b"
        elif op == 15:
            rt, hi = (w >> 16) & 31, w & 0xFFFF
            if 0x8001 <= hi <= 0x800a:
                for k in range(1, 8):
                    if i + k >= n: break
                    w2 = W[i + k]; op2 = w2 >> 26
                    if ((w2 >> 21) & 31) == rt and op2 in (9, 13, 0x23, 0x21, 0x25, 0x20, 0x24, 0x2b, 0x29, 0x28):
                        lo = w2 & 0xFFFF
                        v = (hi << 16) + (lo if op2 == 13 else (lo - 0x10000 if lo & 0x8000 else lo))
                        if LO <= v < HI:
                            yield v, base + i * 4, "const"


def all_refs():
    out = []
    out += list(refs_from(words(EXE[0x800:]), TADDR, True))
    for f in glob.glob(os.path.join(ROOT, "disc/files/P/P*/*.BIN")):
        out += [(t, os.path.basename(f), k) for t, a, k in refs_from(words(open(f, "rb").read()), 0, False) if k != "b"]
    return out


def main():
    minsize = int(sys.argv[1]) if len(sys.argv) > 1 else 256
    W = words(EXE[0x800:])
    refs = all_refs()
    hit = {}
    for t, src, k in refs:
        hit.setdefault(t & ~3, []).append((src, k))
    w = lambda a: W[(a - TADDR) // 4]
    isprol = lambda x: (x >> 16) == 0x27BD and (x & 0xFFFF) >= 0x8000
    starts = [a for a in range(LO, HI, 4) if isprol(w(a)) and (w(a - 8) == 0x03E00008 or (w(a - 4) == 0 and 0x03E00008 in (w(a - 12), w(a - 16), w(a - 8))))]
    def referenced(a, b):
        for x in range(a, b, 4):
            for src, k in hit.get(x, ()):
                if isinstance(src, int) and a <= src < b and k in ("b", "j"):
                    continue             # internal jump
                return True
        return False
    dead = []
    for i, s in enumerate(starts[:-1]):
        e = starts[i + 1]
        if not referenced(s, e):
            if dead and dead[-1][1] == s: dead[-1][1] = e
            else: dead.append([s, e])
    tot = 0
    for s, e in dead:
        if e - s >= minsize:
            tot += e - s
            print(f"{s:08x}-{e:08x} {e - s:6d} bytes")
    print("total", tot)


if __name__ == "__main__":
    main()
