"""XvSF built-in achievements: blob + patches (tools/ach runtime, tools/ach/xvsf/port.c + set.py).

    python tools/mktagdisc.py NAME --logo --title --ach        (mktagdisc calls apply() last; without --ach nothing changes)

See docs/ACHIEVEMENTS.md.  Hooks (each checked against the word it replaces):
    0x800285e0  jal 0x8002d1e8 (first call of the frame routine)  -> jal ach_frame  (popup, after the frame's lists are reset)
    present     jal DrawSync (the one in tools/speed/frame present.S)  -> jal ach_idle  (evaluation while the GPU draws)
    0x80028638 + OPDEMO 0x8009bf54  jal 0x800987c0 (main-menu routine) -> jal ach_menuin (ACHIEVEMENTS page, OPTION on cursor 5)
    P/P4/OPDEMO.BIN: main-menu text table -> ours (6 items), 6 lines drawn, cursor wraps in 0..5
    header pc0 -> the boot copy (0x800a0000, zero in the EXE image), which chains to the previous entry
"""
import hashlib, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import achbuild
import importlib.util
GAMEDIR = os.path.join(HERE, "xvsf")
_spec = importlib.util.spec_from_file_location("xv_ach_set", os.path.join(GAMEDIR, "set.py"))
SET = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(SET)

EXE_BASE, EXE_HDR = 0x80010000, 0x800
COPY_AT, COPY_END = 0x800a0000, 0x800c0000      # zero in the EXE image, below the boot cards (0x800c0000-0x800f0000)
PRESENT = (0x80028b58, 0x80028d60)
DRAWSYNC = 0x80016454
OVL_FILE, OVL_BASE = "P/P4/OPDEMO.BIN", 0x80098000
jal = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)
# words replaced (SHA-1 of the stock words: the sources carry no game code)
OVL_SITES = [(0x80098748, 2), (0x80098770, 1), (0x80098794, 1), (0x80098948, 2)]
OVL_SHA = "ce0919101830bf545007cc8558d7d0b3af41e1f3"     # SHA-1 of the stock words at OVL_SITES (the sources carry no game code)


OVL_AT = [0x80098748, 0x8009874c, 0x80098770, 0x80098794, 0x80098948, 0x8009894c, 0x8009bf54]   # port.c ovl_at


# XvSF: the shared span 0x80007600-0x80007a00 ends at 0x80007880: the START skip module with the ARCADE BALANCE option
# starts there (tools/skippatch.py BASE_BAL, docs/BALANCE.md)
SPANS = [(a, 0x80007880) if (a, b) == (0x80007600, 0x80007A00) else (a, b) for a, b in achbuild.SPANS]
assert SPANS != achbuild.SPANS


def build(defines=None):
    spans = SPANS
    if "--meter" in sys.argv:       # TEST builds with the speed meter (tools/meterpatch.py): keep its kernel ranges free
        base = SPANS if "--arcbal" in sys.argv else achbuild.SPANS          # (no ARCADE BALANCE module: whole 7600 span)
        spans = [(a, min(b, 0x80009A90) if a == 0x80009A10 else b) for a, b in base if a != 0x80009410]
    return achbuild.build_spans(GAMEDIR, SET, spans, defines=defines)


def code(prev_pc0, ds, ovl_sum):
    """our code only (the release builder prebakes this: builder/xvb/pipeline.py PREBAKED): prev_pc0 = the EXE entry
    the copy stub chains to, ds = the present routine's DrawSync call site, ovl_sum = sum of the stock menu-overlay
    words the runtime patches in RAM.  -> dict(copy, hooks, segs, info)"""
    segs, info = build(dict(PORT_OVL_SUM="0x%08xu" % ovl_sum))
    sym = info["sym"]
    A0 = achbuild.SPAN_BASE
    hooks = [(0x800285e0, jal(A0)), (ds, jal(A0 + 0x10)), (0x80028638, jal(sym["ach_menuin"]))]
    copy = achbuild.copy_stub_spans(COPY_AT, segs, hooks, prev_pc0, gd=sym.get("ach_gd"))      # (ACH_GDIAG builds only)
    inf = {k: v for k, v in info.items() if k not in ("sym", "size")}
    return dict(copy=copy, hooks=hooks, segs=segs, info=inf)


def apply(f, lmap, exe_read, exe_write, orig, touched):
    """the boot copy only: it checks that every target span is zero, copies the runtime, writes the hooks into the
    loaded EXE and flushes; the menu overlay is patched in RAM by the runtime (port.c port_ovl).  The disc's EXE code
    and overlay files stay stock."""
    u32 = lambda a: struct.unpack("<I", exe_read(a, 4))[0]
    assert u32(0x800285e0) == jal(0x8002d1e8) and u32(0x80028638) == jal(0x800987c0), "frame / menu hook site not stock"
    ds = [a for a in range(PRESENT[0], PRESENT[1], 4) if u32(a) == jal(DRAWSYNC)]
    assert len(ds) == 1, "present: DrawSync call not found once: %s" % ds
    prev_pc0 = struct.unpack("<I", exe_read(EXE_BASE - EXE_HDR + 0x10, 4))[0]
    l0 = lmap[OVL_FILE][0]
    def ovl_rd(a, n):
        o = a - OVL_BASE; out = bytearray()
        for i in range(n):
            f.seek((l0 + (o + i) // 2048) * 2352 + 24 + (o + i) % 2048); out += f.read(1)
        return bytes(out)
    stock = b"".join(ovl_rd(a, 4 * n) for a, n in OVL_SITES)
    assert hashlib.sha1(stock).hexdigest() == OVL_SHA, "menu overlay not stock"
    assert struct.unpack("<I", ovl_rd(0x8009bf54, 4))[0] == jal(0x800987c0), "OPDEMO: menu call not stock"
    ovl_sum = sum(struct.unpack("<I", ovl_rd(a, 4))[0] for a in OVL_AT) & 0xffffffff
    c = code(prev_pc0, ds[0], ovl_sum)
    copy, info = c["copy"], c["info"]
    assert COPY_AT + len(copy) <= COPY_END and exe_read(COPY_AT, len(copy)) == bytes(len(copy)), "copy area not zero"
    exe_write(COPY_AT, copy)
    exe_write(EXE_BASE - EXE_HDR + 0x10, struct.pack("<I", COPY_AT))
    print("achievements: %d (%d pts), runtime %d bytes in %d spans %s (free %d), copy %08x (%d bytes), idle hook %08x" % (
        info["achievements"], info["points"], info["image"], len(c["segs"]), info["segments"], info["free"], COPY_AT, len(copy), ds[0]))
    return c


if __name__ == "__main__":
    segs, info = build(dict(PORT_OVL_SUM="0u"))
    print({k: (hex(v) if isinstance(v, int) and v > 0x80000000 else v) for k, v in info.items() if k not in ("sym", "size")})
