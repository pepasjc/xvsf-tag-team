"""Speed project, "frame" part: main loop / sprite list glue rewritten compactly, and RAM versions of the BIOS A0
memory functions (bcopy, bzero, memcpy, memset) that the game calls through its stubs at 0x80019290.

    patches() -> [(ram_addr, bytes)]   US EXE, applied on top of the current build's EXE
    RANGES    -> every RAM range written
    python tools/speed/frame.py build  re-assemble tools/speed/frame/src/*.S + the BG layer rewrites (bgtile.py,
                                       bghand.py) into tools/speed/frame/bin/ (the only step that needs the MIPS
                                       binutils; patches() / ovl_patches() / symbols() only read bin/)
    python tools/speed/frame.py show   list the patches

What changes (behaviour identical, see work/speed/frame/REPORT.md for the tests):
- 0x8002e6bc-0x8002e924: sprite-list dispatcher + the four list walkers (0x8002e784/7ec/854/8bc) -> same
  dispatcher, one generic walker, then bcopy + the copy core.
- 0x80028868-0x80028b58: layer dispatch, layers-before-sprites, layers-from-index, DrawSync/one-shot dispatcher
  -> compact versions (new entry points, the three jal sites in 0x80028b58 re-pointed), then memcpy / bzero /
  memset entries and the common A0 return.
- 0x800280e8-0x8002811b: the one-shot dispatcher's jump table (read only by 0x80028a1c) -> function table.
- 0x80019290-0x800192cf: the four A0 stubs -> n < 1 KB: `j f_xxx` (RAM version), else the BIOS routine.
- 0x80018510-0x80018adc: libgpu _addque / _exeque (register-exact), DrawOTag shim, early BG.  Round 5: a GPU
  operation that would start directly while the GPU is still busy (the first DrawOTag after the flip waits for the
  screen clear) is queued instead; _exeque called from _addque does not wait for a busy GPU (the next libgpu
  call, the DMA-completion callback or DrawSync starts the queue).
- 0x80018db4-0x80018f20: libgpu queue timeout check (compact) + that non-blocking _exeque exit.
"""
import os, sys, struct
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame")
BIN = os.path.join(HERE, "bin")

REGION_A = (0x8002e6bc, 0x8002e924)       # src/splist.S
REGION_B = (0x80028868, 0x80028b58)       # src/layers.S
REGION_D = (0x80028b58, 0x80028d60)       # src/present.S  (draw + present, early BG)
REGION_Q1 = (0x80018510, 0x800187f0)      # src/gpuq.S     (libgpu _addque + ebg)
REGION_Q2 = (0x800187f0, 0x80018adc)      # src/gpuq2.S    (libgpu _exeque + early-BG check)
REGION_Q3 = (0x80018db4, 0x80018f20)      # src/gpuq3.S    (libgpu queue timeout check + non-blocking exeque exit)
DRAWOTAG = 0x80016a54
MEM_BIOS_MIN = 0x400                      # bcopy/bzero/memcpy/memset of >= 1 KB keep the BIOS routine (see REPORT round 5:
                                          # the attract demo clears a GPU prim buffer with bzero 0x3000 while DrawOTags into
                                          # it are still queued - stock relies on the slow BIOS loop); all battle calls are < 1 KB
AHEAD_LINES = 240                         # AHEAD callback deadline: hblanks after the last flip vblank (263 per frame; 23 lines margin)
EB_STAGES = 0x770                         # stages whose BG code only calls TermPrim / DrawOTag (work/speed/frame/bgdeps.py)
TABLE = (0x800280e8, 0x8002811c)          # one-shot dispatcher table
STUBS = (0x80019290, 0x800192d0)          # A0 stubs bcopy / bzero / memcpy / memset
REGIONS = [REGION_B, REGION_A, REGION_D, REGION_Q1, REGION_Q2, REGION_Q3]
RANGES = REGIONS + [TABLE, STUBS, (DRAWOTAG, DRAWOTAG + 8)]
A0 = [(0x80019290, "f_bcopy", 0x27), (0x800192a0, "f_bzero", 0x28), (0x800192b0, "f_memcpy", 0x2a), (0x800192c0, "f_memset", 0x2b)]
# one-shot dispatcher (byte 0x8004218f - 1): stock case labels -> called function (| 1: a0 = 0x80042180)
ONESHOT = [0x80098728, 0, 0x80029278 | 1, 0x80029320 | 1, 0x80029dc0, 0x8003159c, 0x80098b84, 0x80085e18, 0,
           0x800867b0, 0x8009a950, 0x8003171c, 0x80031844]
# stock words checked before patching (EXE of the 1.0.1 build)
EXPECT = {0x80019290: 0x240a00a0, 0x80019298: 0x24090027, 0x800192a8: 0x24090028, 0x800192b8: 0x2409002a, 0x800192c8: 0x2409002b,
          0x80028b94: 0x0c00a265, 0x80028bc8: 0x0c00a287, 0x80028d3c: 0x0c00a242, 0x800280e8: 0x80028a80, 0x8002e6bc: 0x27bdffe8,
          0x80028868: 0x27bdffe8, 0x80028a1c: 0x3c028004, 0x80028b58: 0x3c028004, 0x80018510: 0x27bdffd8, 0x800187f0: 0x3c028002,
          0x80016a54: 0x3c028002, 0x80016a58: 0x90422526, 0x80018db4: 0x27bdffe0, 0x80018f1c: 0x00000000}


def _jal(t): return struct.pack("<I", 0x0c000000 | (t >> 2 & 0x3ffffff))
def _j(t): return struct.pack("<I", 0x08000000 | (t >> 2 & 0x3ffffff))


def defined(src, name):
    return ("\n%s:" % name) in "\n" + src


def build():
    sys.path.insert(0, HERE)
    from gas import gas
    src = {k: open(os.path.join(HERE, "src", f)).read().replace("EB_STAGES", "0x%x" % EB_STAGES).replace("AHEAD_LINES", "%d" % AHEAD_LINES) for k, f in
           (("A", "splist.S"), ("B", "layers.S"), ("D", "present.S"), ("Q1", "gpuq.S"), ("Q2", "gpuq2.S"), ("Q3", "gpuq3.S"))}
    org = dict(A=REGION_A, B=REGION_B, D=REGION_D, Q1=REGION_Q1, Q2=REGION_Q2, Q3=REGION_Q3)
    syms = {}
    names = ("copy", "mret", "mret0", "mdone", "bsp", "fromidx", "oneshot", "ebg", "EBV", "exeque", "shim", "ahook", "kchk", "exq3", "exq5", "a0bios")
    for it in range(3):                      # fixed point: sizes do not depend on the symbol values
        out = {}
        for k in ("A", "B", "D", "Q1", "Q2", "Q3"):
            defs = {n: syms.get(n, org[k][0]) for n in names if not defined(src[k], n)}   # (placeholder in branch range)
            out[k], sy = gas(src[k], org[k][0], defs)
            for n, v in sy.items():
                if (org[k][0] <= v < org[k][1] or v == org[k][1]) and not (n in names and not defined(src[k], n)): syms[n] = v
    for k, (lo, hi) in org.items():
        assert lo + len(out[k]) <= hi, "region %s overflow %d > %d" % (k, len(out[k]), hi - lo)
    import hazard                            # R3000 load-delay check on everything this module writes
    bad = [(k, h) for k in out for h in hazard.hazards(out[k], org[k][0])]
    import bgtile as _bt, bghand as _bh
    for f, lst in list(_bt.ovl_patches().items()) + list(_bh.ovl_patches().items()):
        bad += [(f, h) for a, d in lst for h in hazard.hazards(d, a)]
    assert not bad, "load-delay hazards: %s" % bad
    os.makedirs(BIN, exist_ok=True)
    for k, (lo, hi) in org.items():
        open(os.path.join(BIN, "region_%s.bin" % k.lower()), "wb").write(out[k].ljust(hi - lo, b"\0"))
    with open(os.path.join(BIN, "symbols.txt"), "w") as f:
        for n, v in sorted(syms.items(), key=lambda x: x[1]):
            if not n.startswith("_"): f.write("%08x %s\n" % (v, n))
    import json, bgtile, bghand
    ov = bgtile.ovl_patches()
    for f, lst in bghand.ovl_patches().items():
        have = ov.setdefault(f, [])
        for a, d in lst:
            assert not any(b < a + len(d) and a < b + len(e) for b, e in have), "overlay patch overlap %s %08x" % (f, a)
            have.append((a, d))
        have.sort()
    json.dump({f: [["%08x" % ad, d.hex()] for ad, d in lst] for f, lst in ov.items()}, open(os.path.join(BIN, "ovl.json"), "w"), indent=1)
    print("; ".join("region %s %d/%d" % (k, len(out[k]), org[k][1] - org[k][0]) for k in org), "| overlay:",
          ", ".join("%s x%d" % (f, len(l)) for f, l in sorted(ov.items())))


def symbols():
    return {l.split()[1]: int(l.split()[0], 16) for l in open(os.path.join(BIN, "symbols.txt"))}


def ahead_callback():
    """the AHEAD hook's callback (EBV+12): the decode worker's animation-lookahead stub decode.symbols()["ahcb"]
    (magic-checked, a no-op without its per-battle area), 0 when XV_SPEED leaves decode out"""
    if "decode" not in os.environ.get("XV_SPEED", "decode,upload,quad,frame,logic").split(","): return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import decode
    return decode.symbols()["ahcb"]


def patches():
    S = symbols()
    out = [(lo, open(os.path.join(BIN, "region_%s.bin" % k), "rb").read()) for k, (lo, hi) in
           (("b", REGION_B), ("a", REGION_A), ("d", REGION_D), ("q1", REGION_Q1), ("q2", REGION_Q2), ("q3", REGION_Q3))]
    cb = S["EBV"] + 12                                   # AHEAD callback slot: set in the region bytes
    for i, (lo, d) in enumerate(out):
        if lo <= cb < lo + len(d):
            o = cb - lo
            assert d[o:o + 4] == bytes(4), "EBV+12 not empty in the prebuilt region"
            out[i] = (lo, d[:o] + struct.pack("<I", ahead_callback()) + d[o + 4:])
            break
    else: raise AssertionError("EBV+12 outside the regions")
    out.append((TABLE[0], struct.pack("<13I", *ONESHOT)))
    out.append((DRAWOTAG, _j(S["shim"]) + bytes(4)))
    for stub, name, n in A0:                 # n >= MEM_BIOS_MIN (unsigned): the BIOS routine (stock timing), else RAM
        nreg = 5 if name == "f_bzero" else 6
        off = (S[name] - (stub + 8)) >> 2
        assert -0x8000 <= off < 0x8000
        out.append((stub, struct.pack("<4I", 0x2c000000 | nreg << 21 | 10 << 16 | MEM_BIOS_MIN,   # sltiu t2, n, MIN
                                      0x14000000 | 10 << 21 | (off & 0xffff),                  # bnez t2, f_xxx
                                      0x24090000 | n,                                          # addiu t1, zero, N
                                      0x08000000 | (S["a0bios"] >> 2 & 0x3ffffff))))           # j a0bios (delay slot:
    # the next stub's sltiu, or after the last stub the printf stub's `li t2, 0xa0` - both only write t2)
    for a, d in out:
        assert any(lo <= a and a + len(d) <= hi for lo, hi in RANGES), "%08x outside RANGES" % a
    dbg = os.environ.get("FRAME_DEBUG_SKIP")            # debugging only: leave these patch start addresses stock
    if dbg: out = [(a, d) for a, d in out if "%08x" % a not in dbg.split(",")]
    return out


OVL_BASE = 0x80098000
STAGE_BYTE = 0x80042781          # stage id; the battle overlay is P/P4/STAGE<id hex>.BIN at 0x80098000


def ovl_patches():
    """stage-overlay patches (BG tile layers, tools/speed/frame/bgtile.py templates + bghand.py one-offs), prebuilt in
    bin/ovl.json: {"P/P4/STAGEn.BIN": [(ram_addr, bytes)]}.
    File offset = ram_addr - 0x80098000.  Each patch replaces the start of one stock function, in place."""
    import json
    if os.environ.get("FRAME_DEBUG_NOOVL"): return {}    # debugging only
    return {f: [(int(a, 16), bytes.fromhex(d)) for a, d in lst] for f, lst in json.load(open(os.path.join(BIN, "ovl.json"))).items()}


def check_stock(read32):
    """read32(addr) -> word of the EXE/RAM the patches go on; raises if it is not the expected stock code"""
    for a, w in EXPECT.items():
        assert read32(a) == w, "frame.py: unexpected word at %08x: %08x (want %08x)" % (a, read32(a), w)


def apply_ram(emu, overlay=True):
    """poke the EXE patches, and the overlay patches of the stage that is loaded (call it in a fight)"""
    check_stock(emu.u32)
    for a, d in patches(): emu.poke(a, d)
    if not overlay: return
    f = "P/P4/STAGE%X.BIN" % emu.u8(STAGE_BYTE)
    stock = open(os.path.join(HERE, "..", "..", "..", "disc", "files", *f.split("/")), "rb").read()
    for a, d in ovl_patches().get(f, []):
        o = a - OVL_BASE
        assert emu.ram(a, len(d)) == stock[o:o + len(d)], "%s not loaded at %08x" % (f, a)
        emu.poke(a, d)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build": build()
    for a, d in patches(): print("%08x %4d bytes" % (a, len(d)))
