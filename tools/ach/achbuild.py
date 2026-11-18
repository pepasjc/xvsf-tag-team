"""Build the built-in achievements blob of one game (tools/ach runtime + the game's port + its set).

    blob, info = build(game_dir, set_mod, base, limit, defines)      -> code+data image linked at `base`, bss after it
    copy = copy_stub(at, blob, base, bss_len, prev_pc0)               -> boot copy stub + blob, linked at `at`

The game's tools/ach/ holds port.h, port.c and set.py (ACHS = list of dicts id/title/desc/points/memaddr,
TEXT = setc.compile_set options).  The derived bytes of port.c (struct vars ach_v) sit at base + 0x20.
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools")]
import toolenv, setc

GCC = toolenv.mips_prefix()
CF = ["-march=r3000", "-mtune=r3000", "-mno-abicalls", "-fno-pic", "-G0", "-msoft-float", "-Os", "-ffreestanding",
      "-fno-builtin", "-nostdlib", "-Wall", "-Wno-unused-function", "-fno-strict-aliasing", "-mno-check-zero-division",
      "-fno-toplevel-reorder", "-ffunction-sections", "-fdata-sections"]

ICON = ["................",
        "..YYYYYYYYYYYY..",
        ".YYWYYYYYYYYYYY.",
        "YY.YWYYYYYYYY.YY",
        "Y..YWYYYYYYYY..Y",
        "Y..YWYYYYYYYY..Y",
        ".YY.YWYYYYYY.YY.",
        "...YYWYYYYYYY...",
        "....YYYYYYYY....",
        ".....YYYYYY.....",
        "......YYYY......",
        "......OYYO......",
        ".....OYYYYO.....",
        "....OOOOOOOO....",
        "...BBBBBBBBBB...",
        "...BBBBBBBBBB..."]

LD = """OUTPUT_ARCH(mips)
ENTRY(_start)
MEMORY { A (rwx) : ORIGIN = %(a0)s, LENGTH = %(alen)s
         B (rwx) : ORIGIN = %(b0)s, LENGTH = %(blen)s
         C (rwx) : ORIGIN = %(c0)s, LENGTH = %(clen)s }
SECTIONS {
	.textc : { %(ctext)s . = ALIGN(4); } > C
	_endc = .;
	.text : { KEEP(*(.text.entry)) . = 0x20; KEEP(*(.vars)) . = ALIGN(4); %(atext)s } > A
	.data : { icon.o(.rodata*) KEEP(*(.keep*)) *(.data*) *(.sdata*) . = ALIGN(4); } > A
	__bss_start = .;
	.bss : { *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); } > A
	_end = .;
	.textb : { KEEP(*(.keeptext)) %(btext)s *(.rodata*) . = ALIGN(4); *(.bdat) . = ALIGN(4); } > B
	_endb = .;
	/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) }
}
"""
# kernel RAM the BIOS leaves unused (docs/ACHIEVEMENTS.md "Room"): A = code, data, bss; B = read-only data (+ code that
# does not fit A)
REGION_A = (0x8000C000, 0x8000DF80)
REGION_B = (0x8000E600, 0x8000FFF0)
REGION_C = (0x80007600, 0x80008400)       # optional (MvC): only the sections a game names go there


def icon_c():
    pal = {".": 0x0000, "Y": 0x033F, "W": 0x6BFF, "O": 0x0198, "B": 0x2108}
    keys = list(pal)
    out = bytearray()
    for c in keys + [""] * (16 - len(keys)):
        out += struct.pack("<H", pal.get(c, 0))
    for row in ICON:
        for x in range(0, 16, 2):
            out.append(keys.index(row[x]) | keys.index(row[x + 1]) << 4)
    return "#include <stdint.h>\nconst uint8_t ach_icon[] = {" + ",".join(map(str, out)) + "};\n"


def run(args, cwd):
    subprocess.check_call(args, cwd=cwd)


def build(game_tools, set_mod, defines=None, out_dir=None, b_objs=("port.o",), c_secs=()):
    """game_tools = games/<g>/tools/ach; returns ((image A (text+data), image B), info dict with bss/sizes/symbols).
    b_objs: objects whose code goes to region B"""
    base, limit = REGION_A
    out = out_dir or os.path.join(game_tools, "obj")
    gen = os.path.join(out, "gen")
    os.makedirs(gen, exist_ok=True)
    info = setc.compile_set(set_mod.ACHS, os.path.join(gen, "set.c"), os.path.join(gen, "set.txt"), **set_mod.TEXT)
    open(os.path.join(gen, "icon.c"), "w").write(icon_c())
    ld = LD % dict(a0="0x%08x" % REGION_A[0], alen="0x%x" % (REGION_A[1] - REGION_A[0]), b0="0x%08x" % REGION_B[0],
                   blen="0x%x" % (REGION_B[1] - REGION_B[0]), c0="0x%08x" % REGION_C[0], clen="0x%x" % (REGION_C[1] - REGION_C[0]),
                   ctext=" ".join("KEEP(%s)" % c for c in c_secs),
                   atext=("*(EXCLUDE_FILE(%s) .text*)" % " ".join(b_objs)) if b_objs else "*(.text*)",
                   btext=" ".join("%s(.text*)" % o for o in b_objs))
    open(os.path.join(out, "ach.ld"), "w").write(ld)
    defines = dict(defines or {})
    if os.environ.get("ACH_DIAG"): defines["ACH_DIAG"] = os.environ["ACH_DIAG"]      # real-hardware bisect builds (ach.c)
    defines.setdefault("ACH_NOWD", 1)                    # (the watchdog needs build_spans' ranges)
    D = ["-D%s=%s" % (k, v) for k, v in defines.items()]
    inc = ["-I" + HERE, "-I" + game_tools, "-include", os.path.join(game_tools, "port.h")]
    srcs = [(os.path.join(HERE, "start.S"), "start.o"), (os.path.join(HERE, "ach.c"), "ach.o"),
            (os.path.join(HERE, "eval.c"), "eval.o"), (os.path.join(game_tools, "port.c"), "port.o"),
            (os.path.join(gen, "set.c"), "set.o"), (os.path.join(gen, "icon.c"), "icon.o")]
    for src, obj in srcs:
        run([GCC + "gcc"] + CF + (inc if src.endswith(".c") else []) + D + ["-c", src, "-o", obj], out)
    run([GCC + "ld", "--gc-sections", "-T", "ach.ld", "-o", "ach.elf"] + [o for _, o in srcs], out)
    run([GCC + "objcopy", "-O", "binary", "-j", ".text", "-j", ".data", "ach.elf", "ach.bin"], out)
    run([GCC + "objcopy", "-O", "binary", "-j", ".textb", "ach.elf", "achb.bin"], out)
    run([GCC + "objcopy", "-O", "binary", "-j", ".textc", "ach.elf", "achc.bin"], out)
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", "ach.elf"], cwd=out).decode().splitlines():
        p = l.split()
        if len(p) == 3:
            sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    img = open(os.path.join(out, "ach.bin"), "rb").read()
    imgb = open(os.path.join(out, "achb.bin"), "rb").read()
    imgc = open(os.path.join(out, "achc.bin"), "rb").read() if c_secs else b""
    if c_secs:
        assert len(imgc) == sym["_endc"] - REGION_C[0]
    assert len(img) == sym["__bss_start"] - base, (len(img), hex(sym["__bss_start"]))
    assert len(imgb) == sym["_endb"] - REGION_B[0], (len(imgb), hex(sym["_endb"]))
    bss = sym["_end"] - sym["__bss_start"]
    assert sym["ach_v"] == base + 0x20, hex(sym["ach_v"])
    assert sym["_end"] <= limit and sym["_endb"] <= REGION_B[1]
    size = subprocess.check_output([GCC + "size", "ach.elf"] + [o for _, o in srcs], cwd=out).decode()
    info.update(image=len(img), imageb=len(imgb), bss=bss, end=sym["_end"], free=limit - sym["_end"],
                endb=sym["_endb"], freeb=REGION_B[1] - sym["_endb"], imagec=len(imgc), sym=sym, size=size)
    return ((img, imgb, imgc) if c_secs else (img, imgb)), info


def copy_stub(game_tools, at, imgs, bss, prev_pc0, out_dir=None):
    """boot copy stub + both images, linked at `at` (a zero area of the EXE image)"""
    out = out_dir or os.path.join(game_tools, "obj")
    img, imgb = imgs[:2]
    imgc = imgs[2] if len(imgs) > 2 else b""
    for f, d in (("blob.bin", img), ("blobb.bin", imgb), ("blobc.bin", imgc)):
        open(os.path.join(out, f), "wb").write(d + bytes(-len(d) % 4))
    D = ["-DACH_BASE=0x%08x" % REGION_A[0], "-DBLOB_LEN=%d" % (len(img) + (-len(img) % 4)), "-DBSS_LEN=%d" % (bss + (-bss % 4)),
         "-DACH_BASEB=0x%08x" % REGION_B[0], "-DBLOBB_LEN=%d" % (len(imgb) + (-len(imgb) % 4)),
         "-DACH_BASEC=0x%08x" % REGION_C[0], "-DBLOBC_LEN=%d" % (len(imgc) + (-len(imgc) % 4)),
         "-DPREV_PC0=0x%08x" % prev_pc0, '-DBLOB_FILE="blob.bin"', '-DBLOBB_FILE="blobb.bin"', '-DBLOBC_FILE="blobc.bin"']
    run([GCC + "gcc"] + CF + D + ["-c", os.path.join(HERE, "copy.S"), "-o", "copy.o"], out)
    run([GCC + "ld", "-Ttext=0x%08x" % at, "-e", "ach_copy", "-o", "copy.elf", "copy.o"], out)
    run([GCC + "objcopy", "-O", "binary", "-j", ".text", "copy.elf", "copy.bin"], out)
    return open(os.path.join(out, "copy.bin"), "rb").read()


# ---------------------------------------------------------------- 2026-11-17: kernel RAM spans proven free on a real PS1
# A real SCPH-5500 + PSIO boot (both PSIO modes, with and without a memory card) leaves data in 0x8000C000-0x8000C0FF,
# 0x8000C800-0x8000EFFF that emulators and the MiSTer don't (xvsf_kdiag, tools/skip/kdiag.c): the old regions A / B
# crashed it.  Free there (zero at boot, never written in the game), with 0x40 bytes of margin to every used block:
SPANS = [(0x8000F040, 0x8000FFE0), (0x8000A040, 0x8000AFF0), (0x8000B110, 0x8000B7F0), (0x8000C110, 0x8000C7F0),
         (0x80008000, 0x800083C0), (0x80007600, 0x80007A00), (0x80009A10, 0x80009CF0), (0x80009410, 0x800094F0), (0x8000F010, 0x8000F040)]
# margins: 0x40 to the blocks the game writes (8400, 9F00, BA00-BFFF) and below the old kernel heap (F000), 0x10 to the
# blocks that only hold data at boot (N on the map), 0x2d above the kernel's code (ends 0x800075d3).
# NOT 0x80008700-0x800088FF although the map shows it zero and unwritten: a build using it hangs Beetle before the
# game starts (the BIOS reads something there) - zero is not proof of free; every span is boot-tested in emulators.
SPAN_BASE = SPANS[0][0]           # entry table (+0), struct vars (+0x20): the sets read the vars at SPAN_BASE + 0x20

LDS = """OUTPUT_ARCH(mips)
ENTRY(_start)
MEMORY { %(mem)s }
SECTIONS {
	.k0 : { KEEP(*(.text.entry)) . = 0x20; KEEP(*(.vars)) . = ALIGN(4); %(any)s } > K0
%(more)s
	PROVIDE(_end = .);
	/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) }
}
"""
ANY = "KEEP(*(.keeptext)) KEEP(*(.keep*)) *(.text*) *(.rodata*) *(.data*) *(.sdata*) *(.bdat) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4);"


def build_spans(game_tools, set_mod, spans, defines=None, out_dir=None):
    """the runtime packed into `spans` (the linker places every function / object in the first span it fits:
    --enable-non-contiguous-regions; BSS is part of the images, so each span's image is copied whole).
    -> ([(address, bytes)] per used span, info)"""
    out = out_dir or os.path.join(game_tools, "obj")
    gen = os.path.join(out, "gen")
    os.makedirs(gen, exist_ok=True)
    info = setc.compile_set(set_mod.ACHS, os.path.join(gen, "set.c"), os.path.join(gen, "set.txt"), **set_mod.TEXT)
    open(os.path.join(gen, "icon.c"), "w").write(icon_c())
    mem = " ".join("K%d (rwx) : ORIGIN = 0x%08x, LENGTH = 0x%x" % (i, a, b - a) for i, (a, b) in enumerate(spans))
    more = "\n".join("\t.k%d : { %s } > K%d" % (i, ANY, i) for i in range(1, len(spans)))
    open(os.path.join(out, "ach.ld"), "w").write(LDS % dict(mem=mem, any=ANY, more=more))
    defines = dict(defines or {})
    if os.environ.get("ACH_DIAG"): defines["ACH_DIAG"] = os.environ["ACH_DIAG"]
    if os.environ.get("ACH_NOWD"): defines["ACH_NOWD"] = 1          # test builds: watchdog off
    if os.environ.get("ACH_GDIAG"): defines["ACH_GDIAG"] = GD_N          # guard diagnostic build (copy_stub_spans gd)
    if os.environ.get("ACH_GDIAG") == "nopage": defines["ACH_GDIAG_NOPAGE"] = 1     # (no room for the page as well)
    D = ["-D%s=%s" % (k, v) for k, v in defines.items()] + ["-DACH_BASE=0x%08x" % spans[0][0]]
    inc = ["-I" + HERE, "-I" + game_tools, "-include", os.path.join(game_tools, "port.h")]
    srcs = [(os.path.join(HERE, "start.S"), "start.o"), (os.path.join(HERE, "ach.c"), "ach.o"),
            (os.path.join(HERE, "eval.c"), "eval.o"), (os.path.join(game_tools, "port.c"), "port.o"),
            (os.path.join(gen, "set.c"), "set.o"), (os.path.join(gen, "icon.c"), "icon.o")]
    N = len(spans)
    if not defines.get("ACH_NOWD"):                      # watchdog ranges: our read-only part of each span (ach.c)
        open(os.path.join(gen, "wd.c"), "w").write("#include <stdint.h>\nextern char %s;\nconst uint32_t ach_wd_n = %d;\n"
            "const uint32_t ach_wd_tab[%d][2] = { %s };\n" % (", ".join("_ro%d_s[], _ro%d_e[]" % (i, i) for i in range(N)), N, N,
            ", ".join("{ (uint32_t)_ro%d_s, (uint32_t)_ro%d_e }" % (i, i) for i in range(N))))
        srcs.append((os.path.join(gen, "wd.c"), "wd.o"))
    for src, obj in srcs:
        run([GCC + "gcc"] + CF + ["-fdata-sections", "-fno-merge-constants"] + (inc if src.endswith(".c") else []) + D + ["-c", src, "-o", obj], out)
    objs = [o for _, o in srcs]
    # pass 1: which input sections survive --gc-sections (one big region)
    open(os.path.join(out, "ach1.ld"), "w").write(
        "OUTPUT_ARCH(mips) ENTRY(_start) SECTIONS { . = 0x%08x; .all : { KEEP(*(.text.entry)) . = 0x20; KEEP(*(.vars)) %s } PROVIDE(_end = .); %s "
        "/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) } }" % (spans[0][0], ANY,
        " ".join("PROVIDE(_ro%d_s = 0); PROVIDE(_ro%d_e = 0);" % (i, i) for i in range(N))))
    r = subprocess.run([GCC + "ld", "--gc-sections", "--print-gc-sections", "-T", "ach1.ld", "-o", "ach1.elf"] + objs,
                       cwd=out, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    gone = set()
    for l in r.stderr.splitlines():                      # "removing unused section '.text.x' in file 'ach.o'"
        if "removing unused section" in l:
            q = l.split("'")
            gone.add((q[3], q[1]))
    # sizes and alignment of the surviving input sections
    secs = []
    for o in objs:
        for l in subprocess.check_output([GCC + "objdump", "-h", o], cwd=out).decode().splitlines():
            p = l.split()
            if len(p) >= 7 and p[0].isdigit():
                name, size, al = p[1], int(p[2], 16), 2 ** int(p[6].split("**")[1])
                if not size or (o, name) in gone: continue
                if not name.startswith((".text", ".rodata", ".data", ".sdata", ".bdat", ".sbss", ".bss", ".keep", ".vars")): continue
                if name in (".text.entry", ".vars"): continue
                secs.append((o, name, size, max(al, 4)))
    # first fit, largest first; span 0 starts after the entry table + vars (0x30)
    room = [[a + (0x30 if i == 0 else 0), b] for i, (a, b) in enumerate(spans)]
    place = [[] for _ in spans]
    ro = lambda name: name.startswith((".text", ".rodata", ".keeptext"))
    wd = not defines.get("ACH_NOWD")
    for o, name, size, al in sorted(secs, key=lambda x: (wd and not ro(x[1]), -x[2])):  # watchdog: read-only first
        for i, rr in enumerate(room):
            start = (rr[0] + al - 1) & ~(al - 1)
            if start + size <= rr[1]:
                place[i].append((o, name)); rr[0] = start + size; break
        else:
            raise SystemExit("achievements runtime does not fit the spans: %s %s %d bytes (all sections %d, spans %d)" % (o, name, size, sum(x[2] for x in secs) + 0x30, sum(b - a for a, b in spans)))
    body = []
    for i, (a, b) in enumerate(spans):
        if wd:
            items = " ".join("KEEP(%s(%s))" % (o, n) for o, n in place[i] if ro(n)) + " . = ALIGN(4); _ro%d_e = .; " % i +                     " ".join("KEEP(%s(%s))" % (o, n) for o, n in place[i] if not ro(n))
        else:
            items = " ".join("KEEP(%s(%s))" % (o, n) for o, n in place[i]) + " _ro%d_e = .; " % i
        head = ("KEEP(*(.text.entry)) . = 0x20; KEEP(*(.vars)) . = 0x30; " if i == 0 else "") + "_ro%d_s = .; " % i
        body.append(" .k%d 0x%08x : { %s%s . = ALIGN(4); }" % (i, a, head, items))
    open(os.path.join(out, "ach.ld"), "w").write("OUTPUT_ARCH(mips) ENTRY(_start) SECTIONS { %s PROVIDE(_end = 0); "
        "/DISCARD/ : { *(*) } }" % " ".join(body))
    run([GCC + "ld", "-T", "ach.ld", "-o", "ach.elf"] + objs, out)
    segs, used = [], 0
    hdr = subprocess.check_output([GCC + "objdump", "-h", "ach.elf"], cwd=out).decode()
    for l in hdr.splitlines():
        p = l.split()
        if len(p) >= 4 and p[1].startswith(".k") and p[1][2:].isdigit():
            size, vma = int(p[2], 16), int(p[3], 16)
            if not size: continue
            run([GCC + "objcopy", "-O", "binary", "-j", p[1], "ach.elf", p[1][1:] + ".bin"], out)
            data = open(os.path.join(out, p[1][1:] + ".bin"), "rb").read()
            data += bytes(size - len(data)) + bytes(-size % 4)
            segs.append((vma, data)); used += size
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", "ach.elf"], cwd=out).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    assert sym["ach_v"] == spans[0][0] + 0x20, hex(sym["ach_v"])
    # entry +0x1c: the sum of our read-only words (the watchdog's reference; also tells our own leftovers)
    tot = 0
    for i in range(N):
        s0, e0 = sym.get("_ro%d_s" % i, 0), sym.get("_ro%d_e" % i, 0)
        for a, d in segs:
            if a <= s0 < e0 <= a + len(d):
                tot += sum(struct.unpack_from("<%dI" % ((e0 - s0) // 4), d, s0 - a))
    tot &= 0xFFFFFFFF
    assert segs[0][0] == spans[0][0]
    d0 = bytearray(segs[0][1]); struct.pack_into("<I", d0, 0x1c, tot); segs[0] = (segs[0][0], bytes(d0))
    for a, d in segs:
        assert any(s <= a and a + len(d) <= e for s, e in spans), "segment %08x+%x outside the spans" % (a, len(d))
    free = sum(e - s for s, e in spans) - used
    info.update(image=used, free=free, segments=[(hex(a), len(d)) for a, d in segs], sym=sym, rosum=tot)
    return segs, info


PATTERN = 0x5AC3A53C               # boot guard: span word = its address ^ PATTERN
SPIN = 0x100000                    # boot guard wait: ~3 cycles a turn at 33.9 MHz = ~93 ms (~5.6 vblanks)
GD_N = 12                         # guard diagnostic: records (ach.c ach_gd, 4 words each): per segment, then the probes
GD_PROBES = [(0x8000F000, 0x80010000), (0x8000E500, 0x8000E600)]     # records 10, 11


def copy_stub_spans(at, segs, hooks, prev_pc0, gd=None):
    """boot copy (mipsasm, at `at` in a zero area of the EXE image).  GUARD (pattern test): the spans' contents are
    saved behind the stub (the zero area: the returned bytes include it), every span is filled with an address
    pattern, the stub waits ~6 vblanks (interrupts as the BIOS left them), then checks the pattern: if anything
    wrote a span, the contents are put back and nothing is hooked (the game runs stock).  Leftovers do not matter
    (the stale fill of a PSIO menu boot, our own runtime after a reset): only a writer refuses.  Then each segment
    is copied, the backup is cleared, the hook words are written into the loaded EXE, FlushCache, and the previous
    pc0.  sp / gp / a0 / a1 kept.  gd: the diagnostic build (records, no test)."""
    sys.path.insert(0, os.path.join(HERE, ".."))
    from mipsasm import Asm, REG
    REG.setdefault("$s6", 22); REG.setdefault("$s7", 23)
    a = Asm(at)
    a.addu("$s7", "$a0", "$zero"); a.addu("$s6", "$a1", "$zero")
    if not os.environ.get("ACH_NOROMCHECK") and gd is None:  # ROM check (2026-11-18, work/ps3test): the PS1-mode ROMs of the
        a.lui("$t0", 0xBFC0)                                 # PS2 / PS3 (System ROM 5.0, BCD date at 0xBFC00100 >= 2001;
        a.lw("$t0", 0x100, "$t0")                            # PS3 ps1_rom.bin 0x20111012) keep the kernel's device and
        a.lui("$t1", 0x2001)                                 # file tables in 0x8000A8D0-AD60 / B1A0-B7A8: inside our
        a.sltu("$t1", "$t0", "$t1")                          # spans (PS3 black screen after the Capcom logo).  Every PS1
        a.beq("$t1", "$zero", "skip")                        # ROM is dated <= 2000 (v4.5 05/25/00): there the stub runs on
        a.nop()                                              # unchanged.  PS2/PS3: nothing touched, no hooks, stock game
                                                             # (+ START skip, own module).  ACH_NOROMCHECK=1: the 1.3/1.0 RC stub.
    def la(r, lab, off=0):                                   # la r, label + off (resolved at assembly)
        a._i(lambda pc, L: 0x3C000000 | REG[r] << 16 | ((L[lab] + off) >> 16 & 0xFFFF))
        a._i(lambda pc, L: 0x34000000 | REG[r] << 21 | REG[r] << 16 | ((L[lab] + off) & 0xFFFF))
    def gd_scan(i, p0, p1):                                  # DIAGNOSTIC record i: first / last non-zero address,
        assert i < GD_N                                      # non-zero words, words neither 0 nor FFFFFFFF
        la("$t4", "rec", 16 * i)
        a.addu("$t5", "$zero", "$zero"); a.addu("$t7", "$zero", "$zero")
        a.label("g%d" % i)
        a.lw("$t3", 0, "$t1")
        a.addiu("$t1", "$t1", 4)
        a.beq("$t3", "$zero", "z%d" % i)
        a.nop()
        a.bne("$t5", "$zero", "n%d" % i)
        a.addiu("$t6", "$t1", -4)
        a.sw("$t6", 0, "$t4")
        a.label("n%d" % i)
        a.sw("$t6", 4, "$t4")
        a.addiu("$t5", "$t5", 1)
        a.addiu("$t6", "$t3", 1)
        a.beq("$t6", "$zero", "z%d" % i)
        a.nop()
        a.addiu("$t7", "$t7", 1)
        a.label("z%d" % i)
        a.bne("$t1", "$t2", "g%d" % i)
        a.nop()
        a.sw("$t5", 8, "$t4"); a.sw("$t7", 12, "$t4")
    for i, (dst, d) in enumerate(segs):                      # guard
        a.lui("$t1", dst >> 16); a.ori("$t1", "$t1", dst & 0xffff)
        e = dst + len(d)
        a.lui("$t2", e >> 16); a.ori("$t2", "$t2", e & 0xffff)
        if gd is not None:
            gd_scan(i, dst, e)
    def xor(rd, rs, rt):
        a._i(lambda pc, L: REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11 | 0x26)
    def li(r, v):
        a.lui(r, v >> 16 & 0xffff); a.ori(r, r, v & 0xffff)
    bko, nbk = [], 0
    for dst, d in segs:
        bko.append(nbk); nbk += len(d)
    def zero_backup(tag):
        la("$t0", "bk"); la("$t2", "bk", nbk)
        a.label(tag)
        a.sw("$zero", 0, "$t0")
        a.addiu("$t0", "$t0", 4)
        a.bne("$t0", "$t2", tag)
        a.nop()
    if gd is None:
        for i, (dst, d) in enumerate(segs):                  # save
            li("$t1", dst); li("$t2", dst + len(d)); la("$t0", "bk", bko[i])
            a.label("b%d" % i)
            a.lw("$t3", 0, "$t1")
            a.addiu("$t1", "$t1", 4)
            a.sw("$t3", 0, "$t0")
            a.bne("$t1", "$t2", "b%d" % i)
            a.addiu("$t0", "$t0", 4)
        li("$t4", PATTERN)
        for i, (dst, d) in enumerate(segs):                  # fill
            li("$t1", dst); li("$t2", dst + len(d))
            a.label("f%d" % i)
            xor("$t3", "$t1", "$t4")
            a.sw("$t3", 0, "$t1")
            a.addiu("$t1", "$t1", 4)
            a.bne("$t1", "$t2", "f%d" % i)
            a.nop()
        li("$t5", SPIN)                                      # wait (~3 cycles a turn)
        a.label("spin")
        a.addiu("$t5", "$t5", -1)
        a.bne("$t5", "$zero", "spin")
        a.nop()
        for i, (dst, d) in enumerate(segs):                  # verify
            li("$t1", dst); li("$t2", dst + len(d))
            a.label("v%d" % i)
            a.lw("$t3", 0, "$t1")
            xor("$t6", "$t1", "$t4")
            a.bne("$t3", "$t6", "fail")
            a.addiu("$t1", "$t1", 4)
            a.bne("$t1", "$t2", "v%d" % i)
            a.nop()
    if gd is not None:                                       # probes (no copy): the rest of F000-FFFF and E500-E5FF
        for k, (p0, p1) in enumerate(GD_PROBES):
            a.lui("$t1", p0 >> 16); a.ori("$t1", "$t1", p0 & 0xffff)
            a.lui("$t2", p1 >> 16); a.ori("$t2", "$t2", p1 & 0xffff)
            gd_scan(GD_N - len(GD_PROBES) + k, p0, p1)
    for i, (dst, d) in enumerate(segs):                      # copy
        a.lui("$t0", 0); a.ori("$t0", "$t0", 0)              # la t0, data_i (patched below)
        a.lui("$t1", dst >> 16); a.ori("$t1", "$t1", dst & 0xffff)
        e = dst + len(d)
        a.lui("$t2", e >> 16); a.ori("$t2", "$t2", e & 0xffff)
        a.label("c%d" % i)
        a.lw("$t3", 0, "$t0")
        a.addiu("$t0", "$t0", 4)
        a.sw("$t3", 0, "$t1")
        a.addiu("$t1", "$t1", 4)
        a.bne("$t1", "$t2", "c%d" % i)
        a.nop()
    if gd is not None:                                       # the records into the runtime (ach.c ach_gd)
        la("$t0", "rec")
        a.lui("$t1", gd >> 16); a.ori("$t1", "$t1", gd & 0xffff)
        a.lui("$t2", (gd + 16 * GD_N) >> 16); a.ori("$t2", "$t2", (gd + 16 * GD_N) & 0xffff)
        a.label("cr")
        a.lw("$t3", 0, "$t0")
        a.addiu("$t0", "$t0", 4)
        a.sw("$t3", 0, "$t1")
        a.addiu("$t1", "$t1", 4)
        a.bne("$t1", "$t2", "cr")
        a.nop()
    if gd is None:
        zero_backup("zb")
    for adr, w in hooks:                                     # hooks into the loaded EXE (our words only)
        a.lui("$t1", adr >> 16); a.ori("$t1", "$t1", adr & 0xffff)
        a.lui("$t3", w >> 16); a.ori("$t3", "$t3", w & 0xffff)
        a.sw("$t3", 0, "$t1")
    a.label("fl")
    a.addiu("$t2", "$zero", 0xa0)                            # FlushCache
    a.jalr("$t2")
    a.addiu("$t1", "$zero", 0x44)
    a.label("skip")
    a.addu("$a0", "$s7", "$zero"); a.addu("$a1", "$s6", "$zero")
    a.addu("$s7", "$zero", "$zero"); a.addu("$s6", "$zero", "$zero")
    a.j(prev_pc0)
    a.nop()
    if gd is None:                                           # refused: contents back, backup cleared, stock game
        a.label("fail")
        for i, (dst, d) in enumerate(segs):
            la("$t0", "bk", bko[i]); li("$t1", dst); li("$t2", dst + len(d))
            a.label("r%d" % i)
            a.lw("$t3", 0, "$t0")
            a.addiu("$t0", "$t0", 4)
            a.sw("$t3", 0, "$t1")
            a.addiu("$t1", "$t1", 4)
            a.bne("$t1", "$t2", "r%d" % i)
            a.nop()
        zero_backup("zf")
        a.beq("$zero", "$zero", "fl")
        a.nop()
    if gd is not None:
        a.label("rec")
        a.blob(bytes(16 * GD_N))
    for i, (dst, d) in enumerate(segs):
        a.label("d%d" % i)
        a.blob(d)
    a.label("bk")                                            # the backup (zero in the EXE image, cleared again)
    if gd is None:
        a.blob(bytes(nbk))
    out = bytearray(a.assemble())
    L = a.labels()
    # the la's: the copy loop i starts after the guard; find each "lui t0,0 / ori t0,t0,0" pair in order
    pos = 0
    for i in range(len(segs)):
        pos = out.index(struct.pack("<2I", 0x3C080000, 0x35080000), pos)
        src = L["d%d" % i]
        struct.pack_into("<2I", out, pos, 0x3C080000 | (src >> 16), 0x35080000 | (src & 0xffff))
        pos += 8
    return bytes(out)
