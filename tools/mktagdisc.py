"""Build the "four full characters" disc: build/<name>.bin/.cue (default name xvsf_tag22; --noflush = diagnosis build).

Sprite/effects variants on the disc (tools/tagload chooses per battle, model tools/tagpolicy.py):
     base     build/FASTDIR   (XVM1)  in place of the A/A0 originals      + build/EFFDEFAULT in place of A/A2/SP_EFF1.NSP
     strong   build/STRONGDIR (XVH1)                              \
     mid      build/MIDDIR    (XVM1, sustained-super tiles RLE)    \  in the DMY.DAT extent, located by
     fat      build/FATDIR    (XVM1, hot tiles RLE)                /  the directory sector
     stock effects file (RLE, from disc/files)                    /
  A character whose mid file is byte-identical to its base file is not stored twice: its mid entry
  is the in-place file.
Directory sector (also in DMY.DAT, read to 0x801fe004 once per battle): 19 x code file, 19 x strong,
19 x fat, 19 x mid, 1 x stock effects entries (BCD MSF + pad, u32 size) = 616 bytes, then the loader's
policy code (section .ram of tools/tagload, linked at 0x801fe26c).

Relocation table (u16 little endian, word index = offset/4 inside the overlay):
     PTR list ... 0xFFFF         32-bit pointers:   word += delta
     J list   ... 0xFFFF         j / jal:           target field += delta >> 2
     (HI, LO) pairs ... 0xFFFF   lui + lo16:        a = (hi<<16) + (s16)lo + delta; lo = a; hi = (a+0x8000)>>16

    python mktagdisc.py [name] [--breakfill] [--build] [--chd]
        --build      recompile tools/tagload (needs a MIPS toolchain, see tools/toolenv.py)
        --breakfill  test disc: the dead-code ranges are filled with break, loader NOT installed
        --logo       boot card before the game starts (tools/logopatch.py); changes the image; without --nospeed
                     also the second card (fan-patch notice, tools/card2patch.py)
        --ach        built-in achievements (tools/ach/xvach.py, docs/ACHIEVEMENTS.md); changes the image
        --vsmenu     with --ex: VERSUS CPU main-menu row below VERSUS (tools/mtap/mtmenu.h; replaces --mtap / --vscpu)
        --achfix     with --ach: "Last One Standing" needs the 1st pick down (tools/ach/xvsf/set.py; 1.5)
        --infmeter   with --ex --ach: EX OPTIONS row INFINITE SUPER METER OFF / ON (default OFF; ON = every fighter's
                     meter held at level 3, achievements never unlock; tools/ach/xvsf/port.c ACH_INFMETER)
        --noskip     no START skip of the end of a match (tools/skippatch.py; default on in the 1.3 US
                     configuration, never with --nospeed / --nosound)
        --noarcbal   no ARCADE BALANCE option line (tools/arcbalpatch.py, docs/BALANCE.md; default on with the START skip)
        --apodlg     1.4 final: Apocalypse pre-fight dialogue (JP arcade) with our own English text (tools/apodlg.py;
                     loader built with -DAPODLG in tools/tagload/apo; PL08 code + text, 19 tile files in DMY.DAT)
        --nofskip    1.4 final: no FRAME SKIP row (EX OPTIONS page + battle pause menu), option forced OFF (= stock)
        --nosmeter   1.4 final (with --nofskip): no SPEED METER row; battle pause menu stock (test builds keep it)
        --perfect    1.4 final: PERFECT needs the whole team undamaged like the arcade (0x8003b780 bnez -> nop)
        --trsync     1.4 (with --ex): fix of a stock bug - START on the attract demo's SCORE / VS RANKING screen could garble the
                     screen (the attract -> title transition cleared the draw buffers without waiting for the GPU)
        --rdfix      1.4 (with --ex, issue #15): fix of a stock bug - a Raging Demon that ends the match left its voice in SPU
                     noise mode; the bank loader's silence wait (0x8004cb68) then never ended (NOW LOADING + noise).  The wait
                     now keys off noise voices and clears NON first (tools/expatch.py RDFIX).
        --voldef     1.4 (issue #5): power-on OPTION defaults BGM VOLUME 3 / S.E. VOLUME 5 (stock 4 / 4; scale 0-8 stars).
                     Boot init 0x800f00a0-0x800f00b8 only; a memory card save still loads the player's own values.
        --title[=TEXT]  version line on the main menu (tools/titlepatch.py; default text "TAG HACK 1.3", "TAG HACK 1.0.1" with --nospeed, "TAG HACK 1.1" with --nosound); changes the image
"""
import hashlib, os, struct, subprocess, sys, json, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import reloc
from mkdisc import fix_sector, CHDMAN, BUILD
import region

DSRC = os.path.join(HERE, "tagload")                  # loader sources
D = os.path.join(HERE, region.TAGDIR)                 # loader build directory (US: the source directory itself)
import toolenv
GCC = toolenv.mips_prefix()
EXE_BASE, EXE_HDR = 0x80010000, 0x800
_jal = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
FTABLE = region.A(0x8003d91c)
HOOK_AT, HOOK_ORIG = region.C(0x8002b1ac), _jal(region.F(0x80054fe4))       # jal pool init        -> glue      (US 0x0C0153F9)
EFFHOOK_AT, EFFHOOK_ORIG = region.C(0x8002b154), _jal(region.F(0x80054054))  # jal load set 0x26    -> effglue   (US 0x0C015015)
# section -> (address, end of the dead range it may use)
CHUNKS = {".chunke": (0x80015604, 0x800156a0), ".chunkf": (0x8001667c, 0x80016718), ".chunkd": (0x800168a4, 0x80016a54),
          ".chunkc": (0x80016bcc, 0x80016ce8), ".chunka": (0x800171c8, 0x80017350), ".dbg": (0x80017350, 0x80017360),
          ".chunkb": (0x800173b8, 0x800175d0), ".chunkg": (0x8008f4d0, 0x8008f558)}
BOSSHOOK_AT, BOSSHOOK_ORIG = region.C(0x8002b2d0), _jal(region.F(0x8002de3c))   # jal file read (extra boss file 0x10c) -> bossfin (US 0x0C00B78F)
if region.REGION != "us":                             # the same dead ranges, located in this region's executable
    CHUNKS = {k: (region.C(a), region.C(a) + (e - a)) for k, (a, e) in CHUNKS.items()}
LOADER_MACROS = dict(A_FTABLE=region.A(0x8003d91c), A_D130=region.A(0x8003d130), A_POOLSIZE=region.A(0x8004382c), A_IDS=region.A(0x800423b2),
                     A_INITTAB=region.A(0x8003d83c), A_LOADFILE=region.F(0x8002de3c), A_SPRLOAD=region.F(0x80053f78),
                     A_SETLOAD=region.F(0x80054054), A_POOLINIT=region.F(0x80054fe4))
RLEDIR = os.path.join(region.FILES, "A", "A0")              # stock RLE sprite files, read by the boss path
# 0x8008f4d0-0x8008f558 (break-tested free range; used by tag14/15) holds bossfin() since tag20.
DIR_MAGIC = 0x31445658                                # "XVD1" at byte 2040 of the directory sector, sum of words 0..509 at 2044
RESERVED = [(0x800146a8, 0x80015024)]                 # CdSearchFile (live)
FASTDIR, STRONGDIR, MIDDIR, FATDIR = "nspm", "nsph4", "nspm4", "nspfat2"   # base (in place), strong, mid, fat sprite files
# 1.1: strong tier = XVH1 + its most decoded tiles as stock RLE (work/speed/decode/strongrle.py 4); with --nospeed the
# 1.0.x strong files (build/nsp): decided when the build runs (the builder imports this module before setting argv)
_strongdir = lambda: "nsp" if "--nospeed" in sys.argv else STRONGDIR
EFFDEFAULT = "nspm_eff/SP_EFF1.NSP"                   # effects file in place of A/A2/SP_EFF1.NSP (XVM1)
EFFSTOCK = os.path.join(region.FILES, "A", "A2", "SP_EFF1.NSP")             # stock RLE effects file (DMY.DAT extent)
DIRADDR, DIRTABLES, RAMORG = 0x801fe004, (4 * 19 + 1) * 8, 0x801fe26c
POOL, LIMIT, LINKBASE = 19296, 0x801fe000, 0x800d1000


# ---- 1.1 continuous hot-tile tier (tools/speed/decode/hotfile.py): loader variant tools/tagload/hot (tagload.c -DHOT),
# in-place base files = build/nsphot/base, hot regions + hot directory sector in the DMY.DAT extent.  OFF by default (--hot to
# build it; no measured gain over the fat/mid tiers, and its resident code range is the upload worker's now).
HOTDIR = "nsphot"
HOT = False
_CONF0 = None


def configure():
    """set the module globals for this build (the builder imports the module before it sets argv)"""
    global D, CHUNKS, DIRTABLES, RAMORG, FASTDIR, HOT, _CONF0
    if _CONF0 is None: _CONF0 = (D, dict(CHUNKS), DIRTABLES, RAMORG, FASTDIR)
    D, CHUNKS, DIRTABLES, RAMORG, FASTDIR = _CONF0[0], dict(_CONF0[1]), _CONF0[2], _CONF0[3], _CONF0[4]
    HOT = "--hot" in sys.argv and "--nospeed" not in sys.argv and region.REGION == "us"   # opt-in: needs 0x80055c34-0x80055ebc (now upload's)
    if FORCETIER() and not HOT and not R12() and region.REGION == "us":
        D = os.path.join(D, "ft")                            # measurement builds (--forcetier): own build dir, tools/tagload untouched
    if R12() and not HOT and region.REGION == "us":
        D = os.path.join(D, "r12")                           # 1.3: --nospeed / --nosound keep the 1.2 loader (no -DBOSSP1), bit for bit
    if APODLG():                                             # 1.4 final: loader with -DAPODLG in its own build directory
        assert region.REGION == "us" and not HOT and not R12() and not FORCETIER(), "--apodlg: US 1.3+ loader only"
        D = os.path.join(D, "apo8" if os.environ.get("XV_APO8") else "apo")     # (relative to the loader base: the release
                                                             # builder's prebaked tree; apo8 = the 8 MB disc's -DAPO8 loader)
    if HOT:
        D = os.path.join(HERE, region.TAGDIR, "hot")
        CHUNKS[".chunkh"] = (0x80055c34, 0x80055ebc)          # tools/speed/quad.py FREED range
        DIRTABLES += 8; RAMORG += 8                          # + the hot directory entry
        FASTDIR = HOTDIR + "/base"


PREBUILT = False      # the release builder (builder/xvb, no compiler) sets it: the --apodlg loader comes prebaked (tagload/apo, apo8)
R12 = lambda: "--nospeed" in sys.argv or "--nosound" in sys.argv     # the configurations that reproduce 1.0.1 / 1.1 images
APODLG = lambda: "--apodlg" in sys.argv                                 # 1.4 final: Apocalypse dialogue (tools/apodlg.py)
# 1.4 L2 study (work/x14/L2.md), measurement only, default off: --forcetier=C:T,... (hex character id : tier 0 base,
# 1 strong, 2 fat, 3 mid; unnamed characters base) -> tagload.c plan() -DFORCETIER, built in tools/tagload/ft
FORCETIER = lambda: next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--forcetier=")), None)


HDIRADDR, HDIRCODE, HSTEPS = 0x801fd804, 0x801fdc7c, 9


def ahead_area():
    """the 2 sectors behind the directory sector: tools/speed/decode/ahead_sector.py (to 0x801fe804-0x801ff600); the
    cache entry points come from the upload module when it has them (else 0: predictions are discarded)"""
    sys.path.insert(0, os.path.join(HERE, "speed", "decode")); sys.path.insert(0, os.path.join(HERE, "speed"))
    import ahead_sector
    vc = (0, 0)
    try:
        import upload
        sy = upload.symbols() if hasattr(upload, "symbols") else {}
        if "vc_lookup" in sy and "vc_prefetch" in sy: vc = (sy["vc_lookup"], sy["vc_prefetch"])
    except Exception:
        pass
    img, sym = ahead_sector.build(vc)
    assert len(img) == 4096
    return img


def hot_dir_sector(regpos, steps):
    """hot directory sector: word 0 = &hplan, per character (u32 region msf, u8 steps, u8 0, 9 x (u16 S, u16 R - S,
    u16 gain)), code from +1144, magic 'XVHD' at 2040, checksum of words 0..509 at 2044 (tagload.c hplan)"""
    s = symbols()
    d = bytearray(2048)
    struct.pack_into("<I", d, 0, s["hplan"])
    for c in range(19):
        st = steps.get("%02X" % c, [])[:HSTEPS]
        o = 4 + 60 * c
        if c in regpos and st:
            d[o:o + 4] = msf(regpos[c])
            d[o + 4] = len(st)
            g0 = 0.0
            for k, (n, S, R, G) in enumerate(st):
                g = int(round((G - g0) * 3000)); g0 = G
                assert 0 <= S < 65536 and 0 < R - S < 65536 and 0 <= g < 65536, (c, k, S, R, g)
                struct.pack_into("<3H", d, o + 6 + 6 * k, S, R - S, g)
    code = open(os.path.join(D, "tagload.hram.bin"), "rb").read()
    assert HDIRADDR + 1144 == HDIRCODE and HDIRCODE <= s["hplan"] < HDIRCODE + len(code) and 1144 + len(code) <= 2040
    d[1144:1144 + len(code)] = code
    struct.pack_into("<I", d, 2040, 0x44485658)
    struct.pack_into("<I", d, 2044, sum(struct.unpack_from("<510I", d, 0)) & 0xFFFFFFFF)
    return bytes(d)


def build():
    cf = ["-mips1", "-G0", "-mno-abicalls", "-fno-pic"]
    if not R12():
        cf.append("-DBOSSP1")                         # 1.3: boss fight with the player on pad 2 on the new loader (tagload.c bossprep)
    elif not HOT and region.REGION == "us":           # tools/tagload/r12: the 1.2 loader, built from the same sources without -DBOSSP1
        os.makedirs(D, exist_ok=True)
        for fn in ("tagload.c", "glue.S", "link.ld"): shutil.copyfile(os.path.join(DSRC, fn), os.path.join(D, fn))
    if HOT:                                           # 1.1 loader: sources copied into tools/tagload/hot
        os.makedirs(D, exist_ok=True)
        for fn in ("tagload.c", "glue.S"): shutil.copyfile(os.path.join(DSRC, fn), os.path.join(D, fn))
        subprocess.check_call([GCC + "gcc", "-Os", "-ffreestanding", "-msoft-float", *cf, "-DHOT", "-c", "tagload.c", "-o", "tagload.o"], cwd=D)
        for fn in ("glue", "hotdata", "hotspr"):
            subprocess.check_call([GCC + "gcc", *cf, "-c", fn + ".S", "-o", fn + ".o"], cwd=D)
        subprocess.check_call([GCC + "ld", "-T", "link.ld", "glue.o", "hotdata.o", "hotspr.o", "tagload.o", "-o", "tagload.elf"], cwd=D)
        for sec in list(CHUNKS) + [".ram", ".ramb", ".hram"]:
            subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "tagload.elf", "tagload" + sec + ".bin"], cwd=D)
        open(os.path.join(D, "tagload.sym"), "w").write(subprocess.check_output([GCC + "nm", "-n", "tagload.elf"], cwd=D).decode())
        return
    extra = ["-DPOOL=%su" % a.split("=")[1] for a in sys.argv if a.startswith("--pool=")]      # experiment only
    if "--oldlayout" in sys.argv: extra.append("-DSLOTORDER")       # tag14 disc layout: characters loaded in slot order
    if "--noflush" in sys.argv: extra.append("-DNOFLUSH")           # diagnosis build: never call BIOS FlushCache
    if APODLG():                                                    # tools/tagload/apo: sources copied, -DAPODLG (bossfin + apofont)
        os.makedirs(D, exist_ok=True)
        for fn in ("tagload.c", "glue.S", "link.ld"): shutil.copyfile(os.path.join(DSRC, fn), os.path.join(D, fn))
        extra.append("-DAPODLG")
        if os.environ.get("XV_APO8"): extra.append("-DAPO8")     # 8 MB disc (mkap8disc): apo_ptr in .chunkf_data
    if FORCETIER() and region.REGION == "us" and not R12():         # measurement build (see FORCETIER)
        ft = [0, 0, 0]
        for kv in FORCETIER().split(","):
            c, t = (int(x, 16) for x in kv.split(":")); assert 0 <= c < 19 and t in (0, 1, 2, 3)
            ft[c >> 3] |= t << 4 * (c & 7)
        os.makedirs(D, exist_ok=True)
        for fn in ("tagload.c", "glue.S", "link.ld"): shutil.copyfile(os.path.join(DSRC, fn), os.path.join(D, fn))
        extra += ["-DFORCETIER", *("-DFT%d=0x%08xu" % (k, v) for k, v in enumerate(ft))]
    if region.REGION != "us":                         # separate build directory: sources copied, addresses by -D, link script re-addressed
        os.makedirs(D, exist_ok=True)
        for fn in ("tagload.c", "glue.S"): shutil.copyfile(os.path.join(DSRC, fn), os.path.join(D, fn))
        ld = open(os.path.join(DSRC, "link.ld")).read()
        us_chunks = {".chunke": 0x80015604, ".chunkf": 0x8001667c, ".chunkd": 0x800168a4, ".chunkc": 0x80016bcc, ".chunka": 0x800171c8,
                     ".dbg": 0x80017350, ".chunkb": 0x800173b8, ".chunkg": 0x8008f4d0}
        for sec, a in us_chunks.items():
            assert ld.count(f"0x{a:08x}") == 1, sec
            ld = ld.replace(f"0x{a:08x}", f"0x{region.C(a):08x}")
        open(os.path.join(D, "link.ld"), "w").write(ld)
        extra += [f"-D{k}=0x{v:08x}" for k, v in LOADER_MACROS.items()]
    subprocess.check_call([GCC + "gcc", "-Os", "-ffreestanding", "-msoft-float", *cf, *extra, "-c", "tagload.c", "-o", "tagload.o"], cwd=D)
    subprocess.check_call([GCC + "gcc", *cf, *(["-DAPODLG"] if APODLG() else []), *(["-DAPO8"] if APODLG() and os.environ.get("XV_APO8") else []), "-c", "glue.S", "-o", "glue.o"], cwd=D)
    subprocess.check_call([GCC + "ld", "-T", "link.ld", "glue.o", "tagload.o", "-o", "tagload.elf"], cwd=D)
    for sec in list(CHUNKS) + [".ram", ".ramb"]:
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "tagload.elf", "tagload" + sec + ".bin"], cwd=D)
    open(os.path.join(D, "tagload.sym"), "w").write(subprocess.check_output([GCC + "nm", "-n", "tagload.elf"], cwd=D).decode())


def symbols():
    s = {}
    for l in open(os.path.join(D, "tagload.sym")):
        if len(l.split()) == 3:
            a, t, n = l.split(); s[n] = int(a, 16) & 0xFFFFFFFF
    return s


def reloc_table(char):
    r = reloc.get(char)
    assert not r.unknown and not r.unpaired_lo and not r.orphan_hi
    t = [*r.ptr, 0xFFFF, *r.j26, 0xFFFF]
    for l, h in sorted(r.lo_hi.items(), key=lambda x: x[1]):
        t += [h, l]
    t.append(0xFFFF)
    assert all(0 <= x < 0xFFFF for x in r.ptr + r.j26 + r.hi + r.lo)
    return struct.pack(f"<{len(t)}H", *t)


def apply_table(code, table, delta):
    """Python model of load_one()'s relocation loop."""
    W = list(struct.unpack_from(f"<{len(code) // 4}I", code))
    T = struct.unpack(f"<{len(table) // 2}H", table)
    p = 0
    for k in range(3):
        while True:
            t = T[p]; p += 1
            if t == 0xFFFF: break
            v = W[t]
            if k == 0: v = (v + delta) & 0xFFFFFFFF
            elif k == 1: v = (v & 0xFC000000) | ((v + (delta >> 2)) & 0x03FFFFFF)
            else:
                l = T[p]; p += 1
                lv = W[l]
                a = ((v << 16) + ((lv & 0xFFFF) - (0x10000 if lv & 0x8000 else 0)) + delta) & 0xFFFFFFFF
                W[l] = (lv & 0xFFFF0000) | (a & 0xFFFF)
                v = (v & 0xFFFF0000) | (((a + 0x8000) & 0xFFFFFFFF) >> 16)
            W[t] = v
    assert p == len(T)
    return struct.pack(f"<{len(W)}I", *W) + code[len(W) * 4:]


_cf = {}


def code_file(char):
    if char in _cf: return _cf[char]
    r = reloc.get(char)
    tab = reloc_table(char)
    for base in (0x80152000, 0x800c2fa8, 0x801a4568):          # incl. a negative delta
        want = r.relocate(base, 0, exact_noise=False)
        assert apply_table(r.a, tab, (base - LINKBASE) & 0xFFFFFFFF) == want, (char, hex(base))
    _cf[char] = (r.a + b"\0" * (-r.size % 4) + tab, len(tab))
    return _cf[char]


def msf(lba):
    b = lambda x: (x // 10) << 4 | x % 10
    l = lba + 150
    return bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 0])


def sprite_file(d, c):
    return open(os.path.join(BUILD, d, "SP_PL%02X.NSP" % c), "rb").read()


# Game files (file table index) that a battle load reads; copies go into the DMY.DAT extent in read
# order and the game's own file table is repointed to them (the originals stay where they are).
G_STAGE, G_VS, G_AKE, G_EFF2, G_EFF0, G_SO, G_EFF1, G_SPR = 0x4f, 0x93, 0xb8, 0x91, 0x85, 0x86, 0x80, 0x5a


def deadcheck(ranges, exe):
    """static proof for another region: nothing in its executable or overlays refers into the
    ranges we overwrite with new code (j/jal, branches from outside, pointer words, lui+offset pairs)"""
    import glob
    n = (len(exe) - EXE_HDR) // 4
    W = struct.unpack_from(f"<{n}I", exe, EXE_HDR)
    # 0x80010420-0x80010508 is not code but libcd's debug message strings (same bytes, same address in
    # every region); they are only handed to the debug print on CD errors.  Used by the US build since tag4.
    ranges = [(lo, hi) for lo, hi in ranges if not (0x80010420 <= lo and hi <= 0x80010508)]
    def inside(a): return any(lo <= a < hi for lo, hi in ranges)
    bad = []
    def scan(W, base, name):
        for i, w in enumerate(W):
            here = base + 4 * i if base else None
            op = w >> 26
            if op in (2, 3):
                t = 0x80000000 | (w & 0x3FFFFFF) << 2
                if inside(t) and not (here and inside(here)): bad.append((name, i * 4, "j/jal", t))
            elif here and op in (1, 4, 5, 6, 7) and not inside(here):
                imm = w & 0xFFFF; imm -= 0x10000 if imm & 0x8000 else 0
                if inside(here + 4 + imm * 4): bad.append((name, i * 4, "branch", here + 4 + imm * 4))
            elif inside(w) and not w & 3 and not (here and inside(here)): bad.append((name, i * 4, "word", w))
            elif op == 15 and 0x8001 <= (w & 0xFFFF) <= 0x800a and not (here and inside(here)):
                rt = (w >> 16) & 31
                for k in range(1, 8):
                    if i + k >= len(W): break
                    w2 = W[i + k]
                    if ((w2 >> 21) & 31) == rt and (w2 >> 26) in (9, 13, 0x23, 0x21, 0x25, 0x20, 0x24, 0x2b, 0x29, 0x28):
                        lo = w2 & 0xFFFF
                        v = ((w & 0xFFFF) << 16) + (lo if (w2 >> 26) == 13 else (lo - 0x10000 if lo & 0x8000 else lo))
                        if inside(v): bad.append((name, i * 4, "lui pair", v))
                        break
    scan(W, EXE_BASE, "EXE")
    for f in glob.glob(os.path.join(region.FILES, "P", "P*", "*.BIN")):
        d = open(f, "rb").read()
        scan(struct.unpack_from(f"<{len(d) // 4}I", d), 0, os.path.basename(f))
    assert not bad, "references into ranges assumed dead: " + ", ".join(f"{n}+{o:x} {k} {t:08x}" for n, o, k, t in bad[:12])
    print(f"dead-range check ({region.REGION}): {len(ranges)} ranges, no reference from the executable or {len(glob.glob(os.path.join(region.FILES, 'P', 'P*', '*.BIN')))} overlays")


def finish_dir(d, code="tagload.ram.bin"):
    """tables -> full directory sector: + code (policy code / boss-path code), magic, checksum"""
    assert len(d) == DIRTABLES
    d += open(os.path.join(D, code), "rb").read()
    assert len(d) <= 2040, "directory sector overflow"
    d += b"\0" * (2040 - len(d)) + struct.pack("<I", DIR_MAGIC)
    return d + struct.pack("<I", sum(struct.unpack("<510I", d[:2040])) & 0xFFFFFFFF)


def patches(dmy_lba=None, info=None, gamefile=None, base_lba=None):
    """[(addr, bytes)] of the loader.  With dmy_lba: also lays out the DMY.DAT extent (info gets
    (lba, data, label) for every file incl. the directory sector), fills the directory entry and
    repoints the game's file table (MSF only) to the copies.  gamefile(index) -> bytes as on the disc.

    Layout (seek model measured with tools/mktrace.py: a jump below ~1900 sectors costs ~7 frames, a
    longer one ~21-26):
        stages 0-5 (STAGEn.BIN + VSn.SCR) | AKE.PAC, SP_EFF2, SP_EFF0, SP_SO00..0A, directory sector,
        SP_EFF1 (XVM1), SP_EFF1 (stock) | stages 6-A | per character 0..18: code+reloc, base, mid, fat, strong
    """
    s = symbols()
    assert s["plan"] == s["bplan"] == RAMORG == DIRADDR + DIRTABLES and (DIRADDR - FTABLE) % 8 == 0 and s["tl_dbg"] == CHUNKS[".dbg"][0]
    out = []
    dirent = bossdirent = None
    if "--oldlayout" in sys.argv:
        raise SystemExit("--oldlayout (tag14/tag16 disc layout) is not supported any more: the boss path needs the new layout")
    if dmy_lba is not None and "--oldlayout" in sys.argv:       # tag14 layout: only the hack's own files in DMY.DAT
        lba = dmy_lba
        def put(data, label):
            nonlocal lba
            ent = msf(lba) + struct.pack("<I", len(data))
            info.append([lba, data, label]); lba += (len(data) + 2047) // 2048
            return ent
        code = [put(code_file(c)[0], f"code PL{c:02X} (reloc table {code_file(c)[1]})") for c in range(18)]
        code.append(code[11])                                   # char 18 runs PL0B's code (file table index 21)
        d = b"".join(code)
        for dname, lab in ((_strongdir(), "strong"), (FATDIR, "fat"), (MIDDIR, "mid")):      # = tiers 1, 2, 3 of tagload.c
            for c in range(19):
                data = sprite_file(dname, c); base = sprite_file(FASTDIR, c)
                assert len(data) % 4 == 0
                assert len(sprite_file(_strongdir(), c)) < len(base) <= len(sprite_file(MIDDIR, c)) <= len(sprite_file(FATDIR, c)), f"tier sizes out of order for char {c}"
                if lab == "mid" and data == base:                       # no duplicate: the in-place file is the mid file
                    d += msf(base_lba[c]) + struct.pack("<I", len(base))
                else:
                    d += put(data, f"{lab} SP_PL{c:02X}")
        d += put(open(EFFSTOCK, "rb").read(), "stock SP_EFF1")
        dirent = put(finish_dir(d), "directory sector (tables + policy code)")
    elif dmy_lba is not None:
        items = []                                              # (key, data, label)
        import sndpatch                                         # 1.2: full sound banks (tools/sndpatch.py; --nosound: as 1.1)
        SND = sndpatch.enabled()
        if SND:
            snd_res, snd_sym, snd_dcode = sndpatch.code(s["flushcache"])
            snd_items, snd_ref = sndpatch.disc_items()
            items += snd_items                                  # read first at a battle load (the bank list)
        def game(idx, label): items.append((("g", idx), gamefile(idx), label))
        def stages(lo, hi):
            for st in range(lo, hi):
                game(G_STAGE + st, f"STAGE{st:X}.BIN"); game(G_VS + st, f"VS{st:X}.SCR")
        stages(0, 6)
        game(G_AKE, "AKE.PAC"); game(G_EFF2, "SP_EFF2"); game(G_EFF0, "SP_EFF0")
        for st in range(11): game(G_SO + st, f"SP_SO{st:02X}")
        AHEAD = "--nospeed" not in sys.argv and region.REGION == "us" and "--noahead" not in sys.argv   # 1.1: decode-ahead predictor read with the directory (1.4 --noahead: dropped, see work/x14/AUDIT.md)
        items.append((("dir",), bytes(2048 * (3 if AHEAD else 1)), "directory sector (tables + policy code)" + (" + decode-ahead predictor (2 sectors)" if AHEAD else "")))
        items.append((("bossdir",), bytes(2048), "boss directory sector (stock RLE files + boss-path code)"))
        game(G_EFF1, "SP_EFF1 (XVM1, in the game file table)")
        items.append((("eff",), open(EFFSTOCK, "rb").read(), "SP_EFF1 (stock RLE)"))
        stages(6, 11)
        for c in range(19):
            base = sprite_file(FASTDIR, c)
            assert len(sprite_file(_strongdir(), c)) < len(base) <= len(sprite_file(MIDDIR, c)) <= len(sprite_file(FATDIR, c)), f"tier sizes out of order for char {c}"
            cf = code_file(11 if c == 18 else c)                # char 18 runs PL0B's code (own copy, next to its sprites)
            items.append((("code", c), cf[0], f"char {c:2d} code PL{11 if c == 18 else c:02X} (reloc table {cf[1]})"))
            assert gamefile(G_SPR + c) == base, "in-place sprite file is not build/FASTDIR"
            game(G_SPR + c, f"char {c:2d} base SP_PL{c:02X}")
            if sprite_file(MIDDIR, c) != base:                  # else: the base file is the mid file
                items.append((("mid", c), sprite_file(MIDDIR, c), f"char {c:2d} mid"))
            items.append((("fat", c), sprite_file(FATDIR, c), f"char {c:2d} fat"))
            items.append((("strong", c), sprite_file(_strongdir(), c), f"char {c:2d} strong"))
            if HOT:
                reg = open(os.path.join(BUILD, HOTDIR, "region", "SP_PL%02X.REG" % c), "rb").read()
                if reg: items.append((("hot", c), reg, f"char {c:2d} hot region"))
        if HOT: items.append((("hdir",), bytes(2048), "hot directory sector (steps + hplan)"))
        for c in range(19):                                     # boss path: the game's original files
            items.append((("rle", c), open(os.path.join(RLEDIR, "SP_PL%02X.NSP" % c), "rb").read(), f"char {c:2d} stock RLE SP_PL{c:02X}"))
        if APODLG():                                            # Apocalypse dialogue: the speaker's English text tiles
            import apodlg
            for c, data in enumerate(apodlg.font_files(apodlg.kanji_from(region.FILES))[0]):
                items.append((("apo", c), data, f"char {c:2d} Apocalypse dialogue tiles"))
        pos = {}; lba = dmy_lba
        for key, data, label in items:
            assert len(data) % 4 == 0 or key[0] in ("g", "code")
            pos[key] = lba; lba += (len(data) + 2047) // 2048
        size = {key: len(data) for key, data, label in items}
        ent = lambda key: msf(pos[key]) + struct.pack("<I", size[key])
        d = b"".join(ent(("code", c)) for c in range(19))
        for tier in ("strong", "fat", "mid"):                   # = tiers 1, 2, 3 of tagload.c
            d += b"".join(ent((tier, c)) if (tier, c) in pos else ent(("g", G_SPR + c)) for c in range(19))
        d += ent(("eff",))
        if HOT: d += ent(("hdir",))
        d = finish_dir(d)
        # boss directory: code files, var[T_STRONG-1] unused, var[T_FAT-1] = fat files (players on the new
        # loader), var[T_MID-1] = stock RLE files (boss; and the mains on the stock path), eff = stock effects
        bd = (b"".join(ent(("code", c)) for c in range(19)) + bytes(19 * 8) + b"".join(ent(("fat", c)) for c in range(19))
              + b"".join(ent(("rle", c)) for c in range(19)) + ent(("eff",)) + (bytes(8) if HOT else b""))
        bd = finish_dir(bd, "tagload.ramb.bin")
        if APODLG():                                            # apoent[19] in the boss directory's code part
            o = s["apoent"] - DIRADDR
            assert o % 8 == (FTABLE - DIRADDR) % 8 == 0 and bd[o:o + 152] == bytes(152) and s["apoent"] + 152 <= s["ramb_end"]
            bd = bytearray(bd); bd[o:o + 152] = b"".join(ent(("apo", c)) for c in range(19))
            struct.pack_into("<I", bd, 2044, sum(struct.unpack_from("<510I", bd, 0)) & 0xFFFFFFFF); bd = bytes(bd)
        if HOT:
            hd = hot_dir_sector({k[1]: p for k, p in pos.items() if k[0] == "hot"}, json.load(open(os.path.join(BUILD, HOTDIR, "steps.json"))))
        if SND:
            snd_dir = sndpatch.dir_data(pos, size, snd_ref, snd_dcode)
            out += sndpatch.exe_patches(snd_res, snd_sym, msf(pos[("snddir",)]) + struct.pack("<I", len(snd_dir)))
        for key, data, label in items:
            if key == ("snddir",): data = snd_dir
            info.append((pos[key], (d + ahead_area() if AHEAD else d) if key == ("dir",) else bd if key == ("bossdir",) else hd if key == ("hdir",) else data, label))
            if key[0] == "g":
                out.append((FTABLE + 8 * key[1], msf(pos[key])))    # file table: MSF only, the size stays
        dirent = msf(pos[("dir",)]) + struct.pack("<I", 2048 * (3 if AHEAD else 1))   # the loader reads all of it to 0x801fe004
        bossdirent = msf(pos[("bossdir",)]) + struct.pack("<I", 2048)
    for sec, (addr, end) in CHUNKS.items():
        b = open(os.path.join(D, "tagload" + sec + ".bin"), "rb").read()
        assert addr + len(b) <= end, f"{sec} too big: {len(b)} > {end - addr}"
        for sym in ("dirent", "bossdirent"):
            assert (s[sym] - FTABLE) % 8 == 0, f"{sym} at {s[sym]:08x} is not reachable as a fake file index"
        for sym, val in (("dirent", dirent), ("bossdirent", bossdirent)):
            if val is not None and addr <= s[sym] < addr + len(b):
                o = s[sym] - addr
                assert b[o:o + 8] == bytes(8)
                b = b[:o] + val + b[o + 8:]
        out.append((addr, b))
    jal = lambda t: struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))
    out.append((HOOK_AT, jal(s["glue"])))
    out.append((EFFHOOK_AT, jal(s["effglue"])))
    out.append((BOSSHOOK_AT, jal(s["bossfin"])))
    return out


def main():
    configure()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = args[0] if args else region.DISC
    if "--build" in sys.argv or FORCETIER() or (APODLG() and not PREBUILT) or not os.path.exists(os.path.join(D, "tagload.sym")):
        build()
    if APODLG():                                        # patched Apocalypse code (both links) for the relocation tables
        import apodlg
        apodlg.APO_PTR = symbols()["apo_ptr"]          # 0x8001735c (.dbg tail); 8 MB disc: .chunkf_data (XV_APO8)
        assert apodlg.APO_PTR == 0x8001735c or os.environ.get("XV_APO8"), "apodlg: apo_ptr moved"
        _apotab = apodlg.font_files(apodlg.kanji_from(region.FILES))[1]
        for slot, L in ((0, apodlg.P0_BASE), (1, apodlg.P2_BASE)):
            reloc.OVERRIDE[(8, slot)] = apodlg.patch_code(open(reloc.path(8, slot), "rb").read(), L, _apotab)
        reloc._cache.pop(8, None); _cf.pop(8, None)
    import mknspdisc
    argv = sys.argv
    sys.argv = [argv[0], name, "--dir=" + FASTDIR, "--tag", "--eff1=" + EFFDEFAULT]
    if region.REGION != "us":                         # the EXE patches are applied below, re-targeted; here only the files
        sys.argv = [argv[0], name, "--dir=" + FASTDIR, "--noexe", "--eff1=" + EFFDEFAULT]
    sys.argv += [a for a in argv if a in ("--nospeed", "--nosound")]   # nsppatch / tagpatch (inside mknspdisc) must see them too
    mknspdisc.main()
    sys.argv = argv
    out = os.path.join(BUILD, name + ".bin")
    lmap = json.load(open(region.LMAP))
    exe_lba, exe_size = lmap[region.EXE]
    dmy_lba, dmy_size = lmap["DMY.DAT"]
    orig = open(region.EXEPATH, "rb").read()
    assert msf(lmap["P/P0/PL00_10.BIN"][0]) == orig[FTABLE + 8 * 3 - EXE_BASE + EXE_HDR:][:4], "file table MSF format"
    touched = set()
    with open(out, "r+b") as f:
        def wr_data(sec, within, data):
            f.seek(sec * 2352 + 24 + within); f.write(data); touched.add(sec)

        def exe_write(addr, data):
            off = addr - EXE_BASE + EXE_HDR
            assert 0 <= off and off + len(data) <= exe_size
            for i in range(len(data)):
                o = off + i
                wr_data(exe_lba + o // 2048, o % 2048, data[i:i + 1])

        def exe_read(addr, n):
            b = bytearray()
            for i in range(n):
                o = addr - EXE_BASE + EXE_HDR + i
                f.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048); b += f.read(1)
            return bytes(b)

        for sec, (addr, end) in CHUNKS.items():           # still the original (dead) code on the nsp+tag disc
            assert exe_read(addr, end - addr) == orig[addr - EXE_BASE + EXE_HDR:end - EXE_BASE + EXE_HDR], sec
        if "--breakfill" in sys.argv:
            for sec, (addr, end) in CHUNKS.items():
                exe_write(addr, struct.pack("<I", 0x0000000D) * ((end - addr) // 4))
                print(f"break-fill {addr:08x}-{end:08x}")
        else:
            import speedpatch                                                   # 1.1 engine speed-ups (stage overlays first:
            def iso_write(path, off, data):                                     #  the battle layout copies the stage files)
                lba, size = lmap[path]; assert off + len(data) <= size
                for i in range(len(data)):
                    wr_data(lba + (off + i) // 2048, (off + i) % 2048, data[i:i + 1])
            n_ovl = speedpatch.apply_overlays(None, iso_write)
            if n_ovl: print(f"speed: {n_ovl} stage overlay patches")
            if "--st7ko" in sys.argv:                       # 1.4 final: chemical plant (stage 7) explodes on the first KO
                ST7 = "P/P4/STAGE7.BIN"                     #  like the arcade (games/mvc/docs/STAGE_TRANSITION.md): its
                lba7, size7 = lmap[ST7]                     #  handler reads round 0x80042349 in PS1 mode -> read the arcade
                for off in (0x960, 0xb18, 0xf84):           #  KO flag 0x80042372 instead (one-round tag battles)
                    f.seek((lba7 + off // 2048) * 2352 + 24 + off % 2048); old = f.read(4)
                    assert old == struct.pack("<I", 0x80422349), f"st7ko: unexpected word at STAGE7+{off:#x}: {old.hex()}"
                    iso_write(ST7, off, struct.pack("<I", 0x80422372))
                print("st7ko: STAGE7.BIN 3 words (round -> KO trigger)")
            if APODLG():                                    # stock-slot path reads the disc's own PL08 files: same patch
                for slot, pth in ((0, "P/P0/PL08_10.BIN"), (1, "P/P2/PL08_20.BIN")):
                    new = reloc.OVERRIDE[(8, slot)]; old = open(reloc.path(8, slot), "rb").read()
                    lba8, size8 = lmap[pth]; assert size8 == len(new) == len(old)
                    cur = b"".join((f.seek((lba8 + i) * 2352 + 24), f.read(2048))[1] for i in range((size8 + 2047) // 2048))[:size8]
                    assert cur == old, f"apodlg: {pth} on the image is not the disc file"
                    for o in range(0, size8, 4):
                        if new[o:o + 4] != old[o:o + 4]: iso_write(pth, o, new[o:o + 4])
                print("apodlg: PL08_10 / PL08_20 intro calls + text routine + English text table")
            if "--voldef" in sys.argv:                      # issue #5: power-on BGM 3 / SE 5 (the master block 0x800421aa/ab + apply calls)
                VD = [(0x800f00a0, 0xa03021aa, 0x34040003),   # sb s0,0x21aa(at)  -> ori a0,zero,3
                      (0x800f00a8, 0x34040004, 0xa02421aa),   # (jal delay) ori a0,zero,4 -> sb a0,0x21aa(at)  (BGM master = arg = 3)
                      (0x800f00b0, 0xa03021ab, 0x34040005),   # sb s0,0x21ab(at)  -> ori a0,zero,5
                      (0x800f00b8, 0x34040004, 0xa02421ab)]   # (jal delay) ori a0,zero,4 -> sb a0,0x21ab(at)  (SE master = arg = 5)
                for a, old_w, new_w in VD:
                    assert exe_read(a, 4) == struct.pack("<I", old_w), "voldef: unexpected word at %08x" % a
                    exe_write(a, struct.pack("<I", new_w))
                print("voldef: power-on BGM VOLUME 3 / S.E. VOLUME 5 (boot init 0x800f00a0-b8)")
            if "--perfect" in sys.argv:                     # arcade PERFECT rule: always the team branch (main + partner life)
                assert exe_read(0x8003b780, 4) == struct.pack("<I", 0x14400011), "perfect: unexpected word at 0x8003b780"
                exe_write(0x8003b780, bytes(4))
                print("perfect: 0x8003b780 bnez -> nop (PERFECT = whole team undamaged)")
            info = []
            def gamefile(idx):
                ent = exe_read(FTABLE + 8 * idx, 8)
                bcd = lambda x: (x >> 4) * 10 + (x & 15)
                l = (bcd(ent[0]) * 60 + bcd(ent[1])) * 75 + bcd(ent[2]) - 150
                n = struct.unpack_from("<I", ent, 4)[0]; b = bytearray()
                for i in range((n + 2047) // 2048):
                    f.seek((l + i) * 2352 + 24); b += f.read(2048)
                return bytes(b[:n])
            pl = patches(dmy_lba, info, gamefile, [lmap["A/A0/SP_PL%02X.NSP" % c][0] for c in range(19)])
            import nsppatch, tagpatch, palpatch
            pal = [] if "--nopal" in sys.argv else list(palpatch.patches())     # CLUT fix after a tag
            import aipatch, hudpatch                                            # CPU tag AI, partner life bars
            pal += ([] if "--noai" in sys.argv else list(aipatch.patches())) + ([] if "--nohud" in sys.argv else list(hudpatch.patches()))
            import roundpatch, bgmpatch                                         # single-round matches, arcade-style BGM
            pal += ([] if "--norounds" in sys.argv else list(roundpatch.patches())) + ([] if "--nobgm" in sys.argv else list(bgmpatch.patches()))
            import padpatch                                                     # default button layout (HP=R1 HK=R2 3P=L1 3K=L2)
            pal += [] if "--nopad" in sys.argv else list(padpatch.patches())
            import diffpatch, balpatch                                          # arcade parity: CPU rank ticker (port bug), round timer 110
            pal += [] if "--norank" in sys.argv else list(diffpatch.rank_patches())   # (CPU tag-rule tuning in diffpatch is NOT applied: not approved)
            pal += [] if "--nobal" in sys.argv else list(balpatch.patches())
            pal += speedpatch.exe_patches()                                     # 1.1 engine speed-ups (upload, quad, frame)
            other = [(a, a + len(d)) for a, d in list(nsppatch.patches()) + list(tagpatch.patches()) + pal] + RESERVED
            _sp = sorted((a, a + len(d)) for a, d in list(nsppatch.patches()) + list(tagpatch.patches()) + pal)
            for (_a0, _b0), (_a1, _b1) in zip(_sp, _sp[1:]):                    # no two EXE patches may share a byte
                assert _b0 <= _a1, f"EXE patches overlap: {_a0:08x}-{_b0:08x} and {_a1:08x}-{_b1:08x}"
            if region.REGION != "us":
                # every module's assembled US patch, re-targeted to this executable (tools/retarget.py); nsppatch and
                # tagpatch are included here because mknspdisc ran with --noexe
                import retarget
                rt = retarget.Retarget(region.REGION, list(nsppatch.patches()) + list(tagpatch.patches()) + pal)
                pal = rt.run()
                open(os.path.join(BUILD, name + "_retarget.txt"), "w").write("\n".join(rt.report) + "\n")
                other = [(a, a + len(d)) for a, d in pal] + [(region.C(a), region.C(a) + (b - a)) for a, b in RESERVED]
                deadcheck([(a, a + len(d)) for a, d in pal if len(d) >= 32] + list(CHUNKS.values()), orig)
            for addr, data in pal:
                exe_write(addr, data)
                print(f"exe patch (palpatch) {addr:08x}-{addr + len(data):08x} {len(data)} bytes")
            for addr, data in pl:
                for lo, hi in other:
                    assert addr + len(data) <= lo or hi <= addr, f"patch {addr:08x} collides with {lo:08x}-{hi:08x}"
            assert struct.unpack("<I", exe_read(HOOK_AT, 4))[0] == HOOK_ORIG
            assert struct.unpack("<I", exe_read(EFFHOOK_AT, 4))[0] == EFFHOOK_ORIG
            assert struct.unpack("<I", exe_read(BOSSHOOK_AT, 4))[0] == BOSSHOOK_ORIG
            import sndpatch
            if sndpatch.enabled():                              # the words the sound patch replaces are still the game's
                for a, (n, w) in sndpatch.STOCK_WORDS.items():
                    b = exe_read(a, n); assert (b == w) if isinstance(w, bytes) else (hashlib.sha1(b).hexdigest() == w), "sound hook %08x" % a
            for addr, data in pl:
                exe_write(addr, data)
                print(f"exe patch {addr:08x}-{addr + len(data):08x} {len(data)} bytes")
            if "--tagpatch14" in sys.argv:                  # baseline: the tag-hook bytes exactly as on build/xvsf_tag14
                with open(os.path.join(BUILD, "xvsf_tag14.bin"), "rb") as t14:
                    for lo, hi in ((0x80016290, 0x800163b8), (0x8007cc9c, 0x8007cca4), (0x8007ceec, 0x8007cef8)):
                        b14 = bytearray()
                        for i in range(hi - lo):
                            o = lo - EXE_BASE + EXE_HDR + i
                            t14.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048); b14 += t14.read(1)
                        exe_write(lo, bytes(b14))
                        print(f"tagpatch as on tag14: {lo:08x}-{hi:08x}")
            for c, (lba, data, label) in enumerate(info):
                nsec = (len(data) + 2047) // 2048
                assert dmy_lba <= lba and lba + nsec <= dmy_lba + dmy_size // 2048
                pad = data + b"\0" * (nsec * 2048 - len(data))
                for i in range(nsec):
                    f.seek((lba + i) * 2352); raw = f.read(2352)
                    assert raw[15] == 2 and not raw[18] & 0x20 and not any(raw[24:2072]), "DMY.DAT sector not empty mode 2 form 1"
                    wr_data(lba + i, 0, pad[i * 2048:(i + 1) * 2048])
                print(f"{label}: {len(data)} bytes at lba {lba}, {nsec} sectors")
            print(f"DMY.DAT sectors used: {info[-1][0] + (len(info[-1][1]) + 2047) // 2048 - dmy_lba} of {dmy_size // 2048}")
        title = [a for a in sys.argv if a == "--title" or a.startswith("--title=")]
        if title:                                           # optional version line on the main menu (NOT in the default build)
            import titlepatch
            titlepatch.apply(f, lmap, exe_read, exe_write, orig, touched, title[0][8:])
        if "--logo" in sys.argv:                            # "PEPA SOFT HOUSE" boot card (NOT in the default build yet)
            import logopatch
            logopatch.apply(exe_read, exe_write, orig)
            if "--nospeed" not in sys.argv and region.REGION == "us":     # 1.1: second card (fan-patch notice, tools/card2patch.py);
                import card2patch                                           # --nospeed keeps the 1.0.x image
                card2patch.apply(exe_read, exe_write, orig, region.FILES)
        EXOPT = "--ex" in sys.argv                          # 1.4: EX OPTIONS + in-battle options (tools/expatch.py)
        VSMENU = "--vsmenu" in sys.argv                     # 1.4 final: VERSUS CPU main-menu row (tools/mtap/mtmenu.h, common/mtap)
        assert not VSMENU or (EXOPT and "--mtap" not in sys.argv and "--vscpu" not in sys.argv), "--vsmenu needs --ex, replaces --mtap / --vscpu"
        if EXOPT:
            assert "--noahead" in sys.argv and "--noskip" not in sys.argv and "--noarcbal" not in sys.argv and not R12() and region.REGION == "us",                 "--ex needs --noahead and the START skip / ARCADE BALANCE module"
            import expatch, skippatch
            expatch.NOFS = "--nofskip" in sys.argv          # 1.4 final: FRAME SKIP row removed, forced OFF (xvex.c EX_NOFS)
            expatch.NOSM = "--nosmeter" in sys.argv         # 1.4 final: SPEED METER row removed (dev/test builds keep it)
            expatch.TRSYNC = "--trsync" in sys.argv or expatch.TRSYNC     # 1.4: attract -> title transition waits for the GPU (stock bug)
            expatch.RDFIX = "--rdfix" in sys.argv or expatch.RDFIX           # 1.4: #15 Raging Demon NOW LOADING hang (stock bug)
            expatch.CARD = "--excard" in sys.argv           # (2026-11-24) EX OPTIONS rows in the game's option save (card image +9)
            if expatch.CARD and expatch.TLTITLE is None and os.environ.get("XV_EXCARD8"):   # (set by tools/mkap8disc.py: 8 MB disc)
                expatch.TLTITLE = symbols()["tl_dbg"] + 13
            if VSMENU:
                sys.path.insert(0, os.path.join(HERE, "mtap")); import xvmtap
                expatch.VSMENU = xvmtap.MENU_J
            sys.path.insert(0, os.path.join(HERE, "speed")); import frame as _frame
            _bal = skippatch.build_c(arcbal=True)[1]["arcbal"]
            ex_sym = expatch.apply(exe_read, exe_write, _bal, symbols()["flushcache"], _frame.symbols()["EBV"])
            skippatch.GAME_FN = ex_sym["ex_logic"]          # FRAME SKIP MAX runs per logic frame (via the skip module's hook)
            assert skippatch.build_c(arcbal=True)[1]["arcbal"] == _bal
        if "--ach" in sys.argv:                             # built-in achievements (tools/ach, docs/ACHIEVEMENTS.md); last: chains pc0
            sys.path.insert(0, os.path.join(HERE, "ach"))
            if "--achfix" in sys.argv:                      # 1.5: "Last One Standing" = win after losing the 1st pick
                os.environ["XVSF_ACHFIX"] = "1"             # (tools/ach/xvsf/set.py; ach audit 2026-11-21)
            import xvach
            if EXOPT: xvach.EX = ex_sym
            xvach.VSMENU = VSMENU
            xvach.INFMETER = "--infmeter" in sys.argv       # 1.4 final: EX OPTIONS row INFINITE SUPER METER (tools/ach/xvsf/port.c)
            assert not xvach.INFMETER or EXOPT, "--infmeter needs --ex --ach"
            xvach.apply(f, lmap, exe_read, exe_write, orig, touched)
        if "--noskip" not in sys.argv and not R12() and region.REGION == "us":     # 1.3: START skips the end of a match
            import skippatch                                                        # (tools/skippatch.py; chains pc0)
            bal = "--noarcbal" not in sys.argv              # 1.3: ARCADE BALANCE option (tools/arcbalpatch.py, docs/BALANCE.md)
            sk = skippatch.apply(exe_read, exe_write, arcbal=bal)
            if bal:
                import arcbalpatch
                arcbalpatch.apply(f, lmap, touched, sk["bal"], optscreen=not EXOPT, card=ex_sym if EXOPT and "--excard" in sys.argv else None)
            assert "--excard" not in sys.argv or (EXOPT and bal), "--excard needs --ex and ARCADE BALANCE"
        if VSMENU:                                          # VERSUS CPU row: vs CPU core (no multitap) in the EXE string block
            sys.path.insert(0, os.path.join(HERE, "mtap")); import xvmtap
            mtc = xvmtap.apply_m(exe_read, exe_write, ex_sym, symbols()["flushcache"])
        if "--mtap" in sys.argv:                            # 1.4: multitap 2-4 players (tools/mtap/xvmtap.py, common/mtap; EXE
            sys.path.insert(0, os.path.join(HERE, "mtap"))  # debug-string block only, checks every word it replaces is stock)
            import xvmtap
            if "--vscpu" not in sys.argv:
                xvmtap.apply(exe_read, exe_write)
            else:                                           # (vs cpu lead) VERSUS vs CPU seats: + a longer SELECT.BIN copy with
                mtc = xvmtap.apply_v(exe_read, exe_write)   # the select module, in the free tail of DMY.DAT; entry 1 -> it
        if VSMENU or ("--mtap" in sys.argv and "--vscpu" in sys.argv):
                sys.path.insert(0, os.path.join(HERE, "mtap")); import xvmtap
                ent = exe_read(xvmtap.FTAB_SELECT, 8)
                bcd = lambda b: (b >> 4) * 10 + (b & 15)
                lba_s = (bcd(ent[0]) * 60 + bcd(ent[1])) * 75 + bcd(ent[2]) - 150
                size_s = struct.unpack_from("<I", ent, 4)[0]
                assert size_s == xvmtap.SEL_SIZE, "vscpu: SELECT.BIN size %d" % size_s
                sel = b"".join((f.seek((lba_s + i) * 2352 + 24), f.read(2048))[1] for i in range((size_s + 2047) // 2048))[:size_s]
                cp = xvmtap.select_copy_m(sel, mtc) if VSMENU else xvmtap.select_copy(sel, mtc)
                nsec = (len(cp) + 2047) // 2048
                lba_c = dmy_lba + dmy_size // 2048 - nsec  # the tail of DMY.DAT (the hack's items fill it from the front)
                assert info and info[-1][0] + (len(info[-1][1]) + 2047) // 2048 <= lba_c, "vscpu: DMY.DAT tail not free"
                pad = cp + bytes(nsec * 2048 - len(cp))
                for i in range(nsec):
                    f.seek((lba_c + i) * 2352); raw = f.read(2352)
                    assert raw[15] == 2 and not raw[18] & 0x20 and not any(raw[24:2072]), "vscpu: DMY.DAT sector not empty"
                    wr_data(lba_c + i, 0, pad[i * 2048:(i + 1) * 2048])
                exe_write(xvmtap.FTAB_SELECT, msf(lba_c) + struct.pack("<I", len(cp)))
                print(f"vscpu: SELECT.BIN copy {len(cp)} B (module {len(mtc['ovl'][1])} B at {xvmtap.SEL_END:08x}) at lba {lba_c}, {nsec} sectors")
        if "--meter" in sys.argv:                           # TEST BUILDS ONLY: on-screen speed meter (tools/meterpatch.py)
            import meterpatch
            meterpatch.apply(exe_read, exe_write)
        for sec in sorted(touched):
            f.seek(sec * 2352); raw = bytearray(f.read(2352))
            fix_sector(raw)
            f.seek(sec * 2352); f.write(raw)
    print(f"touched {len(touched)} more sectors -> {out}")
    if "--chd" in sys.argv:
        subprocess.check_call([CHDMAN, "createcd", "-i", os.path.join(BUILD, name + ".cue"), "-o", os.path.join(BUILD, name + ".chd"), "-f"], stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
