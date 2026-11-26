"""mktag.py --vcache: VRAM-resident decoded-tile cache (tools/vcache2/vc4.py), image right below the loader's strong
payload: VC_AT = STRONG_AT - VC_SIZE (0x801fc740-0x801fd400).

RAM: tagload.c reserves it as CACHE (the planner's region ends at STRONG - CACHE) whenever the plan still fits with it
and the stage is in STAGES (VCGATE test builds: only when no character gets a DSA1 tier it did not have).  tl_main copies the image (code + tables from the blob,
index zeroed) after the last read, then sets the enable word.  NOT the arena tail: the super cut-in decode
(0x80045a80, 28,800 B) writes 0x80092c40-0x80099d40 during every super.
EXE (static): 0x8008c5cc `jal 0x8008c318` -> `jal STUB`; STUB (dead span 0x8001a79c, released by cpufast): enable word FLAG (in
the span, written by tl_main every tag battle: 0 at its start, 1 after the copy) -> `j vc`, else `j 0x8008c318`.
Chain: vc4 state word NEXT (default the decoder); --vmove / --fxskip put their entry there (SPEED_TEAM.md)."""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "speed", "frame")]
import vc4 as vc3
STRONG_AT = 0x801fd400
SIZE = 0xcc0
WAYS = 4 if "--vcassoc" in sys.argv else 1   # --vcassoc (dx worker, L5): 4-way set-associative index, same 256 entries
if WAYS > 1: SIZE += 0x80                   # +64 B lookup code
AT = STRONG_AT - SIZE
if "--koreload" in sys.argv:                 # tools/koreload: its resident image sits right below STRONG, the cache below it
    sys.path.insert(0, os.path.join(HERE, "..", "koreload")); import build as _krlb
    AT -= _krlb.SIZE
STUB_AT, STUB_END = 0x8001a79c, 0x8001a7c4      # released by cpufast (CODESPACE.md, SPEED_TEAM.md)
FLAG = STUB_END - 4                       # enable word inside the claimed span
# stages with a cache (and its RAM reservation); stage 8 + --pal8 uses only the remainder (vc4 table 1).  VC_NOST8=1:
# no cache on stage 8 at all
STAGES = 0x3ff if not os.environ.get("VC_NOST8") else 0x2ff   # bits 0-9 (Onslaught 9 is off anyway: TOP_ONSL)
SITE, SITEW0, DEC = vc3.SITE, vc3.SITEW0, vc3.DEC


def image():
    img, sym = vc3.build(AT, ways=WAYS)
    assert sym["_end"] <= STRONG_AT, hex(sym["_end"])
    return img[:sym["_img"]], sym


def stub(sym):
    from gas import gas
    src = r"""
        lui   $t0, %%hi(0x%x)
        lw    $t1, %%lo(0x%x)($t0)
        nop
        beqz  $t1, 1f
        nop
        j     0x%x
        nop
1:      j     0x%x
        nop
""" % (FLAG, FLAG, sym["vc"], DEC)
    code, _ = gas(src, STUB_AT)
    assert STUB_AT + len(code) <= FLAG
    return code


def exe_patches():
    nz, sym = image()
    st = stub(sym)
    return [(STUB_AT, st + bytes(FLAG - STUB_AT - len(st)) + bytes(4)),
            (SITE, struct.pack("<I", 0x0c000000 | (STUB_AT >> 2 & 0x3ffffff)))]


def header(outdir):
    """vcache.h for tagload.c: VC_STAGES, VC_AT, VC_SIZE, VC_FLAG, vc_img[] (code + tables; tl_main zeroes the index)"""
    nz, sym = image()
    w = struct.unpack("<%dI" % (len(nz) // 4), nz)
    NL = chr(10)
    rows = ("," + NL).join(", ".join("0x%08xu" % x for x in w[i:i + 6]) for i in range(0, len(w), 6))
    txt = NL.join(["#define VC_STAGES 0x%xu" % STAGES, "#define VC_AT 0x%08xu" % AT, "#define VC_SIZE 0x%xu" % SIZE,
                   "#define VC_FLAG 0x%08xu" % FLAG, "#define VC_NEXT 0x%08xu" % (sym["_st"] + vc3.NEXT),
                   "#define VC_STUBJAL 0x%08xu" % (0x0c000000 | (STUB_AT >> 2 & 0x3ffffff)),
                   "static const u32 vc_img[%d] = {" % len(w), rows, "};", ""])
    open(os.path.join(outdir, "vcache.h"), "w").write(txt)
    return sym


if __name__ == "__main__":
    nz, sym = image()
    print("AT %08x image %d B, end %08x (STRONG %08x), stub %d B, vc %08x" % (AT, len(nz), sym["_end"], STRONG_AT, len(stub(sym)), sym["vc"]))
