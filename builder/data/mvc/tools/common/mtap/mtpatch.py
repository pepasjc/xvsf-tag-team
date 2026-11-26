"""Patch list for the multitap core (common/mtap/mtcore.c) in one game's EXE.

cfg = dict(
    dir      = the game's tools/mtap (holds mtgame.h; obj4/ build output),
    spans    = [(lo, hi)] EXE ranges for the code (first = the debug-string block),
    strings  = [(lo, hi)] ranges that must still be the stock strings (printable / 0) before we write,
    tables   = [(old, new, lw_at, lw_word)] 5-word jump tables moved inside the block (reader lw re-pointed),
    hook     = (addr, orig jal word)   per-frame pad-word update call -> jal mt_tick,
    mask     = (addr, orig 8 bytes)    entry of the disconnected-pad mask -> j mt_mask; nop,
    stubs    = [(addr, orig 8 bytes)]  printf / puts BIOS stubs -> jr ra; nop,
    spare    = optional [(lo, hi, prefix bytes)] extra spans that must start with prefix (checked)
)
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mtbuild

RET = struct.pack("<II", 0x03E00008, 0)               # jr ra; nop


def code(cfg, defines=None):
    r = mtbuild.build(cfg["dir"], cfg["spans"], os.path.join(cfg["dir"], "obj4"), defines,
                      **({"keep": cfg["keep"]} if "keep" in cfg else {}))
    s = r["sym"]
    ha, ho = cfg["hook"]
    ma, mo = cfg["mask"]
    hooks = [(ha, struct.pack("<I", mtbuild.jal(s["mt_tick"])), struct.pack("<I", ho)),
             (ma, struct.pack("<II", mtbuild.j(s.get("mt_mask_v", s.get("mt_mask"))), 0), mo)]
    hooks += [(a, RET, o) for a, o in cfg["stubs"]]
    for old, new, lw_at, lw in cfg.get("tables", ()):
        hooks.append((lw_at, struct.pack("<I", (lw & 0xFFFF0000) | (new & 0xFFFF)), struct.pack("<I", lw)))
    return dict(segs=r["segs"], hooks=hooks, sym=s, used=r["used"], free=r["free"], place=r["place"])


def patches(cfg, read, defines=None):
    """-> ([(addr, bytes)], code dict); read(addr, n) = the EXE bytes as built so far (stock checks)"""
    c = code(cfg, defines)
    for a, new, orig in c["hooks"]:
        assert read(a, len(orig)) == orig, "mtap: %08x not stock" % a
    tabs = cfg.get("tables", ())
    for lo, hi in cfg["strings"]:
        d = bytearray(read(lo, hi - lo))
        for old, new, _, _ in tabs:
            if lo <= old < hi: d[old - lo:old - lo + 20] = bytes(20)
        assert all(b == 0 or 0x09 <= b < 0x7f for b in d), "mtap: %08x-%08x is not the stock string block" % (lo, hi)
    for lo, hi, prefix in cfg.get("spare", ()):
        assert read(lo, len(prefix)) == prefix, "mtap: spare span %08x" % lo
    moved = [(new, read(old, 20)) for old, new, _, _ in tabs]
    for new, t in moved:
        assert all(0x80010000 <= w < 0x80100000 for w in struct.unpack("<5I", t)), "mtap: jump table"
    for a, d in c["segs"]:
        for new, t in moved:
            assert a + len(d) <= new or a >= new + 20, "mtap: code over a moved table"
    # tagged spans (vs CPU): 'vsui' = the select overlay (bytes go into that file, c["ovl"]), '.kc' = kernel code copied
    # by mt_select from the end of the overlay image (vs_kc = src, dst, words), '.kz' = kernel vars (zero at boot: no bytes)
    span_of = lambda a: next(sp for sp in cfg["spans"] if sp[0] <= a < sp[1])
    tag_of = lambda a: span_of(a)[2] if len(span_of(a)) > 2 else ""
    exe = [(a, d) for a, d in c["segs"] if tag_of(a) not in ("vsui", ".kc", ".kz") or (tag_of(a) == ".kz" and a >= 0x80010000)]   # (other tags: fixed EXE slots, e.g. the --vsmenu trampoline)   # (vars in EXE spans: zeros written)
    ovl = [(a, d) for a, d in c["segs"] if tag_of(a) == "vsui"]
    kc = [(a, d) for a, d in c["segs"] if tag_of(a) == ".kc"]
    c["kernel"] = [(a, len(d)) for a, d in c["segs"] if tag_of(a) in (".kc", ".kz") and a < 0x80010000]
    c["kcram"] = [(a, len(d)) for a, d in c["segs"] if tag_of(a) == ".kc" and a >= 0x80010000]     # (.kc in main RAM)
    if ovl:
        assert len(ovl) == 1 and len(kc) <= 1
        oa, od = ovl[0]
        od = bytearray(od)
        if kc:
            ka, kd = kc[0]
            src = oa + len(od)
            assert src + len(kd) <= span_of(oa)[1], "vs CPU: overlay span too small for the kernel-code copy"
            od += kd
            vk = c["sym"]["vs_kc"] - oa
            assert od[vk:vk + 12] == bytes(12)
            od[vk:vk + 12] = struct.pack("<3I", src, ka, len(kd) // 4)
        c["ovl"] = (oa, bytes(od))
    out = exe + moved + [(a, new) for a, new, _ in c["hooks"]]
    return out, c
