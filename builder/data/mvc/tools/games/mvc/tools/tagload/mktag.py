"""Build the MvC tag-hack disc (SLUS-01059).

    python mktag.py [name] [--chd] [--ram] [--ach]      -> games/mvc/build/<name>.bin/.cue (+ .chd, + <name>.patches.json)
    --ach: built-in achievements (games/mvc/tools/ach, docs/ACHIEVEMENTS.md); without it the output is unchanged

Copies disc/mvc.bin and changes it in place (same file positions, same sizes):
  * DMY1.DAT (37 MB of padding at the end of the disc, never read) gets the new data: the loader blob, then per
    character the A0 item (header + code + kind-6 set of PLxx_10.A0, followed by its relocation table,
    tools/reloc.py) and the sprite files of every tier (games/mvc/work/dsp/<tier>/PLxx_10.DSP; "rle" = the stock
    DSP part of PLxx_10.A0).
  * SLUS_010.59: loader glue + hooks (this directory), gameplay switch + assist gate (tools/gameplay), DSM1 decoder
    (common/dsp/dsmpatch.py).
EDC/ECC of every changed sector is recomputed.  --ram: build the blob and the patches only (emulator tests).
"""
import os, sys, struct, shutil, subprocess, json, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [HERE, os.path.join(GAME, "tools"), os.path.join(GAME, "tools", "gameplay"), os.path.join(GAME, "tools", "speed"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "common", "dsp")]



def opt_init():
    """0x800858c8 ASSIST_GATE + the 3 option bytes (optrows): zero; TEST discs only: env OPT_INIT="0x800858c9=2,..."
    (e.g. STAGE ANIM OFF forced at power-on; the menu still changes it)"""
    b = bytearray(4)
    if "--introsimple" in sys.argv and "--introopt" in sys.argv:   # rc4.1 (hw worker): INTRO power-on value 1 = SIMPLE
        sys.path.insert(0, os.path.join(GAME, "tools", "hwprof")); import nointro   # (fx worker's EX OPTIONS byte map:
        k = nointro.intro_byte(); assert 0x800858c9 <= k <= 0x800858cb; b[k - 0x800858c8] = 1   # 0 STOCK / 1 SIMPLE)
    for kv in filter(None, os.environ.get("OPT_INIT", "").split(",")):
        k, v = kv.split("="); k = int(k, 16)
        assert 0x800858c9 <= k <= 0x800858cb, k
        b[k - 0x800858c8] = int(v)
    return bytes(b)

def exopt_exe():
    """--exopt: the EX OPTIONS value block (SPEED METER, ACHIEVEMENT POPUP, ...) zeroed in the EXE (gameplay/exopt.py)"""
    if "--exopt" not in sys.argv: return []
    sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import exopt
    p = exopt.exe_patches()
    if os.environ.get("VQ_INIT"):                   # (voice 2) TEST discs only: VOICE QUALITY power-on value (block +7)
        q = 0x80011763
        p = [(a, (d[:q - a] + bytes([int(os.environ["VQ_INIT"])]) + d[q - a + 1:]) if a <= q < a + len(d) else d) for a, d in p]
        assert any(a <= q < a + len(d) for a, d in p)
    if "--ldbuf" in sys.argv:                       # rc4.10: LDBUF_W (block +8) = stock buffer address (gameplay/ldbuf.py)
        import ldbuf
        p = [(a, (d[:ldbuf.LDBUF_W - a] + ldbuf.init_word(LDBUF_VAL) + d[ldbuf.LDBUF_W - a + 4:]) if a <= ldbuf.LDBUF_W < a + len(d) else d)
             for a, d in p]
        assert any(a <= ldbuf.LDBUF_W < a + len(d) for a, d in p), "--ldbuf: EX block patch not found"
    return p

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); return m


reloc = _load("mvc_reloc", os.path.join(GAME, "tools", "reloc.py"))
import toolenv
from mkdisc import fix_sector
from iso import Disc
import tagmode, assist
import nozoom
sys.path.insert(0, os.path.join(GAME, "tools", "snd"))
import sndbuild                                  # full sound banks for every character (games/mvc/tools/snd)
SND_PATCHES, SND_IMAGE = [], b""
fxeng = _load("fxeng", os.path.join(GAME, "tools", "fxhalf", "fxeng.py"))
import meter as metermod


def _frozen_dsmpatch():
    """common/dsp/dsmpatch.py + dsmdec.S as committed (git HEAD): the codec worker edits the working copies"""
    o = os.path.join(GAME, "work", "tagload", "dsm_head")
    os.makedirs(o, exist_ok=True)
    for f in ("dsmpatch.py", "dsmdec.S"):
        open(os.path.join(o, f), "wb").write(subprocess.check_output(["git", "show", "HEAD:common/dsp/" + f], cwd=ROOT))
    m = _load("dsmpatch_head", os.path.join(o, "dsmpatch.py"))
    m.SRC = os.path.join(o, "dsmdec.S"); m.OBJ = o; m.ROOT = ROOT
    return m


dsmpatch = _frozen_dsmpatch() if "--frozendsm" in sys.argv else _load("dsmpatch", os.path.join(ROOT, "common", "dsp", "dsmpatch.py"))
USE_DSH = "--nodsh" not in sys.argv and "--frozendsm" not in sys.argv
# tiers named dsx* (dsx, dsx_hot16, ..): the dsh* file of the same suffix converted while it is read (common/dsp/dsx.py:
# 4-bit lookup table per Huffman table, +2.4-3.8 KB per character, ~27 % fewer decode cycles per byte); a tier list
# with any dsx tier loads the unified RAM decoder dsxdec.S (work/dsp/dsx/dsxdec.bin: plain DSH1 and DSX files)
dsxmod = _load("dsx", os.path.join(ROOT, "common", "dsp", "dsx.py"))

GCC = toolenv.mips_prefix()
CF = ["-mips1", "-G0", "-mno-abicalls", "-fno-pic"]
SRC_BIN = os.path.join(GAME, "disc", "mvc.bin")


def _stock_exe():
    """the stock executable from the user's disc (--excard: its spans must still be stock)"""
    d = Disc(SRC_BIN)
    return d.read(*lba_map()["SLUS_010.59"])

FILES = os.path.join(GAME, "work", "dsp", "files")
DSPW = os.path.join(GAME, "work", "dsp")
# --fx: option B (games/mvc/tools/fxhalf): sprite tiers of the half-res-effect DSPs (shadow tree of fxhalf.py /
# enc_all.sh) + the engine patches of fxhalf/fxeng.py; characters without a shadow file keep the stock tiers
FX = "--fx" in sys.argv
# --fxchars=01,03,..: option B only for these characters (per-character roll-back); default: every shadow file
FXC = next((set(int(v, 16) for v in a.split("=", 1)[1].split(",") if v) for a in sys.argv if a.startswith("--fxchars=")), None)
FXW = os.environ.get("MVC_FXW") or os.path.join(GAME, "work", "fxhalf", "root", "games", "mvc", "work", "dsp")   # MVC_FXW: experiment shadow trees
BUILD = os.path.join(GAME, "build")
EXE_BASE, EXE_HDR = 0x80010000, 0x800
ARENA = 0x80092c40
LDBUF_VAL = None                    # rc4.10 --ldbuf: set from the blob before exe_patches
HOOK = 0x8002b950
HOOK_ORIG = (0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~)
QUICKLOAD_AT, QUICKLOAD_ORIG = 0x80045e80, 0x14620024    # see exe_patches
HEAPHOOK, HEAPHOOK_ORIG = 0x8002b528, 0x0c008673            # jal 0x800219cc
TAUNT_SB, TAUNT_SB_ORIG = 0x80024988, 0xa142be49           # sb v0, -0x41b7(t2) (--notaunt -> nop)
CHARS = list(range(1, 0x17))                         # 0x11 Onslaught: P2 main only (boss)
NT, NF, NFR = 13, 6, 32
# sprite tiers, smallest first; tier 0 must exist for every character.  cost = play-weighted cycles/byte x 10
# (games/mshvsf/docs/DSP.md MvC rows; replaced by work/dsp/tiercost.json when present)
TIERS = ["dsa_cut16", "dsa_cut8", "dsa_cut4", "dsa", "dsa_hot32", "dsh", "dsh_hot8", "dsh_hot16", "dsh_hot32", "dsm",
         "dsm_hot64", "rle"]
_ts = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tiers=")), None)
if _ts:                                          # calibration / policy builds: only these tiers (first = floor)
    TIERS = _ts.split(",")
KOSPLIT = "--kosplit" in sys.argv                # dx 2026-11-19: the KO item = the last 2 DMY1.DAT sectors read to KOSPLIT_AT:
KOSPLIT_AT = 0x8000E840                          # [pal8 code + table @E840][kocache @F040 (the meter's fixed call), whole sector]


def p8_at(kocache):
    """pal8's code address: after the KO code (one shared sector) or, with --kosplit, its own sector at KOSPLIT_AT"""
    return KOSPLIT_AT if KOSPLIT else kocache.KO_AT + kocache.SIZE


DSR = "--dsr" in sys.argv                        # CPU worker 2026-11-19: DSR1 codec (tools/codec2) in the DSA1 slot
DSR_RATIO = 0.57                                 # play-weighted cycles DSR1 / DSA1, heavy team (dsrtest.py, decoder v3)
COST = {"dsx": 600, "dsx_hot16": 450, "dsa": 5800, "dsa_hot32": 1600, "dsa_hot64": 900, "dsh": 800, "dsh_hot4": 600, "dsh_hot8": 500, "dsh_hot16": 400, "dsh_hot32": 300, "dsm": 330, "dsm_hot16": 220, "dsm_hot32": 175, "dsm_hot64": 120, "rle": 81}
# DSM1 decoder units: the free list of common/dsp/dsmpatch.py GAMES["mvc"] holds ranges that are live code
# (0x80022474.. called from BG09.ARC / END.ARC) or used by the gameplay stub; until it is fixed there, place the
# units in these (tools/tagload/refscan.py: no reference from the EXE or any disc file)
DSM_FREE = [(0x8001a874, 0x8001a96c), (0x8001409c, 0x80014128), (0x800125f0, 0x80012670), (0x80019160, 0x8001924c),
            (0x8002fa78, 0x8002fafc)]      # order matters: first fit, units branch to each other (+-128 KB)


def fecache_header():
    """fecache.S (decoded-tile cache front end) -> fecache.h: u32 fe_code[], FE_DSH, FE_DSA (position-independent:
    assembled at two addresses, must be equal; load-delay hazards checked)"""
    dl = _load("dlib", os.path.join(ROOT, "tools", "speed", "decode", "dlib.py"))
    a, sa = dl.assemble(os.path.join(HERE, "fecache.S"), 0x80100000, outdir=os.path.join(GAME, "work", "tagload"))
    b, _ = dl.assemble(os.path.join(HERE, "fecache.S"), 0x80200000, outdir=os.path.join(GAME, "work", "tagload"))
    assert a == b and len(a) <= 0x200 and len(a) % 4 == 0, "fecache.S: not position-independent or too big"
    bad = dl.hazards(a, 0x80100000)
    assert not bad, "fecache.S load-delay hazards: " + "; ".join(bad)
    w = struct.unpack("<%dI" % (len(a) // 4), a)
    nl = chr(10)
    open(os.path.join(HERE, "fecache.h"), "w").write(
        "/* generated by mktag.py from fecache.S */" + nl + "static const u32 fe_code[%d] = {" % len(w) + nl
        + "".join("0x%08x,%s" % (x, nl if i % 8 == 7 else " ") for i, x in enumerate(w))
        + "};" + nl + "#define FE_DSH 0x%x" % (sa["fe_dsh"] - 0x80100000) + nl + "#define FE_DSA 0x%x" % (sa["fe_dsa"] - 0x80100000) + nl)


def build_blob():
    fecache_header()
    defs = ([] if "--nostagefrag" in sys.argv and "--exefrag" not in sys.argv else ["-DFRAGS"]) + (["-DFECACHE"] if "--cache" in sys.argv else [])
    if "--bgfast" in sys.argv:                              # tools/tagload/bgfast.py: incremental stage-BG rebuild
        import bgfast
        dl, ds = lba_map()["DMY1.DAT"]                      # engine = the last sector of DMY1.DAT (main() keeps it free)
        open(os.path.join(HERE, "bgfast.h"), "w").write(bgfast.header(struct.unpack("<I", msf(dl + ds // 2048 - 1))[0]))
        defs.append("-DBGFAST")
    if "--kocache" in sys.argv:                             # tools/tagload/kocache.py: free-on-KO tile cache
        import kocache                                      # code = the second-last sector of DMY1.DAT, read to 0x801fe000
        dl, ds = lba_map()["DMY1.DAT"]
        open(os.path.join(HERE, "kocache.h"), "w").write(kocache.header(struct.unpack("<I", msf(dl + ds // 2048 - 2))[0]))
        defs.append("-DKOCACHE")
        if "--pal8" in sys.argv:                            # tools/gameplay/pal8.py: stage-8 palette rows in VRAM
            import pal8                                     # (code after the KO code in the same sector)
            c8, s8 = pal8.code(p8_at(kocache), 0x80000000)
            if KOSPLIT: assert len(c8) <= 2048
            else: assert kocache.KO_AT + kocache.SIZE + len(c8) <= 0x8000F840
            open(os.path.join(HERE, "kocache.h"), "a").write(
                "#undef KO_SIZE\n#define KO_SIZE %d\n#define P8UP 0x%08xu\n#define P8MV 0x%08xu\n#define P8HC 0x%08xu\n"
                "#define P8BUF 0x801fc000u\n#define P8FADE 0x%08xu\n#define P8HSITE 0x%08xu\n#define P8AP 0x%08xu\n#define P8APSITE 0x%08xu\n"
                % (kocache.SIZE + len(c8), s8["P8UP"], s8["P8MV"], s8["P8HC"], pal8.FADESITE, pal8.HSITE, s8["P8AP"], pal8.APSITE))
            defs.append("-DPAL8")
        if KOSPLIT:                                         # dx 2026-11-19: KO item = 2 sectors read to KOSPLIT_AT (pal8, kocache)
            open(os.path.join(HERE, "kocache.h"), "a").write("#undef KO_SIZE\n#define KO_SIZE 4096\n#define KO_RD 0x%08xu\n" % KOSPLIT_AT)
    if "--spswait" in sys.argv: defs.append("-DSPSWAIT")   # rc4.8 tester: hardware wait after the SPU store uploads
    if "--xplan" in sys.argv: defs.append("-DXPLAN")      # fx worker: monotone exact tier planner (tools/speed5/planx.py)
    if "--l2g" in sys.argv:                                 # fx worker, rc4 L2: packed frame groups (games/mvc/tools/l2)
        sys.path.insert(0, os.path.join(GAME, "tools", "l2")); import g2get
        code_, sym_ = g2get.build(0x80000000)                  # position independent; installed 128-aligned
        assert len(code_) % 4 == 0
        w_ = struct.unpack("<%dI" % (len(code_) // 4), code_)
        open(os.path.join(HERE, "l2g.h"), "w").write(
            "#define L2G_N %d" % len(w_) + chr(10) + "#define L2G_RAM %du" % g2get.RAMSIZE + chr(10)
            + "#define L2G_ENTRY 0x%xu" % (sym_["g2get"] - 0x80000000) + chr(10)
            + "static const u32 l2g_img[L2G_N] = {" + chr(10) + ("," + chr(10)).join("0x%08xu" % x for x in w_) + chr(10) + "};" + chr(10))
        defs.append("-DL2G")
        if "--l2pc" in sys.argv:                            # fx worker, rc4 per-character L2: unpacked alternates, per-slot pick
            assert "--dirx" in sys.argv, "--l2pc needs --dirx (alternates in the directory item)"
            defs.append("-DL2PC")
            for a_ in sys.argv:
                if a_.startswith("--l2pcmin="): defs.append("-DL2PC_MIN=%du" % int(a_.split("=", 1)[1]))
            if "--l2pcdbg" in sys.argv: defs.append("-DL2PCDBG")   # TEST builds: planner costs to 0x8000ce00 (Beetle)
    if "--hookgate" in sys.argv:                            # freeze worker, rc4 hook-lifecycle audit (hookgate.py): L2 / L1b /
        import hookgate                                     # vcache sites through a kernel gate (battle scene + tag data + image intact)
        open(os.path.join(HERE, "hookgate.h"), "w").write(hookgate.header())
        defs.append("-DHOOKGATE")
    if HRFX:                                                # memory worker, rc4.2 HI-RES FX (AUTO / OFF row)
        assert "--dirx" in sys.argv and ("--spsnostore" in sys.argv or "--spustore" not in sys.argv), "--hrfx needs --dirx, no SPU store"
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import optrows as _orw
        hb = int(os.environ["HRFX_BYTE"], 0) if os.environ.get("HRFX_BYTE") else _orw.byte("HI-RES FX")   # env: TEST builds
        defs += ["-DHRFX", "-DHRFX_BYTE=0x%08xu" % hb]
    if L1B:                                                 # memory worker, rc4 L1b: sec3 offset remap (tools/sec3/l1b.py)
        sys.path.insert(0, os.path.join(GAME, "tools", "sec3")); import l1b as L1
        code_, sym_ = L1.build(0x80000000)                     # position independent
        w_ = struct.unpack("<%dI" % (len(code_) // 4), code_)
        open(os.path.join(HERE, "l1b.h"), "w").write(
            "#define L1B_N %d" % len(w_) + chr(10) + "#define L1B_SITE0 0x%08xu" % L1.SITES[0] + chr(10)
            + "#define L1B_SITE1 0x%08xu" % L1.SITES[1] + chr(10)
            + "static const u32 l1b_img[L1B_N] = {" + chr(10) + ("," + chr(10)).join("0x%08xu" % x for x in w_) + chr(10) + "};" + chr(10))
        defs.append("-DL1B")
    if "--cutguard" in sys.argv:                            # integrator: super cut-in vs --postvc SPVC (cutguard.py)
        import cutguard
        open(os.path.join(HERE, "cutguard.h"), "w").write(cutguard.header())
        defs.append("-DCUTGUARD")
    if "--cutinfix" in sys.argv:                            # memory worker, rc3: banded super cut-in (tools/sec3/cutinfix.py)
        sys.path.insert(0, os.path.join(GAME, "tools", "sec3")); import cutinfix as CI
        code_, sym_ = CI.build(0x80000000)                     # position independent
        w_ = struct.unpack("<%dI" % (len(code_) // 4), code_)
        open(os.path.join(HERE, "cutin.h"), "w").write(
            "#define CUTIN_N %d" % len(w_) + chr(10) + "#define CUTIN_SITE_DEC 0x%08xu" % CI.SITE_DEC + chr(10)
            + "#define CUTIN_SITE_LI 0x%08xu" % CI.SITE_LI + chr(10) + "#define CUTIN_W_DEC 0x%08xu" % CI.W_DEC + chr(10)
            + "#define CUTIN_W_LI 0x%08xu" % CI.W_LI + chr(10)
            + "static const u32 cutin_img[CUTIN_N] = {" + chr(10) + ("," + chr(10)).join("0x%08xu" % x for x in w_) + chr(10) + "};" + chr(10))
        defs.append("-DCUTIN")
    if "--chk" in sys.argv:                                 # fx worker: checker tile form (tools/speed5/chkrt.py, chkform.py)
        assert "--upskip" not in sys.argv, "--chk and --upskip hook the same site"
        sys.path.insert(0, os.path.join(GAME, "tools", "speed5")); import chkrt
        open(os.path.join(HERE, "chkrt.h"), "w").write(chkrt.header())
        defs.append("-DCHK")
    if "--stageanim" in sys.argv:                           # tools/gameplay/stageanim.py: tl_main clears the RAM part's magic
        import stageanim
        defs += ["-DSTAGEANIM", "-DSTAGEANIM_SA=0x%08xu" % stageanim.SA]
    if "--upskip" in sys.argv:                              # tools/tagload/upskip.py: redundant tile-upload skip
        import upskip
        dl, ds = lba_map()["DMY1.DAT"]                      # code = the second-last sector of DMY1.DAT
        open(os.path.join(HERE, "upskip.h"), "w").write(upskip.header(struct.unpack("<I", msf(dl + ds // 2048 - 2))[0]))
        defs.append("-DUPSKIP")
    if "--dirx" in sys.argv: defs.append("-DDIRX")         # dx worker: full directory as a disc item (blob space)
    if "--assisttest" in sys.argv: defs.append("-DASSIST_TESTKEEP")   # assists lead: TEST builds only (tl_main keeps P2 assist bit)
    if "--assist" in sys.argv:                              # assists lead (rc4.4): special-partner assists in tag battles
        assert "--spustore" in sys.argv and "--spsnostore" not in sys.argv and "--dirx" in sys.argv and not HRFX, \
            "--assist needs the live SPU store (--spustore without --spsnostore) and --dirx, and excludes --hrfx"
        defs.append("-DASSIST")
        assert TIERS.index("dsh_cut48") == 2, "tagload.c AS_TMIN = 2 assumes dsh_cut48 at tier index 2"
        if os.environ.get("AS_DBG"): defs.append("-DAS_DBG")
        if os.environ.get("ONS_DBG"): defs.append("-DONS_DBG")   # (rc4.15) TEST builds: Onslaught plan vs load at 0x8000C900   # TEST builds: as_search trace at 0x8000C800 (Beetle only)
    if "--strongx" in sys.argv: defs.append("-DSTRONGX")    # assists lead: the strong payload as a disc item (blob space)
    if "--ashud" in sys.argv:                               # assist bugs lead: HUD assist portrait upload (tagload.c AS_HUD)
        assert "--assist" in sys.argv and "--fs05" in sys.argv   # + EXE words (tools/gameplay/ashud.py)
        defs.append("-DASHUD")
    if "--onslp1" in sys.argv:                              # assist bugs lead: ARCADE with the human on P2 -> the CPU boss
                                                            # Onslaught is the P1 main; the loader declined it (0xfc) and
        assert not any(x.startswith("--force") for x in sys.argv), "--onslp1 drops the --force team block (blob space)"
        defs.append("-DONSLP1")                             # the stock fallback hung on NOW LOADING (tagload.c ONSLP1 +
                                                            # EXE word gameplay/onslp1.py)
    if "--sxfix" in sys.argv and "--onsl" not in sys.argv: defs.append("-DSXFIX")   # arcade-boss Onslaught battles too (onslaught 2026-11-22)
    if "--onsl" in sys.argv:                                # playable Onslaught prototype (tagload.c ONSL, gameplay/onsl.py)
        assert not any(x.startswith("--force") for x in sys.argv), "--onsl drops the --force team block (blob: +232 B over)"
        defs.append("-DSXFIX")                              # strong-payload read vs Onslaught region top (tagload.c SXFIX)
        defs.append("-DONSL")                               # (includes --onslp1's loader rules + EXE word)
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import onsl
        defs.append("-DONSL_TO=%du" % len(onsl.to_stub()))  # time-over stub length (it ends at the giant-form block)
    if "--ldbuf" in sys.argv: defs.append("-DLDBUF")        # rc4.10: loading-screen winner prim buffer (tagload.c LDBUF, ldbuf.py)
    if "--asarc" in sys.argv:                               # assist bugs lead: ARCADE assists when START skips the VS screen
        assert "--assist" in sys.argv and "--assistsel" in sys.argv
        defs.append("-DASARC")
    if "--asps3" in sys.argv:                                # PS2/PS3 ROM: no assists -> no SPU store (tagload.c)
        assert "--assist" in sys.argv and "--asrow1" in sys.argv
        defs.append("-DASPS3")
    if ASRLE:                                               # asdip lead (rc4.6): assist RLE tier with its streams in SPU
        assert "--assist" in sys.argv and "--spsfix" in sys.argv
        defs.append("-DASRLE"); defs.append("-DSPS_ITEM")
    if "--asgov" in sys.argv:                               # asdip lead (rc4.7): assist draw governor (spsfe.py GOV),
        assert ASRLE and "--dxahead" in sys.argv          # in the front-end disc item; needs dxahead's vblank stamp
        defs.append("-DASGOV")
    if "--kofix" in sys.argv:                               # hwfix: kocache read-back of store slots + CHK image item
        assert "--chk" in sys.argv and "--kocache" in sys.argv and "--strongx" in sys.argv
        defs.append("-DKOFIX")
    if "--asside" in sys.argv:                              # asdip lead (rc4.7): assist tier per side
        assert ASRLE, "--asside needs --asrle"
        defs.append("-DASSIDE")
        # tier probe voice floor: the fastest assist tier that fits at ANY ladder level (user: voice drop allowed with
        # assists, speed first); then the voice search climbs back to the best level for that tier (tagload.c as_plan)
        defs.append("-DAS_LVF=%d" % int(os.environ.get("AS_LVF", sndbuild.S.NL - 1)))
        if "--voicevol" in sys.argv:                        # (voice 3) data + snd.c VOLROW (tools/snd); exclusive with --voicehi
            assert "--voicehq" in sys.argv and "--exopt" in sys.argv and "--voicehi" not in sys.argv
        if "--voicehi" in sys.argv:                         # (voice 2) EX row VOICE QUALITY NORMAL / HIGH (tagload.c VOICEHI)
            assert "--exopt" in sys.argv
            defs.append("-DVOICEHI")
            if os.environ.get("VQ_LVF"): defs.append("-DVQ_LVF=%d" % int(os.environ["VQ_LVF"]))
        if os.environ.get("VHQ_SH"):                        # (voice) test knob: voice search cost slack kt >> VHQ_SH
            defs.append("-DVHQ_SH=%d" % int(os.environ["VHQ_SH"]))
    if SPS:                                                 # tools/spustore: SPU store front end + loader part
        sys.path.insert(0, os.path.join(GAME, "tools", "spustore"))
        import spsfe
        spsfe.header(os.path.join(HERE, "spsfe.h"), fix="--spsfix" in sys.argv, rle=rle_entry() if ASRLE else None,
                     gov="--asgov" in sys.argv, guard="--spsguard" in sys.argv)
        defs.append("-DSPUSTORE")
        if os.environ.get("SPS_NOTAIL") == "1": defs.append("-DSPS_NOTAIL")
        if "--spsdrain" in sys.argv: defs.append("-DSPSDRAIN")   # (2026-11-25) MiSTer SPU write-FIFO drain waits
        if "--spspad" in sys.argv: defs.append("-DSPSPAD")      # (2026-11-25) MiSTer SPU upload tail loss: 128 B pads   # (2026-11-25 MiSTer test) no reverb-area span
        if "--spsfix" in sys.argv: defs.append("-DSPS_FIX")   # rc4: no fetch during loads / own SPU DMA (ending freeze)
        if os.environ.get("SPS_NOSTORE") or "--spsnostore" in sys.argv:   # --spustore built (SNDX: sound table off the blob)
            defs.append("-DSPS_NOSTORE")                                  # but the store never used (rc3: Onslaught ending hang)
    if "--share" in sys.argv:                               # fx worker: store-once sprite pairs (tools/speed5/pairs.py)
        assert "--dirx" in sys.argv, "--share needs --dirx (pair entries live in the full directory item)"
        defs.append("-DSHARE")
    if "--dxahead" in sys.argv:                             # tools/speed4/dxahead.py: decode-ahead (dx worker)
        sys.path.insert(0, os.path.join(GAME, "tools", "speed4"))
        import dxahead
        dl, ds = lba_map()["DMY1.DAT"]                      # code = the third-last sector of DMY1.DAT
        open(os.path.join(HERE, "dxahead.h"), "w").write(dxahead.header(struct.unpack("<I", msf(dl + ds // 2048 - 3))[0],
                                                                       struct.unpack("<I", msf(dl + ds // 2048 - 4))[0], 0x8001b4e0,
                                                                       struct.unpack("<I", msf(dl + ds // 2048 - 5))[0]))
        defs.append("-DDXAHEAD")
    gdefs = []
    if "--koreload" in sys.argv:                            # tools/koreload: KO reload resident image (memory worker)
        assert "--kocache" in sys.argv and "--nostagefrag" in sys.argv and "--exefrag" not in sys.argv, "--koreload needs --kocache, no fragments"
        sys.path.insert(0, os.path.join(GAME, "tools", "koreload"))
        import build as krlb, kocache as kc_
        kimg, ksym = krlb.image()
        w_ = struct.unpack("<%dI" % (len(kimg) // 4), kimg)
        NL = chr(10)
        rows = ("," + NL).join(", ".join("0x%08xu" % x for x in w_[i:i + 6]) for i in range(0, len(w_), 6))
        open(os.path.join(HERE, "krl.h"), "w").write(NL.join([
            "#define KRL_AT 0x%08xu" % krlb.AT, "#define KRL_SIZE 0x%xu" % krlb.SIZE, "#define KRL_D 0x%08xu" % ksym["krl_d"],
            "#define KRL_KD 0x%08xu" % kc_.build()[1]["KD"], ""]))
        global KRL_IMG
        KRL_IMG = kimg
        defs += ["-DKORELOAD", "-I" + os.path.join(GAME, "tools", "koreload")]
    if "--vcache" in sys.argv:                              # tools/vcache2/vcache.py: VRAM tile cache (ex-memory worker)
        assert "--cache" not in sys.argv, "--vcache and --cache share CACHE"
        sys.path.insert(0, os.path.join(GAME, "tools", "vcache2"))
        import vcache
        assert vcache.STRONG_AT == metermod.STRONG_AT
        if "--pal8" in sys.argv:                            # stage 8 + pal8: only the VRAM remainder (vc4 table 1)
            vcache.vc3.P8AT = pal8.code(p8_at(kocache), 0x80000000)[1]["P8"]
        vcache.header(HERE)                                 # vcache.h: image for tl_main
        defs.append("-DVCACHE")
        if os.environ.get("VC_GATE"): defs.append("-DVCGATE")     # TEST builds: no cache when a tier drops to DSA1
        if os.environ.get("VC_P8SMALL"): defs.append("-DVCP8SMALL")  # TEST builds: pal8 + the 4 KB VRAM remainder on stage 8
    for c in ("gcc -Os -ffreestanding -msoft-float -Wall -c tagload.c -o tagload.o " + " ".join(defs), "gcc -c glue.S -o glue.o " + " ".join(gdefs)):
        p = c.split(); subprocess.check_call([GCC + p[0]] + CF + p[1:], cwd=HERE)
    sndbuild.objects(GCC, CF, HERE)                         # games/mvc/tools/snd (full sound banks)
    subprocess.check_call([GCC + "ld", "-T", "link.ld", "glue.o", "tagload.o", "snd.o", "-o", "tagload.elf"], cwd=HERE)
    for sec in (".g1", ".g2", ".res", ".rh", ".hg", ".blob", ".post"):
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "tagload.elf", "tagload" + sec + ".bin"], cwd=HERE)
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", "tagload.elf"], cwd=HERE).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    rd = lambda s: open(os.path.join(HERE, "tagload" + s + ".bin"), "rb").read()
    glue = [(0x8002547c, rd(".g1")), (0x8001780c, rd(".g2")), (0x800858b0, rd(".hg"))]
    assert sym["hcguard"] == 0x800858b0 and sym["hg_end"] <= 0x800858c8, ".hg outside its range"
    res, blob = rd(".res"), rd(".blob")
    glue.append((0x80014774, rd(".rh")))                    # restore hook (patched in only with fragments)
    assert sym["rhook"] == 0x80014774 and sym["rh_end"] <= 0x800147dc, ".rh outside its range"
    assert sym["glue"] == 0x8002547c and sym["g1_end"] <= 0x80025540, ".g1 outside its range"
    assert sym["gl_sum"] == 0x8001780c and sym["g2_end"] <= 0x800178b4, ".g2 outside its range"
    assert sym["flushcache"] == 0x8001b454 and sym["res_end"] <= 0x8001b4fc, ".res outside its range"
    assert blob[:4] == struct.pack("<I", 0x08000000 | ((sym["tl_wrap"] >> 2) & 0x3FFFFFF))
    global POST
    POST = rd(".post"); assert len(POST) == sym["post_end"] - sym["post"]
    assert ARENA + len(blob) + 4096 < 0x8009dfcc
    return glue, res, blob, sym


def msf(lba):
    b = lambda x: (x // 10) << 4 | x % 10
    l = lba + 150
    return bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 0])


def a0_parts(c):
    """-> (file, [(off, size)] of code, DSP, kind-6 set, [Onslaught: giant-form block]) """
    a = open(os.path.join(FILES, f"PL{c:02X}_10.A0"), "rb").read()
    n, = struct.unpack_from("<I", a); assert n in (3, 4)
    s = [struct.unpack_from("<2I", a, 4 + 8 * i) for i in range(n)]
    assert s[0][0] == 4 + 8 * n
    if n == 4:                                   # Onslaught: code, DSP, block, set -> code, DSP, set, block
        s = [s[0], s[1], s[3], s[2]]
    return a, s


def a0_item(c):
    """-> (item bytes, a0size, setoff, setsize, kept, spu, forbidden list, hdr, xoff)
    item = header (hdr bytes) + code + [Onslaught: giant-form block] + kind-6 set; then the relocation table"""
    a, s = a0_parts(c)
    H = s[0][0]                                              # 0x1c, Onslaught 0x24
    code = a[H:H + s[0][1]]
    code0 = len(code)
    NI = None
    if any(a_.startswith("--nointro") for a_ in sys.argv):   # INTRO STOCK / SIMPLE (tools/hwprof/nointro.py, table-driven)
        sys.path.insert(0, os.path.join(GAME, "tools", "hwprof")); import nointro
        NI, NI_FN = nointro.mode(), nointro.FN
        if c in NI_FN:                                    # ground routine appended to the code item (no 4th section)
            assert len(s) == 3
            code += bytes(-len(code) % 4); ni_off = len(code); code += nointro.appendix(c, NI["cand"])
    if c == 0x11 and "--onsl" in sys.argv:           # playable Onslaught: time-over stub appended so that it ENDS at the
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import onsl   # giant-form block (xoff); the loader
        code += bytes(-(H + len(code)) % 8) + onsl.to_stub()                        # hooks 0x8004b694 to F + xoff - len
    st = a[s[2][0]:s[2][0] + s[2][1]]
    blk = a[s[3][0]:s[3][0] + s[3][1]] if len(s) == 4 else b""
    xoff = 0
    body = bytes(H) + code
    if blk:
        body += bytes(-len(body) % 8); xoff = len(body); body += blk
    setoff = len(body); setoff += -setoff % 4
    if setoff % 8 != 4: setoff += 4                          # F = 4 mod 8 (P 8-aligned) -> set 8-aligned
    body = struct.pack("<7I", 3, H, len(code), xoff, len(blk), setoff, len(st)) + bytes(H - 0x1c) + body[H:]
    body += bytes(setoff - len(body))
    partA = body
    partB = st + bytes(-len(st) % 4)
    body = body + partB
    r = reloc.get(c)
    assert r.end == H + code0 and not r.unpaired
    tab = r.table()
    # check the C model of the relocation on this item
    for base in (0x800b9004, 0x80123454 & ~7 | 4, 0x801a0004):
        if r.safe(base):
            img = reloc.apply_table(body[:r.end], tab, base)
            assert img[H:] == r.relocate(base)[H:r.end], (c, hex(base))
    kind, o0, o1, o2, o3 = struct.unpack_from("<5I", st)
    assert kind == 6 and o0 == 0x14
    kept_ret = (0x14 + len(st) - o1 + 3) & ~3
    kept = ((kept_ret >> 3) + 1) << 3
    spu = (o1 - o0 + 63) & ~63
    iv = []
    for lo, hi in r.forbidden():
        assert lo < hi, (c, lo, hi)
        if iv and lo <= iv[-1][1]: iv[-1][1] = max(iv[-1][1], hi)
        else: iv.append([lo, hi])
    assert len(iv) <= NF, (c, iv)
    if c == 0x01 and "--wmhover" in sys.argv:     # 2026-11-18 deep scan (tools/speed/fxscan.py): War Machine's flight hover
        # alternates frame groups #433 / #434, the same 16 tiles 1-3 px apart -> the player path re-decodes all 3.2 KB
        # (60 decode lines) every frame.  Group table entry #434 (code part, A0 file offset 0xa650; data, not relocated)
        # -> #433's sec1 offset: the hover shows #433 on both frames = the cached draw path, no decode.  Tag loader only.
        k = H + 0xa650 - s[0][0]
        assert partA[k - 4:k + 4] == bytes.fromhex("~~~~~~~~~~~~~~~~"), "War Machine group table not stock"
        partA = partA[:k] + bytes.fromhex("ab8e") + partA[k + 2:]
    if c == 0x11 and "--onsl" in sys.argv:      # playable Onslaught: human form 1 KO / low timer = no form 2 (gameplay/onsl.py)
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import onsl
        partA = onsl.pl11_patch(partA)
    if NI and c in NI_FN:                       # INTRO option (tools/hwprof/nointro.py): stock +8 dispatcher -> byte check
        ni_at, ni_blob = nointro.dispatcher(c, ni_off, NI["force"])
        assert nointro.stock_dispatch_ok(c, partA[H:]), ("intro dispatcher not stock", c)
        partA = partA[:H + ni_at] + ni_blob + partA[H + ni_at + len(ni_blob):]
    if "--redcut" in sys.argv:                  # dx worker 2026-11-19: near-identical frames show their neighbour group
        # (tools/speed4/redcut.py frames: same animation, cutrules-protected groups never, floors kept; frame-table
        # u16 sec1 offset only, sec3 / hit data unchanged).  Consecutive frames on one group = cached draw, no decode.
        rc = json.load(open(os.path.join(GAME, "work", "speed4", "redcut_frames.json"))).get("%02X" % c, [])
        for o, old, new in rc:
            k = H + o - s[0][0]
            assert s[0][0] <= o < s[0][0] + s[0][1] and struct.unpack_from("<H", partA, k)[0] == old, (c, o)
            partA = partA[:k] + struct.pack("<H", new) + partA[k + 2:]
    if L1B: L1B_PARTA[c] = partA                 # --l1b: sec3 references from the FINAL code item (redcut / wmhover)
    return (partA, partB + tab), len(partB), setoff, len(st), kept, spu, iv, H, xoff


def tier_file(c, t):
    a, s = a0_parts(c)
    rle = a[s[1][0]:s[1][0] + s[1][1]]
    fx = FX and (FXC is None or c in FXC) and os.path.exists(os.path.join(FXW, "files", f"PL{c:02X}_10.A0"))
    if fx:                                       # option B: the half-res-effect DSP replaces the stock one
        b = open(os.path.join(FXW, "files", f"PL{c:02X}_10.A0"), "rb").read()
        n_, = struct.unpack_from("<I", b); fs = [struct.unpack_from("<2I", b, 4 + 8 * i) for i in range(n_)]
        assert b[fs[2][0]:] == a[s[2][0]:] and b[fs[0][0]:fs[0][0] + fs[0][1]] == a[s[0][0]:s[0][0] + s[0][1]], c
        rle = b[fs[1][0]:fs[1][0] + fs[1][1]]
    if t == "rle":
        return l1b(l2g(chk_apply(rle, rle), rle), c)
    p = os.path.join(FXW if fx else DSPW, "dsh" + t[3:] if t.startswith("dsx") else t, f"PL{c:02X}_10.DSP")
    if t.startswith("dxm"):                      # mixed tiers (tools/speed4/mix.py, dx worker): strong part + DSM1 sub-part
        p = os.path.join(GAME, "work", "speed4", "dsp", t, f"PL{c:02X}_10.DSP")
    if not os.path.exists(p):
        return None
    x = open(p, "rb").read()
    if t.startswith("dsx"):
        x = dsxmod.convert(x)[0]
    if fx: a = b; s = fs
    # the codec files hold the A0 from the DSP part to the end: the kind-6 set follows the DSP (loaded with the
    # A0 item here) -> cut at the stock DSP's length of section 3
    o3 = struct.unpack_from("<I", rle, 16)[0]; p3 = struct.unpack_from("<I", x, 16)[0]
    n = p3 + len(rle) - o3
    assert x[n:] == a[s[1][0] + s[1][1]:] and x[p3:n] == rle[o3:], (c, t)       # the A0 after its DSP
    return l1b(l2g(chk_apply(x[:n], rle), rle), c)


L2G = "--l2g" in sys.argv
L2PC = L2G and "--l2pc" in sys.argv              # --l2pc: every table item also unpacked (struct l2x after the chr entries)
L2OFF = [False]                                  # tier_file without the packing (the --l2pc alternates)
L1B = "--l1b" in sys.argv
HRFX = next((os.path.join(a.split("=", 1)[1], "games", "mvc", "work", "dsp") if os.path.isdir(os.path.join(a.split("=", 1)[1], "games")) else a.split("=", 1)[1]
             for a in sys.argv if a.startswith("--hrfx=")), None)   # --hrfx=TREE (dsp root, or a codec2 tree): full-res effect variants
HR_CHARS = []


def hr_differs(c):
    """--hrfx: character c has a full-res variant = its A0 DSP in the HRFX tree differs from MVC_FXW's"""
    p = lambda root: os.path.join(root, "files", f"PL{c:02X}_10.A0")
    if not os.path.exists(p(HRFX)): return False
    return not os.path.exists(p(FXW)) or open(p(HRFX), "rb").read() != open(p(FXW), "rb").read()


def hrx_size():
    return 16 * NT + 16 + ((8 * NT + 16) if L2PC else 0)


def dirx_len():
    return (0x17 + 2 * SHARE_N[0]) * (CHR + L2X) + ((len(HR_CHARS) * (4 + hrx_size()) + 4) if HRFX else 0)
L1B_PARTA = {}


def l1b(x, c):
    """--l1b (memory worker, rc4 L1b, games/mvc/tools/sec3/l1b.py, SEC3.md): sec3 deduped + offset map; REMAP (installed by
    tl_main, -DL1B) maps the stock offsets at the two readers.  Default: x unchanged."""
    if not L1B or x is None: return x
    sys.path.insert(0, os.path.join(GAME, "tools", "sec3")); import l1b as L1
    if c not in L1B_PARTA: a0_item(c)
    return L1.replace_sec3(x, c, L1B_PARTA[c])


def l1b_sec3(c, s3):
    """--l1b: a bare stock sec3 (the --share variant item) -> the packed section"""
    if not L1B or not s3: return s3
    sys.path.insert(0, os.path.join(GAME, "tools", "sec3")); import l1b as L1
    if c not in L1B_PARTA: a0_item(c)
    S3, sec = L1.packed(c, L1B_PARTA[c])
    if S3 is None: return s3
    assert S3 == s3, (c, "variant sec3 not stock")
    return sec


def l2g(x, ref):
    """--l2g (fx worker, rc4 L2, games/mvc/tools/l2): frame groups (sec1) in the packed G2 form; the runtime g2get
    (installed by tl_main, -DL2G) gives the draw path the stock bytes.  Default: x unchanged."""
    if not L2G or L2OFF[0]: return x
    sys.path.insert(0, os.path.join(GAME, "tools", "l2")); import g2pack
    return g2pack.pack_dsp(x, ref)


def chk_apply(x, src):
    """--chk: checker tiles of the source DSP `src` (stock / fx / union) stored as filled RLE + record (chkform.py)"""
    if "--chk" not in sys.argv: return x
    sys.path.insert(0, os.path.join(GAME, "tools", "speed5")); import chkform
    sys.path.insert(0, os.path.join(ROOT, "common", "dsp")); import dsp as D_
    d = D_.DSP(src); idx = chkform.tiles(d)
    return chkform.apply(x, d, idx) if idx else x


# --cutpen=A,B: planner cost of a dsh cut tier = dsh + A + B * frames cut (default 1000,100: any cut is lifted before
# speed upgrades; e.g. 0,5 lets spare RAM buy dsx / hot tiers first when the cut frames are rarely played ones)
DSXHOT = next((float(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--dsxhot=")), None)
CUTPEN = [int(v) for v in next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--cutpen=")), "1000,100").split(",")]


def costs():
    p = os.path.join(DSPW, "tiercost.json")
    tab = json.load(open(p)) if os.path.exists(p) else {}
    out = {}
    for c in CHARS:
        row = tab.get("PL%02X_10" % c, tab.get("%02X" % c, tab.get(str(c), {})))
        r = {t: int(row.get(t, COST.get(t, 330))) for t in TIERS if "_cut" not in t}
        if DSR and "dsr" in r:                       # DSR1 = DSA1 cost x the measured ratio (tools/codec2/dsrtest.py)
            r["dsr"] = int(row.get("dsa", COST["dsa"]) * DSR_RATIO)
        # MiSTer calibration (docs/TAGLOAD.md): above DSM1 the hot tiers / RLE buy little on hardware -> count them
        # only slightly cheaper than DSM1, so leftover RAM lifts DSA1 / DSH1 characters first
        dsm = r.get("dsm", 330)
        for t, f in (("dsm_hot16", 0.95), ("dsm_hot32", 0.92), ("dsm_hot64", 0.88), ("rle", 0.85)):
            if t in r: r[t] = int(dsm * f)
        # --dsxhot=F (2026-11-18): the hot tiles of dsx_hot* are the idle / walk / normals tiles of the fight runs;
        # attack frames (specials, beams) decode at DSX speed: War Machine's specials cost 117-131 decode lines per
        # frame on dsx_hot16 vs 72-74 on dsm.  Count dsx_hot* as dsm + F * (dsx - dsm) so spare RAM buys dsm first.
        if DSXHOT is not None and "dsx" in r:
            for t in r:
                if t.startswith("dsx_hot"): r[t] = max(r[t], int(dsm + DSXHOT * (r["dsx"] - dsm)))
        for t in TIERS:                                   # frame-cut tiers: as their base codec, plus a penalty
            if "_cut" not in t: continue
            n = int(t.split("_cut")[1])
            if t.startswith(("dsm", "dsx")):             # 2026-11-18 fast-decoder cut tiers (dsm_cutN encoded from the
                r[t] = r.get(t[:3], COST.get(t[:3], 600)) + CUTPEN[0] + CUTPEN[1] * n   # rule cut stock, dsx_cutN = dsh_cutN
                continue                                  # converted): their codec + the cut penalty
            if t.startswith("dsh"):                       # speed policy (build 03): a DSH1 file with N frames cut is
                r[t] = r.get("dsh", 963) + CUTPEN[0] + CUTPEN[1] * n # preferred to uncut DSA1 (~6x the decode cost per byte),
                                                          # but any cut is lifted before hot-tier speed-ups
            elif t.startswith("dsr") and XPLAN2:        # --xplan2 (fx, rc4): DSR1 cut tiers priced from DSR1 (--xplan
                r[t] = r.get("dsr", 3339) + CUTPEN[0] + CUTPEN[1] * n   # priced them from DSA1: 5,840 vs 3,579)
            else:
                r[t] = (r.get("dsa", 5600) + CUTPEN[0] + CUTPEN[1] * n if "--xplan" in sys.argv   # --xplan: speed cost
                        else 20000 + 900 * n)             # DSA1 with cuts: the last resort (u16 in the directory:
                                                          # 2500 * n overflowed at the dsa_cut48 floor, 2026-11-18)
        if any(t.startswith("dxm") for t in TIERS):     # mixed tiers (tools/speed4/mix.py): base codec + DSM1 hot part
            sys.path.insert(0, os.path.join(GAME, "tools", "speed4"))
            import mix as dxmix
            for t in TIERS:
                if t.startswith("dxm"): r[t] = dxmix.mixcost(c, t, row, CUTPEN)
        out[c] = [r[t] for t in TIERS]
    if XPLAN2:                                           # per-character decode volume (STOCK disc, the character acting;
        vol = charvol()                                  # tools/speed5/charvol.py) weighted by phase: cost x V_c / mean
        if vol:
            m = sum(vol.values()) / len(vol)
            for c in out:
                f = vol.get(c, m) / m
                out[c] = [min(0xfffe, max(3000, int(x * f))) if x >= 3000 else min(2999, int(x * f)) for x in out[c]]
                # (the planner's first criterion counts characters on tiers costing >= 3000 = DSA class: the scale
                #  must not move a tier across that line, 2026-11-20: Strider's DSR at 0.87 x fell under it)
    return out


XPLAN2 = "--xplan2" in sys.argv
PHASEW = {"idle": 0.1, "walking": 0.1, "normals": 0.2, "specials": 0.3, "super": 0.3}


def charvol():
    """{char: phase-weighted decoded KB per logic frame} from games/mvc/work/speed5/charvol.json ({} if missing)"""
    p = os.path.join(GAME, "work", "speed5", "charvol.json")
    if not os.path.exists(p) or not os.environ.get("XPLAN2_VOL"): return {}  # TEST only (XPLAN2_VOL=1): volume weights
    # (Beetle 2026-11-20: they trade the opponent's main down for a heavy-super character, 14,10,e,c st0 both normals
    #  55.8 -> 39.2; --xplan2 ships the DSR cut price fix alone)
    j = json.load(open(p))
    return {int(k, 16): sum(w * v[ph] for ph, w in PHASEW.items()) for k, v in j.items() if all(ph in v for ph in PHASEW)}


def char_tiers(c):
    """tier files of character c (half-res tree MVC_FXW, or the --hrfx tree via hr_tree()) -> (tiers, pix, tab, offs, first, tiers_u)"""
    tiers_u = None
    tiers = [tier_file(c, t) if USE_DSH or not t.startswith("dsh") else None for t in TIERS]
    if any(t.startswith("dxm") for t in TIERS):     # MIX1 trailer only in the mixed tiers (front end test)
        sys.path.insert(0, os.path.join(GAME, "tools", "speed4"))
        import mix as dxmix
        for t, x in zip(TIERS, tiers):
            if x and x[0x14:0x18] in (b"DSH1", b"DSA1"): assert dxmix.is_mix(x) == t.startswith("dxm"), (c, t)
    first = next(k for k, x in enumerate(tiers) if x)
    for k in range(first):                       # e.g. Onslaught has no cut / hot tiers: the floor repeats
        tiers[k] = tiers[first]
    for t in tiers:
        assert t is None or len(t) % 4 == 0 or True
    if L2PC:                                     # the same tiers with stock sec1 (--l2pc alternates)
        L2OFF[0] = True
        tiers_u = [tier_file(c, t) if USE_DSH or not t.startswith("dsh") else None for t in TIERS]
        L2OFF[0] = False
        for k in range(first): tiers_u[k] = tiers_u[first]
    if L2G:                                      # packed sec1 sizes differ a little per tier: pad to the largest
        m1 = max(struct.unpack_from("<I", x, 12)[0] - struct.unpack_from("<I", x, 8)[0] for x in tiers if x)
        for k, x in enumerate(tiers):
            if not x: continue
            kk, o0, o1, o2, o3 = struct.unpack_from("<5I", x); d = m1 - (o2 - o1)
            if d:
                y = bytearray(x[:o2] + bytes(d) + x[o2:]); struct.pack_into("<2I", y, 12, o2 + d, o3 + d); tiers[k] = bytes(y)
    offs = None
    pix, tab = [], []
    for x in tiers:
        if not x: pix.append(None); tab.append(None); continue
        k, o0, o1, o2, o3 = struct.unpack_from("<5I", x)
        assert k == 8 and o0 == 0x14 and o1 % 4 == 0
        t = (len(x) - o1, o2 - o1, o3 - o1)
        assert offs is None or offs == t, (c, offs, t)
        offs = t
        pix.append(x[:o1]); tab.append(x[o1:] + bytes(-(len(x) - o1) % 4))
    return tiers, pix, tab, offs, first, tiers_u


def layout():
    items, chars = [], {}
    for c in CHARS:
        item, a0size, setoff, setsize, kept, spu, iv, H, xoff = a0_item(c)
        tiers, pix, tab, offs, first, tiers_u = char_tiers(c)
        chars[c] = dict(a0size=a0size, setoff=setoff, setsize=setsize, kept=kept, spu=spu, iv=iv, tiers=pix, tabs=tab, hdr=H, xoff=xoff,
                        offs=offs, a0len=len(item[0]), stlen=len(item[1]))
        if L2PC:
            chars[c]["tabsu"], chars[c]["offsu"] = l2u_tabs(c, tiers_u, pix)
            items += [(("bu", c, k), x) for k, x in enumerate(chars[c]["tabsu"]) if x]
        if HRFX and hr_differs(c):                   # --hrfx: the full-res effect variant (same tier list, own tables)
            global FXW
            fx0 = FXW; FXW = HRFX
            try: htiers, hpix, htab, hoffs, hfirst, htiers_u = char_tiers(c)
            finally: FXW = fx0
            assert [x is None for x in hpix] == [x is None for x in pix], ("--hrfx tier list differs", c)
            hr = dict(pix=hpix, tab=htab, offs=hoffs)
            if L2PC: hr["tabsu"], hr["offsu"] = l2u_tabs(c, htiers_u, hpix)
            chars[c]["hr"] = hr; HR_CHARS.append(c)
            items += [(("th", c, k), x) for k, x in enumerate(hpix) if x] + [(("bh", c, k), x) for k, x in enumerate(htab) if x]
            if L2PC: items += [(("bhu", c, k), x) for k, x in enumerate(hr["tabsu"]) if x]
            print("hrfx: %02X full-res variant, pixels %+d B at the top tier" % (c, len(hpix[-1] or b"") - len(pix[-1] or b"")))
        items += [(("a0", c), item[0]), (("st", c), item[1])] + [(("t", c, k), x) for k, x in enumerate(pix) if x] +                  [(("b", c, k), x) for k, x in enumerate(tab) if x]
        if SPS: items += sps_layout(c, chars[c], tiers, tab)
    if "--share" in sys.argv: items += share_layout(chars)
    items += sndbuild.items()                               # sound level files (tools/snd)
    return items, chars


def l2u_tabs(c, tiers_u, pix):
    """--l2pc: the unpacked table items of a character's tier files (pixel parts must equal the packed files')"""
    tabs, offs = [], None
    for k, x in enumerate(tiers_u):
        if not x or not pix[k]: tabs.append(None); continue
        kk, o0, o1, o2, o3 = struct.unpack_from("<5I", x)
        assert kk == 8 and o0 == 0x14 and o1 % 4 == 0 and x[0x14:o1] == pix[k][0x14:], (c, k)   # header offsets differ
        t = (len(x) - o1, o2 - o1, o3 - o1)
        assert offs is None or offs == t, (c, offs, t)
        offs = t
        tabs.append(x[o1:] + bytes(-(len(x) - o1) % 4))
    return tabs, offs


def l2u_variant(h, k, vb):
    """--l2pc: a store variant's tables with the unpacked sec1 (sec2 / sec3 keep their bytes; mod-4 alignment kept)"""
    o, u, ou = h["offs"], h["tabsu"][k], h["offsu"]
    assert (o[1] - ou[1]) % 4 == 0
    r = u[:ou[1]] + vb[o[1]:]
    assert len(r) == len(u), (k, len(r), len(u))
    return r


SHARE_TREE = os.path.join(GAME, "work", "speed5", "root_pair")
SHARE_TIERS = ("dsa", "dsh", "dsx", "dsx_hot16", "dsm", "rle")
if DSR:                                          # --dsr: union DSR1 files in the CPU worker's mirror of root_pair
    SHARE_TREE = os.path.join(GAME, "work", "codec2", "pairtree")
    SHARE_TIERS = ("dsr",) + SHARE_TIERS[1:]


def share_layout(chars):
    """--share (tools/speed5/pairs.py): per pair (base b, variant u) two extra directory entries 0x17 + 2i / 0x18 + 2i.
    Base: b's code / set, tiers = the union tier files (pixels + b's tables with the union tile table) at the pair tiers
    (lower tiers repeat the floor, cut tiers absent); variant: u's code / set, tiers = a 24-byte dummy pixel item, tables =
    u's sec1 (tile indices into the union table) + u's sec3 (no sec2: tagload.c registers u on b's tile table)."""
    sys.path.insert(0, os.path.join(GAME, "tools", "speed5"))
    import pairs as PR
    items = []; n = 0
    tiny = struct.pack("<5I", 8, 0x14, 0x18, 0x18, 0x18) + bytes(4)
    sx = next((x_.split("=", 1)[1] for x_ in sys.argv if x_.startswith("--sharex=")), "")   # --sharex=10:08: pairs left out
    skip = {tuple(int(h, 16) for h in x_.split(":")) for x_ in sx.split(",") if x_}           # (integrator: 10+08 tag-in bug)
    for b, u in PR.PAIRS:
        if (b, u) in skip: continue
        jp = os.path.join(SHARE_TREE, "pair_%02X_%02X.json" % (b, u))
        if b not in chars or u not in chars or not os.path.exists(jp): continue
        J = json.load(open(jp))
        A = open(os.path.join(SHARE_TREE, "games", "mvc", "work", "dsp", "files", "PL%02X_10.A0" % b), "rb").read()
        s_ = [struct.unpack_from("<2I", A, 4 + 8 * i) for i in range(3)]
        U = A[s_[1][0]:s_[1][0] + s_[1][1]]
        pix = [None] * len(TIERS); tab = [None] * len(TIERS); offs = None; pixu = [None] * len(TIERS)
        for k, t in enumerate(TIERS):
            if t not in SHARE_TIERS: continue
            if t == "rle": x = U
            else:
                pth = os.path.join(SHARE_TREE, "games", "mvc", "work", "dsp", "dsh" + t[3:] if t.startswith("dsx") else t, "PL%02X_10.DSP" % b)
                if not os.path.exists(pth): continue
                x = open(pth, "rb").read()
                if t.startswith("dsx"): x = dsxmod.convert(x)[0]
                o3 = struct.unpack_from("<I", U, 16)[0]; p3 = struct.unpack_from("<I", x, 16)[0]
                x = x[:p3 + len(U) - o3]
                assert x[p3:] == U[o3:], (b, t)                    # sec3 unchanged by the encoders
            x = chk_apply(x, U)
            kk, o0, o1, o2, o3_ = struct.unpack_from("<5I", x)
            assert kk == 8 and o0 == 0x14 and o1 % 4 == 0
            assert x[o1:o2] == U[struct.unpack_from("<I", U, 8)[0]:struct.unpack_from("<I", U, 12)[0]], (b, t)   # sec1 = b's
            pix[k] = l1b(l2g(x, U), b)                              # --l2g: packed sec1, --l1b: packed sec3 (default: unchanged)
            if L2PC: pixu[k] = l1b(x, b)                            # --l2pc: the unpacked alternate
        if L2G:                                                     # pad the packed sec1 to one size over the tiers
            m1 = max(struct.unpack_from("<I", x, 12)[0] - struct.unpack_from("<I", x, 8)[0] for x in pix if x)
            for k, x in enumerate(pix):
                if not x: continue
                kk, o0, o1, o2, o3_ = struct.unpack_from("<5I", x); d = m1 - (o2 - o1)
                if d: y = bytearray(x[:o2] + bytes(d) + x[o2:]); struct.pack_into("<2I", y, 12, o2 + d, o3_ + d); pix[k] = bytes(y)
        for k, x in enumerate(pix):
            if not x: continue
            kk, o0, o1, o2, o3_ = struct.unpack_from("<5I", x)
            ot = (len(x) - o1, o2 - o1, o3_ - o1)
            assert offs is None or offs == ot, (b, TIERS[k], offs, ot)
            offs = ot; pix[k] = x[:o1]; tab[k] = x[o1:] + bytes(-(len(x) - o1) % 4)
        have = [k for k, x in enumerate(pix) if x]
        if not have or TIERS.index("dsr" if DSR else "dsa") not in have: continue
        cb = costs()[b]
        cost = [cb[k] if pix[k] else 0xffff for k in range(len(TIERS))]
        for k in range(have[0]):                                  # floor repeats (as layout())
            pix[k] = pix[have[0]]; tab[k] = tab[have[0]]; cost[k] = cost[have[0]]; pixu[k] = pixu[have[0]]
        s1u = bytes.fromhex(J["user_sec1"]); s3u = l1b_sec3(u, bytes.fromhex(J["user_sec3"]))   # --l1b: packed
        if L2G:                                                     # the variant's own frame groups, packed too
            sys.path.insert(0, os.path.join(GAME, "tools", "l2")); import g2pack
            s1u = g2pack.pack(s1u)
        s1uu = bytes.fromhex(J["user_sec1"]); s1uu += bytes(-len(s1uu) % 4)   # --l2pc: the variant's unpacked tables
        tuu = s1uu + s3u; tuu += bytes(-len(tuu) % 4)
        s1u += bytes(-len(s1u) % 4)
        tu = s1u + s3u; tu += bytes(-len(tu) % 4)
        PB, PU = 0x17 + 2 * n, 0x18 + 2 * n
        chars[PB] = dict(chars[b], tiers=pix, tabs=tab, offs=offs, src=b, cost=cost, pb=b, pu=u)
        chars[PU] = dict(chars[u], tiers=[tiny if x else None for x in pix], tabs=[tu if x else None for x in pix],
                         offs=(len(tu), len(s1u), len(s1u)), src=u, cost=cost, pb=b, pu=u)
        if L2PC:
            chars[PB]["tabsu"], chars[PB]["offsu"] = l2u_tabs(b, pixu, [x if x else None for x in pix])
            chars[PU]["tabsu"] = [tuu if x else None for x in pix]; chars[PU]["offsu"] = (len(tuu), len(s1uu), len(s1uu))
        for k, x in enumerate(pix):
            if not x: continue
            items += [(("t", PB, k), x), (("b", PB, k), tab[k]), (("t", PU, k), tiny), (("b", PU, k), tu)]
            if L2PC: items += [(("bu", PB, k), chars[PB]["tabsu"][k]), (("bu", PU, k), tuu)]
        print("share: pair %02X+%02X entries %02x/%02x, tiers %s, union pixels %s" % (
            b, u, PB, PU, ",".join(TIERS[k] for k in have), [len(pix[k]) for k in have]))
        n += 1
    SHARE_N[0] = n
    return items


SHARE_N = [0]


CHR = (16 + 28 + 4 * NF + 16 * NT + 16 + 2 * NT + 3) & ~3   # sizeof(struct chr) (C pads to 4)
SPS = "--spustore" in sys.argv                   # SPU store (tools/spustore): + tv[NT], bv[NT], cut8[NT][6], ntile
CHR0 = CHR
if SPS: CHR = (CHR0 + 8 * NT + 4 * NT + NT + 1 + 2 + 3) & ~3
L2X = 8 * NT + 16 + 4 * NT if L2PC else 0        # --l2pc: sizeof(struct l2x)


def frag_list():
    """fragments usable during a tag battle -> [(lo, hi, flags)], flags = stage mask | 1 << 31 for EXE RAM.
    EXE: games/mvc/work/cold/cold_ranges.json {"ranges": [[lo, hi], ...]} (battle-cold + pristine, restored after the
    battle by rhook / tl_restore).  Stage: games/mvc/work/cold/stage_cold.json {"stage N": [[off_lo, off_hi], ...]}
    relative to 0x8009dfcc (no restore: the next battle reloads its stage).  Pieces >= MINFRAG, at most NFR."""
    if "--nofrag" in sys.argv: return []
    out = []
    cw = os.path.join(GAME, "work", "cold")
    p = os.path.join(cw, "cold_ranges.json")
    if os.path.exists(p) and "--exefrag" in sys.argv:      # opt-in: restore path unverified; the one >= 4 KB piece
        # (0x8002a700-0x8002c700) holds the stock loaders that run before / around our hook
        j = json.load(open(p))
        for lo, hi in j.get("ranges", j):
            lo = int(lo, 0) if isinstance(lo, str) else lo; hi = int(hi, 0) if isinstance(hi, str) else hi
            lo = (lo + 7) & ~7; hi &= ~7
            if hi - lo >= MINFRAG: out.append((lo, hi, 0x3ff | 1 << 31))
    p = os.path.join(cw, "stage_cold.json")
    if os.path.exists(p) and "--nostagefrag" not in sys.argv:
        j = json.load(open(p))
        per = {}
        for k, rr in j.items():
            if not k.startswith("stage"): continue
            st = int(k.split()[1])
            sc = j.get("_detail", {}).get(k, {}).get("scenarios", [])
            if st == 9 and not (isinstance(rr, dict) and rr.get("non_onslaught_checked")) and not {"S9", "X9"} <= set(sc):
                continue                             # stage 9 measured with Onslaught only so far
            for lo, hi in (rr["ranges"] if isinstance(rr, dict) else rr):
                lo = 0x8009dfcc + lo; hi = 0x8009dfcc + hi
                lo = (lo + 7) & ~7; hi &= ~7
                if hi - lo >= MINSFRAG: per[(lo, hi)] = per.get((lo, hi), 0) | 1 << st
        if any(a.startswith("--stagelite") for a in sys.argv):   # stagelite moves the stage data: cold offsets invalid
            import stagelite
            for st in stagelite.selected(sys.argv):
                per = {k: m & ~(1 << st) for k, m in per.items()}
        out += [(lo, hi, m) for (lo, hi), m in per.items() if m]
    out.sort(key=lambda r: r[0] - r[1])
    return sorted(out[:NFR])


MINFRAG = 4096
MINSFRAG = 2048                                  # stage pieces (no restore): 2 KB pieces count too


def sps_layout(c, h, tiers, tab):
    """--spustore: store variants of the DSH1-family tiers (tools/spustore/spsvar.py) -> disc items ("tv"/"bv", c, k)"""
    # --share: the pair entries (0x17+) get no variants (plain union tier files); ordinary characters do
    sys.path.insert(0, os.path.join(GAME, "tools", "spustore"))
    import spsvar
    out = []
    h["vt"], h["vb"], h["cut"] = [None] * len(tiers), [None] * len(tiers), [[0] * 12 for _ in tiers]
    for k, x in enumerate(tiers):
        r = spsvar.variant(c, TIERS[k], x) if x else None
        if not r or not any(r[1]): continue
        v = r[0]
        _, o0, o1, o2, o3 = struct.unpack_from("<5I", v)
        vt, vb = v[:o1], v[o1:] + bytes(-(len(v) - o1) % 4)
        assert len(vb) == len(tab[k]) and len(vt) % 4 == 0, (c, k)
        assert r[1] == [2048 * (i + 1) for i in range(len(r[1]))]
        h["vt"][k], h["vb"][k], h["cut"][k] = vt, vb, r[1]
        h["ntile"] = len(spsvar.D.DSP(v).tiles)
        out += [(("tv", c, k), vt), (("bv", c, k), vb)]
        if L2PC: out += [(("bvu", c, k), l2u_variant(h, k, vb))]
    return out


def sps_fields(c, h, ent):
    tv = [ent(("tv", c, k), len(x)) if x else bytes(8) for k, x in enumerate(h.get("vt", []))]
    bv = [ent(("bv", c, k), len(x))[:4] if x else bytes(4) for k, x in enumerate(h.get("vb", []))]
    tv += [bytes(8)] * (NT - len(tv)); bv += [bytes(4)] * (NT - len(bv))
    cu = [sum(1 for m in cl if m) for cl in h.get("cut", [])]; cu += [0] * (NT - len(cu))
    b = b"".join(tv) + b"".join(bv) + bytes(cu) + bytes(1) + struct.pack("<H", h.get("ntile", 0))
    return b + bytes(CHR - CHR0 - len(b))


def directory(pos, chars, flags, frags=()):
    cost = costs()
    ent = lambda key, n: msf(pos[key]) + struct.pack("<I", n) if key in pos else bytes(8)
    out = b""
    for c in range(0x17 + 2 * SHARE_N[0]):
        if c not in chars:
            out += bytes(CHR); continue
        h = chars[c]; sc = h.get("src", c)
        forb = [x for lo, hi in h["iv"] for x in (lo, hi)]
        forb += [0] * (2 * NF - len(forb))
        t = [ent(("t", c, k), len(x)) if x else bytes(8) for k, x in enumerate(h["tiers"])]
        t += [bytes(8)] * (NT - len(t))
        b = [ent(("b", c, k), len(x)) if x else bytes(8) for k, x in enumerate(h["tabs"])]
        b += [bytes(8)] * (NT - len(b))
        cs = h["cost"] if "cost" in h else cost[c]
        cs = cs + [0xffff] * (NT - len(cs))
        out += (ent(("a0", sc), h["a0len"]) + ent(("st", sc), h["stlen"]) + struct.pack("<7I", h["a0size"], h["hdr"], h["xoff"], h["setoff"], h["setsize"], h["kept"], h["spu"])
                + struct.pack(f"<{2 * NF}H", *forb) + b"".join(t) + b"".join(b) + struct.pack("<4I", h["offs"][0], 0, h["offs"][1], h["offs"][2])
                + struct.pack(f"<{NT}H", *cs) + bytes([h.get("pb", 0), h.get("pu", 0)]) + bytes(CHR0 - (16 + 28 + 4 * NF + 16 * NT + 16 + 2 * NT + 2))
                + (sps_fields(sc, h, ent) if SPS else b""))
    assert len(out) == (0x17 + 2 * SHARE_N[0]) * CHR
    if L2PC:                                     # struct l2x per entry after the chr entries (tagload.c L2PC)
        for c in range(0x17 + 2 * SHARE_N[0]):
            h = chars.get(c)
            if not h or "tabsu" not in h: out += bytes(L2X); continue
            u = [ent(("bu", c, k), len(x)) if x else bytes(8) for k, x in enumerate(h["tabsu"])]
            u += [bytes(8)] * (NT - len(u))
            v = [msf(pos[("bvu", c, k)]) if ("bvu", c, k) in pos else bytes(4) for k in range(NT)]
            out += b"".join(u) + struct.pack("<4I", h["offsu"][0], 0, h["offsu"][1], h["offsu"][2]) + b"".join(v)
        assert len(out) == (0x17 + 2 * SHARE_N[0]) * (CHR + L2X)
    if HRFX:                                     # tagload.c HRFX: n x {u32 char, struct hrx}, then u32 n
        for c in HR_CHARS:
            hr = chars[c]["hr"]
            t = [ent(("th", c, k), len(x)) if x else bytes(8) for k, x in enumerate(hr["pix"])] + [bytes(8)] * (NT - len(hr["pix"]))
            b = [ent(("bh", c, k), len(x)) if x else bytes(8) for k, x in enumerate(hr["tab"])] + [bytes(8)] * (NT - len(hr["tab"]))
            out += struct.pack("<I", c) + b"".join(t) + b"".join(b) + struct.pack("<4I", hr["offs"][0], 0, hr["offs"][1], hr["offs"][2])
            if L2PC:
                u = [ent(("bhu", c, k), len(x)) if x else bytes(8) for k, x in enumerate(hr["tabsu"])] + [bytes(8)] * (NT - len(hr["tabsu"]))
                out += b"".join(u) + struct.pack("<4I", hr["offsu"][0], 0, hr["offsu"][1], hr["offsu"][2])
        out += struct.pack("<I", len(HR_CHARS))
    fr = [x for r in frags for x in r] + [0] * (3 * NFR - 3 * len(frags))
    force = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--force=")), None)
    fb = bytes(int(x, 16) for x in force.split(",")) if force else bytes(4)
    if force: flags |= 2
    if "--stockmeter" in sys.argv: flags |= 4
    flags |= 16                                  # the dispatch jumps through dshptr / dsaptr (any decoder address)
    if "--cache" in sys.argv: flags |= 64        # decoded-tile cache (fecache.S) when the team can spare the RAM
    exe_lba = lba_map()["SLUS_010.59"][0]
    nstrong = 0
    while nstrong < len(TIERS) and TIERS[nstrong].startswith(("dsh", "dsa", "dsx", "dsr")): nstrong += 1
    ncut = sum(1 for t in TIERS if "_cut" in t)
    return (struct.pack("<8I", 0x4c474154, 0, 0, 0, 0, ncut, nstrong, flags) + fb + struct.pack("<I", len(frags)) + struct.pack(f"<{3 * NFR}I", *fr)
            + msf(exe_lba) + out)


def dsm_patches():
    cfg = dsmpatch.GAMES["mvc"]
    assert [tuple(r) for r in cfg["free"]] == DSM_FREE or "--frozendsm" in sys.argv, "dsmpatch mvc free list changed"
    saved = cfg["free"]
    cfg["free"] = DSM_FREE
    try:
        dsmpatch._cache.clear()
        if USE_DSH:
            out = dsmpatch.patches("mvc", dshptr=SYM["dshptr"], dsaptr=SYM["dsaptr"])
            if ASRLE: assert dsmpatch.symbols("mvc", dshptr=SYM["dshptr"], dsaptr=SYM["dsaptr"])["rle"] & 0xffffffff == rle_entry(), "rle moved"
            if DSR:                                  # the DSA1 route matches 'DSR1' sections (one word, entry unit)
                out = list(out); k_ = [i for i, (a_, d_) in enumerate(out) if a_ == 0x8001bd48]; assert len(k_) == 1
                a_, d_ = out[k_[0]]; w_ = struct.pack("<I", 0x3c0d000c)     # lui t5, 0x000c ('DSA1' ^ 'DSM1')
                assert d_.count(w_) == 1, "dispatch DSA1 constant not found once"
                out[k_[0]] = (a_, d_.replace(w_, struct.pack("<I", 0x3c0d001f)))   # 'DSR1' ^ 'DSM1'
            return out
        return dsmpatch.patches("mvc")
    finally:
        cfg["free"] = saved


def dsh_decoder():
    """the RAM decoders (position-independent): DSH1, then DSA1 -> (bytes, offset of DSA1)"""
    dsx = any(t.startswith("dsx") for t in TIERS)
    dsh = open(os.path.join(DSPW, "dsx", "dsxdec.bin") if dsx else os.path.join(DSPW, "dsh", "dshdec.bin"), "rb").read(); dsh += bytes(-len(dsh) % 8)
    dsa = open(os.path.join(DSPW, "dsa", "dsadec.bin"), "rb").read()
    if "--dxdsa" in sys.argv:                        # dx worker: DSA1 decoder with a leaf cache (tools/speed4/dsa)
        sys.path.insert(0, os.path.join(GAME, "tools", "speed4", "dsa"))
        import dsadx
        dsa = dsadx.binary()
    if DSR:                                          # CPU worker: DSR1 (tools/codec2) takes the DSA1 slot (no DSA1 tiers then)
        assert not any(t.startswith("dsa") for t in TIERS), "--dsr replaces the dsa tiers (use dsr / dsr_cutN)"
        sys.path.insert(0, os.path.join(GAME, "tools", "codec2"))
        import dsrbuild
        dsa = dsrbuild.binary()
    code = dsh + dsa
    if any(t.startswith("dxm") for t in TIERS):         # mixed tiers: MIX1 front ends (tools/speed4/fe.py) before both
        sys.path.insert(0, os.path.join(GAME, "tools", "speed4"))
        import fe as dxfe
        dm = dsmpatch.symbols("mvc", dshptr=SYM["dshptr"], dsaptr=SYM["dsaptr"])["dsm_dec"] & 0xffffffff
        assert dm == dxfe.dsm_dec(), "dsm_dec moved"
        code, off = dxfe.payload(metermod.STRONG_AT, dsx, dm)
        assert code[off + dxfe.FE_LEN:] == dsa
        assert len(code) <= metermod.MRAM - metermod.STRONG_AT
        return code, off
    assert len(code) <= metermod.MRAM - metermod.STRONG_AT
    return code, len(dsh)


SYM = {}


RDHOOK, RDHOOK_ORIG = 0x~~~~~~~~, (0x~~~~~~~~, 0x~~~~~~~~)       # file loader entry


def exe_patches(sym, glue, res, blob_ent, mparts=None, frags=()):
    jal = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
    o = sym["blobent"] - sym["flushcache"]
    res = res[:o] + blob_ent + res[o + 8:]
    bnez = 0x14400000 | (((0x8002b9b4 - (HOOK + 8 + 4)) >> 2) & 0xFFFF)
    if not any(f[2] >> 31 for f in frags):              # restore hook only with EXE fragments
        glue = [g for g in glue if g[0] != 0x80014774]
    else:
        glue = glue + [(RDHOOK, struct.pack("<2I", 0x08000000 | (sym["rhook"] >> 2 & 0x3ffffff), 0))]
    # state bytes (dead span, zeroed): 0x800858ac +0 LOADER_FULL, +1 RESTORE, +2/+3 ap8; 0x800858c8 ASSIST_GATE
    out = [(HOOK, struct.pack("<4I", jal(sym["glue"]), 0x27a40010, bnez, 0))] + [(0x800858ac, bytes(4)), (0x800858c8, opt_init())] + exopt_exe() + glue + [(sym["flushcache"], res),
           (HEAPHOOK, struct.pack("<I", jal(sym["heapcap"])))]
    out += tagmode.patches(tail=mparts[2]["mcopy"] if mparts else None, assist="--assist" in sys.argv) + assist.patches(assist="--assist" in sys.argv)
    if "--onslp1" in sys.argv or "--onsl" in sys.argv:   # assist bugs lead: P1-side Onslaught stage buffer (onslp1.py)
        import onslp1
        out += onslp1.patches()
    if "--ashud" in sys.argv:                            # assist bugs lead: HUD portrait gate / counter / P2 x (ashud.py;
        import ashud                                     # its stub uses stageanim chunk D, unused with --fs05)
        out += ashud.patches()
        if "--ashudpal" in sys.argv:                     # rc4.9: secret assists 0x14 / 0x15 HUD portrait colours (data)
            out += ashud.palpatches()
    else:
        assert "--ashudpal" not in sys.argv, "--ashudpal needs --ashud"
    if "--asarc" in sys.argv:                            # assist bugs lead: loader's ARCADE assist bits (asarc.py, stageanim
        import asarc                                     # chunk C, unused with --fs05)
        assert "--fs05" in sys.argv
        out += asarc.patches()
    if "--ldbuf" in sys.argv:                            # rc4.10: scene-12 winner prim buffer address from LDBUF_W (ldbuf.py)
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay"))
        import ldbuf
        assert "--exopt" in sys.argv, "--ldbuf needs --exopt (its word lives in the EX OPTIONS block)"
        out += ldbuf.patches()
    if "--onsl" in sys.argv:                             # playable Onslaught: no endless phase 10 for a human loser (onsl.py)
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import onsl
        out += onsl.exe_patches()
    if "--onslfix" in sys.argv:                          # (onslaught fixes 2026-11-24) ARCADE stage rotation etc. (onsl.py)
        assert "--onsl" in sys.argv, "--onslfix needs --onsl"
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import onsl
        out += onsl.fix_exe_patches()
    if "--cputag" in sys.argv:                           # (mvc cpu tag ai 2026-11-24) the CPU tags in tag battles (gameplay/cputag.py)
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import cputag
        _ex = open(os.path.join(GAME, "disc", "SLUS_010.59"), "rb").read()
        out += cputag.exe_patches(lambda a, n: _ex[a - 0x80010000 + 0x800:a - 0x80010000 + 0x800 + n])
    if "--notaunt" in sys.argv:                          # user decision 2026-11-18: no taunt (SELECT does nothing).
        out += [(TAUNT_SB, bytes(4))]                    # pad mapper 0x80024934: a button mapped to function 0x2000
                                                         # (taunt; SELECT by default) ORs its side's bit into
                                                         # 0x8007be49, the move decoder (0x8005698c) starts the taunt
                                                         # from it -> that store becomes a nop (the byte is cleared
                                                         # every frame at 0x80024904, so it stays 0)
    # Battle-scene init 0x80045df4 picks the battle loader by 0x8007b75a: 1 = the quick loader 0x8002bfe0 (ARCADE
    # START shortcut after a won fight: keeps the human side's characters from a RAM snapshot, loads only the CPU's,
    # bypasses our hook in 0x8002b7a4 -> stock load, no tag, a FREEZE on the MiSTer).  `bne v1,v0,0x80045f14` -> `b`:
    # every battle goes through 0x8002b7a4 (type 2 = 0x8008a700 is not affected: its beq comes first).
    out += [(QUICKLOAD_AT, struct.pack("<I", 0x10000024))]
    kol = next((int(a_.split("=", 1)[1]) for a_ in sys.argv if a_.startswith("--kolife=")), None)
    if kol is not None:                                  # TEST builds only (dx 2026-11-19, postko.py): every fighter starts
        assert 1 <= kol <= 0x90                          # with N life: the battle-start init 0x8002d9a8 `addiu v0, zero, 0x90`
        out += [(0x8002d9a8, struct.pack("<I", 0x24020000 | kol))]   # (sh v0, 0x294(s0) follows; stock word 0x24020090)
    stg = next((int(a_.split("=", 1)[1]) for a_ in sys.argv if a_.startswith("--stage=")), None)
    if stg is not None:                                  # TEST builds only: every battle on stage N (also Onslaught's)
        assert 0 <= stg <= 9                             # stage loader 0x8002b544: `bne` (mode 3 -> stage 9) -> nop,
        out += [(0x8002b568, bytes(4)), (0x8002b574, struct.pack("<I", 0x24020000 | stg))]   # `li v0, 9` -> N
    arn = next((int(a_.split("=", 1)[1], 0) for a_ in sys.argv if a_.startswith("--arena=")), None)
    if arn is not None:                                  # tile-decode staging arena size (stock 0x7c64, set by
        assert 0x1000 <= arn <= 0x7c64 and arn % 4 == 0  # 0x800923e0 at every battle init; the allocator 0x8008dedc
        out += [(0x80092450, struct.pack("<I", 0x24020000 | arn))]   # DrawSyncs + resets when it is full)
    stt = next((int(a_.split("=", 1)[1]) for a_ in sys.argv if a_.startswith("--stagetab=")), None)
    if stt is not None:                                  # TEST builds (hardware A/B): the stage-order table 0x80071584
        assert 0 <= stt <= 8                             # (32 B, read by 0x80047074 for VERSUS / ARCADE before the VS
        out += [(0x80071584, bytes([stt]) * 32)]         # screen preloads the ARC) all N; Onslaught keeps stage 9
        out += [(0x80072b2c, bytes([stt]) * 16),         # VERSUS: 0x8005b634 random pick from this 16-B table,
                (0x8005b658, bytes(4)),                  # `beq` retry while equal to the last stage -> nop
                (0x800470c8, struct.pack("<I", 0x24030000 | stt))]   # mode 1 (VERSUS): `lbu v1, 0x98(a0)` -> li v1, N
    if "--bgfast" in sys.argv:                           # bgfast.py: WRAP + the per-frame BG builder call site
        import bgfast
        out += bgfast.exe_patches()
    if "--vcache" in sys.argv:                           # tools/vcache2/vcache.py: decode-site stub (+ enable word)
        import vcache
        if "--pal8" in sys.argv:
            import pal8, kocache
            vcache.vc3.P8AT = pal8.code(p8_at(kocache), 0x80000000)[1]["P8"]
        out += vcache.exe_patches()
    if "--duonocutstatic" in sys.argv:                   # (2026-11-26, HW bisect) the Duo cut-in nops as a plain static EXE patch
        _x = open(os.path.join(GAME, "disc", "SLUS_010.59"), "rb").read(); _t = struct.unpack_from("<I", _x, 0x18)[0]
        for _a, _w in ((0x80030650, 0x0c01a2d5), (0x8003066c, 0x0c01974a)):
            assert struct.unpack_from("<I", _x, 0x800 + _a - _t)[0] == _w, "Duo cut-in spawn call not stock"
            out.append((_a, bytes(4)))
    fsk = next((a_ for a_ in sys.argv if a_.startswith("--frameskip")), None)
    if fsk:                                              # tools/hwprof/frameskip.py: battle catch-up (FRAME SKIP)
        sys.path.insert(0, os.path.join(GAME, "tools", "hwprof")); import frameskip
        out += frameskip.exe_patches(force=fsk != "--frameskip")
    if "--nogpovl" not in sys.argv:                      # gameplay/selscreen.py 5: ARCADE stage-screen CPU team stub
        import selscreen
        out += selscreen.exe_patches()
    if "--zoom" not in sys.argv:                         # gameplay/nozoom.py: no throw / hit camera zoom
        out += nozoom.patches()
    if mparts:
        out += mparts[0]
    dp = dsm_patches()
    out += dp
    if FX:
        out += fxeng.patches()
    out += SND_PATCHES                                      # tools/snd: play entry -> sndstub, sndrest
    iv = sorted((a, a + len(d)) for a, d in out)
    for (a, b), (c, d) in zip(iv, iv[1:]):
        assert b <= c, f"patch overlap {a:08x}-{b:08x} / {c:08x}-{d:08x}"
    return out


class Img:
    def __init__(self, path):
        self.f = open(path, "r+b"); self.touched = set()

    def wbytes(self, lba, off, data):
        for i in range(len(data)):
            o = off + i
            self.f.seek((lba + o // 2048) * 2352 + 24 + o % 2048); self.f.write(data[i:i + 1])
            self.touched.add(lba + o // 2048)

    def rbytes(self, lba, off, n):
        out = bytearray()
        for i in range(n):
            o = off + i
            self.f.seek((lba + o // 2048) * 2352 + 24 + o % 2048); out += self.f.read(1)
        return bytes(out)

    def wsectors(self, lba, data):
        data = data + bytes(-len(data) % 2048)
        for i in range(len(data) // 2048):
            self.f.seek((lba + i) * 2352)
            raw = bytearray(self.f.read(2352))
            assert raw[18] & 0x20 == 0, "not a form-1 sector"
            raw[24:24 + 2048] = data[i * 2048:(i + 1) * 2048]
            self.f.seek((lba + i) * 2352); self.f.write(raw); self.touched.add(lba + i)

    def extend(self, start, n):
        self.f.seek((start - 1) * 2352); tmpl = bytearray(self.f.read(2352))
        assert tmpl[15] == 2 and not tmpl[18] & 0x20, "last sector is not mode 2 form 1"
        b = lambda x: (x // 10) << 4 | x % 10
        for i in range(n):
            l = start + i + 150
            sec = bytearray(tmpl[:12] + bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 2]) + tmpl[16:24] + bytes(2048 + 280))
            self.f.seek((start + i) * 2352); self.f.write(sec); self.touched.add(start + i)

    def fix(self):
        for l in sorted(self.touched):
            self.f.seek(l * 2352); raw = bytearray(self.f.read(2352))
            fix_sector(raw); self.f.seek(l * 2352); self.f.write(raw)
        self.f.close()


def lba_map():
    p = os.path.join(GAME, "work", "lba_map.json")
    if not os.path.exists(p):
        d = Disc(SRC_BIN)
        json.dump({f.split("/")[-1].split(";")[0]: (l, s) for f, l, s, _ in d.walk()}, open(p, "w"))
    return json.load(open(p))


ASSIST_DATA = os.environ.get("ASSIST_DATA", os.path.join(GAME, "work", "assist", "data"))
ASRLE = "--asrle" in sys.argv                      # asdip lead (rc4.6): + rles = stock RLE with its streams in SPU
ASSIST_TIERS = ("rle", "rles", "dsx", "dsxs", "dshs") if ASRLE else ("rle", "dsx", "dsxs", "dshs")   # assists lead: assist
                                                 # pixel tiers, fastest first (tagload.c NAT); dsxs / dshs = dsx / dsh with
                                                 # every stream in SPU (games/mvc/tools/assist/asvar*.py), rles: asvar_rle.py
ASSIST_COST = {"rle": 290, "rles": 330, "dsx": 680, "dsxs": 760, "dshs": 1050}   # decode cost class (the characters' cost scale)


def rle_entry():
    """--asrle: address of the game's byte RLE decoder (dsmdec.S label rle, entry unit at 0x8001bd48; its offset does
    not depend on the dshptr / dsaptr word addresses: dsm_patches() asserts the same value with the real ones)"""
    T = dsmpatch.TEST["mvc"]
    return dsmpatch.symbols("mvc", dshptr=T["dshptr"], dsaptr=T["dsaptr"])["rle"] & 0xffffffff
ASX = 28 + 8 * 2 * len(ASSIST_TIERS) + 4 * 2 * len(ASSIST_TIERS) + 2 * len(ASSIST_TIERS) + 4   # tagload.c struct asx
ASX_PAD = -ASX % 4                               # C pads the struct to 4 (NAT = 5 under --asrle: 162 -> 164)
ASX += ASX_PAD


def header_words(path, name):
    """the u32 array NAME of a generated header (l2g.h / vcache.h) as bytes"""
    import re
    t = open(path).read()
    m = re.search(r"static const u32 %s\[[^\]]*\] = \{(.*?)\};" % name, t, re.S)
    w = [int(x.strip().rstrip("u"), 16) for x in " ".join(m.group(1).split()).split(",") if x.strip()]
    return struct.pack("<%dI" % len(w), *w)


def _ascut():
    sys.path.insert(0, os.path.join(GAME, "tools", "assist"))
    import ascut
    return ascut


def assist_items():
    """--assist: per assist (00-15) code + relocation table, per tier tables + pixels; then the 22-entry table"""
    out = []
    j = json.load(open(os.path.join(ASSIST_DATA, "daprep.json")))
    for a in range(0x16):
        d = os.path.join(ASSIST_DATA, "DA%02X" % a)
        code = open(os.path.join(d, "code.bin"), "rb").read()
        assert len(code) % 4 == 0 and len(code) == j["%02X" % a]["code"] and j["%02X" % a]["reloc_exact_11_to_21"]
        if "--ascut" in sys.argv:                    # asdip lead (rc4.6): assist frame cuts (tools/assist/ascut.py)
            code = _ascut().patch(a, code)
        assert not j["%02X" % a]["forbidden"], "assist %02X: forbidden residues not supported" % a
        out.append((("asc", a), code + open(os.path.join(d, "reloc.bin"), "rb").read()))
        for t in ASSIST_TIERS:
            out.append((("ast", a, t), open(os.path.join(d, t + ".tab"), "rb").read()))
            out.append((("asp", a, t), open(os.path.join(d, t + ".pix"), "rb").read()))
    global ASSIST_ITEMS
    ASSIST_ITEMS = dict(out)
    out.append((("asx",), bytes(ASX * 0x16)))
    return out


def assist_table(pos):
    """tagload.c struct asx x 22: fent a0, codesz, tabsz, toff[3], fent tb[NAT], fent t[NAT], u16 cost[NAT + 1]"""
    j = json.load(open(os.path.join(ASSIST_DATA, "daprep.json")))
    for k_, f_ in (("dshs", "asvar.json"), ("dsxs", "asvar_dsx.json")) + ((("rles", "asvar_rle.json"),) if ASRLE else ()):
        v = json.load(open(os.path.join(ASSIST_DATA, f_)))
        for a_ in range(0x16):
            j["%02X" % a_]["tiers"][k_] = dict(v["%02X" % a_], tab=v["%02X" % a_]["sec1"] + v["%02X" % a_]["sec2"] + v["%02X" % a_]["sec3"])
    t = b""
    for a in range(0x16):
        r = j["%02X" % a]["tiers"]
        r0 = r[ASSIST_TIERS[0]]
        t += msf(pos[("asc", a)]) + struct.pack("<5I", len(ASSIST_ITEMS[("asc", a)]), j["%02X" % a]["code"], r0["tab"], 0, r0["sec1"])              + struct.pack("<I", r0["sec1"] + r0["sec2"])
        for k in ASSIST_TIERS:
            tb = ASSIST_ITEMS[("ast", a, k)]
            assert len(tb) == r0["tab"] == r[k]["sec1"] + r[k]["sec2"] + r[k]["sec3"] and r[k]["sec1"] == r0["sec1"] and r[k]["sec2"] == r0["sec2"]
            t += msf(pos[("ast", a, k)]) + struct.pack("<I", len(tb))
        for k in ASSIST_TIERS:
            px = ASSIST_ITEMS[("asp", a, k)]; assert len(px) == r[k]["pix"]
            t += msf(pos[("asp", a, k)]) + struct.pack("<I", len(px))
        n_ = len(ASSIST_TIERS)
        t += struct.pack("<%dI" % n_, *[r[k].get("ram", r[k]["pix"]) for k in ASSIST_TIERS])
        t += struct.pack("<%dI" % n_, *[r[k].get("spu", 0) for k in ASSIST_TIERS])
        t += struct.pack("<%dH" % n_, *[ASSIST_COST[k] for k in ASSIST_TIERS])
        t += struct.pack("<2H", r0["sec2"] // 5, 0) + bytes(ASX_PAD)
    assert len(t) == ASX * 0x16, len(t)
    return t


def main(argv):
    name = next((a for a in argv[1:] if not a.startswith("--")), "mvc_tag")
    global mvcver
    _gp = os.path.join(GAME, "tools", "gameplay"); sys.path.insert(0, _gp); import mvcver; sys.path.remove(_gp)
    if mvcver.text_of(argv):                                 # (logo) --title[=TEXT]: needs --exopt (the 6th main-menu line is
        assert "--exopt" in argv, "--title needs --exopt"     # EX OPTIONS); the same text on the EX OPTIONS screen (--ver)
        if not any(a.startswith("--ver=") for a in argv):
            argv.append("--ver=" + mvcver.text_of(argv))
            if argv is not sys.argv: sys.argv.append(argv[-1])
    flags = 0 if "--novc" in argv else 1
    if "--rescue" in argv: flags |= 256                    # tagload.c rescue(): no DSA1 tier when a lift fits
    SA6 = None
    if "--sa06" in argv:                                     # tools/gameplay/sa06.py: STAGE ANIM OFF = lite stage ARCs
        assert "--stageanim" in argv and not any(a.startswith("--stagelite") for a in argv), "--sa06 needs --stageanim, excludes --stagelite"
        import sa06, stageanim
        stageanim.HOLDS = [(st_, sa06.reloc(st_, a_), v_) for st_, a_, v_ in stageanim.HOLDS]   # held words in the lite ARC
    if "--postvc" in argv:                                   # SPVC after the load into the freed arena tail (tagload.c)
        assert flags & 1 and "--arena=0x3000" in argv, "--postvc needs --arena=0x3000"
        flags |= 128
    glue, res, blob, sym = build_blob()
    if "--hwprof" in argv:                                   # TEST builds: hardware frame profiler (tools/hwprof)
        sys.path.insert(0, os.path.join(GAME, "tools", "hwprof")); import hwprof; hwprof.install(metermod)
    if "--stageanim" in argv:                                # MCOPY must not copy the STAGE ANIM RAM part (stale blob tail)
        import stageanim
        metermod.MCOPY_SIZE = stageanim.SA - metermod.MRAM
    msym = dict(sym)
    if "--strongx" in argv:                                  # the payload is not in the blob: MCOPY's magic test reads a
        msym["tl_strong"] = sym["tl_nometer"] - (metermod.MRAM - metermod.STRONG_AT)   # zero word (tagload.c tl_nometer)
    mparts = None if "--nometer" in argv else metermod.parts(msym, on="--meteroff" not in argv)
    LBA = lba_map()
    sndbuild.extract(SRC_BIN, LBA)                          # stock sound files from the user's disc (tools/snd)
    global SND_PATCHES, SND_IMAGE
    SND_PATCHES, SND_IMAGE = sndbuild.exe_patches(GCC, CF, os.path.join(BUILD, "sndobj"))
    items, chars = layout()
    if "--koreload" in argv:                                 # tools/koreload: switch item after each pixel item (one read)
        sys.path.insert(0, os.path.join(GAME, "tools", "koreload"))
        import items as kitems
        KPS = {}
        for c_, h_ in chars.items():
            if not isinstance(c_, int) or c_ >= 0x17: continue
            for k_, it_ in enumerate(kitems.switch_items(h_["tabs"], h_["offs"])):
                if it_: KPS[(c_, k_)] = it_
        items = [(k_, d_ + bytes(-len(d_) % 2048) + KPS[(k_[1], k_[2])]) if k_[0] == "t" and (k_[1], k_[2]) in KPS else (k_, d_) for k_, d_ in items]
        items.append((("kpdir",), bytes(0x17 * len(TIERS) * 8)))
        items.append((("krlimg",), KRL_IMG))
    if "--dirx" in argv: items.append((("dirx",), bytes(dirx_len())))   # filled after directory() (needs pos)
    if SPS:                                          # SNDX (snd.c): the sound level table as a disc item (blob space)
        assert "--dirx" in argv, "--spustore needs --dirx"
        items.append((("sndx",), bytes(8 * len(sndbuild.S.bank_names()) * sndbuild.S.NL)))
    if "--assist" in argv: items += assist_items()     # assists lead: DAxx code / tables / dsr pixels + the table
    if ASRLE:                                        # asdip lead: the SPU front-end code as a disc item (blob space;
        items.append((("spximg",), header_words(os.path.join(HERE, "spsfe.h"), "sps_code")      # tagload.c SPS_ITEM)
                      + header_words(os.path.join(HERE, "spsfe.h"), "sps_tramp")))
    if "--strongx" in argv:                                  # filled below (<= 4 KB); g2get / vcache images (tagload.c STRONGX)
        items.append((("strongx",), bytes(4096)))
        for k_, h_, a_ in (("l2img", "l2g.h", "l2g_img"), ("vcimg", "vcache.h", "vc_img")):
            if os.path.exists(os.path.join(HERE, h_)) and (("--l2g" in argv) if k_ == "l2img" else ("--vcache" in argv)):
                items.append(((k_,), header_words(os.path.join(HERE, h_), a_)))
    P8 = None
    global mvcore, ACHMOD
    if "--ach" in argv:                                      # achievements (games/mvc/tools/ach/core): a copy of OPDEMO.ARC with
        sys.path.insert(0, os.path.join(GAME, "tools", "ach", "core"))   # the menu module after it (disc item, filled below)
        import mvcore
        ACHMOD = mvcore.module(next((a.split("=", 1)[1] for a in argv if a.startswith("--ver=")), None))
        items.insert(0, (("achopd",), bytes(len(mvcore.opdemo(bytes(LBA[mvcore.OVL_FILE][1]), ACHMOD)))))   # first: DMY1.DAT, a short seek from the original
    if "--pal8" in argv:                                     # stage-8 palette rows: 3 disc items, BG08.ARC rewritten
        import pal8, stagelite as SL_
        assert "--kocache" in argv and 8 not in SL_.selected(argv), "--pal8 needs --kocache and excludes --stagelite 8"
        src_ = Disc(SRC_BIN)
        p8arc, p8exe, p8rows, p8rep = pal8.stage_file(lambda fn: src_.read(*LBA[fn]), SL_.exe_word)
        p8items, p8n = pal8.items(p8rows)
        for k, d_ in enumerate(p8items): items.append((("pal8", k), d_))
        P8 = (p8arc, p8exe, p8items, p8n)
        print("pal8: stage 8 -%d B, %d palette rows to VRAM, fade lists packed to %d B" % (p8rep["stage_cut"], p8n, p8rep["packed"]))
    if "--sa06" in argv:                                     # lite ARCs (same size as BGnn.ARC) as disc items
        import sa06, stagelite as SL6
        src6 = Disc(SRC_BIN)
        p8w = {a_: struct.unpack("<I", d_)[0] for a_, d_ in P8[1]} if P8 else {}
        ew = SL6.exe_word
        SL6.exe_word = lambda a_: p8w.get(a_, ew(a_))           # stage 8: pal8 already relocated its EXE words
        SA6 = {}
        for st_ in sa06.STAGES:
            arc_ = P8[0] if (st_ == 8 and P8) else src6.read(*LBA["BG%02d.ARC" % st_])
            r_ = sa06.lite(st_, arc_)
            if not r_: continue
            SA6[st_] = r_; items.append((("sa06", st_), r_[0]))
            print("sa06: stage %d lite ARC -%d B (%d ranges, %d EXE words)" % (st_, sum(h - l for l, h in r_[2]), len(r_[2]), len(r_[1])))
        SL6.exe_word = ew
    dmy_lba, dmy_size = LBA["DMY1.DAT"]
    dmy_end = dmy_lba + dmy_size // 2048
    if "--bgfast" in argv or "--upskip" in argv or "--kocache" in argv: dmy_end -= 2   # bgfast / upskip / kocache sectors
    if "--dxahead" in argv: dmy_end = min(dmy_end, dmy_lba + dmy_size // 2048 - (5 if "--koprefill" in argv else 4))   # dxahead sectors (DX_MSF, 2, 3)
    nblob = (len(blob) + 4 + 4096 + 2047) // 2048               # + room for the strong payload (<= 4 KB)
    if "--dirx" in argv: nblob = max(nblob, 16)              # --dirx pads the blob to a 16-sector read
    lba = dmy_lba + nblob
    pos = {}
    img_end = os.path.getsize(SRC_BIN) // 2352
    ext = img_end                                    # what does not fit in DMY1.DAT goes after the end of the image
    for key, data in items:
        n = (len(data) + 2047) // 2048
        if lba + n <= dmy_end: pos[key] = lba; lba += n
        else: pos[key] = ext; ext += n
    appended = ext - img_end
    d = sym["tl_dir"] - ARENA
    assert blob[d:d + 4] == b"TAGL"
    frags = frag_list()
    dirb = directory(pos, chars, flags, frags)
    if "--koreload" in argv:
        assert not frags and struct.unpack_from("<I", dirb, 36)[0] == 0, "--koreload keeps its fent in frag[0..1]"
        kd_ = bytearray(0x17 * len(TIERS) * 8)
        for (c_, k_), it_ in KPS.items():
            struct.pack_into("<2I", kd_, (c_ * len(TIERS) + k_) * 8, struct.unpack("<I", msf(pos[("t", c_, k_)]))[0], len(it_))
        items = [(k_, bytes(kd_) if k_ == ("kpdir",) else d_) for k_, d_ in items]
        dirb = dirb[:40] + msf(pos[("kpdir",)]) + struct.pack("<I", len(kd_)) + msf(pos[("krlimg",)]) + struct.pack("<I", len(KRL_IMG)) + dirb[56:]
    SYM.update(sym)
    dec, dsa_off = dsh_decoder() if USE_DSH else (b"", 0)
    strong = dec                                 # payload copied to STRONG_AT after the last read: decoders, meter
    if flags & 128:                                   # post routine at a8(dec_size) (tagload.c tl_postfn)
        ds4 = len(dec) + (-len(dec) % 4)
        strong = dec + bytes(((ds4 + 7) & ~7) - len(dec)) + POST
        assert len(strong) <= metermod.MRAM - metermod.STRONG_AT, ("post routine does not fit before the meter", len(dec), len(POST), len(strong))
        vc = sorted(v[1] for k, v in LBA.items() if k.startswith("SPVC"))
        PA_LO, PA_HI, PA_LIM = 0x80095c40, 0x8009a8a4, 0x8009ac40
        sec_ = lambda x: (x + 2047) & ~2047
        for a in vc:                                   # every pair (largest two decide): tagload.c placement
            for b in vc:
                bs = (PA_HI - b) & ~7
                if bs + sec_(b) > PA_LIM: bs = (PA_LIM - sec_(b)) & ~7
                bs2 = (PA_HI - a) & ~7
                if bs2 + sec_(a) > PA_LIM: bs2 = (PA_LIM - sec_(a)) & ~7
                assert PA_LO + a <= bs or PA_LO + b <= bs2, ("SPVC pair does not fit the arena tail", a, b)
    if mparts:
        ram_ = mparts[1]
        if "--stageanim" in argv:                    # tools/gameplay/stageanim.py: RAM part right after the meter's
            import stageanim
            assert metermod.MRAM + len(ram_) <= stageanim.SA and stageanim.SA_END == metermod.MEND
            ram_ = ram_ + bytes(stageanim.SA - metermod.MRAM - len(ram_)) + stageanim.ram_part()
        strong = metermod.strong(strong, ram_)
    if strong:
        strong += bytes(-len(strong) % 4)
        dirb = dirb[:4] + struct.pack("<4I", len(strong), metermod.STRONG_AT, len(dec) + (-len(dec) % 4), dsa_off) + dirb[20:]
    if "--dirx" in argv:                             # tagload.c DIRX: header .. exe_msf, fent full, struct chr c[4]
        hl = len(dirb) - dirx_len()
        full = dirb[hl:]
        items = [(k, full if k == ("dirx",) else v) for k, v in items]
        assert len(full) == len(dict(items)[("dirx",)]), "DIRX item size changed after placement"
        dirb = dirb[:hl] + msf(pos[("dirx",)]) + struct.pack("<I", len(full)) + bytes(4 * CHR)
        assert sym["blob_end"] - sym["tl_dir"] >= len(dirb), "DIRX dir struct size mismatch"
    blob = blob[:d] + dirb + blob[d + len(dirb):]
    ds = sym["snd_dir"] - ARENA                             # tools/snd directory (struct sdir in snd.c)
    if SPS:
        sdir, stab = sndbuild.directory(pos, msf, SND_IMAGE, split=msf(pos[("sndx",)]))
        assert len(stab) == len(dict(items)[("sndx",)])
        items = [(k, stab if k == ("sndx",) else v) for k, v in items]
    else:
        sdir = sndbuild.directory(pos, msf, SND_IMAGE)
    assert blob[ds:ds + 4] == sndbuild.MAGIC and ds + len(sdir) <= d
    if "--nosnd" in argv: sdir = b"NONE" + sdir[4:]               # A/B: stock sound handling (snd_* do nothing)
    blob = blob[:ds] + sdir + blob[ds + len(sdir):]
    assert len(blob) == sym["blob_end"] - ARENA and sym["tl_strong"] == sym["blob_end"]
    if "--assist" in argv:
        tab_ = assist_table(pos)
        items = [(k, tab_ if k == ("asx",) else v) for k, v in items]
        ax = sym["tl_asx"] - ARENA
        blob = blob[:ax] + msf(pos[("asx",)]) + struct.pack("<I", len(tab_)) + blob[ax + 8:]
    if "--strongx" in argv:                           # tagload.c STRONGX: read to TOP - 4096, copied down to STRONG
        if "--kofix" in argv:                         # hwfix: the CHK image rides in the same item at +3072
            assert len(strong) <= 0xc00, len(strong)
            strong = strong + bytes(0xc00 - len(strong)) + header_words(os.path.join(HERE, "chkrt.h"), "chk_code")
        assert len(strong) <= 4096
        items = [(k, strong if k == ("strongx",) else v) for k, v in items]
        sx = sym["tl_sx"] - ARENA
        blob = blob[:sx] + msf(pos[("strongx",)]) + struct.pack("<I", len(strong)) + blob[sx + 8:]
        for k_, s_, lim_ in (("l2img", "tl_l2x", 4560), ("vcimg", "tl_vcx", 0xd40)):
            if (k_,) in pos:
                d_ = dict(items)[(k_,)]; assert (len(d_) + 2047) // 2048 * 2048 <= lim_, (k_, len(d_))
                o_ = sym[s_] - ARENA
                blob = blob[:o_] + msf(pos[(k_,)]) + struct.pack("<I", len(d_)) + blob[o_ + 8:]
        if ASRLE:                                    # tagload.c SPS_ITEM: 1 sector read into the staging buffer (2112 B)
            d_ = dict(items)[("spximg",)]; assert len(d_) <= 2048
            o_ = sym["tl_spx"] - ARENA
            blob = blob[:o_] + msf(pos[("spximg",)]) + struct.pack("<I", len(d_)) + blob[o_ + 8:]
        print("strongx: payload %d B as a disc item, blob %d B" % (len(strong), len(blob)))
        strong = b""
    blob += strong
    assert len(blob) + 4 <= nblob * 2048
    blob += bytes(-len(blob) % 4)
    blob += struct.pack("<I", -sum(struct.unpack(f"<{len(blob) // 4}I", blob)) & 0xFFFFFFFF)
    # the blob is read in whole 2 KB sectors into the tile decode area; game data from 0x8009b805 (set before the
    # battle, never rewritten) must survive: at most 17 sectors (18 -> freeze at a KO hand-over, ap8 worker)
    assert ARENA + (len(blob) + 2047) // 2048 * 2048 <= 0x8009b805, f"blob {len(blob)} B: more than 17 sectors"
    # 2026-11-18: a 34,004 B blob (data up to 0x8009b214) hung the GPU in Hyper Mega Man (stage 2): live data between
    # 0x8009adf4 and 0x8009b214 that the blob bytes clobber.  Largest blob with a full regression: 32,948 B.
    # 2026-11-18 (bgfast): a 32,908 B blob failed glue's word sum (tl_dbg 0xfb, stock load) in a wprof stage-1 boot:
    # the RAM past ~0x8009ac44 is NOT quiet during the read on every path.  Limit = tag11 (31,632 B) + margin.
    assert len(blob) <= 31800, f"blob {len(blob)} B: more than the 31,800 B limit (0xfb seen at 32,908 B)"
    if flags & 128 and "--dirx" in argv and ARENA + (len(blob) + 2047) // 2048 * 2048 < 0x8009ac40:
        blob += bytes(0x8009ac40 - 2048 + 4 - ARENA - len(blob))      # --dirx: smaller content, read stays 16 sectors
        assert len(blob) <= nblob * 2048
    if flags & 128:                                   # the post reads' sector tails stay inside what the blob read
        assert ARENA + (len(blob) + 2047) // 2048 * 2048 >= 0x8009ac40, "blob < 16 sectors: PA_LIM (tagload.c)"
    blob_ent = msf(dmy_lba) + struct.pack("<I", len(blob))
    if "--ldbuf" in argv:                             # rc4.10: LDBUF_W = the blob's ldbuf_at constant (tagload.c LDBUF)
        global LDBUF_VAL
        LDBUF_VAL = struct.unpack_from("<I", blob, sym["ldbuf_at"] - ARENA)[0]
        assert 0x801f0000 <= LDBUF_VAL < 0x801fce00 and LDBUF_VAL % 128 == 0, hex(LDBUF_VAL)
        print("ldbuf: winner prim buffer %08x-%08x" % (LDBUF_VAL, LDBUF_VAL + 0x1000))
    patches = exe_patches(sym, glue, res, blob_ent, mparts, frags)
    if "--ram" in argv:
        return patches, blob, sym
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, name + ".bin")
    shutil.copyfile(SRC_BIN, out)
    img = Img(out)
    if appended:                                     # form-1 data sectors after the last one (+150 empty: read-ahead)
        img.extend(img_end, appended + 150)
    exe_lba, exe_size = LBA["SLUS_010.59"]
    for at, orig in ((HOOK, HOOK_ORIG), (HEAPHOOK, (HEAPHOOK_ORIG,)), (QUICKLOAD_AT, (QUICKLOAD_ORIG,))):
        for i, w in enumerate(orig):
            assert img.rbytes(exe_lba, at - EXE_BASE + EXE_HDR + 4 * i, 4) == struct.pack("<I", w), "hook site not stock"
    if "--notaunt" in argv:
        assert img.rbytes(exe_lba, TAUNT_SB - EXE_BASE + EXE_HDR, 4) == struct.pack("<I", TAUNT_SB_ORIG), "--notaunt site not stock"
    for a, data in patches:
        img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
    if "--bgfast" in argv:
        import bgfast
        img.wbytes(dmy_end + 1, 0, bgfast.sector())
    if "--kocache" in argv:
        import kocache
        assert sym["tl_dbg"] == kocache.TLDBG and sym["flushcache"] == kocache.FLUSH and sym["dshptr"] == kocache.DSHPTR and sym["dsaptr"] == kocache.DSAPTR
        site = [w for a, w in patches if a == kocache.HSITE]
        assert site == [struct.pack("<I", 0x0c000000 | (sym["heapcap"] >> 2 & 0x3ffffff))], "kocache: 0x8002b528 is not jal heapcap"
        assert "--bgfast" not in argv and "--upskip" not in argv, "--kocache uses the bgfast / upskip sector and 0x801fe000"
        ksec = kocache.sector()
        if P8:                                       # pal8 code + item table after the KO code (same sector, KO_SIZE covers it)
            import pal8
            c8, s8 = pal8.code(p8_at(kocache), sym["heapcap"])
            tab = pal8.table([(struct.unpack("<I", msf(pos[("pal8", k)]))[0], len(P8[2][k])) for k in range(3)], P8[3])
            o = s8["P8TAB"] - p8_at(kocache)
            c8 = c8[:o] + tab + c8[o + len(tab):]
            if KOSPLIT: psec = c8 + bytes(2048 - len(c8))
            else: ksec = ksec[:kocache.SIZE] + c8 + bytes(2048 - kocache.SIZE - len(c8))
            for a, w in ((pal8.APSITE, pal8.APW[0]), (pal8.APSITE + 4, pal8.APW[1]), (pal8.HSITE, 0x0c000000 | (sym["heapcap"] >> 2 & 0x3ffffff))):
                assert struct.unpack("<I", img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, 4))[0] == w, "pal8 hook site %08x" % a
        if KOSPLIT:                                  # --kosplit: [pal8 sector][kocache sector] = the last two (KO_MSF = the first)
            img.wbytes(dmy_lba + dmy_size // 2048 - 2, 0, psec if P8 else bytes(2048))
            img.wbytes(dmy_lba + dmy_size // 2048 - 1, 0, ksec)
        else:
            img.wbytes(dmy_lba + dmy_size // 2048 - 2, 0, ksec)   # = KO_MSF (second-last sector)
    if "--upskip" in argv:
        import upskip
        assert sym["tl_dbg"] == upskip.TLDBG
        for a, w in ((upskip.LOGF, 0x27bdffe0), (upskip.LOGF + 4, 0x00804021), (upskip.UPSITE, 0x0c0230c6)):
            assert img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, 4) == struct.pack("<I", w), "upskip hook site not stock"
        img.wbytes(dmy_end, 0, upskip.sector())
    if "--dxahead" in argv:
        import dxahead
        assert sym["tl_dbg"] == 0x8001b4e0
        for a_, w_ in ((dxahead.H1, dxahead.H1W0), (dxahead.H2, dxahead.H2W0), (dxahead.H3, dxahead.H3W0)):
            assert img.rbytes(exe_lba, a_ - EXE_BASE + EXE_HDR, 4) == struct.pack("<I", w_), "dxahead hook site not stock"
        for a_, d_ in patches:
            for h_ in (dxahead.H1, dxahead.H2, dxahead.H3): assert not (a_ <= h_ < a_ + len(d_)), "dxahead hook site patched"
        for k_, sec_ in enumerate(dxahead.sectors(0x8001b4e0)):
            img.wbytes(dmy_lba + dmy_size // 2048 - 3 - k_, 0, sec_)
    if "--nogpovl" not in argv:                      # tools/gameplay/allpatches.py: select / VS / main-menu overlays
        import allpatches as gpovl
        src = Disc(SRC_BIN)
        asl = "--assistsel" in argv                  # assists helper B: stock assist roulette in the select (assistsel.py)
        gpovl.check(lambda fn: src.read(*LBA[fn]), assist=asl)
        ver = next((a.split("=", 1)[1] for a in argv if a.startswith("--ver=")), None)
        for fn, off, data in gpovl.overlay_patches(ver, assist=asl):
            img.wbytes(LBA[fn][0], off, data)
        if "--askeep" in argv:                       # assist bugs lead: ARCADE stage screen no longer re-picks the
            assert asl, "--askeep needs --assistsel"     # human's assist (tools/gameplay/askeep.py)
            import askeep
            l_, n_ = LBA[askeep.FILE]
            askeep.check_file(img.rbytes(l_, 0, n_))
            for fn, off, data in askeep.overlay_patches():
                img.wbytes(LBA[fn][0], off, data)
        if "--galexit" in argv:                      # (2026-11-25) GALLERY -> ILLUSTRATION -> back: ILLUST.BIN sets main-menu
            l_, n_ = LBA["DAT/ILLUST.BIN"] if "DAT/ILLUST.BIN" in LBA else LBA["ILLUST.BIN"]   # state 5 = stock GALLERY; since menus.py
            w_ = img.rbytes(l_, 0x15ec, 4)                                                       # (CROSS OVER gone) GALLERY = state 4 and
            assert w_ == struct.pack("<I", 0x24020005), "ILLUST.BIN +0x15ec not stock"            # 5 = OPTION / ACHIEVEMENTS page
            img.wbytes(l_, 0x15ec, struct.pack("<I", 0x24020004))
        if "--asselfix" in argv:                     # assist-bugs helper B (rc4.8): partner figure / name kept under the
            assert asl, "--asselfix needs --assistsel"   # roulette (tools/gameplay/asselfix.py)
            import asselfix
            l_, n_ = LBA[asselfix.FILE]
            asselfix.check_file(img.rbytes(l_, 0, n_))
            for fn, off, data in asselfix.overlay_patches():
                img.wbytes(LBA[fn][0], off, data)
        assert "--asrou" not in argv or "--asopt" in argv, "--asrou needs --asopt"
        assert "--asrow1" not in argv or ("--asopt" in argv and "--asrou" in argv), "--asrow1 (one ASSISTS row) needs --asopt --asrou"
        assert "--infmeter" not in argv or ("--exopt" in argv and "--ach" in argv and "--voicehi" not in argv and "--voicevol" not in argv),             "--infmeter (EX row INFINITE SUPER METER) needs --exopt --ach (refill + no-unlock in the ach core), excludes --voicehi / --voicevol (same byte)"
        if "--asopt" in argv:                       # assist-bugs helper C (rc4.8): EX rows ASSIST / ASSIST MODE, select +
            assert asl and "--exopt" in argv and "--assist" in argv, "--asopt needs --assistsel --exopt --assist"
            # --asrou (rc4.9): ASSIST MODE byte 0 = ROULETTE (default) + stock code reader on (arcade rules), asopt.rou()
            import asopt                             # VS screen side (tools/gameplay/asopt.py; rows: exopt.rows)
            l_, n_ = LBA[asopt.FILE]
            asopt.check_file(img.rbytes(l_, 0, n_))
            for fn, off, data in asopt.overlay_patches():
                img.wbytes(LBA[fn][0], off, data)
        if "--onsl" in argv:                         # playable Onslaught: hidden cell open + (with --assistsel) no roulette
            import onsl                              # for his side (tools/gameplay/onsl.py; after asopt: chains its clr)
            l_, n_ = LBA[onsl.FILE]
            onsl.check_file(img.rbytes(l_, 0, n_))
            if asl: onsl.check_slack(img.rbytes(l_, 0, (n_ + 2047) // 2048 * 2048), argv)
            for fn, off, data in onsl.overlay_patches(argv if asl else ()):
                img.wbytes(LBA[fn][0], off, data)
    vss = next((int(a_.split("=", 1)[1]) for a_ in argv if a_.startswith("--vsstage=")), None)
    if vss is not None:                              # TEST builds (dx 2026-11-19, preko discs): VERSUS stage pinned.  The
        assert 0 <= vss <= 8 and "--nogpovl" not in argv   # select overlay copies the VERSUS stage setting 0x8007b780 into the
        import selscreen as _ss                      # stage byte at SEL01 0x8018f070 (`lbu v1, -0x4880(v0)`) -> `li v1, N`
        _o = 0x8018f070 - _ss.BASE                   # (--stage / --stagetab do not reach this path)
        assert img.rbytes(LBA[_ss.FILE][0], _o, 4) == struct.pack("<I", 0x9043b780), "SEL01 VERSUS stage read not stock"
        img.wbytes(LBA[_ss.FILE][0], _o, struct.pack("<I", 0x24030000 | vss))
    if "--stageanim" in argv:                       # STAGE ANIM option line + battle hook (tools/gameplay/stageanim.py)
        import stageanim
        assert mparts, "--stageanim needs the meter (its RAM part rides with it)"
        src = Disc(SRC_BIN)
        stageanim.check(lambda a: struct.unpack("<I", img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, 4))[0], src.read(*LBA[stageanim.OPD]))
        for fn, off, data in stageanim.overlay_patches():
            img.wbytes(LBA[fn][0], off, data)
        sap = stageanim.exe_patches()
        for a, data in sap:
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "stageanim patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        patches = list(patches) + list(sap)
    if "--frameskip" in argv:                         # FRAME SKIP option line (tools/hwprof/frameskip.py; =auto: no line)
        import frameskip
        for fn, off, data in frameskip.overlay_patches(
                lambda a: struct.unpack("<I", img.rbytes(LBA[frameskip.OPD][0], a - frameskip.OPD_BASE, 4))[0]):
            img.wbytes(LBA[fn][0], off, data)
    if "--exopt" in argv:                            # EX OPTIONS (fx worker, rc4.1+): own main-menu screen in the OPDEMO slack
        assert "--fs05" in argv, "--exopt: the option bytes / PAUSE rows are the --fs05 ones"   # (tools/gameplay/exopt.py);
        import optrows, exopt                                                                     # stock OPTION MODE stays stock
        assert LBA[optrows.OPD][1] == optrows.OPD_SIZE, "OPDEMO.ARC size changed: slack moved"
        for fn, off, data in exopt.overlay_patches(argv):
            assert img.rbytes(LBA[fn][0], off, len(data)) == bytes(len(data)), "OPDEMO slack not free"
            img.wbytes(LBA[fn][0], off, data)
        if mvcver.text_of(argv) and "--titlefix" in argv:   # rc4.8 tester: stub resident in the EXE (mvcver.resident_patches)
            (ea, code), [(fn2, off2, jw)] = mvcver.resident_patches(mvcver.text_of(argv))
            eo = ea - EXE_BASE + EXE_HDR
            so = mvcver.RES - EXE_BASE + EXE_HDR
            assert img.rbytes(LBA["SLUS_010.59"][0], so, len(mvcver.RES_ORIG)) == mvcver.RES_ORIG, "--titlefix: SDK string span not stock"
            assert img.rbytes(LBA[fn2][0], off2, 4) == struct.pack("<I", mvcver.MENU_ORIG), "--title: menu routine end not stock"
            img.wbytes(LBA["SLUS_010.59"][0], eo, code); img.wbytes(LBA[fn2][0], off2, jw)
            print("title: '%s', stub %d B at %08x (EXE, --titlefix)" % (mvcver.text_of(argv), len(code), ea))
        elif mvcver.text_of(argv):                   # (logo) --title[=TEXT]: main-menu version line (tools/gameplay/mvcver.py)
            (fn, off, code), (fn2, off2, jw) = mvcver.overlay_patches(mvcver.text_of(argv))
            assert img.rbytes(LBA[fn][0], off, len(code)) == bytes(len(code)), "--title: OPDEMO slack end not free (EX OPTIONS code too long)"
            assert img.rbytes(LBA[fn2][0], off2, 4) == struct.pack("<I", mvcver.MENU_ORIG), "--title: menu routine end not stock"
            img.wbytes(LBA[fn][0], off, code); img.wbytes(LBA[fn2][0], off2, jw)
            print("title: '%s', stub %d B at %08x" % (mvcver.text_of(argv), len(code), optrows.OPD_BASE + off))
    elif "--fs05" in argv:                           # fs05 (fx worker): OPTION rows + values (tools/gameplay/optrows.py)
        assert "--frameskip" in argv, "--fs05: the PAUSE row lives in the FRAME SKIP menu spans"
        import optrows
        assert LBA[optrows.OPD][1] == optrows.OPD_SIZE, "OPDEMO.ARC size changed: slack moved"
        for fn, off, data in optrows.overlay_patches(
                lambda a: struct.unpack("<I", img.rbytes(LBA[optrows.OPD][0], a - optrows.OPD_BASE, 4))[0]):
            img.wbytes(LBA[fn][0], off, data)
    if P8:                                           # pal8: BG08.ARC without the palette rows, EXE table words
        assert len(P8[0]) == LBA["BG08.ARC"][1]
        img.wbytes(LBA["BG08.ARC"][0], 0, P8[0])
        for a, data in P8[1]:
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "pal8 patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        patches = list(patches) + list(P8[1])
    if any(a.startswith("--stagelite") for a in argv):  # tools/gameplay/stagelite.py: smaller stage overlays (default off)
        import stagelite
        src = Disc(SRC_BIN)
        sfiles, sexe = stagelite.files(lambda fn: src.read(*LBA[fn]), stagelite.selected(argv))
        for fn, data in sfiles:
            assert len(data) == LBA[fn][1]
            img.wbytes(LBA[fn][0], 0, data)
        for a, data in sexe:                           # per-stage EXE table entries (spawn list / CLUTs)
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "stagelite patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        patches = list(patches) + list(sexe)          # also in NAME.patches.json (tests poke the EXE patches)
    if SA6 is not None:                              # sa06 VS hook in SEL01's last sector + the call site
        import sa06, selscreen as _ss6
        sl = LBA[_ss6.FILE]
        rex = lambda a_: struct.unpack("<I", img.rbytes(exe_lba, a_ - EXE_BASE + EXE_HDR, 4))[0]
        lmsf = [struct.unpack("<I", msf(pos[("sa06", st_)]))[0] if st_ in SA6 else 0 for st_ in range(9)]
        recs = [(st_, a_, rex(a_), n_) for st_ in sorted(SA6) for a_, o_, n_ in SA6[st_][1]]
        for st_, a_, full_, n_ in recs:
            o_ = next(o for a2, o, n in SA6[st_][1] if a2 == a_)
            assert full_ == o_, "sa06: EXE word %08x is %08x, lite built from %08x" % (a_, full_, o_)
        if "--fs05" in argv:                             # fs05: option values in optrows' RAM bytes (fx worker)
            import optrows
            mode6 = optrows.byte("STAGE ANIM", argv)
        else:
            mode6 = 0x8007b708
        code6, (site6, w6) = sa06.hook(lmsf, recs, mode_addr=mode6, force_off="--sa06off" in argv)   # --sa06off: TEST build, OFF forced
        print("sa06: STAGE ANIM mode byte %08x" % mode6)
        assert sl[1] == sa06.HOOK_AT - _ss6.BASE and img.rbytes(sl[0], sl[1], len(code6)) == bytes(len(code6)), "SEL01 tail not free"
        assert img.rbytes(sl[0], site6 - _ss6.BASE, 4) == struct.pack("<I", sa06.SITE_STOCK), "SEL01 stage read not stock"
        img.wbytes(sl[0], sa06.HOOK_AT - _ss6.BASE, code6)
        img.wbytes(sl[0], site6 - _ss6.BASE, w6)
        print("sa06: hook %d B at %08x, %d stages, %d EXE words" % (len(code6), sa06.HOOK_AT, len(SA6), len(recs)))
    if any(a.startswith("--cpufast") for a in argv):  # tools/cpuprof/cpufast.py: game-logic rewrites (opt-in, CPU worker)
        sys.path.insert(0, os.path.join(GAME, "tools", "cpuprof"))
        import cpufast
        cfw = next((a.split("=", 1)[1] for a in argv if a.startswith("--cpufast=")), None)
        rd_ = lambda a, n: img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, n)
        for a, data in cpufast.stock_words():
            assert rd_(a, len(data)) == data, "cpufast site %08x not stock" % a
        cfp = cpufast.patches(cfw)
        for a, data in cfp:
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "cpufast patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        patches = list(patches) + list(cfp)
    if "--arcbal" in argv:                           # ARCADE BALANCE (tools/gameplay/arcbal.py, docs/ARCADE_BALANCE.md): EX row +
        assert "--exopt" in argv and "--sa06" not in argv, "--arcbal needs --exopt, excludes --sa06 (same SEL01 site + tail)"
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay"))
        import arcbal, selscreen as _ssab
        spd_ = "--arcspeed" in argv
        sl_ = LBA[_ssab.FILE]
        rex_ = lambda a_: struct.unpack("<I", img.rbytes(exe_lba, a_ - EXE_BASE + EXE_HDR, 4))[0]
        for a_, w_ in arcbal.stock_words(spd_):
            assert rex_(a_) == w_, "arcbal: EXE word %08x is %08x, expected stock %08x" % (a_, rex_(a_), w_)
        codeab, (siteab, wab) = arcbal.hook(spd_)
        assert sl_[1] == arcbal.HOOK_AT - _ssab.BASE, "arcbal: SEL01 size changed"
        assert img.rbytes(sl_[0], siteab - _ssab.BASE, 4) == struct.pack("<I", arcbal.SITE_STOCK), "arcbal: SEL01 select site not stock"
        img.wbytes(sl_[0], siteab - _ssab.BASE, wab)
        assert img.rbytes(sl_[0], sl_[1], len(codeab)) == bytes(len(codeab)), "arcbal: SEL01 last-sector slack not free"
        img.wbytes(sl_[0], sl_[1], codeab)               # in place: the select path loads SEL01 whole sectors (no copy / seek)
        abp = arcbal.exe_patches()                   # empty: cold boot = OFF (the hook writes the row's set before every VS-path battle)
        for a_, d_ in abp:
            for b, d in patches:
                assert a_ + len(d_) <= b or a_ >= b + len(d), "arcbal patch %08x overlaps %08x" % (a_, b)
            img.wbytes(exe_lba, a_ - EXE_BASE + EXE_HDR, d_)
        patches = list(patches) + list(abp)
        print("arcbal: hook %d B at %08x (SEL01 slack, in place), %d words swapped, OFF at boot%s" % (len(codeab), arcbal.HOOK_AT, len(arcbal.groups()[0][2]), ", ARCADE SPEED row" if spd_ else ""))
    else:
        assert "--arcspeed" not in argv, "--arcspeed needs --arcbal"
    if "--excard" in argv:                       # (2026-11-24) EX OPTIONS rows in MvC's own card save (tools/gameplay/excard.py)
        assert "--exopt" in argv, "--excard: needs --exopt"
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import excard
        stock_exe = _stock_exe()
        rx_ = lambda a, n: img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, n)
        ro_ = lambda a, n: img.rbytes(LBA[excard.OPD][0], a - excard.OPD_BASE, n)
        exc, opc, sy_ = excard.patches(argv, rx_, ro_)
        for a_, d_ in exc:
            n_ = len(d_)                         # (its own bytes: the span tail can hold other flags' code, e.g. --onslfix 0x80049da4; overlap checked below)
            assert rx_(a_, n_) == stock_exe[a_ - EXE_BASE + EXE_HDR:a_ - EXE_BASE + EXE_HDR + n_], "--excard: EXE span %08x not stock (used by another flag)" % a_
            for b, d in patches:
                assert a_ + len(d_) <= b or a_ >= b + len(d), "--excard patch %08x overlaps %08x" % (a_, b)
            img.wbytes(exe_lba, a_ - EXE_BASE + EXE_HDR, d_)
        for off_, w_ in opc: img.wbytes(LBA[excard.OPD][0], off_, w_)
        patches = list(patches) + list(exc)
        print("excard: EX rows on the card: save hook %08x, load hook %08x, %d B in %d EXE spans" % (sy_["svhook"], sy_["ldhook"], sum(len(d) for a, d in exc), len(exc)))
    ach = None
    if "--ach" in argv or "--achold" in argv:   # built-in achievements (games/mvc/tools/ach, docs/ACHIEVEMENTS.md), on top of everything else
        sys.path.insert(0, os.path.join(GAME, "tools", "ach"))
        import mvcach
        ol = LBA[mvcach.OVL_FILE][0]
        _ach_args = (lambda a, n: img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, n), lambda o, n: img.rbytes(exe_lba, o, n),
                     lambda a, n: img.rbytes(ol, a - mvcach.OVL_BASE, n),
                     next((a.split("=", 1)[1] for a in argv if a.startswith("--ver=")), None))
        if "--ach" in argv:      # rc4 line (freeze worker 2026-11-20): resident core in kernel spans + menu module in OPDEMO
            ach = mvcore.parts(*_ach_args)
            n_ = LBA[mvcore.OVL_FILE][1] + 2047 & ~2047           # OPDEMO.ARC as every edit left it (incl. its last-sector
            opd_ = mvcore.opdemo(img.rbytes(ol, 0, n_), ACHMOD)    # slack: exopt), + the module -> the "achopd" item
            items = [(k_, opd_ if k_ == ("achopd",) else d_) for k_, d_ in items]
            ft_ = mvcore.FTAB + 8 * mvcore.OPD_INDEX              # the game's file table entry of OPDEMO.ARC -> the copy
            assert img.rbytes(exe_lba, ft_ - EXE_BASE + EXE_HDR, 8) == msf(ol) + struct.pack("<I", LBA[mvcore.OVL_FILE][1]), "OPDEMO.ARC file table entry"
            ftw_ = msf(pos[("achopd",)]) + struct.pack("<I", len(opd_))
            for b, d in patches:
                assert ft_ + 8 <= b or ft_ >= b + len(d), "achievements file-table patch %08x overlaps %08x" % (ft_, b)
            img.wbytes(exe_lba, ft_ - EXE_BASE + EXE_HDR, ftw_)
            patches = list(patches) + [(ft_, ftw_)]
            print("achievements: OPDEMO.ARC copy %d B + module %d B at lba %d (file table %08x)" % (n_, len(ACHMOD), pos[("achopd",)], ft_))
            if "--modreload" in argv:   # (2026-11-24) the copy's tail for the core's menu re-read (mvcore.RL_*): private entry
                assert "--titlefix" in argv and "--diag" not in argv and "--mtap" not in argv, "--modreload: needs --titlefix; the RL_AT bytes are DIAG's / mtap's spare"
                rl_ = mvcore.RL_AT - EXE_BASE + EXE_HDR
                assert img.rbytes(exe_lba, rl_, 8) == b"Library ", "--modreload: RL_AT not the stock SDK string"
                for b, d in patches:
                    assert mvcore.RL_AT + 8 <= b or mvcore.RL_AT >= b + len(d), "--modreload entry %08x overlaps %08x" % (mvcore.RL_AT, b)
                rlw_ = msf(pos[("achopd",)] + mvcore.RL_SECTOR) + struct.pack("<I", len(opd_) - mvcore.RL_SECTOR * 2048)
                MODRL = (rl_, rlw_)       # written after the --vscpu block (mtpatch's guard reads the stock span prefix)
                print("modreload: tail entry %08x = lba %d, %d B -> %08x (index %d)" % (mvcore.RL_AT, pos[("achopd",)] + mvcore.RL_SECTOR,
                      len(opd_) - mvcore.RL_SECTOR * 2048, mvcore.RL_DEST, mvcore.RL_INDEX))
        else:                   # the 2026-11-17 runtime (emulator only: its kernel regions crash a real PS1)
            ach = mvcach.parts(*_ach_args)
        for a, data in ach["exe"]:
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "achievements patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        img.wbytes(exe_lba, 0x10, struct.pack("<I", ach["pc0"]))
        for off, data in ach["ovl"]:
            img.wbytes(ol, off, data)
        i = ach["info"]
        print("achievements: A %d+%d bss (free %d), B %d (free %d), C %d" % (i["image"], i["bss"], i["free"], i["imageb"], i["freeb"], i["imagec"]))
    def _mtv_stock_sel01(off, n):
        f_ = open(SRC_BIN, "rb"); l_ = LBA["SEL01.ARC"][0]; out = bytearray()
        for i in range(n):
            o = off + i; f_.seek((l_ + o // 2048) * 2352 + 24 + o % 2048); out += f_.read(1)
        f_.close(); return bytes(out)
    mtp = None
    if "--vscpu" in argv and "--mtap" not in argv:   # (rc4.15) VERSUS CPU main-menu row, no multitap: all resident in the
        assert "--ach" in argv and "--exopt" in argv, "--vscpu without --mtap = the menu row: needs the --ach menu module"
        sys.path.insert(0, os.path.join(GAME, "tools", "mtap")); import mvcmtap   # EXE debug-string block (mvcmtap.CFG_M)
        mtp, mtc = mvcmtap.patches_m(lambda a, n: img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, n))
        for a, data in mtp:
            for b, d in list(patches) + (list(ach["exe"]) if ach else []):
                assert a + len(data) <= b or a >= b + len(d), "vscpu patch %08x overlaps %08x" % (a, b)
        for a, data in mtp:
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        patches = list(patches) + list(mtp)
        print("vscpu (menu): %d bytes in %s (%d free), mt_tick %08x" % (mtc["used"], [(hex(a), len(d)) for a, d in mtc["segs"]], mtc["free"], mtc["sym"]["mt_tick"]))
        assert "ovl" not in mtc and not mtc.get("kernel"), "vscpu (menu): resident only (no SEL01 module: VS-screen texture)"
    if "--modreload" in argv:      # (2026-11-24) the private tail entry (see the --ach block); --mtap is refused there
        for a, data in (mtp or []):
            assert mvcore.RL_AT + 8 <= a or mvcore.RL_AT >= a + len(data), "--modreload entry overlaps vscpu %08x" % a
        img.wbytes(exe_lba, MODRL[0], MODRL[1])
        patches = list(patches) + [(mvcore.RL_AT, MODRL[1])]
        if "--menufont" in argv:   # (2026-11-25) BATTLE.TEX rows 32-63 for the core's menu font re-upload (mvcore.MF_*)
            mf_ = mvcore.MF_AT - EXE_BASE + EXE_HDR
            assert img.rbytes(exe_lba, mf_, 8) not in (b"", None)
            for a, data in list(patches) + list(mtp or []):
                assert mvcore.MF_AT + 8 <= a or mvcore.MF_AT >= a + len(data), "--menufont entry overlaps %08x" % a
            bt_ = [k for k in LBA if k.upper().startswith("BATTLE.TEX")]
            assert len(bt_) == 1, bt_
            mfw_ = msf(LBA[bt_[0]][0] + mvcore.MF_SECTOR) + struct.pack("<I", mvcore.MF_SIZE)
            img.wbytes(exe_lba, mf_, mfw_); patches = list(patches) + [(mvcore.MF_AT, mfw_)]
            print("menufont: entry %08x = lba %d, %d B -> %08x (index %d), was %r" % (mvcore.MF_AT, LBA[bt_[0]][0] + mvcore.MF_SECTOR,
                  mvcore.MF_SIZE, mvcore.MF_BUF, mvcore.MF_INDEX, img.rbytes(exe_lba, mf_, 8)))
    elif "--mtap" in argv:         # (multitap lead) 2-4 players: common/mtap/mtcore.c in the EXE debug-string block only
        sys.path.insert(0, os.path.join(GAME, "tools", "mtap"))       # (tools/mtap/mvcmtap.py; every replaced word checked stock)
        import mvcmtap
        mtp, mtc = (mvcmtap.patches_v if "--vscpu" in argv else mvcmtap.patches)(lambda a, n: img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, n))
        for a, data in mtp:
            for b, d in list(patches) + (list(ach["exe"]) if ach else []):
                assert a + len(data) <= b or a >= b + len(d), "mtap patch %08x overlaps %08x" % (a, b)
        for a, data in mtp:
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        patches = list(patches) + list(mtp)
        print("mtap: %d bytes in %s (%d free), mt_tick %08x" % (mtc["used"], [(hex(a), len(d)) for a, d in mtc["segs"]], mtc["free"], mtc["sym"]["mt_tick"]))
        if "--vscpu" in argv:    # (vs cpu lead) the select module inside SEL01 (mvcmtap.MOD_AT)
            assert "--diag" not in argv, "--vscpu uses the kernel spans the DIAG runtime takes"
            aram_ = [(a, len(d)) for a, d in (ach["ram"] if ach else [])]
            for ka_, kn_ in mtc["kernel"]:
                assert 0x8000C110 <= ka_ and ka_ + kn_ <= 0x8000C7F0, "vscpu kernel span (achbuild C110-C7F0, cut from the dx pool)"
                for b, n_ in aram_:
                    assert ka_ + kn_ <= b or ka_ >= b + n_, "vscpu kernel %08x overlaps the achievements' %08x" % (ka_, b)
            sys.path.insert(0, os.path.join(GAME, "tools", "mtap")); import mvcmtap as _mtv
            sl_ = LBA["SEL01.ARC"]
            sp_ = _mtv.sel01_patches(mtc)
            assert img.rbytes(sl_[0], sp_[1][0], 4) == struct.pack("<I", _mtv.SELMAIN), "vscpu: SEL01 select-main table word not stock"
            _tw = img.rbytes(sl_[0], sp_[2][0], 124)
            assert _tw[3] == 0x27 and _tw[2] == 0xbd and _tw == _mtv_stock_sel01(sp_[2][0], 124), "vscpu: SEL01 trampoline site not the stock (dead) function"
            for o_, d_ in sp_:   # in place: same size, same file table entry (--arcbal's SEL01 copy gets the same bytes)
                img.wbytes(sl_[0], o_, d_)
            if ("absel",) in dict(items):
                ab_ = bytearray(dict(items)[("absel",)])
                for o_, d_ in sp_: ab_[o_:o_ + len(d_)] = d_
                items = [(k_, bytes(ab_) if k_ == ("absel",) else d_) for k_, d_ in items]
            print("vscpu: module %d B in SEL01 at %08x (in place), kernel %s" % (len(mtc["ovl"][1]), mtc["ovl"][0], [(hex(a), n) for a, n in mtc["kernel"]]))
    # kernel RAM 0x80000000-0x8000ffff: a real console boot (SCPH-5500 + PSIO, 2026-11-17) leaves data in C000-C0FF,
    # C800-E4FF, E600-EFFF (XvSF / MSHvSF code there black-screened); only these spans are safe on hardware
    KSAFE = [(0x7600, 0x8400), (0x8700, 0x8900), (0x9400, 0x9500), (0x9a00, 0x9d00), (0xa000, 0xb000), (0xb100, 0xb800),
             (0xc100, 0xc800), (0xf000, 0x10000)]
    kuse = [(a, len(d)) for a, d in list(patches) + (list(ach["ram"]) if ach else []) if 0x80000000 <= a < 0x80010000]
    kbad = [(a, n) for a, n in kuse if not any(lo <= (a & 0xffff) and (a & 0xffff) + n <= hi for lo, hi in KSAFE)]
    if kbad:
        msg = "KERNEL RAM VIOLATION (not hardware-safe): " + ", ".join("%08x-%08x" % (a, a + n) for a, n in kbad)
        if "--allow-kernel" not in argv:
            raise SystemExit(msg + "  (use --allow-kernel for emulator-only builds)")
        print("WARNING", msg)
    img.wsectors(dmy_lba, blob)
    for key, data in items:
        img.wsectors(pos[key], data)
    assert "--logo2" not in argv or "--logo" in argv, "--logo2 needs --logo"
    if "--logo" in argv:        # (logo) boot cards before the game (tools/logo/mvccards.py): EXE zero area, chained from pc0
        sys.path.insert(0, os.path.join(GAME, "tools", "logo")); import mvccards
        exe_ = img.rbytes(exe_lba, 0, exe_size)
        pc0_ = struct.unpack_from("<I", exe_, 0x10)[0]
        for lo, hi in mvccards.ram_ranges():
            for a, data in list(patches) + (list(ach["exe"]) if ach else []):
                assert a + len(data) <= lo or a >= hi, "EXE patch %08x inside the boot-card area" % a
        lay_ = 2 if "--logo2" in argv else 1     # (logo2) card 2 layout 2: eyes on one line, centred composition
        for off, data in mvccards.disc_patches(exe_, lambda n: mvccards.disc_file(n, SRC_BIN), pc0_, layout=lay_):
            img.wbytes(exe_lba, off, data)
        print("logo: boot cards %08x-%08x, pc0 %08x -> %08x, card 2 layout %d" % (mvccards.LOGO_AT, mvccards.STUB_END, pc0_, mvccards.LOGO_AT, lay_))
    img.fix()
    jd = dict(patches=[(a, d.hex()) for a, d in patches], sym=sym)
    if ach:      # tests poke the images first (ach_ram), then the hooks; the boot copy stub is never poked
        jd["ach_ram"] = [(a, d.hex()) for a, d in ach["ram"]]
        jd["patches"] += [(a, d.hex()) for a, d in ach["exe"] if a < mvcach.COPY_AT]
        jd["ach_sym"] = {k: v for k, v in ach["info"]["sym"].items() if k.startswith(("ach_", "port_", "c_"))}
    json.dump(jd, open(os.path.join(BUILD, name + ".patches.json"), "w"))
    open(os.path.join(BUILD, name + ".cue"), "w").write(f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(f"blob {len(blob)} bytes, data {lba - dmy_lba} sectors of DMY1.DAT + {appended} appended, {len(patches)} EXE patches -> {out}")
    if "--chd" in argv:
        chd = os.path.join(BUILD, name + ".chd")
        subprocess.check_call([toolenv.chdman(), "createcd", "-i", os.path.join(BUILD, name + ".cue"), "-o", chd, "-f"],
                              stdout=subprocess.DEVNULL)
        print("chd:", chd)
    return patches, blob, sym


if __name__ == "__main__":
    main(sys.argv)
