"""Build the MvC tag-hack disc with the 8 MB loader ("ap8", 1.0 line).

    python games/mvc/tools/ap8/mkap8.py NAME [--chd] [mktag.py options]          (NAME = mvc_ap8* / mvc_8*)

Same disc as tools/tagload/mktag.py (it does the whole build, every 1.0 option), plus:
  * the loader blob gets a tiny stub (ap8stub.c + entry8.S, blob word 0 -> j ap8_ent): no 8 MB -> tl_wrap = the 2 MB
    loader, unchanged; 8 MB -> the 8 MB module.
  * the 8 MB module = tools/tagload/tagload.c compiled again with the same defines + AP8MOD (placement region
    [AP8_START, AP8_TOP) in upper RAM, stock RLE sprite files for everybody, no SPU store, no --share pairs) + snd.c +
    ap8m.c, linked at MOD (0x80200000).  Its directories are copied from the blob at every battle (same layout,
    checked here).  Appended after the image; the blob's .dir8 entry points at it.
Objects go to tools/ap8/obj/.  Holds the shared lock games/mvc/work/mktag.lock (as mk.sh / the old mkap8).
"""
import os, sys, struct, subprocess, time, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
TL = os.path.join(GAME, "tools", "tagload")
OBJ = os.path.join(HERE, "obj")
LOCK = os.path.join(GAME, "work", "mktag.lock")

MOD, PRIS, MODMAX = 0x80200000, 0x80210000, 0x10000
AP8_START = int(os.environ.get("AP8_START", "0x80220000"), 0)   # (env: test builds)
AP8_TOP = int(os.environ.get("AP8_TOP", "0x80340000"), 0)   # code + kind-6 sets + SPVC + assists; then the A0 cache
AP8_A0C = int(os.environ.get("AP8_A0C", "0x80220000"), 0)     # stock PLxx_10.A0 cache .. 0x80600000 (ap8m.c); the
                                                                # characters' code / sets / assists stay in the 2 MB region
BOOT8 = 0x8014d800              # boot stub (zero in the EXE image 0x800f229e-0x8014e500; diag discs use 0x8014e000)


def boot8_code(prev):
    """boot stub between the --ach copy stub and the game's entry (user 2026-11-24: on 8 MB the INTRO row defaults
    to STOCK = full intros; 2 MB keeps the image's power-on value).  8 MB write test as entry8.S; only t0-t5
    (a0 / a1 / sp / gp untouched)."""
    sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import optrows
    ib = optrows.BYTES["INTRO"]
    w = [0x3c088008, 0x8d0958ac, 0x3c0a8068, 0x01205827,          # lui t0,0x8008; lw t1,0x58ac(t0); lui t2,0x8068; nor t3,t1,0
         0xad4b58ac, 0x8d4c58ac, 0x8d0d58ac, 0xad0958ac,          # sw t3,hi; lw t4,hi; lw t5,lo; sw t1,lo
         0x158b0004, 0x00000000, 0x15a90002, 0x3c080000 | (ib + 0x8000 >> 16),   # bne t4,t3,+4; nop; bne t5,t1,+2; lui t0,%hi(INTRO)
         0xa1000000 | (ib & 0xffff),                              # sb zero,%lo(INTRO)(t0)
         0x3c080000 | (prev >> 16), 0x35080000 | (prev & 0xffff),  # lui t0; ori t0 (prev)
         0x01000008, 0]                                           # jr t0; nop
    return struct.pack("<%dI" % len(w), *w)


R8MENU, R8BYTE = 0x807dfe00, 0x807dff40   # --frames8: 8 MB menu routine + ARCADE FRAMES byte (0 = ON) in upper RAM


def _hl(a): return ((a + 0x8000) >> 16) & 0xFFFF, a & 0xFFFF


def fr8_menu(args):
    """--frames8 menu pieces (user 2026-11-24): on 8 MB the main-menu version line reads "<title> 8MB" and the EX OPTIONS
    INTRO row becomes ARCADE FRAMES ON / OFF (same slot; intros are always full on 8 MB).  The EX table lives in OPDEMO's
    slack (reloaded with the menu), so the resident version-line stub (mvcver, --titlefix) is routed through a routine in
    upper RAM (copied by the boot stub, 8 MB only) that re-points the INTRO row entry every main-menu frame and draws the
    text.  -> (routine bytes, row entry address, resident stub word address)"""
    sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); sys.path.insert(0, os.path.join(ROOT, "tools"))
    import mvcver, exopt, optrows
    from mipsasm import Asm
    title = mvcver.text_of(args)
    assert title and "--titlefix" in args and "--exopt" in args and "--introopt" in args, "--frames8 menu: needs --title --titlefix --exopt --introopt"
    rows = [l for l, v in exopt.rows(args)]
    code, syms = exopt.build(args + ["--ver=" + title])  # (as mktag: --title adds --ver=TITLE before EX OPTIONS is built)
    rowent = syms["ROWS"] + 24 * rows.index("INTRO")
    h_, l_ = _hl(syms["VER"])                          # the EX screen's version line: lui a0 / addiu a0 VER, lui a1 VERX
    vi = code.find(struct.pack("<2I", 0x3C040000 | h_, 0x24840000 | l_))
    assert vi >= 0 and vi % 4 == 0 and struct.unpack_from("<I", code, vi + 8)[0] >> 16 == 0x3C05, "EX OPTIONS version line code"
    verpos = optrows.SLACK + vi
    (org, rcode), _ = mvcver.resident_patches(title)
    text = title + " 8MB"
    x = mvcver.X_RIGHT - mvcver.CHAR_W * len(text)
    a = Asm(R8MENU)
    def la(r, lab_addr):
        h, l = _hl(lab_addr); a.lui(r, h); a.addiu(r, r, l - 0x10000 if l >= 0x8000 else l)
    a.label("r8menu")
    la("$t0", rowent)
    la("$t1", R8BYTE); a.sw("$t1", 0, "$t0")
    a.addiu("$t1", "$zero", 2); a.sw("$t1", 4, "$t0")
    strs = [("lab", b"ARCADE FRAMES"), ("on", b"ON"), ("off", b"OFF"), ("txt", text.encode())]
    n_code = 2 + 3 + 2 + 3 * 3 + 1 + 2 + 3 * 3 + 2 + 2 + 3 + 4   # instructions before the strings (checked below)
    base = R8MENU + 4 * n_code; sa = {}
    for k, b_ in strs: sa[k] = base; base += (len(b_) + 4) // 4 * 4
    la("$t1", sa["lab"]); a.sw("$t1", 8, "$t0")
    la("$t1", sa["on"]); a.sw("$t1", 12, "$t0")
    la("$t1", sa["off"]); a.sw("$t1", 16, "$t0")
    a.sw("$zero", 20, "$t0")
    la("$t0", verpos)                                  # EX OPTIONS footer: the same "... 8MB" text, centred
    h2, l2 = _hl(sa["txt"])
    for k_, w_ in enumerate((0x3C040000 | h2, 0x24840000 | l2, 0x3C050000 | (0x100 - 4 * len(text)))):
        a.lui("$t1", w_ >> 16); a.ori("$t1", "$t1", w_ & 0xFFFF); a.sw("$t1", 4 * k_, "$t0")
    la("$a0", sa["txt"])
    a.lui("$a1", x); a.ori("$a1", "$a1", mvcver.Y)
    a.lui("$a2", 0x0800 | mvcver.COLOUR); a.jal(mvcver.FONT); a.ori("$a2", "$a2", 1)
    a.lw("$ra", 0x10, "$sp"); a.nop(); a.jr("$ra"); a.addiu("$sp", "$sp", 0x18)
    assert a.size() == 4 * n_code, (a.size(), n_code)
    for k, b_ in strs: a.label(k); a.blob(b_ + b"\0" * (4 - len(b_) % 4))
    rt = a.assemble()
    assert a.labels()["lab"] == sa["lab"] and a.labels()["txt"] == sa["txt"] and len(rt) <= R8BYTE - R8MENU
    hook = org + 8                                     # mvcver.build: word 2 = lui a0, %hi(text)
    assert struct.unpack_from("<I", rcode, 8)[0] >> 16 == 0x3C04, "resident stub layout"
    fr8_menu.verpos = verpos
    return rt, rowent, hook, optrows.BYTES["INTRO"]


def boot8_fr(prev, args):
    """boot stub with the --frames8 menu (8 MB only after the write test): INTRO byte STOCK, the routine copied to
    R8MENU, ARCADE FRAMES byte = 0 (ON), resident stub word 2 -> j r8menu (its delay slot = the stub's addiu a0: harmless)"""
    sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, os.path.join(GAME, "tools", "gameplay"))
    from mipsasm import Asm
    import optrows
    rt, rowent, hook, ib = fr8_menu(args)
    a = Asm(BOOT8)
    for w in (0x3c088008, 0x8d0958ac, 0x3c0a8068, 0x01205827, 0xad4b58ac):
        a.word(w)                                      # 8 MB write test (as boot8_code / entry8.S): lo, ~lo -> hi
    a.lui("$t4", 0xbfc0); a.lw("$t4", 0, "$t4"); a.nop()   # BIOS-ROM read: drains the CPU write buffer (real hardware
                                                           # answers a load right after a store from RAM, not the buffer)
    for w in (0x8d4c58ac, 0x8d0d58ac, 0xad0958ac):
        a.word(w)                                      # lw t4, hi; lw t5, lo; sw t1, lo (lo back)
    a.bne("$t4", "$t3", "done"); a.nop()
    a.bne("$t5", "$t1", "done"); a.nop()
    h, l = _hl(ib); a.lui("$t0", h); a.sb("$zero", l - 0x10000 if l >= 0x8000 else l, "$t0")
    def la(r, v):
        h, l = _hl(v); a.lui(r, h); a.addiu(r, r, l - 0x10000 if l >= 0x8000 else l)
    la("$t0", 0); la("$t1", R8MENU); la("$t2", 0)     # src / end patched below (data label)
    a.label("cp")
    a.lw("$t3", 0, "$t0"); a.addiu("$t0", "$t0", 4); a.sw("$t3", 0, "$t1"); a.bne("$t0", "$t2", "cp"); a.addiu("$t1", "$t1", 4)
    la("$t0", R8BYTE); a.sb("$zero", 0, "$t0")
    # read-back check (SwanStation's 2 MB mode answers the write test from open bus): the routine's first and last word
    # must read back from upper RAM, else no hook (the version line / EX table stay stock)
    a.lui("$t4", 0xbfc0); a.lw("$t4", 0, "$t4"); a.nop()   # drain the write buffer before reading the copy back
    la("$t0", R8MENU); la("$t1", 0); a.lw("$t2", 0, "$t0"); a.lw("$t3", 0, "$t1"); a.nop(); a.bne("$t2", "$t3", "done"); a.nop()
    la("$t0", R8MENU + len(rt) - 4); la("$t1", 0); a.lw("$t2", 0, "$t0"); a.lw("$t3", 0, "$t1"); a.nop(); a.bne("$t2", "$t3", "done"); a.nop()
    jw = 0x08000000 | (R8MENU >> 2 & 0x3FFFFFF)
    la("$t0", hook); h, l = _hl(jw); a.lui("$t1", (jw >> 16) & 0xFFFF); a.ori("$t1", "$t1", jw & 0xFFFF); a.sw("$t1", 0, "$t0")
    a.label("done")
    a.lui("$t0", prev >> 16); a.ori("$t0", "$t0", prev & 0xFFFF); a.jr("$t0"); a.nop()
    a.label("data"); a.blob(rt)
    code = bytearray(a.assemble()); L = a.labels()
    src, end = L["data"], L["data"] + len(rt)
    def put(o, r, v):                                  # la r, v at byte offset o (lui + addiu)
        h, l = _hl(v); struct.pack_into("<2I", code, o, 0x3C000000 | r << 16 | h, 0x24000000 | r << 21 | r << 16 | l)
    i0 = (L["cp"] - BOOT8) // 4 - 6                    # the three la's before cp: t0 src, t1 dst, t2 end
    put(i0 * 4, 8, src); put((i0 + 4) * 4, 10, end)
    rb = [i for i in range(0, len(code) - 8, 4) if struct.unpack_from("<2I", code, i) == (0x3C090000, 0x25290000)]
    assert len(rb) == 2, rb                            # the read-back checks' source words (la t1, 0)
    put(rb[0], 9, src); put(rb[1], 9, end - 4)
    assert len(code) <= 0x800 and BOOT8 + len(code) <= 0x8014e000
    print("ap8: frames8 menu: routine %d B at %#x, EX row entry %#x (INTRO -> ARCADE FRAMES, byte %#x), version hook %#x, EX footer %#x, boot stub %d B" % (
        len(rt), R8MENU, rowent, R8BYTE, hook, fr8_menu.verpos, len(code)))
    fr8_menu.rowent = rowent; fr8_menu.ib = ib
    return bytes(code)


@contextlib.contextmanager
def lock(timeout=7200):
    t0 = time.time()
    while True:
        try:
            os.mkdir(LOCK); break
        except (FileExistsError, PermissionError):
            if time.time() - t0 > timeout: raise SystemExit("mktag.lock held for two hours: " + LOCK)
            time.sleep(5)
    try:
        yield
    finally:
        os.rmdir(LOCK)


def r2k(x): return (x + 2047) & ~2047


def nm(GCC, elf, cwd):
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", elf], cwd=cwd).decode().splitlines():
        q = l.split()
        if len(q) == 3: sym[q[2]] = int(q[0], 16) & 0xFFFFFFFF
    return sym


def jword(a): return struct.pack("<I", 0x08000000 | ((a >> 2) & 0x3FFFFFF))


def uncut_header():
    """per character the code-item words the 2 MB build changed for frame substitution (--redcut / --wmhover), with
    their stock values: the 8 MB module puts them back (ap8m.c ap8_uncut).  Built by comparing mktag's code item with
    the same item built without those two options; any other difference is an error."""
    import mktag
    cut = [a for a in ("--redcut", "--wmhover") if a in sys.argv]
    rows, tot = [], 0
    for c in mktag.CHARS:
        it = mktag.a0_item(c)[0][0]
        argv0 = list(sys.argv)
        sys.argv[:] = [a for a in sys.argv if a not in cut]
        try:
            st = mktag.a0_item(c)[0][0]
        finally:
            sys.argv[:] = argv0
        assert len(it) == len(st), c
        diff = [k for k in range(0, len(it), 2) if it[k:k + 2] != st[k:k + 2]]
        if not diff: continue
        rows.append([c, len(diff)] + sum(([k, struct.unpack_from("<H", st, k)[0]] for k in diff), []))
        tot += len(diff)
    assert all(k < 0x100000 for r in rows for k in r)
    print("ap8: uncut %d frame-table words in %d characters" % (tot, len(rows)))
    w = sum(rows, []) + [0]
    NL = chr(10)
    return "static const u32 uncut_tab[] = {" + NL + ("," + NL).join(", ".join("%d" % x for x in w[i:i + 16]) for i in range(0, len(w), 16)) + NL + "};" + NL


def build_blob8(orig):
    import mktag
    GCC, CF = mktag.GCC, mktag.CF
    os.makedirs(OBJ, exist_ok=True)
    seen = []
    cc0 = mktag.subprocess.check_call
    def spy(cmd, *a, **k):
        if any(str(x).endswith("tagload.c") for x in cmd): seen.append(list(cmd))
        return cc0(cmd, *a, **k)
    mktag.subprocess.check_call = spy
    try:
        glue, res, blob, rsym = orig()                  # the 2 MB build (tagload.o, snd.o, glue.o in tools/tagload)
    finally:
        mktag.subprocess.check_call = cc0
    assert len(seen) == 1, seen
    cc = lambda args, cwd=OBJ: subprocess.check_call([GCC + "gcc"] + CF + args, cwd=cwd)
    cc(["-c", os.path.join(HERE, "entry8.S"), "-o", "entry8.o"] + (["-DDRAIN8"] if FR8 else []))   # FR8: write-buffer drain
    o = lambda n: os.path.join(OBJ, n)
    t = lambda n: os.path.join(TL, n)
    subprocess.check_call([GCC + "ld", "-T", os.path.join(HERE, "link8.ld"), "glue.o", "tagload.o", "snd.o",
                           o("entry8.o"), "-o", o("ap8.elf")], cwd=TL)   # link8.ld names glue.o
    out = {}
    for sec in (".g1", ".g2", ".res", ".rh", ".hg", ".blob", ".post"):
        p = o("ap8" + sec + ".bin")
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "ap8.elf", p], cwd=OBJ)
        out[sec] = open(p, "rb").read()
    sym = nm(GCC, "ap8.elf", OBJ)
    rd = lambda s: open(t("tagload" + s + ".bin"), "rb").read()
    for sec in (".g1", ".g2", ".res", ".rh", ".hg", ".post"):
        assert out[sec] == rd(sec), "resident %s differs from the 2 MB build" % sec
    for k in ("glue", "flushcache", "blobent", "heapcap", "tl_entry", "tl_dbg", "dshptr", "dsaptr", "hcguard", "rhook",
              "tl_pend", "post", "post_list", "tl_wrap"):
        assert sym[k] == rsym[k], k
    b = bytearray(out[".blob"])
    assert sym["tl_wrap"] == 0x80092c50, hex(sym["tl_wrap"])
    assert b[:4] == jword(sym["tl_wrap"]) and b[8:12] == jword(sym["tl_restore"])
    b[:4] = jword(sym["ap8_ent"])
    grow = len(b) - len(blob)
    print("ap8: blob %d B (2 MB blob %d, stub +%d)" % (len(b), len(blob), grow))
    assert sym["blob_end"] - sym["snd_dir"] == rsym["blob_end"] - rsym["snd_dir"]
    # ---- the module ----
    cmd = seen[0]
    i = cmd.index("-o"); cmd = cmd[:i] + ["-o", o("tagload8.o")] + cmd[i + 2:]
    cmd += ["-DAP8MOD"] + (["-DAP8FR"] if FR8 and not MENUONLY else []) + (["-DAP8UP", "-DAP8_START=0x%08xu" % AP8_START, "-DAP8_TOP=0x%08xu" % AP8_TOP] if os.environ.get("AP8UP") else [])
    L = mktag.lba_map()
    a0sz = r2k(max(L["PL%02X_10.A0" % c][1] for c in mktag.CHARS))
    assert (0x80600000 - AP8_A0C) // a0sz >= 6, "A0 cache: fewer than 6 slots"
    subprocess.check_call(cmd, cwd=TL)
    S8 = os.path.join(HERE, "s8")                         # obj/snd.o: the blob's defines + SND8 (voice streaming, s8/snd8.inc)
    mktag.sndbuild.objects(GCC, CF + ["-DSND8", "-I", S8], OBJ)
    cc(["-Os", "-ffreestanding", "-msoft-float", "-Wall", "-c", os.path.join(S8, "s8.c"), "-o", "s8.o"])
    open(o("uncut.h"), "w").write(uncut_header())
    cc(["-Os", "-ffreestanding", "-msoft-float", "-Wall", "-I", OBJ, "-DAP8_BSDIR=0x%08xu" % sym["snd_dir"]] + (["-DAP8FR"] if FR8 and not MENUONLY else []) +
        ["-DAP8FR_" + x.upper() for x in os.environ.get("FR8_DBG", "").split(",") if x] + [
        "-DAP8_A0C=0x%08xu" % AP8_A0C, "-DAP8_A0SZ=0x%xu" % a0sz,
        "-c", os.path.join(HERE, "ap8m.c"), "-o", "ap8m.o"])
    objs = ["ap8m.o", "tagload8.o", "snd.o", "s8.o"]
    undef, defd = set(), set()
    for ob in objs:
        for l in subprocess.check_output([GCC + "nm", ob], cwd=OBJ).decode().splitlines():
            q = l.split()
            if len(q) == 2 and q[0] == "U": undef.add(q[1])
            elif len(q) == 3 and q[1] in "TDBRCGSV": defd.add(q[2])
    need = sorted((undef - defd) - {"m_sdir", "m_end"})
    miss = [x for x in need if x not in sym]
    assert not miss, ("module symbols not in the blob", miss)
    open(o("mod.ld"), "w").write(
        "SECTIONS {\n  .mod 0x%08x : { ap8m.o(.text.start) *(.text) *(.text.*) *(.rodata*) *(.data*) *(.sdata*) *(.sbss*) "
        "*(.bss*) *(COMMON) . = ALIGN(4); *(.dir8m) . = ALIGN(4); m_sdir = .; *(.sdir) . = ALIGN(4); *(.dir) . = ALIGN(4); m_end = .; }\n"
        "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }\n}\n" % MOD)
    defs = sum((["--defsym", "%s=0x%08x" % (x, sym[x])] for x in need), [])
    subprocess.check_call([GCC + "ld", "-T", "mod.ld"] + defs + objs + ["-o", "mod.elf"], cwd=OBJ)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".mod", "mod.elf", "mod.bin"], cwd=OBJ)
    msym = nm(GCC, "mod.elf", OBJ)
    mod = open(o("mod.bin"), "rb").read()
    assert msym["m_end"] - msym["m_sdir"] == sym["blob_end"] - sym["snd_dir"], "module directory layout differs"
    assert len(mod) == msym["m_end"] - MOD and len(mod) % 4 == 0
    assert r2k(len(mod)) <= MODMAX, "module %d B > %d" % (len(mod), MODMAX)
    build_blob8.mod = mod
    build_blob8.msym = msym
    print("ap8: module %d B at %#x (tl_main %#x), A0 cache %#x-0x80600000 (%d x %#x), %d blob symbols" %
          (len(mod), MOD, msym["tl_main"], AP8_A0C, min(8, (0x80600000 - AP8_A0C) // a0sz), a0sz, len(need)))
    glue = [(a, out[s]) for (a, _), s in zip(glue, (".g1", ".g2", ".hg", ".rh"))]
    return glue, out[".res"], bytes(b), sym


MENUONLY = "menuonly" in os.environ.get("FR8_DBG", "").split(",")   # (bisect) boot stub + 8 MB menu only, no frames module
SPEED8 = False                                          # --frames8-speed (main sets it)
ASCUT8 = False                                          # --frames8-ascut (main sets it)
FR8 = None                                              # --frames8: {char: PLxx.R8 bytes} (main sets them)
R8LO, R8HI = 0x80220000, 0x80600000                     # ap8r.c arena range 0 (range 1 0x80740000-0x807d0000)


def r8_files(arcade):
    """arcade frames (--frames8): tools/ap/build8.py run on the user's arcade set + the stock disc at build time;
    cached in work/ap8fr/cache_<key> (key = builder sources + the inputs' sizes / times).  -> {char: PLxx.R8 bytes}"""
    import hashlib, json
    sys.path.insert(0, os.path.join(GAME, "tools", "ap"))
    import build8
    disc = os.path.join(GAME, "disc", "mvc.bin")
    h = hashlib.sha1()
    keeps = [os.path.join(os.path.dirname(build8.__file__), "keep8.json")]
    if SPEED8: keeps.append(os.path.join(os.path.dirname(build8.__file__), "keep8_speed.json"))
    for f in [build8.__file__, build8.aplib.__file__, build8.dsp.__file__] + keeps:
        h.update(open(f, "rb").read())
    for f in arcade + [disc]:
        st = os.stat(f); h.update(("%s %d %d" % (os.path.basename(f), st.st_size, int(st.st_mtime))).encode())
    h.update(os.environ.get("FR8_STOCKCH", "").encode())   # (bisect) mains built without restored animations
    out = os.path.join(GAME, "work", "ap8fr", "cache_" + h.hexdigest()[:16])
    man = os.path.join(out, "manifest.json")
    if not os.path.exists(man):
        env = dict(os.environ, FR8_KEEP=keeps[1]) if SPEED8 else {k: v for k, v in os.environ.items() if k != "FR8_KEEP"}
        subprocess.check_call([sys.executable, build8.__file__, "--arcade"] + arcade + ["--disc", disc, "--out", out + ".tmp"], env=env)
        if os.path.exists(out): import shutil; shutil.rmtree(out)
        os.rename(out + ".tmp", out)
    m = json.load(open(man))
    fs = {}
    for c in range(1, 0x17):
        e = m["chars"].get("%02X" % c, {})
        assert "error" not in e and e, ("arcade frames: character %02X not built" % c, e)
        fs[c] = open(os.path.join(out, "PL%02X.R8" % c), "rb").read()
        assert hashlib.sha1(fs[c]).hexdigest() == e["sha1"]["r8"]
    for x in range(0x16):                            # special partners (DAxx.R8, key 0x100 + id)
        e = m.get("assists", {}).get("%02X" % x)
        assert e, "arcade frames: assist %02X not built" % x
        fs[0x100 + x] = open(os.path.join(out, "DA%02X.R8" % x), "rb").read()
        assert hashlib.sha1(fs[0x100 + x]).hexdigest() == e["sha1"]
        if ASCUT8:                                   # --frames8-ascut: keep the 2 MB --ascut assist frame cuts on 8 MB
            sys.path.insert(0, os.path.join(GAME, "tools", "assist")); import ascut          # (speed = 1.0 8 MB)
            r = bytearray(fs[0x100 + x]); w = struct.unpack_from("<16I", r, 0)
            for f, o, old, new in json.load(open(os.path.join(ascut.OUT, "ascut.json")))["DA%02X" % x]:
                t = w[4] + 4 * f
                assert f < w[6] and struct.unpack_from("<H", r, t)[0] == old, ("ascut", x, f)
                struct.pack_into("<H", r, t, new)
            struct.pack_into("<I", r, 48, 1)        # word 12 = 1: assist table carries the --ascut words (audit8.py)
            fs[0x100 + x] = bytes(r)
    big = sorted(r2k(len(f)) for c, f in fs.items() if c < 0x100)[-4:] + sorted(r2k(len(f)) for c, f in fs.items() if c >= 0x100)[-2:]
    assert sum(big) <= R8HI - R8LO, "arcade frames: the four largest characters + two largest assists do not fit arena range 0"
    print("ap8: frames8 %s: %d R8 files, %d B, four largest %d B of %d (restored records %d)" % (
        os.path.basename(out), len(fs), sum(len(f) for f in fs.values()), sum(big), R8HI - R8LO,
        sum(struct.unpack_from("<I", f, 44)[0] for f in fs.values())))
    print("ap8: frames8 assists restored records %s" % {"%02X" % (c - 0x100): struct.unpack_from("<I", f, 44)[0] for c, f in fs.items() if c >= 0x100 and struct.unpack_from("<I", f, 44)[0]})
    return fs


def sn8_files(arcade):
    """{bank index: .SN8 bytes} in sndbank.bank_names() order (tools/snd/sn8build.py); arcade = [zip paths] or None"""
    import sn8build
    fs = sn8build.all_files(arcade)
    return [fs[n] for n in sn8build.S.bank_names()]


def add_module(name, blob, sym, sn8=None):
    """module (+ the .SN8 files) after the end of the built image; tl8_dir in the blob on the disc (its word 2 keeps the
    sum at 0); the module's s8d directory points at the .SN8 files"""
    import mktag
    mod = bytearray(build_blob8.mod)
    out = os.path.join(mktag.BUILD, name + ".bin")
    end = os.path.getsize(out) // 2352
    img = mktag.Img(out)
    n = r2k(len(mod)) // 2048
    tail = []
    if sn8:
        o = build_blob8.msym["s8d"] - MOD
        assert struct.unpack_from("<2I", mod, o) == (0x44384e53, 0)
        lba = end + n
        ents = []
        for k, f in enumerate(sn8):
            assert len(f) <= (0x60000 if k == 0 else 0x38000), ("SN8 file too big for its upper RAM area", k, len(f))
            samp = struct.unpack_from("<I", f, 16)[0]
            ents.append(struct.unpack("<I", mktag.msf(lba))[0]); ents += [len(f), samp]
            tail.append((lba, f)); lba += r2k(len(f)) // 2048
        struct.pack_into("<2I%dI" % len(ents), mod, o, 0x44384e53, 1, *ents)
        print("ap8: %d .SN8 files, %d sectors (COMMON %d B, largest bank %d B)" % (len(sn8), lba - end - n, len(sn8[0]), max(len(f) for f in sn8[1:])))
        total = lba - end
    else:
        total = n
    if FR8 and not MENUONLY:
        o = build_blob8.msym["r8d"] - MOD
        assert struct.unpack_from("<2I", mod, o) == (0x52443852, 0)
        lba = end + total
        ents = [0, 0]
        for c in list(range(1, 0x17)) + [0x100 + x for x in range(0x16)]:    # r8dir: f[0x17] (f[0] unused), a[0x16]
            f = FR8[c]
            ents += [struct.unpack("<I", mktag.msf(lba))[0], len(f)]
            tail.append((lba, f)); lba += r2k(len(f)) // 2048
        struct.pack_into("<2I%dI" % len(ents), mod, o, 0x52443852, 1, *ents)
        print("ap8: %d .R8 files, %d sectors" % (len(FR8), lba - end - total))
        total = lba - end
    mod = bytes(mod)
    img.extend(end, total + 150)
    img.wsectors(end, mod + bytes(n * 2048 - len(mod)))
    for lba, f in tail: img.wsectors(lba, f)
    d8 = sym["tl8_dir"] - mktag.ARENA
    b = bytearray(blob)
    assert b[d8:d8 + 12] == bytes(12) and len(b) % 4 == 0
    assert sum(struct.unpack("<%dI" % (len(b) // 4), b)) & 0xFFFFFFFF == 0, "blob sum"
    struct.pack_into("<3I", b, d8, struct.unpack("<I", mktag.msf(end))[0], len(mod), 0)
    struct.pack_into("<I", b, d8 + 8, -sum(struct.unpack("<%dI" % (len(b) // 4), b)) & 0xFFFFFFFF)
    img.wsectors(mktag.lba_map()["DMY1.DAT"][0], bytes(b) + bytes(-len(b) % 2048))
    img.fix()
    print("ap8: module %d B at LBA %d" % (len(mod), end))


def main(argv):
    name = next((a for a in argv[1:] if not a.startswith("--")), None)
    assert name and name.startswith(("mvc_ap8", "mvc_8")), "build names: mvc_ap8* / mvc_8*"
    assert not any(a.startswith("--force") or a == "--stockmeter" for a in argv), "test-team builds: use mktag.py"
    chd = "--chd" in argv
    arcade = []
    if "--arcade" in argv:                              # the user's mvsc.zip (sound ROMs): arcade voices in the .SN8 files
        arcade = [argv[argv.index("--arcade") + 1]]
        argv = [a for i, a in enumerate(argv) if a != "--arcade" and argv[i - 1] != "--arcade"]
    global FR8
    global ASCUT8
    global SPEED8
    ASCUT8 = "--frames8-ascut" in argv
    SPEED8 = "--frames8-speed" in argv
    fr8 = "--frames8" in argv or ASCUT8 or SPEED8                          # arcade animation frames (tools/ap/build8.py from the arcade set)
    nosn8 = "--nosn8" in argv                           # A/B: 8 MB without voice streaming (the 2 MB sound plan)
    args = [a for a in argv[1:] if a not in ("--chd", "--nosn8", "--frames8", "--frames8-ascut", "--frames8-speed")]
    if fr8:
        assert arcade, "--frames8 needs --arcade (the user's mvsc.zip)"
        FR8 = r8_files(arcade)
    sys.argv = [argv[0]] + args                         # mktag.py reads its options at import
    sys.path.insert(0, TL)
    import mktag
    if "--ach" in args and "--logo" in args and "--introopt" in args:   # 8 MB: INTRO default STOCK (boot stub)
        sys.path.insert(0, os.path.join(GAME, "tools", "ach", "core")); import mvcore   # --ach: rc4 core (mktag's import)
        cs0, parts0 = mvcore.achbuild.copy_stub_spans, mvcore.parts
        prev = []
        def cs(at, segs, hooks, prev_pc0, gd=None):
            prev.append(prev_pc0)
            return cs0(at, segs, hooks, BOOT8, gd)
        def parts(*a, **k):
            r = parts0(*a, **k)
            bc = boot8_fr(prev[0], args) if FR8 else boot8_code(prev[0])
            assert len(prev) == 1 and a[0](BOOT8, len(bc)) == bytes(len(bc)), "boot stub area not zero"
            r["exe"].append((BOOT8, bc))
            print("ap8: boot stub %#x (INTRO STOCK on 8 MB) -> %#x" % (BOOT8, prev[0]))
            return r
        mvcore.achbuild.copy_stub_spans, mvcore.parts = cs, parts
    with lock():
        orig = mktag.build_blob
        mktag.build_blob = lambda: build_blob8(orig)
        patches, blob, sym = mktag.main([argv[0]] + args)
        sn8 = None if nosn8 else sn8_files(arcade or None)
        add_module(name, blob, sym, sn8)
    if chd:
        out = os.path.join(mktag.BUILD, name)
        subprocess.check_call([mktag.toolenv.chdman(), "createcd", "-i", out + ".cue", "-o", out + ".chd", "-f"],
                              stdout=subprocess.DEVNULL)
        print("chd:", out + ".chd")


if __name__ == "__main__":
    main(sys.argv)
