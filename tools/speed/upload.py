"""XvSF 1.1 speed: sprite upload path (per-object sprite draw 0x80059e60 and the arena / VRAM-upload code around it).
    patches() -> [(ram_addr, bytes)]   for the US executable (same bytes in the stock, tag-hack and 8 MB builds)
    RANGES    every RAM range written by patches()
Sources and tests in tools/speed/upload/ (README in work/speed/upload/REPORT.md).
    python tools/speed/upload.py        assemble, check load-delay hazards and ranges, print the patch list"""
import hashlib, os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "upload")
sys.path.insert(0, SRC)
import ulib

ARENA, ARENA_END = 0x80058d04, 0x800590c4          # arena block allocator 0x80058d04 + end-of-frame sweep 0x80058f84 (arena.S)
HELP, HELP_END = 0x800590c4, 0x80059d68            # flush 0x800590c4 + upload loops 0x8005935c / 0x80059564 / 0x80059930 (helpers.S)
KEEP = (0x800592e8, 0x8005935c)                     # inside HELP, not patched (stock DrawSync loop + flush + list reset)
# single-block frees outside the two functions above: two delay-slot nops each become "lui v1, %hi(HINT)" /
# "sw zero, %lo(HINT)(v1)" (v1 is dead there; checked against the stock words below)
USE_FC = os.environ.get("UP_FC", "0") == "1" and os.environ.get("UP_VC", "0") != "1" and os.environ.get("UP_DRAW", "0") != "1"           # frame cache in the sprite pool (fcache.c, hooks in the stock 0x80059e60)
USE_DRAW = os.environ.get("UP_DRAW", "0") == "1"
FCRES = 2608                                         # frame-cache data at the end of the arena (fcache.c FCDATA)
FCDATA = 0x800620e0 + 31088 - FCRES
FCBAD = FCDATA + 32 * 48 + 8 * 128 + 0x18
FCHITA = FCDATA + 32 * 48 + 8 * 128 + 0x1c
assert FCDATA + 32 * 48 + 8 * 128 + 0x28 <= FCDATA + FCRES and FCRES % 4 == 0
FC_RT, FC_ALLOC = 0x8005a2a0, 0x8005a510             # stock 0x80059e60: before the old rect's unlink; its jal 0x8005883c
FCFAIL = 0x80058ba4                                  # the rect allocator's failure path: j fc_evict; nop
USE_VC = os.environ.get("UP_VC", "0") == "1"          # VRAM tile cache (vc.c)
VC_CODE, VC_CODE_END = 0x80056b94, 0x800577c8       # quad worker's FREED range
VCRES = int(os.environ.get("UP_VCRES", "3584"))                                        # bytes taken from the end of the arena (0x800620e0 + 31088) for the cache's data
VC_DATA = 0x800620e0 + 31088 - VCRES
VC_RUNS, VC_RUNS_END = 0x80057d7c, 0x80057f48      # stage tables: quad worker's FREED range (draw.c's quad loop with UP_DRAW=1)
QFREE = (0x80057fbc, 0x80058000)                    # quad worker's FREED tail of sec1_parse: more stage tables
VC_API, VC_API_END = 0x80055c34, 0x80055ebc        # vc_lookup / vc_prefetch (decode-ahead API): quad worker's FREED range
VC_E60_DECODE = 0x8005b348                          # stock 0x80059e60: jal 0x8001b5b0 of the pre-decode   # draw.c in place of 0x80059e60 (equivalent, no faster yet: off by default)
FREE_SITES = [0x800584c4] + ([] if USE_DRAW else [0x8005a5b8, 0x8005af90])   # nop (load delay) ... +8: nop (bne delay slot)
E60_JALS = {0x8005a7b4: "up_cached", 0x8005a7d4: "up_partial", 0x8005a8e8: "up_stream"}   # the stock 0x80059e60's calls of the loops
HOT, HOT_END = 0x80057000, 0x80057340             # draw.c's pre-decode loop: quad worker's FREED 0x80056b94-0x800577c8, I-cache index 0x000-0x33f
HOT2, HOT2_END = 0x80057d7c, 0x80057f48            # draw.c's quad-only loop: FREED 0x80057d7c-0x80057f48, index 0xd7c-0xf47
#  (both index windows hold no quad / sec0 / sec1 code)
                              # cache index 0x000-0x0ff (no quad / sec0 / sec1 code there)
DRAW, DRAW_END = 0x80059e60, 0x8005b3ac            # per-object sprite draw (draw.c); 0x8005b3ac-0x8005b424 (other function) untouched
CALLEES = dict(parse0=0x80057be4, parse1=0x80057f48, quad=0x80056340, f55ebc=0x80055ebc, f55ef8=0x80055ef8, f55fa4=0x80055fa4,
               f5c4f8=0x8005c4f8, f5c258=0x8005c258, f5883c=0x8005883c, f57a70=0x80057a70, decode=0x8001b5b0, alloc=0x80058d04,
               up_cached=0x8005935c, up_partial=0x80059564, up_stream=0x80059930)
NOP = bytes(4)

RANGES = [(ARENA, ARENA_END), (HELP, KEEP[0]), (KEEP[1], HELP_END)] + ([(DRAW, DRAW_END), (HOT, HOT_END), (HOT2, HOT2_END)] if USE_DRAW else [(a, a + 4) for a in E60_JALS])     + ([(VC_CODE, VC_CODE_END), (VC_RUNS, VC_RUNS_END), QFREE, (VC_API, VC_API_END), (VC_DATA, VC_DATA + VCRES), (VC_E60_DECODE, VC_E60_DECODE + 4)] if USE_VC else []) + [(a, a + 4) for a in FREE_SITES] + [(a + 8, a + 12) for a in FREE_SITES] \
    + ([(FCFAIL, FCFAIL + 8), (FCDATA, FCDATA + FCRES), (FC_RT, FC_RT + 16), (FC_ALLOC, FC_ALLOC + 4), (VC_CODE, VC_CODE_END)] if USE_FC else [])
jal = lambda t: struct.pack("<I", 0x0C000000 | (t >> 2 & 0x03FFFFFF))


def _sound():
    """1.2 sound banks on (tools/sndpatch.py): cdtile reads the stash from where the set-0x37 loader put it"""
    sys.path.insert(0, os.path.dirname(HERE))
    import sndpatch
    return sndpatch.enabled()


def build(hint_override=None):
    vc = None
    arena, sa = ulib.gas(os.path.join(SRC, "arena.S"), ARENA, {"VCRES": VCRES if USE_VC else FCRES if USE_FC else 0})
    hint = sa["HINT"]
    assert ARENA + len(arena) <= ARENA_END and sa["alloc"] == 0x80058d04 and sa["sweep"] == 0x80058f84
    FB = FCBAD if USE_FC else 0
    fcd = {"FCBAD": FB, "FC": 1 if USE_FC else 0, "FCHITA": FCHITA, "FC_DONE": HELP}
    fcd["SOUND"] = 1 if _sound() else 0                         # 1.2 sound banks: the SP_EFF2 stash moves (tools/sndpatch.py)
    h0, sh0 = ulib.gas(os.path.join(SRC, "helpers.S"), HELP, dict({"ALLOC_W": sa["alloc_w"], "DECODE": 0x8001b5b0, "LOADIMG": HELP}, **fcd))
    fastload = sh0["fastload"]                                   # (its address does not depend on DECODE / LOADIMG)
    cold = HELP + (len(h0) + 3 & ~3)                             # the cache's cold code (stage setup) after the upload loops
    fc = None
    if USE_FC:
        assert not USE_VC and not USE_DRAW, "the frame cache: stock 0x80059e60, code in the VRAM tile cache's place"
        fcode, sfc = ulib.cc(os.path.join(SRC, "fcache.c"), VC_CODE, dict(alloc_rect=0x8005883c), extra=["-DFCDATA=0x%08x" % FCDATA])
        assert VC_CODE + len(fcode) <= VC_CODE_END, hex(VC_CODE + len(fcode))
        fcd["FC_DONE"] = sfc["fc_done"]; fc = (fcode, sfc)
    if USE_VC:
        assert not USE_DRAW, "the VRAM cache code shares the FREED range with draw.c's loops: one at a time for now"
        ext = lambda r: ulib.cc(os.path.join(SRC, "vc.c"), VC_CODE, dict(decode=0x8001b5b0, StoreImage=0x8001677c, LoadImage=0x80016718, fastload=fastload,
                                                                       alloc=0x80058d04), hot={"hapi": VC_API, "hcold": cold},
                                extra=["-DVC_DATA=0x%08x" % VC_DATA, "-DVC_RUNS=0x%08x" % r] + ["-D" + d for d in os.environ.get("UP_VC_DEFS", "").split(",") if d])
        vcode, svc, segs = ext(VC_RUNS); api, vcold = segs["hapi"], segs["hcold"]
        assert VC_API + len(api) <= VC_API_END, len(api)
        assert cold + len(vcold) <= HELP_END, hex(cold + len(vcold))
        assert VC_CODE + len(vcode) <= VC_CODE_END, hex(VC_CODE + len(vcode))
        areas = [(VC_RUNS, VC_RUNS_END), (VC_CODE + (len(vcode) + 3 & ~3), VC_CODE_END), (ARENA + (len(arena) + 3 & ~3), ARENA_END), QFREE,
                 (cold + len(vcold), HELP_END)]
        tabs = vc_table(areas)
        vc = (vcode, svc["vc_decode"], tabs, api, vcold)
        VCSYM.update(svc)
    helpers, sh = ulib.gas(os.path.join(SRC, "helpers.S"), HELP, {"ALLOC_W": sa["alloc_w"], "DECODE": VCSYM["vc_decode"] if vc else 0x8001b5b0,
                                                                  "LOADIMG": VCSYM["vc_load"] if vc else fastload, **fcd})
    assert sh["fastload"] == fastload and len(helpers) == len(h0)
    assert HELP + len(helpers) <= HELP_END and not any(helpers[KEEP[0] - HELP:KEEP[1] - HELP])
    assert sh["flush"] == 0x800590c4 and sh["up_cached"] == 0x8005935c
    sa.update(sh)
    if not USE_DRAW:
        out = [(ARENA, arena), (HELP, helpers[:KEEP[0] - HELP]), (KEEP[1], helpers[KEEP[1] - HELP:])]
        out += [(a, jal(sh[n])) for a, n in E60_JALS.items()]
        if vc:
            out += [x for x in [(VC_CODE, vc[0]), (VC_API, vc[3]), (cold, vc[4]), (VC_E60_DECODE, jal(vc[1]))] if x[1]] + vc[2]   # (empty API segment with VC_NOAPI: not written)
        if fc:
            stub, ss = ulib.gas(os.path.join(SRC, "fcstub.S"), cold, {"FC_DROP": fc[1]["fc_drop"]})
            assert cold + len(stub) <= HELP_END
            exe = ulib.exe_image()
            w = lambda a: struct.unpack_from("<I", exe, a & 0x1fffff)[0]
            assert hashlib.sha1(struct.pack("<4I", *[w(FC_RT + 4 * i) for i in range(4)])).hexdigest() == "082d94ed799e8f2df4ab1d5e382b82aee7ebec5a", "stock 0x8005a2a0 changed"
            assert w(FC_ALLOC) == 0x0c01620f and w(FCFAIL) == 0x8fa20020
            # jal fc_rt; nop; beqz v0, 0x8005a33c; move a0, v0   (fc_rt(node): 0 = skip the stock unlink, else the node)
            beqz = 0x10400000 | ((0x8005a33c - (FC_RT + 12)) >> 2 & 0xffff)
            out += [(VC_CODE, fc[0]), (cold, stub), (FCFAIL, struct.pack("<II", 0x08000000 | (ss["fc_evict"] >> 2 & 0x3ffffff), 0)),
                    (FC_RT, jal(fc[1]["fc_rt"]) + struct.pack("<III", 0, beqz, 0x00402021)), (FC_ALLOC, jal(fc[1]["fc_alloc"]))]
            sa.update({k: v for k, v in fc[1].items() if k.startswith("fc_")}, fc_evict=ss["fc_evict"])
        hi, lo = (hint + 0x8000) >> 16 & 0xffff, hint & 0xffff
        for a in FREE_SITES:
            out.append((a, struct.pack("<I", 0x3c030000 | hi))); out.append((a + 8, struct.pack("<I", 0xac600000 | lo)))
        return out, sa
    draw, sd, hotc = ulib.cc(os.path.join(SRC, "draw.c"), DRAW, dict(CALLEES, HINT=hint if hint_override is None else hint_override,
                                                               up_partial=sh["up_partial"], up_stream=sh["up_stream"]), hot={"hot": HOT, "hot2": HOT2},
)
    assert HOT + len(hotc["hot"]) <= HOT_END and HOT2 + len(hotc["hot2"]) <= HOT2_END
    assert sd["draw"] == DRAW and DRAW + len(draw) <= DRAW_END, hex(DRAW + len(draw))
    out = [(ARENA, arena), (HELP, helpers[:KEEP[0] - HELP]), (KEEP[1], helpers[KEEP[1] - HELP:]), (DRAW, draw), (HOT, hotc["hot"]), (HOT2, hotc["hot2"])]
    hi, lo = (hint + 0x8000) >> 16 & 0xffff, hint & 0xffff
    for a in FREE_SITES:
        out.append((a, struct.pack("<I", 0x3c030000 | hi)))              # lui v1, %hi(HINT)
        out.append((a + 8, struct.pack("<I", 0xac600000 | lo)))          # sw zero, %lo(HINT)(v1)
    return out, sa


VCSYM = {}


def vc_table(areas):
    """per-stage cache runs (tools/speed/upload/vcmap.txt) -> patches: at areas[0] "VCMP" + 12 x u16 (address of the
    stage's table - 0x80050000), the stage tables (n, n x (band, x0, len)) packed into the free areas (first fit,
    largest first)"""
    st = {}
    for l in open(os.path.join(SRC, "vcmap.txt")):
        if l.startswith("#") or not l.strip(): continue
        p = l.split(); st[int(p[0])] = [tuple(int(v) for v in r.split(",")) for r in p[2:]]
    blobs = {s: bytes([len(st.get(s, []))]) + b"".join(bytes(r) for r in st.get(s, [])) for s in range(12)}
    free = [list(a) for a in areas]; free[0][0] += 28
    place = {}; data = {i: bytearray() for i in range(len(areas))}
    for s in sorted(blobs, key=lambda s: -len(blobs[s])):
        for i, f in enumerate(free):
            if f[0] + len(blobs[s]) <= f[1]:
                place[s] = f[0]; data[i] += blobs[s]; f[0] += len(blobs[s]); break
        else: raise AssertionError("no room for the cache table of stage %d" % s)
    head = b"VCMP" + b"".join(struct.pack("<H", place[s] - 0x80050000) for s in range(12))
    out = [(areas[0][0], head + bytes(data[0]))]
    out += [(areas[i][0] if i else 0, bytes(d)) for i, d in data.items() if i and d]
    return [(a, d) for a, d in out if d]


def patches():
    return build()[0]


def symbols():
    """the cache's entry points (decode-ahead API: vc_lookup, vc_prefetch) when UP_VC=1, else {}"""
    if not USE_VC or os.environ.get("UP_VC_AHEAD", "0") != "1": return {}
    # decode-ahead feeding is OFF by default (UP_VC_AHEAD=1 enables it): a predicted tile decoded in the idle hook
    # overwrote 19-24 KB of RAM past its arena block (Storm 2,7,6,4 stage 2, Bison stage 10: the game hangs;
    # work/speed/cache/REPORT.md) - predicted descriptors need validating before their streams are decoded
    if not VCSYM: build()
    return dict(VCSYM)


def check():
    exe = ulib.exe_image()
    p, info = build()
    for a in FREE_SITES:                                                 # the expected stock pattern (checked in the stock image)
        w = [struct.unpack_from("<I", exe, (a & 0x1fffff) + 4 * i)[0] for i in range(-2, 4)]
        assert w[0] >> 16 == 0x3c02 and w[1] >> 16 == 0x8c42 and w[2] == 0 and w[3] >> 16 == 0x1444 and w[4] == 0 and w[5] >> 16 == 0x8c82, (hex(a), [hex(x) for x in w])
    for a, d in p:
        assert any(lo <= a and a + len(d) <= hi for lo, hi in RANGES), hex(a)
        bad = ulib.hazards(d, a) if len(d) > 8 else []
        assert not bad, bad
    return p, info


if __name__ == "__main__":
    p, info = check()
    for a, d in p: print("%08x %4d bytes" % (a, len(d)))
    print({k: hex(v) for k, v in info.items() if k in ("alloc", "alloc_w", "sweep", "reclaim", "HINT", "fastload", "flush", "up_cached", "up_partial", "up_stream")})
