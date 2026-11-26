"""XvSF tag hack 1.4: EX OPTIONS + in-battle options (tools/exopt/xvex.c).  mktagdisc.py ... --ex (needs --noahead).

What it adds (docs: work/x14/NOTES.md):
  * main menu: EX OPTIONS (last line; 6 lines, 7 with the achievements runtime): ARCADE BALANCE (moved here from OPTION
    MODE, still saved on the card with the game's options), FRAME SKIP OFF / AUTO / MAX, STAGE ANIM FULL / OFF,
    SPEED METER OFF / ON, ACHIEVEMENT POPUP ON / OFF (with the runtime only), EXIT
  * battle pause menu (START, then SELECT): + FRAME SKIP and SPEED METER rows
  * FRAME SKIP: the engine's own present skip (0x800421c2, on in every scene but battle) allowed in battle
  * SPEED METER: game loops per second (and pictures per second while FRAME SKIP is on), top left
Code: EXE dead span 0x80056b94-0x800577c8 (quad worker FREED; free while UP_FC=0 and UP_VC=0), i.e. in the disc's EXE:
no kernel RAM, no boot copy, on every console.  Hooks (stock words checked):
  EBV+12 (present's idle callback, the decode-ahead stub before --noahead)  -> ex_idle
  0x80028638 jal 0x800987c0 (main-menu routine)                             -> jal ex_menuin (OPDEMO 0x8009bf54: in RAM)
  one-shot table entry 2 (0x800280f0, pause-menu draw 0x80029278 | 1)       -> ex_pdraw | 1
  0x80029544 / 48 (pause-menu input: cursor wrap slti 3 / ori 2)            -> 5 / 4
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SRC = os.path.join(HERE, "exopt", "xvex.c")
OBJ = os.path.join(HERE, "exopt", "obj")
BASE, LIMIT = 0x80056b94, 0x800577c8
RBASE, RLIMIT = 0x80057d7c, 0x80057f48           # read-only data (quad worker FREED tail of sec0_parse)
ZBASE, ZLIMIT = 0x80057fbc, 0x80058000           # variables (quad worker FREED tail of sec1_parse), zero in the image
MENU_SITE, MENU_JAL = 0x80028638, 0x0C000000 | (0x800987c0 >> 2 & 0x3FFFFFF)
ONESHOT2, ONESHOT2_OLD = 0x800280f0, 0x80029278 | 1
SK = 0x5ec7a11d                                  # stock words stored masked (no game words in the sources)
PWRAP_AT, PWRAP_OLD, PWRAP_NEW = 0x80029544, (0x7685a11e ^ SK, 0x6ac5a11f ^ SK), (0x7685a118 ^ SK, 0x6ac5a119 ^ SK)   # pause cursor 0..2 -> 0..4
LAYOUT = dict(EX_MENU_Y=0x88, EX_MENU_STEP=0x0e,              # 7-line main menu (6 lines keep the stock 0x90 / 16)
              EX_TX=0xd4, EX_TY=0x40, EX_LX=0x84, EX_RY=0x58, EX_RSTEP=0x10, EX_VX0=0x134,   # EX OPTIONS page (2026-11-25 align: block 240 wide centred on the title, values after the longest label + 16)
              EX_MX=0x5c, EX_MY=0x41,                         # speed meter (picture x 16, y 56)
              EX_PY=0x48, EX_PSTEP=0x1c, EX_PCX=0x108,
              EX_FSCAP=3)                                     # FRAME SKIP MAX: at most 3 skipped pictures in a row        # pause menu: 5 rows, long rows centred on routine x 0x108
jal = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)
j_ = lambda t: 0x08000000 | (t >> 2 & 0x03FFFFFF)


NOFS = False    # 1.4 final --nofskip: no FRAME SKIP row (page + pause menu), option forced OFF (xvex.c EX_NOFS)
PWRAP_NOFS = (0x7685a119 ^ SK, 0x6ac5a11e ^ SK)  # pause cursor 0..3 (4 rows)
NOSM = False    # 1.4 final --nosmeter (needs NOFS): no SPEED METER row; pause menu stock (no hooks) (xvex.c EX_NOSM)
CARD = bool(os.environ.get("XV_EXCARD"))    # --excard (mktagdisc sets it from its argv; test harnesses: env XV_EXCARD=1): the EX OPTIONS rows in the game's own option save (card image +9 bits, xvex.c EX_CARD)
TLTITLE = None  # with CARD on an 8 MB disc: address of tl_dbg.title (ARCADE FRAMES 2 ON / 3 OFF; tools/mkap8disc.py sets it)
TRSYNC = bool(os.environ.get("XV_TRSYNC"))  # --trsync (1.4, stock bug): the attract -> title transition 0x8002a4f0 waits for the GPU (libgpu sync core) before it
                # resets / clears the draw buffers (START on the demo's SCORE / VS RANKING could leave half-cleared lists in flight)
TRS_SITE, TRS_OLD = 0x8002a4f8, 0x0C000000 | (0x8002ea50 >> 2 & 0x3FFFFFF)   # jal 0x8002ea50 (buffer-pointer reset), first call of 0x8002a4f0
RDFIX = bool(os.environ.get("XV_RDFIX"))  # --rdfix (GitHub #15, stock bug): a Raging Demon that ends the match leaves its SPU voice
# in NOISE mode (never ends, no key-off) -> the bank loader 0x8004cb18 waits forever for silence (SpuGetKeyStatus loop at
# 0x8004cb68) = NOW LOADING + noise.  The loader's call -> stub: key off the noise voices, NON = 0, then SpuGetKeyStatus.
RDF_SITE, RDF_FIX = 0x8004cb68, 0x800577a8       # stub = last 32 B of the EX module area (free in 2 MB and 8 MB: same address)
RDF_STUB = [0x3c081f80, 0x95091d94, 0x950a1d96, 0xa5091d8c, 0xa50a1d8e, 0xa5001d94,
            0x08000000 | (0x8001b710 >> 2 & 0x3FFFFFF), 0xa5001d96]
# lui t0,0x1f80; lhu t1/t2 = NON; sh t1/t2 -> KOFF; sh zero -> NON lo; j SpuGetKeyStatus 0x8001b710; (delay) sh zero -> NON hi
TRS_FIX = 0x80057f28                           # addiu sp,-8; sw ra; jal DrawSync core 0x80018c38 (a0=0); lw ra; j 0x8002ea50; addiu sp,8
TRS_STUB = [0x27bdfff8, 0xafbf0000, 0x0C000000 | (0x80018c38 >> 2 & 0x3FFFFFF), 0x00002021, 0x8fbf0000,
            0x08000000 | (0x8002ea50 >> 2 & 0x3FFFFFF), 0x27bd0008]
VSMENU = None   # --vsmenu: address of the VERSUS CPU row wrapper's trampoline (tools/mtap/xvmtap.py MENU_J)


def build(arcbal, flush, extra=None):
    if VSMENU: extra = list(extra or []) + ["-DEX_VSMENU=0x%08xu" % VSMENU]
    if NOFS: extra = list(extra or []) + ["-DEX_NOFS"]
    assert not NOSM or NOFS, "NOSM needs NOFS"
    if NOSM: extra = list(extra or []) + ["-DEX_NOSM"]
    if CARD: extra = list(extra or []) + ["-DEX_CARD"] + (["-DEX_TLTITLE=0x%08xu" % TLTITLE] if TLTITLE else [])
    import toolenv
    gcc = toolenv.mips_prefix()
    os.makedirs(OBJ, exist_ok=True)
    ld = os.path.join(OBJ, "xvex.ld")
    open(ld, "w").write(("MEMORY { A (rwx) : ORIGIN = 0x%08x, LENGTH = 0x%x  B (rwx) : ORIGIN = 0x%08x, LENGTH = 0x%x  Z (rwx) : ORIGIN = 0x%08x, LENGTH = 0x%x }\n" +
                        ("SECTIONS { .text : { *(.text*) . = ALIGN(4); } > A  .data : { *(.data*) *(.sdata*) . = ALIGN(4); ex_end = .; } > A " if CARD else   # (--excard: the strings go to B)
                         "SECTIONS { .text : { *(.text*) *(.rodata.str*) . = ALIGN(4); } > A  .data : { *(.data*) *(.sdata*) . = ALIGN(4); ex_end = .; } > A ") +
                        ".bss : { ex_bss = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); ex_zend = .; } > Z "
                        ".rodata : { *(.rodata*) . = ALIGN(4); ex_rend = .; } > B "
                        "/DISCARD/ : { *(.comment) *(.MIPS.*) *(.reginfo) *(.pdr) *(.gnu.attributes) } }") % (BASE, LIMIT - BASE, RBASE, RLIMIT - RBASE, ZBASE, ZLIMIT - ZBASE))
    defs = ["-DEX_ARCBAL=0x%08xu" % arcbal, "-DEX_FLUSH=0x%08xu" % flush] + ["-D%s=%d" % kv for kv in LAYOUT.items()] + list(extra or [])
    o, elf, b = (os.path.join(OBJ, "xvex" + x) for x in (".o", ".elf", ".bin"))
    subprocess.check_call([gcc + "gcc", "-Os", "-G0", "-mips1", "-mno-abicalls", "-fno-pic", "-ffreestanding", "-nostdlib",
                           "-msoft-float", "-fno-builtin", "-mno-check-zero-division", "-c", SRC, "-o", o] + defs)
    subprocess.check_call([gcc + "ld", "-T", ld, "-o", elf, o])
    subprocess.check_call([gcc + "objcopy", "-O", "binary", "-j", ".text", "-j", ".data", elf, b])
    img = open(b, "rb").read()
    subprocess.check_call([gcc + "objcopy", "-O", "binary", "-j", ".rodata", elf, b + ".ro"])
    ro = open(b + ".ro", "rb").read()
    sym = {}
    for l in subprocess.check_output([gcc + "nm", elf]).decode().splitlines():
        q = l.split()
        if len(q) == 3: sym[q[2]] = int(q[0], 16) & 0xffffffff
    end = sym["ex_end"]
    assert end <= LIMIT, "EX module too big: %d > %d" % (end - BASE, LIMIT - BASE)
    assert sym["ex_rend"] <= RLIMIT and RBASE + len(ro) == sym["ex_rend"], "EX read-only data too big"
    assert BASE + len(img) == end and sym["ex_bss"] == ZBASE and sym["ex_zend"] <= ZLIMIT, "EX layout"
    sys.path.insert(0, os.path.join(HERE, "speed", "upload"))
    import ulib
    bad = ulib.hazards(img, BASE) if hasattr(ulib, "hazards") else []
    assert not bad, "load-delay hazards: %s" % bad
    return [(BASE, img), (RBASE, ro), (ZBASE, bytes(sym["ex_zend"] - ZBASE))], sym     # BSS as zeros in the EXE image


def apply(exe_read, exe_write, arcbal, flush, ebv):
    """-> symbols (ex_achmenu / ex_opt / ex_menuin for the achievements build)"""
    segs, sym = build(arcbal, flush)
    u32 = lambda a: struct.unpack("<I", exe_read(a, 4))[0]
    assert u32(MENU_SITE) == MENU_JAL, "main-menu call site not stock"
    assert u32(ONESHOT2) == ONESHOT2_OLD, "one-shot entry 2 not the pause draw"
    assert (u32(PWRAP_AT), u32(PWRAP_AT + 4)) == PWRAP_OLD, "pause cursor wrap not stock"
    sys.path.insert(0, os.path.join(HERE, "speed")); import frame
    assert u32(ebv + 12) in (0, frame.ahead_callback()), "EBV+12: unexpected callback"   # the predictor stub (its area is gone: --noahead)
    for a, d in segs: exe_write(a, d)
    exe_write(ebv + 12, struct.pack("<I", sym["ex_idle"]))
    exe_write(MENU_SITE, struct.pack("<I", jal(sym["ex_menuin"])))
    if TRSYNC:
        assert u32(TRS_SITE) == TRS_OLD, "trsync: 0x8002a4f8 not the stock jal 0x8002ea50"
        # stub at ONE fixed address in the 2 MB and 8 MB EX variants (free RO tail): a module-placed stub sat at
        # different addresses -> different icache timing -> the timer-based random seed 0x80042308 differed in 2 MB mode
        assert sym["ex_rend"] <= TRS_FIX and TRS_FIX + 4 * len(TRS_STUB) <= RLIMIT, "trsync: RO tail not free"
        exe_write(TRS_FIX, struct.pack("<%dI" % len(TRS_STUB), *TRS_STUB))
        exe_write(TRS_SITE, struct.pack("<I", jal(TRS_FIX)))
        print("trsync: attract -> title transition waits for the GPU (0x8002a4f8 -> fixed stub %08x)" % TRS_FIX)
    if RDFIX:
        assert u32(RDF_SITE) == 0x0C000000 | (0x8001b710 >> 2 & 0x3FFFFFF), "rdfix: 0x8004cb68 not the stock jal SpuGetKeyStatus"
        assert sym["ex_end"] <= RDF_FIX and RDF_FIX + 4 * len(RDF_STUB) <= LIMIT, "rdfix: EX module tail not free"
        exe_write(RDF_FIX, struct.pack("<%dI" % len(RDF_STUB), *RDF_STUB))
        exe_write(RDF_SITE, struct.pack("<I", jal(RDF_FIX)))
        print("rdfix: bank loader silence wait keys off noise voices first (0x8004cb68 -> stub %08x)" % RDF_FIX)
    if not NOSM:                                 # (--nosmeter with --nofskip: the pause menu has no extra rows, stays stock)
        exe_write(ONESHOT2, struct.pack("<I", sym["ex_pdraw"] | 1))
        exe_write(PWRAP_AT, struct.pack("<2I", *(PWRAP_NOFS if NOFS else PWRAP_NEW)))
    print("EX OPTIONS: module %08x-%08x (%d of %d bytes) + data %08x-%08x, opt %08x, achmenu %08x, idle %08x" % (
        BASE, sym["ex_end"], sym["ex_end"] - BASE, LIMIT - BASE, RBASE, sym["ex_rend"], sym["ex_opt"], sym["ex_achmenu"], sym["ex_idle"]))
    return sym


if __name__ == "__main__":
    segs, sym = build(0x80007e60, 0x800171d8)
    print([(hex(a), len(d)) for a, d in segs], {k: hex(v) for k, v in sym.items() if k.startswith("ex_")})
