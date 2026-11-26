"""MSHvSF speed, part "a0mem": RAM versions of the BIOS A0 memcpy / bzero (port of XvSF 1.1 frame.py's A0 routines).

Stock battle frames spend ~35-48K cycles (6-8% of a vblank) in the BIOS ROM byte loops (uncached ROM fetches):
PutDrawEnv's memcpy(92) and memcpy(20) once per frame each, bzero(6) twice per frame (capmem.py), plus occasional
bzero(136..208).  The stubs at 0x800144a8 (memcpy) and 0x80014498 (bzero) are rewritten: n < 1 KB -> RAM routine,
n >= 1 KB -> the BIOS routine (stock timing: XvSF found a game race with large clears of queued GPU buffers).
bcopy / memset are left stock (bcopy unused in battle, memset 64 bytes rarely).

Code lives in statically AND dynamically dead EXE ranges (deadcode.py: no reference from the EXE or any disc file;
deadtest.py: filled with traps through boot, attract demo, versus and Cross Over fights with KOs / continue):
    0x80010a38-0x80010aec  (libgpu SetGraphQueue-like debug function)        C1
    0x8001117c-0x800111d8  (unused libgpu wrapper)                           C2
    0x80013a38-0x80013a9c  (two unused libgpu dispatch stubs)               C3
    0x80013acc-0x80013afc  (unused libgpu dispatch stub)                    C4
    0x800147bc-0x800147f0  (unused libapi DisableEvent-like helper)         C5

    patches() -> [(ram_addr, bytes)];  RANGES;  apply_ram(emu);  python a0mem.py build|show
"""
import os, sys, struct, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "a0mem", "a0mem.S")
BIN = os.path.join(HERE, "a0mem", "bin")
CHUNKS = {"C1": (0x80010a38, 0x80010aec), "C2": (0x8001117c, 0x800111d8), "C3": (0x80013a38, 0x80013a9c), "C4": (0x80013acc, 0x80013afc),
          "C5": (0x800147bc, 0x800147f0)}
MEM_BIOS_MIN = 0x400
GALFIX = "--galfix" in sys.argv   # (2026-11-25) chunk C2 (0x8001117c) is NOT dead: libgpu DrawPrim, the GALLERY picture overlay
                                  # ILLUST.BIN calls it (jal at file +0x15e4); bzero then fills with the byte loop only
# stub address, entry symbol, A0 number, register holding n (5 = a1 bzero, 6 = a2 memcpy)
STUBS = [(0x80014498, "f_bzero", 0x28, 5), (0x800144a8, "f_memcpy", 0x2a, 6)]
EXPECT = {0x80014498: "4c1ff663724d006bd2bd53e2362cecc0bf517e58", 0x800144a8: "3c813cf8d2ec4c9380ce30a69b131415c6f87cf7"}    # SHA-1 of the 4 stock words of each stub
RANGES = list(CHUNKS.values()) + [(s, s + 16) for s, *_ in STUBS]


def build():
    sys.path.insert(0, HERE)
    import slib
    out, syms = slib.chunks(SRC, CHUNKS)
    os.makedirs(BIN, exist_ok=True)
    for k, (lo, hi) in CHUNKS.items(): open(os.path.join(BIN, "%s.bin" % k), "wb").write(out[k])
    open(os.path.join(BIN, "symbols.txt"), "w").write("".join("%08x %s\n" % (v, n) for n, v in sorted(syms.items(), key=lambda x: x[1])))
    print("; ".join("%s %d/%d" % (k, len(out[k]), hi - lo) for k, (lo, hi) in CHUNKS.items()))


def symbols():
    return {l.split()[1]: int(l.split()[0], 16) for l in open(os.path.join(BIN, "symbols.txt"))}


def patches():
    S = symbols()
    out = [(lo, open(os.path.join(BIN, "%s.bin" % k), "rb").read()) for k, (lo, hi) in CHUNKS.items()]
    if GALFIX:                       # (2026-11-25) C2 = libgpu DrawPrim, called by ILLUST.BIN (GALLERY pictures): keep it stock
        out = [(a, d) for a, d in out if a != CHUNKS["C2"][0]]
        jw = 0x80013a50                                                  # f_bzero's `j fill` -> `j fbyte4` (RAM byte loop, C4)
        c3 = bytearray(dict(out)[CHUNKS["C3"][0]]); o = jw - CHUNKS["C3"][0]
        assert struct.unpack_from("<I", c3, o)[0] == 0x08000000 | (S["fill"] >> 2 & 0x3ffffff), "C3 layout changed"
        struct.pack_into("<I", c3, o, 0x08000000 | (S["fbyte4"] >> 2 & 0x3ffffff))
        out = [(a, bytes(c3) if a == CHUNKS["C3"][0] else d) for a, d in out]
    for stub, name, n, nreg in STUBS:
        off = (S[name] - (stub + 8)) >> 2
        assert -0x8000 <= off < 0x8000
        # the 4th word's delay slot is the next stub's first word (li t2, 0xa0): only writes t2, which the BIOS path sets anyway
        out.append((stub, struct.pack("<4I", 0x2c000000 | nreg << 21 | 10 << 16 | MEM_BIOS_MIN,   # sltiu t2, n, MIN
                                      0x14000000 | 10 << 21 | (off & 0xffff),                    # bnez t2, f_xxx
                                      0x24090000 | n,                                            # addiu t1, zero, N
                                      0x08000000 | (S["a0bios"] >> 2 & 0x3ffffff))))             # j a0bios
    for a, d in out:
        assert any(lo <= a and a + len(d) <= hi for lo, hi in RANGES), "%08x outside RANGES" % a
    return out


def check_stock(read):
    """read(addr, n) -> bytes; assert the patched words are the stock ones"""
    for stub, w in EXPECT.items():
        assert hashlib.sha1(bytes(read(stub, 16))).hexdigest() == w, "stub %08x not stock" % stub


def apply_ram(e):
    """poke into a running game.  Two phases: the code chunks first (unreachable while the stubs are stock), 2 frames
    so that any I-cache line holding stale stock words of a chunk (lines shared with live code, e.g. 0x80013a30) is
    evicted, then the stubs.  (Poking everything at once hung the game: f_bzero ran from a stale cached line.
    A disc build has no such issue.)"""
    check_stock(e.ram)
    stubs = {s for s, *_ in STUBS}
    for a, d in patches():
        if a not in stubs: e.poke(a, d)
    e.step(2)
    for a, d in patches():
        if a in stubs: e.poke(a, d)


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]: build()
    for a, d in patches(): print("%08x %4d bytes" % (a, len(d)))
