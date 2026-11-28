"""Build the MSHvSF tag-hack disc with the optional 8 MB loader ("ap8").

    python tools/ap8/mkap8.py NAME [--chd] [--content DIR | --arcade SET.zip [PARENT.zip]] [mktag.py options]
                                                                                    (NAME = mshvsf_ap8*)

Same disc as tools/tagload/mktag.py (it does the whole build), with these differences:
  * the loader blob read into the sprite decode arena each battle is linked with tools/ap8/ap8.c and its entry is
    ap8_main instead of tl_main.  Without 8 MB, ap8_main calls tl_main at once: the 2 MB loader, unchanged, same
    data.  The resident glue and every EXE patch are those of the 2 MB build (checked).
  * --content DIR (tools/ap/build8.py output, from the user's own arcade ROMs): the restored sprite files and
    animation patches are appended after the end of the image, the 8 MB loader uses them (tl8_dir in the blob).
    Never ship such a disc: it contains arcade-derived graphics.

Build products go to tools/ap8/obj/ (nothing is written into tools/tagload/).  mktag.py itself still builds the
decoder patches (common/dsp), so the run holds the shared lock games/mshvsf/work/mktag.lock.
"""
import os, sys, struct, subprocess, time, contextlib, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
TL = os.path.join(GAME, "tools", "tagload")
OBJ = os.path.join(HERE, "obj")
LOCK = os.path.join(GAME, "work", "mktag.lock")
sys.path.insert(0, TL)

# upper RAM layout of ap8.c (keep in sync)
UP = 0x80200000
WA = 0x1c000
CACHE = UP + 0x1000 + 4 * WA
C_A0CAP = 0x32000
HLPCAP = 0x6000
NCSMAX = 16
S8_CODE, S8_CODEMAX = 0x807f0000, 0x3000         # s8/s8.h: engine code, state above it (to 0x80800000)
# 1.1 8 MB (--exopt): ARCADE FRAMES ON / OFF is the last EX OPTIONS row (--afrow, exopt.py: option byte OPTB + 9 =
# AFOPT, 0 = ON; shown only on an 8 MB console).  (Before 2026-11-24 the slack had no room: FRAME SKIP / SPEED METER rows
# were removed since.)  OPTB is the meter's flag word (tools/speed/meter.py), fixed: exopt.screen asserts optb == AFOPT_OPTB.  --l2g is 2 MB only: its EXE gate is the 8 MB menu's span
# 0x80011bd4 (ap8menu.S) and the 8 MB path never runs g2get (whole stock / restored SP_PLxx.DSP files from upper RAM).
EXOPT = "--exopt" in sys.argv
OPTB = 0x800243c0                                 # exopt option bytes (mktag: the meter's flag word); AFOPT = OPTB + 9
assert "--l2g" not in sys.argv, "--l2g is 2 MB only (gate span = the 8 MB menu's; the 8 MB path reads no tier files)"


@contextlib.contextmanager
def lock(timeout=3600):
    t0 = time.time()
    while True:
        try:
            os.mkdir(LOCK); break
        except FileExistsError:
            if time.time() - t0 > timeout: raise SystemExit("mktag.lock held for an hour: " + LOCK)
            time.sleep(5)
    try:
        yield
    finally:
        os.rmdir(LOCK)


def link(GCC, pad):
    subprocess.check_call([GCC + "ld", "-T", os.path.join(HERE, "link8.ld"), "--defsym", "PAD=%d" % pad,
                           "entry8.o", "glue.o", "tagload.o", "snd.o", "ap8.o", "-o", "ap8.elf"], cwd=OBJ)
    out = {}
    for sec in (".glue", ".heapcap", ".blob"):
        p = os.path.join(OBJ, "ap8" + sec + ".bin")
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "ap8.elf", p], cwd=OBJ)
        out[sec] = open(p, "rb").read()
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", "ap8.elf"], cwd=OBJ).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    return out, sym


def build_s8():
    """8 MB voice streaming: engine + battle sound (s8/s8.c, s8/snd8e.c) linked at S8_CODE, a disc file (not in the
    blob) -> code bytes (4-padded).  Its own function: the release builder prebakes it (no compiler there)."""
    import mktag
    GCC, CF = mktag.GCC, mktag.CF
    os.makedirs(OBJ, exist_ok=True)
    for f in ("s8", "snd8e"):
        subprocess.check_call([GCC + "gcc"] + CF + ["-Os", "-ffreestanding", "-msoft-float", "-Wall", "-c",
                              os.path.join(HERE, "s8", f + ".c"), "-o", f + ".o"], cwd=OBJ)
    subprocess.check_call([GCC + "ld", "-T", os.path.join(HERE, "s8", "s8.ld"), "s8.o", "snd8e.o", "-o", "s8.elf"], cwd=OBJ)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".text", "s8.elf", "s8.bin"], cwd=OBJ)
    code = open(os.path.join(OBJ, "s8.bin"), "rb").read()
    assert len(code) <= S8_CODEMAX
    return code + bytes(-len(code) % 4)


def build_blob8():
    import mktag
    GCC, CF = mktag.GCC, mktag.CF
    os.makedirs(OBJ, exist_ok=True)
    cc = lambda args: subprocess.check_call([GCC + "gcc"] + CF + args, cwd=OBJ)
    # the 2 MB loader inside (no 8 MB / not a tag fight) gets mktag.build_blob's defines: the same 2 MB behaviour
    shrink = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--testshrink=")), 0)
    xdef = ["-DREGION_SHRINK=%d" % shrink] + (["-DMCFIX"] if "--mcfix" in sys.argv else []) + (
        ["-DPSTALL=1"] if "--pstall" in sys.argv else [])
    gdef = []
    if mktag.L2G:
        xdef += ["-DL2G", "-DG2AT=0x%xu" % mktag.L2IMG[0], "-DL2WORDS=%d" % (len(mktag.L2IMG[1]) // 4)]
        gdef = ["-DL2G", "-DG2AT=0x%x" % mktag.L2IMG[0]]
    cc(["-Os", "-ffreestanding", "-msoft-float", "-Wall"] + xdef + ["-c", os.path.join(TL, "tagload.c"), "-o", "tagload.o"])
    import re
    nt = int(re.search(r"(?m)^#define NT (\d+)", open(os.path.join(TL, "tagload.c")).read()).group(1))
    cc(["-Os", "-ffreestanding", "-msoft-float", "-Wall", "-DNT=%d" % nt] + (["-DAFOPT=0x%xu" % (OPTB + 9)] if EXOPT else []) +
       (["-DWORK2=0x80140000u"] if "--work2" in sys.argv else []) +       # GitHub #23: code copies in the 2 MB area
       ["-c", os.path.join(HERE, "ap8.c"), "-o", "ap8.o"])
    cc(gdef + ["-c", os.path.join(TL, "glue.S"), "-o", "glue.o"])
    mktag.sndbuild.objects(GCC, CF, OBJ)                       # tools/snd/snd.c (full sound banks, v10)
    cc(["-c", os.path.join(HERE, "entry8.S"), "-o", "entry8.o"])
    build_s8()
    assert mktag.sndbank.NL == 36, "ap8.c struct schr_ assumes SND_NL 36"
    # mktag.py reserves ceil((blob + 4) / 2048) sectors for the blob but appends the strong decoder + the check word
    # after it: pad the blob so that they fit in those sectors
    strong = os.path.getsize(mktag.DSHDEC) if os.path.exists(mktag.DSHDEC) else 0
    out, sym = link(GCC, 0)
    L = len(out[".blob"]); pad = 0
    while -(-(L + pad + 4) // 2048) * 2048 < L + pad + strong + 4: pad += 4
    if pad: out, sym = link(GCC, pad)
    blob = out[".blob"]
    assert -(-(len(blob) + 4) // 2048) * 2048 >= len(blob) + strong + 4
    assert sym["heapcap"] == 0x80010df8 and sym["heapcap_end"] <= 0x80010e90
    assert sym["glue"] == 0x80013580 and sym["glue_end"] <= 0x80013748, "glue outside its range"
    assert blob[:4] == struct.pack("<I", 0x08000000 | ((sym["ap8_main"] >> 2) & 0x3FFFFFF))
    assert mktag.ARENA + len(blob) + strong < 0x80091e00, "blob too big for the arena"
    # the resident part must be the 2 MB build's (same source, same flags): compare with the 2 MB link script
    ref = os.path.join(OBJ, "ref.elf")
    subprocess.check_call([GCC + "ld", "-T", os.path.join(TL, "link.ld"), "glue.o", "tagload.o", "snd.o", "-o", ref], cwd=OBJ)
    for sec in (".glue", ".heapcap"):
        p = os.path.join(OBJ, "ref" + sec + ".bin")
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, ref, p], cwd=OBJ)
        assert open(p, "rb").read() == out[sec], "resident %s differs from the 2 MB build" % sec
    print("ap8 blob", len(blob), "bytes (pad %d, arena limit %d)" % (pad, 0x80091e00 - mktag.ARENA))
    import menus
    if not EXOPT: menus.AP8 = (sym["tl_dbg"] + 13, sym["tl_dbg"] + 15)   # OPTION line "ARCADE FRAMES": flag, show-if
    else:
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import exopt
        exopt.TLDBG = sym["tl_dbg"]                                      # EX OPTIONS row ARCADE FRAMES: shown if tl_dbg[15]
    build_blob8.sym = sym
    return out[".glue"], blob, sym, out[".heapcap"]


# resident menu part (ap8menu.S): small dead EXE ranges (tools/gameplay/deadcode.py candidates under 96 bytes,
# no j / jal into them from the EXE or any disc file incl. *.ARC: tools/speed/ahead.refcheck; see CODESPACE.md)
MRANGES = {"p": (0x80011bd4, 0x80011c28), "q": (0x800222cc, 0x80022310), "r": (0x8004c6e4, 0x8004c724),
           "s": (0x8003c2c4, 0x8003c2f4), "t": (0x8005795c, 0x8005798c), "u": (0x8007a8f4, 0x8007a920)}
MENU_AT, OVL_BASE = 0x800994e0, 0x80094800


def menu_part(title):
    """EXE patches of ap8menu.S (unused range bytes = break) and the OPDEMO word -> (exe, overlay word)"""
    sys.path[:0] = [os.path.join(GAME, "tools", "speed"), os.path.join(GAME, "tools", "gameplay")]
    import slib, menuversion, ahead
    ahead.refcheck(extra=list(MRANGES.values()))
    hook = menuversion.build(title)[1]
    x = menuversion.X_RIGHT - menuversion.CHAR_W * (len(title) + 4)
    defs = dict(TLDBG=build_blob8.sym["tl_dbg"], MENUHOOK=hook, MARKX=x, MARKY=menuversion.Y)
    out, syms, plan = slib.pack(open(os.path.join(HERE, "ap8menu.S")).read(), MRANGES, defs)
    exe = []
    for k, (lo, hi) in MRANGES.items():
        b = out.get(k, b"")
        exe.append((lo, b + struct.pack("<I", 0x0000000d) * ((hi - lo - len(b)) // 4)))
    return exe, struct.pack("<I", 0x08000000 | (syms["ap8menu"] >> 2 & 0x3ffffff))


def r2k(x): return (x + 2047) & ~2047


def geometry(content, sn8=None):
    """cache slot geometry for the files of this disc -> (cs, c_dsp, c_hlp, c_ap8, ncs), and the A0 checks;
    sn8 = {bank: .SN8 bytes} (tools/snd/sn8build.py): a slot part for the character's file, COMMON's below the engine
    (geometry.c_sn8 / geometry.comat)"""
    import mktag
    dmax = 0; amax = 0
    for c in range(mktag.NCHAR):
        a0, a0size, iv = mktag.a0_file(c)
        n, = struct.unpack_from("<I", a0); assert n == 3
        o3, = struct.unpack_from("<I", a0, 20)                 # sec3 offset = header + sec1 + sec2
        span = iv[1] - iv[0]
        nf = 0
        if content and os.path.exists(os.path.join(content, "PL%02X.AP8" % c)):
            nf = struct.unpack_from("<I", open(os.path.join(content, "PL%02X.AP8" % c), "rb").read(), 12)[0]
            amax = max(amax, os.path.getsize(os.path.join(content, "PL%02X.AP8" % c)))
        assert 0x1c + 8 + span + 8 + o3 + 8 + 4 * nf <= WA, ("work area", c)
        assert r2k(len(a0)) <= C_A0CAP, ("a0", c)
        dmax = max(dmax, os.path.getsize(os.path.join(mktag.FILES, f"SP_PL{c:02X}.DSP")))
        if content and os.path.exists(os.path.join(content, "SP_PL%02X.DSP" % c)):
            dmax = max(dmax, os.path.getsize(os.path.join(content, "SP_PL%02X.DSP" % c)))
        h = os.path.join(mktag.FILES, f"HLP{c:02X}.SE")
        assert not os.path.exists(h) or r2k(os.path.getsize(h)) <= HLPCAP
    c_dsp = C_A0CAP; c_hlp = c_dsp + r2k(dmax); c_ap8 = c_hlp + HLPCAP; cs = c_ap8 + r2k(amax)
    top = 0x80800000
    geometry.c_sn8 = geometry.comat = 0
    if sn8:
        # voice streaming disc: ap8.c packs the cache records in one arena (exact sizes) up to COMMON.SN8; the four
        # biggest records of a battle (list ids 0x17-0x19 are separate records of the files of 2 / 8 / 7) must fit
        import sn8build
        geometry.comat = top = S8_CODE - r2k(len(sn8[sn8build.S.COMMON]))
        rec = {}
        for c in range(0x1a):
            f = {0x17: 2, 0x18: 8, 0x19: 7}.get(c, c)
            a0 = mktag.a0_file(f)[0]
            d = os.path.getsize(os.path.join(mktag.FILES, f"SP_PL{f:02X}.DSP"))
            ap = 0
            if content and os.path.exists(os.path.join(content, "SP_PL%02X.DSP" % f)):
                d = max(d, os.path.getsize(os.path.join(content, "SP_PL%02X.DSP" % f)))
                ap = os.path.getsize(os.path.join(content, "PL%02X.AP8" % f))
            rec[c] = r2k(len(a0)) + r2k(d) + r2k(ap) + r2k(len(sn8[f]))
        worst = sum(sorted(rec.values())[-4:])
        print("arena %#x (%.2f MB), worst four records %#x (%.2f MB)" % (top - CACHE, (top - CACHE) / 2 ** 20, worst, worst / 2 ** 20))
        assert worst <= top - CACHE, "four characters do not fit in the cache arena"
        return cs, c_dsp, c_hlp, c_ap8, NCSMAX
    ncs = min(NCSMAX, (top - CACHE) // cs)
    assert ncs >= 4, "four characters do not fit in the cache"
    return cs, c_dsp, c_hlp, c_ap8, ncs


def add_content(name, content, blob, sym, geo, sn8=None):
    """append the content files (and the .SN8 voice streaming files) after the end of the built image, fill tl8_dir
    and tl8_snd in the blob on the disc"""
    import mktag
    out = os.path.join(mktag.BUILD, name + ".bin")
    files = []
    for c in range(0x17 if content else 0):
        d = os.path.join(content, "SP_PL%02X.DSP" % c); a = os.path.join(content, "PL%02X.AP8" % c)
        files.append((open(d, "rb").read(), open(a, "rb").read()) if os.path.exists(d) and os.path.exists(a) else None)
    end = os.path.getsize(out) // 2352
    img = mktag.Img(out)
    n = sum((len(x[0]) + 2047) // 2048 + (len(x[1]) + 2047) // 2048 for x in files if x)
    nsn = sum((len(b) + 2047) // 2048 for b in sn8.values()) + 4 if sn8 else 0
    if n + nsn: img.extend(end, n + nsn + 150)
    lba = end; ents = b""
    for x in files:
        if not x: ents += bytes(16); continue
        e = b""
        for data in x:
            img.wsectors(lba, data); e += mktag.msf(lba) + struct.pack("<I", len(data)); lba += (len(data) + 2047) // 2048
        ents += e
    d8 = sym["tl8_dir"] - mktag.ARENA
    assert blob[d8:d8 + 4] == b"AP8D"
    dirb = b"AP8D" + struct.pack("<6I", *geo, 1 if n else 0) + ents
    blob = bytearray(blob[:-4])
    blob[d8:d8 + len(dirb)] = dirb
    if sn8:
        import sn8build
        pos = {}
        for c in [sn8build.S.COMMON] + list(range(0x17)):
            pos[c] = mktag.msf(lba) + struct.pack("<I", len(sn8[c]))
            img.wsectors(lba, sn8[c]); lba += (len(sn8[c]) + 2047) // 2048
        ds = sym["tl8_snd"] - mktag.ARENA
        assert blob[ds:ds + 4] == b"SN8D"
        code = build_s8()
        cpos = mktag.msf(lba) + struct.pack("<I", len(code)); img.wsectors(lba, code); lba += (len(code) + 2047) // 2048
        csum = (0x5a17 + sum(struct.unpack("<%dI" % (len(code) // 4), code))) & 0xffffffff
        sdb = b"SN8D" + struct.pack("<3I", 1, csum, geometry.comat) + cpos + pos[sn8build.S.COMMON] + b"".join(pos[c] for c in range(0x17))
        blob[ds:ds + len(sdb)] = sdb
        print("sn8: %d sectors (COMMON at %#x, slot part %#x)" % (nsn, geometry.comat, geometry.c_sn8))
    blob += struct.pack("<I", -sum(struct.unpack(f"<{len(blob) // 4}I", blob)) & 0xFFFFFFFF)
    dmy_lba, dmy_size = mktag.LBA["DMY.DAT"]
    img.wsectors(dmy_lba, bytes(blob))
    img.fix()
    print("content: %d characters, %d sectors appended at %d; cache slot %#x x %d" % (sum(1 for x in files if x), n, end, geo[0], geo[4]))
    return bytes(blob)


def main(argv):
    import mktag
    name = next((a for a in argv[1:] if not a.startswith("--")), None)
    assert name and name.startswith("mshvsf_ap8"), "build names: mshvsf_ap8*"
    content = next((a.split("=", 1)[1] for a in argv if a.startswith("--content=")), None)
    if "--content" in argv: content = argv[argv.index("--content") + 1]
    chd = "--chd" in argv
    arc = []
    if "--arcade" in argv:
        i = argv.index("--arcade") + 1
        while i < len(argv) and not argv[i].startswith("--"): arc.append(argv[i]); i += 1
        sys.path.insert(0, os.path.join(GAME, "tools", "ap"))
        import build8
        prg, roms, desc = build8.read_arcade(arc)
        content = os.path.join(GAME, "work", "ap", "b8", "set_" + hashlib.sha1(json.dumps(desc, sort_keys=True).encode()).hexdigest()[:10]
                               + ("_introfx" if "--introfx" in argv else ""))
        # --introfx: Blackheart's intro pool animations (build8.INTRO_FX_SET) restored too (8 MB content only)
        build8.main(["build8", "--arcade"] + arc + ["--out", content] + (["--introfx"] if "--introfx" in argv else []))
    # --sn8arc ZIP [ZIP]: the sound ROMs for the arcade voices when the frames come from --content (release builder)
    snarc = []
    if "--sn8arc" in argv:
        i = argv.index("--sn8arc") + 1
        while i < len(argv) and not argv[i].startswith("--"): snarc.append(argv[i]); i += 1
    args = [a for a in argv[1:] if a not in ("--chd", "--content", "--arcade", "--sn8arc", "--introfx") and a != content and a not in arc
            and a not in snarc and not a.startswith("--content=")]
    sys.path.insert(0, os.path.join(GAME, "tools", "snd"))
    import sn8build
    # 8 MB voice streaming (arcade voices with --arcade; --sn8stock: stock voices; --nosn8: none, the v10 banks)
    # --sn8full (1.1 8 MB, user): arcade voices to the arcade sample's own end, not cut to the PS1 span
    sn8 = None if "--nosn8" in argv else sn8build.all_files(None if "--sn8stock" in argv else (arc or snarc or None),
                                                            full="--sn8full" in argv)
    args = [a for a in args if a not in ("--nosn8", "--sn8stock", "--sn8full", "--work2")]
    with lock():
        geo = geometry(content, sn8)
        mktag.build_blob = build_blob8
        allp = mktag.allpatches
        p0, o0 = allp.patches, allp.overlay_patches
        allp.patches = lambda title=allp.menuversion.DEFAULT, msyms=None: p0(title, msyms) + (menu_part(title)[0] if title else [])
        allp.overlay_patches = lambda title=allp.menuversion.DEFAULT, msyms=None: o0(title, msyms) + (
            [("OPDEMO.BIN", MENU_AT - OVL_BASE, menu_part(title)[1])] if title else [])
        if EXOPT: args = args + ["--afrow"]                  # EX OPTIONS row ARCADE FRAMES (8 MB discs only)
        patches, blob, sym = mktag.main([argv[0]] + args)
        blob = add_content(name, content, blob, sym, geo, sn8)
    if chd:
        out = os.path.join(mktag.BUILD, name)
        subprocess.check_call([mktag.toolenv.chdman(), "createcd", "-i", out + ".cue", "-o", out + ".chd", "-f"],
                              stdout=subprocess.DEVNULL)
        print("chd:", out + ".chd")


if __name__ == "__main__":
    main(sys.argv)
