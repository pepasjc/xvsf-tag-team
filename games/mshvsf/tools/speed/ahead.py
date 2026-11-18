"""MSHvSF speed, part "ahead": deferred pre-decode = decode-ahead in the idle time of the frame (source ahead/ahead.S,
design notes at its top and in docs/PERFORMANCE.md).

The engine's own pre-decode of the predicted next animation frame (0x8008555c -> 0x80084cd4 -> 0x80084ab8, once per
logic frame) keeps running at the stock time with all its bookkeeping; only its tile decodes are deferred: the last
tile of each block at once, the others tile by tile in the idle time before the next vblank, and completely before
anything uses or frees the block.  Exact: every block holds the stock bytes when it is read.

Hooks (stock word -> new):
    0x80084c40  jal 0x8001bd68 -> jal ah_d1      decoder call inside 0x80084ab8 (record instead of decode)
    0x80084d5c  jal 0x80084ab8 -> jal ah_d2      in 0x80084cd4 (cursor per pre-decoded block)
    0x80020c44  jal 0x8008555c -> jal ah_frame   main loop (stock pre-decode, then slices until the deadline)
    0x8008187c  jal 0x80084984 -> jal ah_chk     per-object draw (finish a block that is about to be used)
    0x80083704  beqz a2,..     -> j ah_free      arena block free
    0x80083a2c  addiu sp,-0x18 -> j ah_flush     arena flush
    0x80080298  addiu sp,-0x20; sw s1 -> j ah_init; nop      arena init
    0x80020c7c  jal ResetRCnt(1) -> nop          hblank counter free running (the game never reads it)
    0x80081844  beq v1,v0 -> b                   AH_FXCHK (default 1): effect objects get the pre-decode check during
                                                 supers too (stock: players only while 0x800245a8 != -1)
    0x80084a64  jal 0x800845cc -> jal ah_pred1   AH_PRED (default 1): type-1 next-frame predictor rewritten in place
                                                 (chunk P = 0x80084528-0x80084660) that follows jump records
Rebuild after changing AH_* (python ahead.py build); the prebuilt bin/ is what mktag.py uses.

    patches(); RANGES; symbols(); apply_ram(e); python ahead.py build
"""
import os, sys, struct, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ahead", "ahead.S")
BIN = os.path.join(HERE, "ahead", "bin")
# Code ranges.  EVERY range is checked at build time against j/jal targets in the EXE and in every code file on the
# disc (*.A0, *.BIN, *.ARC: stage overlays call into the EXE too; the earlier dead-code scans skipped *.ARC, and the
# parse.py "FREED" tails are entry points of character code -> the tag05 stage-6 freeze).
CHUNKS = {"A": (0x80011308, 0x80011414), "B": (0x80013330, 0x8001341c), "C": (0x8002c288, 0x8002c344),
          "D": (0x8002c5f4, 0x8002c6ac), "I": (0x8005bed4, 0x8005bf58), "J": (0x800149c4, 0x80014a30),
          "L": (0x8001a8b4, 0x8001a91c), "M": (0x8001a74c, 0x8001a784), "N": (0x8004a388, 0x8004a428),
          "R": (0x80084528, 0x80084764),      # in place: stock type-1/type-2 predictors + steps (callers hooked)
          "Q": (0x8008555c, 0x800855b0)}      # in place: stock 0x8008555c (inlined into ah_frame, caller hooked)
MARGIN = 10                     # hblank lines kept free before the vblank (rest of the frame + the IRQ at VSync)
DEFS = dict(AH=0x100, NK=12, CUR=0x128, ST=0x2e0, DEC=0x8001bd68, AB8=0x80084ab8, PREDEC=0x8008555c, CHECK=0x80084984,
            LINES=263, MARGIN=MARGIN, STATS=int(os.environ.get("AH_STATS", "0")))
J = lambda op, t: struct.pack("<I", (op << 26) | (t >> 2 & 0x3ffffff))
# site: (stock words, new words as a function of the symbols)
HOOKS = {0x80084c40: ((0x0c006f5a,), lambda S: J(3, S["ah_d1"])),
         0x80084d5c: ((0x0c0212ae,), lambda S: J(3, S["ah_d2"])),
         0x80020c44: ((0x0c021557,), lambda S: J(3, S["ah_frame"])),
         0x8008187c: ((0x0c021261,), lambda S: J(3, S["ah_chk"])),
         0x80083704: ((0x10c0002a,), lambda S: J(2, S["ah_free"])),
         0x80083a2c: ((0x27bdffe8,), lambda S: J(2, S["ah_flush"])),
         0x80080298: ((2, "3671dc81daa0533ddaeb1fca162567d294535d18"), lambda S: J(2, S["ah_init"]) + bytes(4)),     # 2 stock words: count, SHA-1
         0x80020c7c: ((0x0c0051fc,), lambda S: bytes(4))}
if os.environ.get("AH_FXCHK", "1") == "1":     # pre-decode effect objects during supers too (stock: players only)
    HOOKS[0x80081844] = ((0x1062000d,), lambda S: struct.pack("<I", 0x1000000d))
HOOKS[0x80084a64] = ((0x0c021173,), lambda S: J(3, S["ah_pred1"]))     # type-1 predictor (follows jump records)
HOOKS[0x80084a7c] = ((0x0c0211b3,), lambda S: J(3, S["ah_pred2"]))     # type-2 predictor (stock result, compact)
RANGES = list(CHUNKS.values()) + [(a, a + 4 * len(w)) for a, (w, f) in HOOKS.items()]


def pieces():
    import re
    s = open(SRC).read()
    hdr, *funcs = re.split(r"(?m)^(?=# -{20,} )", s)
    return {re.search(r"(?m)^(ah\w*):", f).group(1): f for f in funcs}


def refcheck(extra=()):
    """no j/jal into our ranges from the EXE (outside the hooked sites) or from any code file on the disc"""
    import glob, json
    GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
    files = [f for f in glob.glob(os.path.join(GAME, "work", "loader", "files", "*")) if not f.endswith((".DSP", ".SE", ".TEX"))]
    exe = open(os.path.join(GAME, "disc", "SLUS_007.93"), "rb").read()[0x800:]
    hooks = set(HOOKS)
    bad = []
    for name, b, base in [("EXE", exe, 0x80010000)] + [(os.path.basename(f), open(f, "rb").read(), None) for f in files]:
        W = struct.unpack_from("<%dI" % (len(b) // 4), b)
        for i, w in enumerate(W):
            if w >> 26 not in (2, 3): continue
            t = 0x80000000 | (w & 0x3ffffff) << 2
            site = base + 4 * i if base else None
            for lo, hi in list(CHUNKS.values()) + list(extra):
                if lo <= t < hi and not (site and (site in hooks or lo <= site < hi)):
                    bad.append((name, hex(4 * i), hex(t)))
    assert not bad, "live references into our ranges: %s" % bad[:20]


def build():
    sys.path.insert(0, HERE)
    import slib, tempfile
    refcheck()
    P = pieces()
    # sizes: each piece alone, other labels at its own address
    import re
    sys.path.insert(0, os.path.join(slib.ROOT, "tools", "speed", "frame"))
    from gas import gas
    labels = {k: set(re.findall(r"(?m)^\s*([A-Za-z_]\w*):", v)) for k, v in P.items()}
    allab = set().union(*labels.values())
    size = {}
    for k, v in P.items():
        d = dict(DEFS); d.update({l: 0x80021234 for l in allab - labels[k]})
        size[k] = len(gas(v, 0x80020000, d)[0])
    # first fit decreasing (fixed placements first)
    fixed = {"ah_pred1": "R", "ah_pred2": "R"}
    free = {k: hi - lo for k, (lo, hi) in CHUNKS.items()}
    plan = {k: [] for k in CHUNKS}
    for f in sorted(P, key=lambda f: (f not in fixed, -size[f])):
        ks = [fixed[f]] if f in fixed else sorted(free, key=lambda k: free[k])
        k = next(k for k in ks if free[k] >= size[f])
        plan[k].append(f); free[k] -= size[f]
    src = os.path.join(tempfile.mkdtemp(), "ahead_packed.S")
    open(src, "w").write("".join("#@%s" % k + chr(10) + "".join(P[f] for f in fs) for k, fs in plan.items()))
    out, syms = slib.chunks(src, CHUNKS, DEFS)
    os.makedirs(BIN, exist_ok=True)
    for f in os.listdir(BIN): os.remove(os.path.join(BIN, f))
    for k in CHUNKS: open(os.path.join(BIN, k + ".bin"), "wb").write(out[k])
    open(os.path.join(BIN, "symbols.txt"), "w").write("".join("%08x %s" % (v, n) + chr(10) for n, v in sorted(syms.items(), key=lambda x: x[1])))
    print("; ".join("%s %d/%d %s" % (k, len(out[k]), hi - lo, "+".join(plan[k])) for k, (lo, hi) in CHUNKS.items()))


def symbols():
    return {l.split()[1]: int(l.split()[0], 16) for l in open(os.path.join(BIN, "symbols.txt"))}


def code():
    return [(lo, open(os.path.join(BIN, k + ".bin"), "rb").read()) for k, (lo, hi) in CHUNKS.items()]


def hooks():
    S = symbols()
    return [(a, f(S)) for a, (w, f) in HOOKS.items()]


def patches():
    return code() + hooks()


def check_stock(read):
    for a, (w, f) in HOOKS.items():
        if isinstance(w[-1], str): assert hashlib.sha1(bytes(read(a, 4 * w[0]))).hexdigest() == w[1], "%08x not stock" % a
        else: assert struct.unpack("<%dI" % len(w), read(a, 4 * len(w))) == w, "%08x not stock" % a


def apply_ram(e):
    """poke into a running game: code first, 2 frames (stale I-cache lines), then the hooks.  Pending engine
    pre-decodes at that moment were decoded by the stock code (nothing to take over)."""
    check_stock(e.ram)
    for a, d in code(): e.poke(a, d)
    e.step(2)
    for a, d in hooks(): e.poke(a, d)


def stats(e_scratch):
    """statistics words from a 0x400-byte scratchpad image"""
    names = ["blocks", "deferred", "slice", "forced", "cancel", "onfree", "dropped"]
    return dict(zip(names, struct.unpack_from("<7I", e_scratch, 0x2e0)))


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]: build()
    for a, d in patches(): print("%08x %d bytes" % (a, len(d)))
