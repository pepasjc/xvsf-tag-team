"""MvC achievements core + menu module build (freeze worker, rc4 line 2026-11-20).

  build(spans, defines) -> segs, sym, info:  core.S (hand-written MIPS) + the corec.py tables (gen/tables.c), packed into
      the kernel spans (first fit per section, as tools/ach/achbuild.py build_spans).  Span 0 starts with the entry block
      (+0 `j ach_frame`, +0x1c the sum of our read-only words).  The boot copy / guard stub is achbuild.copy_stub_spans.
  build_module(sym, ovl) -> bytes, msym:  module.c (tools/ach/ach.c page + card, the menu words) linked at MOD_AT =
      the end of OPDEMO.ARC's last sector in RAM: mktag appends it to a copy of OPDEMO.ARC (the game loads it with the
      menu).  Header: 'ACHM', size, sum of the code + rodata words from +0x10, end of code + rodata.

    python corebuild.py   (sizes)
"""
import os, sys, struct, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "ach"), os.path.join(ROOT, "tools")]
import achbuild, corec
GCC, CF = achbuild.GCC, achbuild.CF
OUT = os.path.join(HERE, "obj")

# kernel RAM free in rc4 (SPEED_TEAM.md "achievements on rc4"): inside achbuild.SPANS (real-PS1 proven), not used by
# kocache / pal8 (F040-F834), dx (state F840-FEE0, aux A100-A858 = its sector to A900, pools), spustore (FF40-FFDC),
# hookgate (9A10-9BBC), CHK (9410-94F0).  dx stash RAM given up with --ach (dxahead.py): 0x8000A900-B000, 0x80007600-7A00
# (side 0: 5.25 -> 2.5 KB), 0x8000B100-B500 (side 1: 3.5 -> 2.5 KB); Beetle cost work/frz/ach (npbench).
SPANS = [(0x8000A900, 0x8000B000), (0x80007600, 0x80007A00), (0x8000B100, 0x8000B500), (0x80009BC0, 0x80009CF0),
         (0x8000A040, 0x8000A100), (0x8000FEE0, 0x8000FF40)]
if os.environ.get("ACH_SPANS"):           # TEST builds (emulator only, mktag --allow-kernel): other spans, "lo-hi,lo-hi"
    SPANS = [tuple(int(x, 16) for x in p.split("-")) for p in os.environ["ACH_SPANS"].split(",")]
HOOK_FRAME, FRAMEBEGIN = 0x80022fe8, 0x8002097c
OPD_BASE, OPD_SIZE = 0x8009dfe4, 434932          # OPDEMO.ARC in RAM / on the disc (menus.py / exopt.py keep the size)
MOD_AT = OPD_BASE + (OPD_SIZE + 2047 & ~2047)    # = 0x801087e4: untouched in the main menu, OPTION, GALLERY (menufill.py)
MOD_MAX = 0x4000
OVL_CAP = 24
jal = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)

ENTRY = """	.set noreorder
	.section .text.entry,"ax"
	.globl _start
_start:
	j	ach_frame
	nop
	.space 0x14
	.word	0
"""
RO = (".text", ".rodata")


def run(args, cwd=OUT):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode: raise SystemExit("%s\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout


def nm(elf):
    sym = {}
    for l in run([GCC + "nm", "-n", elf]).splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    return sym


def _exact(secs, spans):
    """depth-first bin packing of the sections into the spans (largest first); None if impossible"""
    if any(al > 4 for o, n, sz, al in secs): return None
    room = [b - a - (0x20 if i == 0 else 0) for i, (a, b) in enumerate(spans)]
    items = sorted(secs, key=lambda x: -((x[2] + 3) & ~3))
    asg = [None] * len(items)
    def dfs(k):
        if k == len(items): return True
        sz, tried = (items[k][2] + 3) & ~3, set()
        for i in range(len(room)):
            if room[i] >= sz and room[i] not in tried:
                tried.add(room[i]); room[i] -= sz; asg[k] = i
                if dfs(k + 1): return True
                room[i] += sz
        return False
    if not dfs(0): return None
    place = [[] for _ in spans]
    for (o, n, sz, al), i in zip(items, asg): place[i].append((o, n))
    return place


def build(spans=SPANS, defines=None):
    """defines: MENUS5 = menus.py's OPDEMO state-table entry 5 (the core sees the unpatched main menu by it)"""
    gen = os.path.join(OUT, "gen")
    os.makedirs(gen, exist_ok=True)
    corec.main(gen)
    open(os.path.join(gen, "tables.c"), "w").write("#include <stdint.h>\n#define static\n#include \"core_set.h\"\n")
    open(os.path.join(OUT, "entry.S"), "w").write(ENTRY)
    N = len(spans)
    D = ["-D%s=%s" % kv for kv in (defines or {}).items()] + ["-DMOD_AT=0x%08x" % MOD_AT, "-DMOD_MAX=0x%x" % MOD_MAX]
    objs = [("entry.S", "entry.o"), (os.path.join(HERE, "core.S"), "core.o"), (os.path.join(gen, "tables.c"), "tables.o")]
    for src, o in objs:
        run([GCC + "gcc"] + CF + ["-I" + gen, "-Wa,-I" + gen] + D + ["-c", src, "-o", o])
    objs = [o for _, o in objs]
    open(os.path.join(OUT, "c1.ld"), "w").write("OUTPUT_ARCH(mips) ENTRY(_start) SECTIONS { . = 0x%08x; .all : { KEEP(*(.text.entry)) %s } %s "
        "/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) } }" % (spans[0][0], achbuild.ANY,
        " ".join("PROVIDE(_ro%d_s = 0); PROVIDE(_ro%d_e = 0);" % (i, i) for i in range(N))))
    r = subprocess.run([GCC + "ld", "--gc-sections", "--print-gc-sections", "-T", "c1.ld", "-o", "c1.elf"] + objs, cwd=OUT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    gone = {(l.split("'")[3], l.split("'")[1]) for l in r.stderr.splitlines() if "removing unused section" in l}
    secs = []
    for o in objs:
        for l in run([GCC + "objdump", "-h", o]).splitlines():
            p = l.split()
            if len(p) >= 7 and p[0].isdigit():
                name, size, al = p[1], int(p[2], 16), 2 ** int(p[6].split("**")[1])
                if not size or (o, name) in gone or name == ".text.entry": continue
                if not name.startswith((".text", ".rodata", ".data", ".sdata", ".sbss", ".bss", ".keep")): continue
                secs.append((o, name, size, max(al, 4)))
    room = [[a + (0x20 if i == 0 else 0), b] for i, (a, b) in enumerate(spans)]
    place = [[] for _ in spans]
    ro = lambda n: n.startswith(RO)
    for o, name, size, al in sorted(secs, key=lambda x: (not ro(x[1]), -x[2])):
        for i, rr in enumerate(room):
            st = (rr[0] + al - 1) & ~(al - 1)
            if st + size <= rr[1]:
                place[i].append((o, name)); rr[0] = st + size; break
        else:
            # (rc4.12) first fit failed: exact packing (sizes rounded up to 4; every section is 4-aligned), and if that fails
            # too, once more with CORE_SPLIT (core.S: modok in its own section).  Builds that fit first-fit are unchanged.
            ex = _exact(secs, spans)
            if ex is not None:
                place = ex; break
            if not (defines or {}).get("CORE_SPLIT"):
                return build(spans, dict(defines or {}, CORE_SPLIT="1"))
            raise SystemExit("core does not fit: %s %s %d B (all %d B, spans %d B)" % (o, name, size, sum(x[2] for x in secs) + 0x20,
                             sum(b - a for a, b in spans)))
    body = []
    for i, (a, b) in enumerate(spans):
        items = " ".join("KEEP(%s(%s))" % (o, n) for o, n in place[i] if ro(n)) + " . = ALIGN(4); _ro%d_e = .; " % i + \
                " ".join("KEEP(%s(%s))" % (o, n) for o, n in place[i] if not ro(n))
        head = "KEEP(*(.text.entry)) " if i == 0 else ""
        body.append(" .k%d 0x%08x : { %s_ro%d_s = .; %s . = ALIGN(4); }" % (i, a, head, i, items))
    open(os.path.join(OUT, "core.ld"), "w").write("OUTPUT_ARCH(mips) ENTRY(_start) SECTIONS { %s /DISCARD/ : { *(*) } }" % " ".join(body))
    run([GCC + "ld", "-T", "core.ld", "-o", "core.elf"] + objs)
    segs, used = [], 0
    for l in run([GCC + "objdump", "-h", "core.elf"]).splitlines():
        p = l.split()
        if len(p) >= 4 and p[1].startswith(".k") and p[1][2:].isdigit():
            size, vma = int(p[2], 16), int(p[3], 16)
            if not size: continue
            run([GCC + "objcopy", "-O", "binary", "-j", p[1], "core.elf", p[1][1:] + ".bin"])
            d = open(os.path.join(OUT, p[1][1:] + ".bin"), "rb").read()
            d += bytes(size - len(d)) + bytes(-size % 4)
            segs.append((vma, d)); used += len(d)
    sym = nm("core.elf")
    tot = 0                               # the read-only sum (entry +0x1c; the entry block itself is not in it)
    for i in range(N):
        s0, e0 = sym.get("_ro%d_s" % i, 0), sym.get("_ro%d_e" % i, 0)
        for a, d in segs:
            if a <= s0 < e0 <= a + len(d):
                tot += sum(struct.unpack_from("<%dI" % ((e0 - s0) // 4), d, s0 - a))
    a0, d0 = segs[0]
    assert a0 == spans[0][0] and sym["_ro0_s"] == a0 + 0x20
    d0 = bytearray(d0)
    struct.pack_into("<I", d0, 0x1c, tot & 0xFFFFFFFF); segs[0] = (a0, bytes(d0))
    for a, d in segs:
        assert any(s <= a and a + len(d) <= e for s, e in spans), "segment %08x+%x outside the spans" % (a, len(d))
    info = dict(used=used, free=sum(b - a for a, b in spans) - used, secs=sorted(((n, o, s) for o, n, s, _ in secs), key=lambda x: -x[2]))
    return segs, sym, info


def hooks(sym):
    return [(HOOK_FRAME, jal(sym["_start"]))]


# ---- the menu module ---------------------------------------------------------------------------------------------
MOD_MAGIC = 0x4d484341


def build_module(csym, ovl=None):
    """ovl = (word indexes from OPDEMO's base, new words), <= OVL_CAP (fixed size: the layout does not depend on it)"""
    import setc
    gen = os.path.join(OUT, "mgen"); os.makedirs(gen, exist_ok=True)
    SET = corec.SET
    setc.compile_set(SET.ACHS, os.path.join(gen, "set.c"), os.path.join(gen, "set.txt"), **SET.TEXT)
    open(os.path.join(gen, "icon.c"), "w").write(achbuild.icon_c())
    at, w = ovl or ([], [])
    assert len(at) <= OVL_CAP
    n = len(at); at = list(at) + [0] * (OVL_CAP - n); w = list(w) + [0] * (OVL_CAP - n)
    open(os.path.join(gen, "ovl.c"), "w").write("#include <stdint.h>\nconst uint32_t m_ovl_n = %d;\nconst uint16_t m_ovl_at[%d] = { %s };\n"
        "const uint32_t m_ovl_w[%d] = { %s };\n" % (n, OVL_CAP, ", ".join(str(x) for x in at), OVL_CAP, ", ".join("0x%08xu" % x for x in w)))
    gt = os.path.abspath(os.path.join(HERE, ".."))                          # games/mvc/tools/ach: port.h
    inc = ["-I" + os.path.join(ROOT, "tools", "ach"), "-I" + gt, "-include", os.path.join(gt, "port.h")]
    D = ["-DC_DONE=0x%08x" % csym["c_done"], "-DC_DIRTY=0x%08x" % csym["c_dirty"], "-DC_PAGE=0x%08x" % csym["c_page"],
         "-DMOD_AT=0x%08x" % MOD_AT, "-DNACH_CORE=%d" % len(SET.ACHS), "-DACH_BASE=0"]
    if "--vscpu" in sys.argv and "--mtap" not in sys.argv: D.append("-DVSMENU=1")   # (rc4.15) 8-line menu: VERSUS CPU
    objs = []
    for src, o in ((os.path.join(HERE, "module.c"), "module.o"), (os.path.join(gen, "set.c"), "mset.o"),
                   (os.path.join(gen, "icon.c"), "micon.o"), (os.path.join(gen, "ovl.c"), "movl.o")):
        run([GCC + "gcc"] + CF + inc + D + ["-c", src, "-o", o]); objs.append(o)
    open(os.path.join(OUT, "mod.ld"), "w").write("OUTPUT_ARCH(mips) ENTRY(_mstart) SECTIONS { . = 0x%08x; .m : { KEEP(*(.text.entry)) "
        "*(.text*) *(.rodata*) . = ALIGN(4); _mro_end = .; *(.data*) *(.sdata*) *(.bdat) KEEP(*(.keep*)) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); } "
        "/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) } }" % MOD_AT)
    run([GCC + "ld", "--gc-sections", "-T", "mod.ld", "-o", "mod.elf"] + objs)
    run([GCC + "objcopy", "-O", "binary", "-j", ".m", "mod.elf", "mod.bin"])
    sz = int(next(l.split()[2] for l in run([GCC + "objdump", "-h", "mod.elf"]).splitlines() if len(l.split()) > 3 and l.split()[1] == ".m"), 16)
    d = bytearray(open(os.path.join(OUT, "mod.bin"), "rb").read())
    d += bytes(sz - len(d)) + bytes(-sz % 4)
    assert struct.unpack_from("<I", d, 0)[0] == MOD_MAGIC
    msym = nm("mod.elf")
    assert msym["mod_menu"] and struct.unpack_from("<I", d, 0x28)[0] == jal(msym["mod_menu"]), "+0x28 is not the state stub"
    struct.pack_into("<I", d, 4, len(d))
    ro = msym["_mro_end"] - MOD_AT
    struct.pack_into("<I", d, 12, ro)
    open(os.path.join(OUT, "mod.sym"), "w").write(chr(10).join("%08x %s" % (v, k) for k, v in sorted(msym.items(), key=lambda x: x[1])))
    return d, msym


def seal_module(d):
    """the code + rodata sum at +8 (after any patching of the module's bytes)"""
    d = bytearray(d)
    ro = struct.unpack_from("<I", d, 12)[0]
    struct.pack_into("<I", d, 8, sum(struct.unpack_from("<%dI" % ((ro - 16) // 4), d, 16)) & 0xFFFFFFFF)
    return bytes(d)


if __name__ == "__main__":
    segs, sym, info = build(defines={"MENUS5": "0x800a2de0"})
    print("core %d B in %s, %d B of the spans free" % (info["used"], ", ".join("%08x+%d" % (a, len(d)) for a, d in segs), info["free"]))
    for n, o, s in info["secs"][:30]: print("  %5d %s %s" % (s, o, n))
    m, ms = build_module(sym)
    print("module %d B at %08x" % (len(m), MOD_AT))
