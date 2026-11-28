"""The MSHvSF build, from an untouched disc image to the patched image.

    stage      reads                                     writes (all under the work directory / the tool root)
    ---------  ----------------------------------------  ---------------------------------------------------------
    verify     the image (SHA-1, size)                   -
    extract    the image (ISO9660)                       G/work/loader/files/*, G/work/dsp/files/SP_PLxx.DSP,
                                                         G/work/lba_map.json, G/disc/SLUS_007.93
    sprites    G/work/dsp/files/SP_PLxx.DSP              G/work/dsp/<tier>/SP_PLxx.DSP (9 tiers: mshb/sprites.py)
    sound      G/work/loader/files/PLxx_10.A0            G/build/snd/*.pkl (every level of every character's bank:
                                                         tools/snd/sndbank.py, the cache mktag.py reads)
    arcade     the arcade ROM zip(s), the image          G/work/ap/content/ (tools/ap/build8.py; 8 MB variant only)
    disc       all of the above, data/mshvsf/blobs       the patched image as an Overlay (tools/tagload/mktag.py,
                                                         or tools/ap8/mkap8.py, which runs mktag.py inside)
    seal       -                                         EDC/ECC of every rewritten sector

G = <root>/games/mshvsf.  <root> is a copy of the project's tools (the same files the browser patcher carries in its
bundle; in the browser it is the unpacked bundle itself), so the tools run UNMODIFIED with their own relative paths:
their data directories (work/, build/, disc/) are filled from the user's disc in that copy, never in the repository.
The harness (class Tools)
  * hands the tools the user's image as their source (mktag.SRC_BIN) and an Overlay (copy-on-write, xvb/cdrom.py)
    when they copy and open the output image,
  * defers their per-sector EDC/ECC (fix_sector) to one vectorised pass,
  * takes ALL of our MIPS code from builder/data/mshvsf/blobs (PREBAKED below): the builder compiles nothing and runs
    no external program.  Words of the game inside our code are stored as references to the user's disc
    (xvb/gameref.py), filled in after the SHA-1 check.
So whatever those tools build, this builds, with the same bytes (work/mshvsf_release/record.py checks it).
"""
import builtins, contextlib, hashlib, importlib, io, json, os, shutil, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(BUILDER, ".."))
if BUILDER not in sys.path: sys.path.insert(0, BUILDER)
from xvb import cdrom                                          # noqa: E402
from xvb.pipeline import BuildError, sha1_file, _enc, _dec, _plain_sha1, _LineLog, _argv, cue_text   # noqa: E402

GAME = "mshvsf"
DATA = os.path.join(BUILDER, "data", GAME)
BLOBS = os.path.join(DATA, "blobs")
G_REL = "games/mshvsf"
EXE = "SLUS_007.93"
NCHAR = 0x17
TITLE = "Marvel Super Heroes vs. Street Fighter (USA)"


def known():
    return json.load(open(os.path.join(DATA, "known.json")))


# ---------------------------------------------------------------- the tool root
# (directory, file filter, recursive): the files of the repository the build runs.  Shared with patcher/make.py
# (the browser bundle) - the command line copies exactly these into <work>/root.
def _py(f): return f.endswith(".py")


ROOT_SPEC = [
    ("builder/xvb", _py, False), ("builder/mshb", _py, False),
    ("builder/data/mshvsf", lambda f: f.endswith(".json"), True),
    ("tools", lambda f: _py(f) and not f.startswith("cold"), False),
    ("tools/snd", _py, False), ("tools/ap", _py, False),
    ("common/dsp", lambda f: f in ("dsp.py", "dsmpatch.py"), False),
    ("games/mshvsf/tools", lambda f: f == "reloc.py", False),
    ("games/mshvsf/tools/tagload", lambda f: _py(f) and f in ("mktag.py", "tiercost.py"), False),
    ("games/mshvsf/tools/ap8", lambda f: f == "mkap8.py", False),
    ("games/mshvsf/tools/ap", lambda f: f == "build8.py", False),
    ("games/mshvsf/tools/gameplay", lambda f: f in ("allpatches.py", "tagmode.py", "menuversion.py", "pad.py", "menus.py", "cyber.py", "training.py",
                                                    "cyswap.py", "exopt.py", "arcbal.py", "norimaro.py"), False),   # 1.1: Cyber-Akuma fix, EX OPTIONS, ARCADE BALANCE, Norimaro
    ("games/mshvsf/tools/l2", lambda f: f in ("l2.py", "g2get.py", "g2pack.py"), False),                   # 1.1: packed frame groups (--l2g)
    ("games/mshvsf/tools/mtap", lambda f: f == "mtap4.py", False),                                         # 1.1: VERSUS CPU row (--vsmenu)
    ("common/mtap", lambda f: f in ("mtpatch.py", "mtbuild.py"), False),                                    # (shared VERSUS CPU core: its patch list)
    ("games/mshvsf/tools/logo", lambda f: f in ("mshcards.py", "mshcard2.bin"), False),
    ("games/mshvsf/tools/snd", lambda f: f in ("sndbank.py", "sndbuild.py", "sn8build.py", "arcvox.json"), False),   # 1.1 8 MB: voice streaming (+ arcade voices)
    ("games/mshvsf/tools/speed", lambda f: f in ("a0mem.py", "parse.py", "ahead.py", "meter.py", "slib.py"), False),
    ("games/mshvsf/tools/ach", lambda f: f in ("mshach.py", "set.py"), False),          # --ach (built-in achievements)
    ("games/mshvsf/tools/skip", lambda f: f == "mshskip.py", False),                    # START skips the end of a match
    ("tools/ach", lambda f: f in ("achbuild.py", "setc.py"), False),
]
# record mode (developers): the tools compile our code, so their sources come along (everything but caches/objects)
RECORD_SPEC = [("games/mshvsf/tools", lambda f: not f.endswith((".pyc", ".o", ".elf")), True),
               ("common/dsp", lambda f: not f.endswith(".pyc"), True),
               ("common/mtap", lambda f: not f.endswith((".pyc", ".o", ".elf")), True),
               ("tools", lambda f: not f.endswith(".pyc"), True)]
SKIP_DIRS = ("__pycache__", "obj", "mister", "test")


# The game's tool files the build runs are taken from a frozen copy, builder/data/mshvsf/tools (repository layout), made
# by work/mshvsf_release/record.py from the sources it baked: development in games/mshvsf/tools goes on without
# touching the release builder (and the blobs always match the tools that use them).
SNAP = os.path.join(DATA, "tools")
SNAP_PREFIXES = ("games/mshvsf/", "common/dsp/", "common/mtap/")


def root_files(spec=ROOT_SPEC, repo=REPO, snapshot=True):
    """[(relative path, path on disk)] of the tool root, sorted (reproducible bundle).  snapshot: the game's tool
    files from SNAP (when it exists) instead of the repository"""
    out = {}
    for rel, keep, rec in spec:
        base = SNAP if snapshot and (rel + "/").startswith(SNAP_PREFIXES) and os.path.isdir(SNAP) else repo
        top = os.path.join(base, *rel.split("/"))
        if not os.path.isdir(top): continue
        for d, sub, files in os.walk(top):
            sub[:] = sorted(s for s in sub if s not in SKIP_DIRS) if rec else []
            for f in sorted(files):
                p = os.path.join(d, f)
                if keep(f): out[os.path.relpath(p, base).replace(os.sep, "/")] = p
    return sorted(out.items())


def make_root(root, record=False):
    """copy the tool root (CLI); record mode: the live sources the tools compile (repository), and local_paths.json"""
    files = dict(root_files(ROOT_SPEC, snapshot=not record))
    if record: files.update(root_files(RECORD_SPEC, snapshot=False))
    for rel, p in sorted(files.items()):
        dst = os.path.join(root, *rel.split("/"))
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(p) and open(dst, "rb").read() == open(p, "rb").read(): continue
        os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(p, dst)
    lp = os.path.join(root, "local_paths.json")
    if record and os.path.exists(os.path.join(REPO, "local_paths.json")): shutil.copyfile(os.path.join(REPO, "local_paths.json"), lp)
    elif not record and os.path.exists(lp): os.remove(lp)            # no compiler path in a normal build


def snapshot(repo=REPO):
    """record.py: freeze the game's tool files of the build (from the repository) into SNAP"""
    if os.path.isdir(SNAP): shutil.rmtree(SNAP)
    for rel, p in root_files(ROOT_SPEC, repo, snapshot=False):
        if rel.startswith(SNAP_PREFIXES):
            dst = os.path.join(SNAP, *rel.split("/")); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(p, dst)


def gdir(root, *p): return os.path.join(root, *G_REL.split("/"), *p)


# ---------------------------------------------------------------- stage: verify
SYSTEM_CNF_SERIALS = {          # boot file -> (game, region text); identification of discs this builder does not take
    "SLUS_007.93": ("mshvsf", "USA"), "SLPS_011.42": ("mshvsf", "Japan"), "SLES_011.44": ("mshvsf", "Europe"),
    "SLPS_911.43": ("mshvsf", "Japan, PlayStation the Best"),
}


def identify(path, sha1=None, size=None):
    """-> dict(status ok | patched | region | notgame | notimage | baddump, message, sha1, size)"""
    kn = known(); inp = kn["input"]
    if sha1 is None: sha1, size = sha1_file(path)
    if sha1 == inp["sha1"]:
        return dict(status="ok", sha1=sha1, size=size, message=inp["title"], game=GAME)
    for e in kn.get("expected", []) + kn.get("previous", []):
        if sha1 == e["sha1"]:
            return dict(status="patched", sha1=sha1, size=size, game=GAME, message="This image is already patched (it is a %s image this builder made). "
                        "Use the original, unmodified disc image." % ("tag hack + restored frames" if e.get("arcade_set") else "tag hack with the 8 MB loader" if e["variant"] == "8mb" else "tag hack"))
    try:
        if size % cdrom.SECTOR: raise ValueError
        d = cdrom.Disc(path); names = {n: (l, s) for n, l, s in d.walk()}
    except Exception:
        return dict(status="notimage", sha1=sha1, size=size, message="This is not a raw PlayStation disc image (MODE2/2352 .bin).")
    if EXE not in names:
        return dict(status="notgame", sha1=sha1, size=size, message="This disc is not Marvel Super Heroes vs. Street Fighter (USA, %s)." % inp["serial"])
    l, s = names.get("DMY.DAT", (None, 0))
    patched = size != inp["size"]
    if l is not None and not patched:
        blk = d.sec(l)
        patched = any(blk)                       # stock DMY.DAT is padding (zeros); the tag hack puts its loader there
    if patched:
        return dict(status="patched", sha1=sha1, size=size, game=GAME, message="This looks like an image that already carries the tag hack (or another modification). "
                    "Use the original, unmodified disc image.")
    return dict(status="baddump", sha1=sha1, size=size, game=GAME, message="This is the right game (%s) but not the known good dump: its SHA-1 is %s, expected %s "
                "(size %d bytes). It may be modified or badly dumped; the patch is only applied to the exact original." % (inp["serial"], sha1, inp["sha1"], inp["size"]))


# ---------------------------------------------------------------- stage: extract
def extract(image, root):
    """the game files into the tool root -> lba map {name: [lba, size]} (the format of games/mshvsf/work/lba_map.json).
    Every file up to 8 MB goes to G/work/disc_files (blob references read from there); the tools' own file directory
    G/work/loader/files gets the set it has on the development machine (data/mshvsf/loader_files.json: the battle
    files; tools/speed/ahead.py scans that directory)"""
    d = cdrom.Disc(image); lmap = {}
    allf = gdir(root, "work", "disc_files"); os.makedirs(allf, exist_ok=True)
    files = gdir(root, "work", "loader", "files"); os.makedirs(files, exist_ok=True)
    dspd = gdir(root, "work", "dsp", "files"); os.makedirs(dspd, exist_ok=True)
    os.makedirs(gdir(root, "disc"), exist_ok=True)
    loader = set(json.load(open(os.path.join(DATA, "loader_files.json"))))
    for full, lba, sz in d.walk():
        n = full.split("/")[-1]
        assert n not in lmap, "duplicate file name " + n
        lmap[n] = [lba, sz]
        if sz <= 8 << 20:
            b = d.read(lba, sz)
            dsts = [os.path.join(allf, n)] + ([os.path.join(files, n)] if n in loader else []) +                    ([os.path.join(dspd, n)] if n.startswith("SP_PL") and n.endswith(".DSP") else []) + ([gdir(root, "disc", EXE)] if n == EXE else [])
            for p in dsts:
                with open(p, "wb") as f: f.write(b)
    with open(gdir(root, "work", "lba_map.json"), "w") as f: json.dump(lmap, f)
    hot = os.path.join(DATA, "hot")                   # our play-volume tables (tiercost.py, hot tiers)
    if os.path.isdir(hot):
        os.makedirs(gdir(root, "work", "dsp", "hot"), exist_ok=True)
        for f in sorted(os.listdir(hot)):
            shutil.copyfile(os.path.join(hot, f), gdir(root, "work", "dsp", "hot", f))
    return lmap


# ---------------------------------------------------------------- stage: sprites
TIERS = ["dsh_cut", "dsh", "dsh_hot4", "dsh_hot8", "dsh_hot16", "dsh_hot32", "dsm", "dsm_hot16", "dsm_hot32", "dsm_hot64"]     # = mktag.TIERDIRS


def sprite_key(root):
    """the stock sprite files + the encoder sources + their data (parameters, hot tiles) -> cache key of the tiers"""
    key = hashlib.sha1()
    files = gdir(root, "work", "dsp", "files")
    for f in sorted(os.listdir(files)): key.update(f.encode() + open(os.path.join(files, f), "rb").read())
    for d in (HERE, os.path.join(DATA, "hot"), DATA):
        if not os.path.isdir(d): continue
        for f in sorted(os.listdir(d)):
            if f.endswith((".py", ".json")) and f != "known.json": key.update(f.encode() + open(os.path.join(d, f), "rb").read().replace(bytes((13, 10)), bytes((10,))))
    return key.hexdigest()


def stage_sprites(root, jobs=1, progress=None, log=print, reference=None):
    """the 9 sprite tiers of every character -> G/work/dsp/<tier>/.  reference (developers): copy the tiers from that
    directory (games/mshvsf/work/dsp) instead of encoding them"""
    out = gdir(root, "work", "dsp")
    files = gdir(root, "work", "dsp", "files")
    if reference:
        for t in TIERS:
            os.makedirs(os.path.join(out, t), exist_ok=True)
            for c in range(NCHAR):
                p = os.path.join(reference, t, "SP_PL%02X.DSP" % c)
                if os.path.exists(p): shutil.copyfile(p, os.path.join(out, t, "SP_PL%02X.DSP" % c))
        log("sprites: copied from %s" % reference)
        return dict(reference=True)
    key = sprite_key(root)
    stamp = os.path.join(out, "tiers.stamp")
    if os.path.exists(stamp) and open(stamp).read() == key:
        log("sprites: tiers in the work directory are current (cache)"); return dict(cached=True)
    t0 = time.time()
    from mshb import sprites, kernels
    assert list(sprites.TIERS) == TIERS
    if kernels.backend == "python": kernels.auto_backend()       # numba when it is there (the browser installs its JavaScript kernels)
    P = (lambda d, n, t, c, secs: progress(d / n, "%s %02X" % (t, c))) if progress else None
    sprites.encode_all(files, out, progress=P, jobs=jobs)
    open(stamp, "w").write(key)
    log("sprites: %.1f s" % (time.time() - t0))
    return dict(cached=False, seconds=time.time() - t0)


# ---------------------------------------------------------------- stage: sound
def _snd_job(a):
    root, c = a
    sb = _import_sndbank(root)
    t0 = time.time(); sb.levels(c)
    return c, time.time() - t0


def _import_sndbank(root):
    p = gdir(root, "tools", "snd")
    if p not in sys.path: sys.path.insert(0, p)
    t = os.path.join(root, "tools")
    if t not in sys.path: sys.path.insert(0, t)
    import sndbank
    assert os.path.normcase(os.path.dirname(os.path.abspath(sndbank.__file__))) == os.path.normcase(os.path.abspath(p)), sndbank.__file__
    return sndbank


NBANK = NCHAR + 1                                       # the 23 character banks + COMMON.SE (sndbank.COMMON = 0x17)


def stage_sound(root, jobs=1, progress=None, log=print):
    """every level of every bank (characters + COMMON), into the cache sndbank.py keeps (G/build/snd); mktag.py then
    finds them.  The banks do not depend on each other: the command line builds them in parallel processes."""
    todo = [(root, c) for c in range(NBANK)]; done = 0
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(min(jobs, NCHAR)) as ex:
            for c, s in ex.map(_snd_job, todo):
                done += 1; log("sound: bank %02X %.1f s" % (c, s))
                if progress: progress(done / NBANK, "bank %d of %d" % (done, NBANK))
    else:
        for j in todo:
            c, s = _snd_job(j); done += 1; log("sound: bank %02X %.1f s" % (c, s))
            if progress: progress(done / NBANK, "bank %d of %d" % (done, NBANK))


# ---------------------------------------------------------------- arcade sets
def arcade_sets():
    return json.load(open(os.path.join(DATA, "arcade_sets.json")))


def check_arcade(paths, root):
    """identify an arcade set -> (set name or "unknown set", desc); raises BuildError"""
    b8 = _tool(root, "games/mshvsf/tools/ap", "build8")
    try: prg, roms, desc = b8.read_arcade(list(paths))
    except b8.Fail as ex: raise BuildError(str(ex), code="arcade")
    del prg, roms
    for name, e in arcade_sets().items():
        if all(desc.get(k) == v for k, v in e["roms"].items()): return e["title"], desc
    return None, desc


def _tool(root, rel, name):
    """a tool module of this game by its path, under its own module name ("mshb_tool_" + name): XvSF has tools of the
    same name (tools/ap/build8.py) and both builders may run in one interpreter (the patcher page)"""
    p = os.path.join(root, *rel.split("/"))
    for q in (p, os.path.join(root, "tools", "ap"), os.path.join(root, "tools"), os.path.join(root, "common", "dsp")):
        if q not in sys.path: sys.path.insert(0, q)
    key = "mshb_tool_" + name
    m = sys.modules.get(key)
    f = os.path.join(p, name + ".py")
    if m is None or os.path.normcase(os.path.abspath(m.__file__)) != os.path.normcase(os.path.abspath(f)):
        import importlib.util
        spec = importlib.util.spec_from_file_location(key, f); m = importlib.util.module_from_spec(spec)
        sys.modules[key] = m; spec.loader.exec_module(m)
    return m


def stage_arcade(root, arcade, image, outdir, log=print):
    b8 = _tool(root, "games/mshvsf/tools/ap", "build8")
    if os.path.isdir(outdir): shutil.rmtree(outdir)
    try:
        with _argv("build8.py"): b8.main(["build8.py", "--arcade", *arcade, "--disc", image, "--out", outdir])
    except b8.Fail as ex: raise BuildError(str(ex), code="arcade")
    man = json.load(open(os.path.join(outdir, "manifest.json")))
    bad = {k: v["error"] for k, v in man["chars"].items() if "error" in v}
    if bad: log("arcade: characters kept stock: %s" % bad)


# ---------------------------------------------------------------- prebaked blobs (our own MIPS code)
# Every function of the tools that generates OUR code (the compiler / assembler runs inside them), with the module
# it lives in.  Their recorded results are in builder/data/mshvsf/blobs, keyed by function + arguments + context.
PREBAKED = [
    ("mktag", "build_blob"),        # loader blob + resident glue + GPU pool cap (tools/tagload: tagload.c, glue.S, snd.c)
    ("mkap8", "build_blob8"),       # the 8 MB loader blob (tools/ap8: ap8.c, entry8.S + the 2 MB loader)
    ("mkap8", "menu_part"),         # 8 MB menu code (ap8menu.S)
    ("mkap8", "build_s8"),          # 1.1 8 MB voice streaming engine (tools/ap8/s8: s8.c, snd8e.c), a disc file
    ("sndbuild", "hook"),           # sound unload hook (unlhook.S)
    ("meter", "parts"),             # speed meter (meter.S)
    ("allpatches", "patches"), ("allpatches", "overlay_patches"),       # gameplay layer (tagmode, pad, menus, cyber, version line)
    ("dsmpatch", "patches"),        # sprite decoders (common/dsp dsmdec.S)
    ("a0mem", "patches"), ("parse", "patches"), ("ahead", "patches"),   # speed modules
    ("mshcards", "card1"), ("mshcards", "card2_stub"),                 # boot card stubs (the card 2 picture is composed at build time)
    ("mshach", "code"),             # built-in achievements (--ach; tools/ach runtime + games/mshvsf/tools/ach)
    ("mshskip", "code"),            # START skips the end of a match (games/mshvsf/tools/skip; default on, --noskip)
    ("cyswap", "build"),            # 1.1 --cyswap: post-boss scene with the partner on point (gameplay/cyswap.S)
    ("exopt", "exe_build"), ("exopt", "screen"),     # 1.1 --exopt: EX OPTIONS / pause rows / FRAME SKIP / STAGE ANIM / ARCADE BALANCE
    ("l2", "image"), ("l2", "gate"), ("l2", "_asm"),  # 1.1 --l2g: packed frame groups (g2get image, gate, reader sites)
    ("mtpatch", "code"),            # 1.1 --vsmenu: the VERSUS CPU core (common/mtap + games/mshvsf/tools/mtap)
]
KEY_ARGS = {                        # call-key arguments that would carry a machine path: made relative to the tool root
    "mtpatch.code": lambda T, args, kw: (({"cfg_sha1": hashlib.sha1(json.dumps(_enc(dict(args[0], dir=os.path.relpath(args[0]["dir"], T.root).replace(os.sep, "/"))),
                                                                                sort_keys=True).encode()).hexdigest()},) + tuple(args[1:]), kw),   # (the cfg holds stock words: only its SHA-1 goes into the manifest)
}
ARGS_IGNORED = {"sndbuild.hook"}                       # its arguments are the compiler prefix and an object directory
CONTEXT_FLAGS = ("--nospeed", "--noahead", "--meter", "--meteron", "--stockmeter", "--nodsh", "--nologo",
                 "--mcfix", "--exopt", "--frameskip", "--stageanim", "--achpop", "--fpsmeter", "--l2g", "--cyswap", "--arcbal", "--vsmenu",
                 "--sndverify", "--pstall",      # 1.1 (absent before: the 1.0 keys are unchanged)
                 "--nori", "--infmeter", "--nosmrow", "--sn8full",    # 1.1 final (m11_f6 / mshvsf_ap8_f5)
                 "--excard",                                          # 1.1 final 2026-11-24: EX OPTIONS rows in the card save
                 "--galfix",                                          # 2026-11-25 m11_gf1: a0mem.py GALFIX (read at import)
                 "--work2")                                           # GitHub #23: ap8.c -DWORK2 (8 MB blob only; new bake keys)
FILE_BLOBS = {"dshdec.bin": ("work", "dsp", "dsh", "dshdec.bin")}     # the DSH1 decoder (common/dsp/dsh.py build mshvsf)


def manifest():
    p = os.path.join(BLOBS, "manifest.json")
    if not os.path.exists(p): return dict(format=1, calls={}, files={}, resolved={}, sources={})
    return json.load(open(p))


def _blob(sha):
    b = open(os.path.join(BLOBS, sha), "rb").read()
    if hashlib.sha1(b).hexdigest() != sha.split(".")[0]: raise BuildError("builder/data/mshvsf/blobs/%s is damaged (SHA-1 mismatch)" % sha, code="toolchain")
    return b


def source_hashes(repo=REPO):
    """SHA-1 of every source our code is made from (newlines normalised)"""
    out = {}
    for rel, p in root_files(RECORD_SPEC, repo, snapshot=False):
        if not rel.endswith((".py", ".c", ".S", ".h", ".ld", ".bin", ".json")) or rel.startswith("tools/") and not rel.startswith(("tools/logo/", "tools/snd/", "tools/speed/frame/")):
            continue
        out[rel] = hashlib.sha1(open(p, "rb").read().replace(b"\r\n", b"\n")).hexdigest()
    return out


def stale_sources(repo=REPO):
    rec = manifest().get("sources", {}); now = source_hashes(repo)
    return sorted(k for k in now if rec.get(k) != now[k])


class Tools:
    """the project's disc tools, imported from the tool root, with the output image virtual and our code prebaked"""

    def __init__(self, root, image, record=False, log=print):
        self.root = os.path.abspath(root); self.image = os.path.abspath(image); self.log = log; self.record = record
        self.G = gdir(self.root)
        self.overlays = {}; self.cache_events = []; self.man = manifest()
        self._corpus = None; self._files = {}
        self.purge()
        for p in [os.path.join(self.G, "tools", d) for d in ("tagload", "ap8", "ap", "gameplay", "speed", "snd", "logo", "ach", "skip", "l2", "mtap")] + \
                 [self.G + "/tools", os.path.join(self.root, "tools"), os.path.join(self.root, "common", "dsp"), os.path.join(self.root, "common", "mtap")]:
            if p not in sys.path: sys.path.insert(0, p)
        self.mods = {}

    KEEP = ("xvb", "mshb", "games", "snd")               # stateless libraries (snd: the browser puts its JavaScript kernels into it)

    def purge(self):
        """forget the tool modules imported before (another build, the other game): fresh module state per build"""
        r = os.path.normcase(self.root)
        for n, m in list(sys.modules.items()):
            if n.split(".")[0] in self.KEEP: continue
            f = getattr(m, "__file__", None)
            if f and os.path.normcase(os.path.abspath(f)).startswith(r): del sys.modules[n]
        for n in ("parse", "meter", "ahead", "reloc", "tagmode", "menus", "pad", "cyber", "slib", "deadcode", "dsp", "sndbank", "sndbuild"):
            m = sys.modules.get(n)                        # same names elsewhere (XvSF tools/speed ...): must come from the tool root
            if m is not None and not os.path.normcase(os.path.abspath(getattr(m, "__file__", "") or "")).startswith(r): del sys.modules[n]

    def _key(self, p): return os.path.normcase(os.path.abspath(p))

    def _open(self, path, mode="r", *a, **k):
        ov = self.overlays.get(self._key(path)) if isinstance(path, str) else None
        if ov is None:
            if isinstance(path, str) and self._key(path) == self._key(self.image) and mode == "rb" and not a and not k:
                return builtins.open(path, "rb", buffering=cdrom.READ_AHEAD)
            return builtins.open(path, mode, *a, **k)
        assert "b" in mode
        return cdrom.OverlayFile(ov)

    def _copyfile(self, src, dst):
        if self._key(src) == self._key(self.image):
            self.overlays[self._key(dst)] = cdrom.Overlay(self.image); return dst
        return shutil.copyfile(src, dst)

    def _getsize(self, p):
        ov = self.overlays.get(self._key(p))
        return ov.nsec * cdrom.SECTOR if ov is not None else os.path.getsize(p)

    def mod(self, name):
        if name in self.mods: return self.mods[name]
        m = importlib.import_module(name)
        f = os.path.normcase(os.path.abspath(m.__file__))
        assert f.startswith(os.path.normcase(self.root)), "%s imported from %s, not from the tool root" % (name, m.__file__)
        if hasattr(m, "shutil"):
            sh = type("shutil_shim", (), {"__getattr__": lambda s, n: getattr(shutil, n)})()
            sh.copyfile = self._copyfile; m.shutil = sh
        if hasattr(m, "subprocess"): m.subprocess = _Subprocess(self, name)
        if name in ("mktag", "mkap8"):
            m.open = self._open
            osm = type("os_shim", (), {"__getattr__": lambda s, n: getattr(os, n)})()
            pth = type("path_shim", (), {"__getattr__": lambda s, n: getattr(os.path, n)})()
            pth.getsize = self._getsize; osm.path = pth; m.os = osm
        if name == "mktag":
            m.fix_sector = cdrom.mark_for_seal
            m.SRC_BIN = self.image
        self.mods[name] = m
        return m

    # ---- prebaked blobs -------------------------------------------------------------------------------
    def read_game(self, name, off, n):
        if name not in self._files:
            p = gdir(self.root, "work", "disc_files", name)
            if os.path.isfile(p): self._files[name] = builtins.open(p, "rb").read()
            else:
                lmap = json.load(builtins.open(gdir(self.root, "work", "lba_map.json")))
                if name not in lmap: raise BuildError("builder/data/mshvsf/blobs refers to %s, which is not a file of the disc image" % name, code="toolchain")
                self._files[name] = tuple(lmap[name])
        f = self._files[name]
        if isinstance(f, bytes): return f[off:off + n]
        lba, size = f
        if off + n > size: return b""
        return cdrom.Disc(self.image).read(lba + off // 2048, off % 2048 + n)[off % 2048:]

    def ref(self, data):
        from xvb import gameref
        if self._corpus is None:
            fd = gdir(self.root, "work", "disc_files")
            self._corpus = gameref.Corpus({n: builtins.open(os.path.join(fd, n), "rb").read() for n in sorted(os.listdir(fd))}, first=(EXE,), cache_all=True)
        return gameref.encode(data, self._corpus)

    def load_blob(self, sha, resolved, what):
        res = _dec(json.loads(_blob(sha)), self.read_game)
        if resolved and _plain_sha1(res) != resolved:
            raise BuildError("%s: the code filled in from the disc image does not match the recorded result (blob %s)" % (what, sha[:12]), code="toolchain")
        return res

    def store_blob(self, res):
        b = json.dumps(_enc(res, self.ref), separators=(",", ":")).encode()
        sha = hashlib.sha1(b).hexdigest() + ".json"
        os.makedirs(BLOBS, exist_ok=True)
        if not os.path.exists(os.path.join(BLOBS, sha)): builtins.open(os.path.join(BLOBS, sha), "wb").write(b)
        assert _plain_sha1(_dec(json.loads(b), self.read_game)) == _plain_sha1(res)
        return sha, len(b), _plain_sha1(res)

    def context(self):
        menus = sys.modules.get("menus")
        ap8 = getattr(menus, "AP8", None) if menus else None
        return dict(argv=sorted(set(a for a in sys.argv if a in CONTEXT_FLAGS)), ap8=list(ap8) if ap8 else None)

    def prebake(self, m, fname):
        orig = getattr(m, fname)
        if getattr(orig, "_mshb_prebaked", None) is self: return
        orig = getattr(orig, "_mshb_orig", orig)
        fn = m.__name__ + "." + fname

        def after(res):                                   # side effects of the original that the tools rely on
            if fn == "mkap8.build_blob8":
                sym = res[2]
                if "--exopt" not in sys.argv:            # (as mkap8.build_blob8: the 1.1 EX OPTIONS build has no OPTION line)
                    sys.modules["menus"].AP8 = (sym["tl_dbg"] + 13, sym["tl_dbg"] + 15)
                wrapped.sym = sym
            return res

        def wrapped(*args, **kw):
            ka = () if fn in ARGS_IGNORED else args; kk = {} if fn in ARGS_IGNORED else kw
            if fn in KEY_ARGS: ka, kk = KEY_ARGS[fn](self, ka, kk)
            ctx = self.context()
            key = hashlib.sha1(json.dumps([fn, _enc(tuple(ka)), _enc(dict(kk)), ctx], sort_keys=True).encode()).hexdigest()
            if self.record:
                res = orig(*args, **kw)
                # (build_blob8 sets build_blob8.sym = this wrapper's attribute, and menus.AP8, itself)
                sha, size, rsha = self.store_blob(res)
                self.man["calls"][key] = dict(function=fn, args=_enc(tuple(ka)), kwargs=_enc(dict(kk)), context=ctx, blob=sha, size=size, resolved=rsha)
                self.cache_events.append((fn, "baked")); self.log("%s: baked %s" % (fn, sha[:12]))
                return res
            e = self.man["calls"].get(key)
            if e is None:
                if os.environ.get("MSHB_DUMP_MISSING"):
                    json.dump([fn, _enc(tuple(ka)), _enc(dict(kk)), ctx], open(os.environ["MSHB_DUMP_MISSING"], "w"))
                raise BuildError("This combination of options needs our code %s(%s), which is not prebaked in builder/data/mshvsf/blobs "
                                 "(the builder never compiles; work/mshvsf_release/record.py bakes it)." % (fn, ", ".join(repr(x)[:40] for x in ka)), code="toolchain")
            self.cache_events.append((fn, "prebaked")); self.log("%s: prebaked %s" % (fn, e["blob"][:12]))
            return after(self.load_blob(e["blob"], e.get("resolved"), fn))
        wrapped._mshb_prebaked = self; wrapped._mshb_orig = orig
        setattr(m, fname, wrapped)

    def prebake_all(self, ap8=False):
        """(called with the build's argv in sys.argv: mktag.py reads --l2g / --nodsh at import)"""
        if "--l2g" in sys.argv: self.prebake(self.mod("l2"), "image")      # mktag.py runs l2.image() at import
        mods = ["mktag"] + (["mkap8"] if ap8 else [])
        for n in mods: self.mod(n)
        for mn, fn in PREBAKED:
            if mn == "mkap8" and not ap8: continue
            self.prebake(self.mod(mn), fn)
        for name, rel in FILE_BLOBS.items():           # our prebuilt files the tools read
            dst = gdir(self.root, *rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if self.record:
                src = os.path.join(REPO, G_REL, *rel)
                b = builtins.open(src, "rb").read()
                sha, size, rsha = self.store_blob(b)
                self.man["files"][name] = sha; self.man["resolved"][name] = rsha
            sha = self.man["files"].get(name)
            if sha is None: raise BuildError("the prebuilt %s is not in builder/data/mshvsf/blobs" % name, code="toolchain")
            builtins.open(dst, "wb").write(self.load_blob(sha, self.man["resolved"].get(name), name))

    def save_manifest(self):
        if not self.record: return
        self.man.update(format=1, sources=source_hashes(), note="our own MIPS code, made by work/mshvsf_release/record.py; blob name = SHA-1 of the blob")
        os.makedirs(BLOBS, exist_ok=True)
        json.dump(self.man, builtins.open(os.path.join(BLOBS, "manifest.json"), "w"), indent=1, sort_keys=True)

    def finish(self, name):
        ov = self.overlays[self._key(gdir(self.root, "build", name + ".bin"))]
        t0 = time.time(); n = ov.seal_marked(); self.seal_time = time.time() - t0
        self.log("sealed %d sectors (EDC/ECC); %d sectors differ from or follow the original image" % (n, len(ov.dirty)))
        return ov


class _Subprocess:
    """the builder runs no external program; only record mode passes the calls through"""
    def __init__(self, tools, name): self.t = tools; self.name = name

    def __getattr__(self, n):
        import subprocess
        f = getattr(subprocess, n)
        if n not in ("check_call", "check_output", "run", "call", "Popen"): return f

        def run(cmd, *a, **k):
            prog = cmd[0] if isinstance(cmd, (list, tuple)) else cmd
            if not self.t.record:
                raise BuildError("%s tried to run %s: the builder never compiles; this code must be prebaked in builder/data/mshvsf/blobs."
                                 % (self.name, os.path.basename(str(prog))), code="toolchain")
            return f(cmd, *a, **k)
        return run


INTERNAL = {"2mb": "mshvsf_tag", "8mb": "mshvsf_ap8"}


def stage_disc(T, flags, content=None, ap8=False, arcade=()):
    """tools/tagload/mktag.py NAME [flags]  or  tools/ap8/mkap8.py NAME [--content DIR] [flags]  -> Overlay.
    ap8 without content: the 8 MB loader without restored frames (all four characters full from upper RAM)"""
    ap8 = ap8 or content is not None
    name = INTERNAL["8mb" if ap8 else "2mb"]
    if ap8:
        argv = ["mkap8.py", name] + (["--content", content] if content else []) + list(flags) + (
            ["--sn8arc"] + list(arcade) if content and arcade else [])          # 1.1: the arcade voices from the same set
        with _argv(*argv): T.prebake_all(ap8); T.mod("mkap8").main(argv)
    else:
        argv = ["mktag.py", name] + list(flags)
        with _argv(*argv): T.prebake_all(ap8); T.mod("mktag").main(argv)
    return T.finish(name)


# ---------------------------------------------------------------- configurations
RELEASE = "1.1"
RELEASE_TITLE = "TAG HACK 1.1"                          # 2 MB = games/mshvsf/build/m11_f6, 8 MB = mshvsf_ap8_f5
RELEASE_FLAGS = ["--meter"]                            # the meter is built (its flag word holds the EX option bytes); 1.1 has no row for it
RELEASE_11 = ["--mcfix", "--exopt", "--stageanim", "--l2g", "--cyswap", "--arcbal", "--vsmenu", "--nori", "--infmeter", "--nosmrow",
              "--excard", "--galfix"]   # (2026-11-25 --galfix: m11_gf1 / mshvsf_ap8_gf1) 1.1, 2 MB (--excard: EX OPTIONS rows saved with the game's memory card save, 2026-11-24)
RELEASE8_TITLE = RELEASE_TITLE                          # 8 MB loader (--ram8 / --arcade): the 1.1 set without --l2g (2 MB only)
RELEASE8 = [f for f in RELEASE_11 if f != "--l2g"] + ["--sn8full", "--work2"]   # + voice streaming (arcade voices with an arcade set)
# --work2 (GitHub #23, mshvsf_ap8_i23e): a code slot keeps one character per boot, others run from the 2 MB area (emulators
# with a block cache missed the upper-RAM rewrites).  The blob grows 1120 B; dual.py takes its window from the link symbols.


def tool_flags(logo=True, meter="off", extra=(), achievements=True, ap8=False):
    """the builder's options -> flags of tools/tagload/mktag.py (and tools/ap8/mkap8.py, which hands them on).
    meter: "off" (in the OPTION menu, off at boot; the release), "on" (on at boot), "none" (no meter code).
    2 MB = the 1.1 release (its EX OPTIONS menu needs the meter: "none" is refused); ap8 (8 MB loader) = 1.0.1."""
    f = []
    if meter in ("off", "on"): f.append("--meter")
    if meter == "on": f.append("--meteron")
    if not logo: f.append("--nologo")
    if achievements: f.append("--ach")                    # built-in achievements (CLI opt-out --no-achievements)
    if meter == "none": raise BuildError("--meter none: the 1.1 image keeps its EX option bytes in the meter's flag word; use --meter off.", code="option")
    if meter == "on": raise BuildError("--meter on: the 1.1 release has no speed meter (development builds only).", code="option")
    f += (RELEASE8 if ap8 else RELEASE_11) + (["--achpop"] if achievements else []) + ["--title=" + (RELEASE8_TITLE if ap8 else RELEASE_TITLE)]
    return f + list(extra)


def version_text(root=None, flags=()):
    t = next((a.split("=", 1)[1] for a in flags if a.startswith("--title=")), None)
    if t: return t
    try:
        return importlib.import_module("menuversion").DEFAULT
    except Exception:
        return "TAG HACK"


def output_name(arcade, ver="TAG HACK 0.1", ap8=False):
    return "%s [%s%s]" % (TITLE, ver.title(), " + Restored Frames" if arcade else " 8 MB" if ap8 else "")


STAGES = [("verify", "Checking the disc image"), ("extract", "Reading the game files"), ("sprites", "Re-encoding the character graphics"),
          ("sound", "Rebuilding the sound banks"), ("arcade", "Restoring animation frames from the arcade set"), ("disc", "Assembling the patched disc")]


def expected(variant, setname, flags):
    for e in known().get("expected", []):
        if e["variant"] == variant and e.get("arcade_set") == setname and e["flags"] == sorted(flags): return e
    return None


def run(disc, work, root=None, arcade=(), flags=(), name=None, jobs=1, progress=None, log=print, record=False, known_sha1=None,
        sprite_ref=None, skip_sound=False, arcade_built=False, ap8=False):
    """-> dict(overlay=Overlay, name=..., variant, arcade_set, times).  root: the tool root (default <work>/root, made
    here); the browser passes its unpacked bundle.  ap8: the 8 MB loader without an arcade set (an arcade set implies
    it).  progress(stage, fraction, text); log(line)."""
    times = {}; info = dict(times=times, flags=list(flags))
    P = (lambda s, f, t="": progress(s, f, t)) if progress else (lambda s, f, t="": None)

    def stage(key):
        @contextlib.contextmanager
        def cm():
            t0 = time.time(); P(key, 0.0)
            yield
            times[key] = times.get(key, 0) + time.time() - t0; P(key, 1.0)
        return cm()
    os.makedirs(work, exist_ok=True)
    if root is None:
        root = os.path.join(work, "root"); make_root(root, record)
    with stage("verify"):
        idn = identify(disc, *(known_sha1 or sha1_file(disc, lambda f: P("verify", f))))
        if idn["status"] != "ok": raise BuildError(idn["message"], code=idn["status"])
        log("input: %s  sha1 %s" % (idn["message"], idn["sha1"])); info["input"] = idn
    with stage("extract"):
        stamp = gdir(root, "work", "extract.stamp")
        if os.path.exists(stamp) and open(stamp).read() == idn["sha1"]: log("extract: files are current")
        else:
            lmap = extract(disc, root); log("extracted %d files" % len(lmap))
            open(stamp, "w").write(idn["sha1"])
    if arcade:
        with stage("verify"):
            setname, desc = check_arcade(arcade, root)
            info["arcade_set"] = setname or "unknown set"; log("arcade set: %s" % info["arcade_set"])
    with stage("sprites"):
        info["sprites"] = stage_sprites(root, jobs, lambda f, t="": P("sprites", f, t), log, reference=sprite_ref)
    if not skip_sound:
        with stage("sound"):
            stage_sound(root, jobs, lambda f, t="": P("sound", f, t), log)
    buf = _LineLog(log)
    content = None
    if arcade:
        content = gdir(root, "work", "ap", "content")
        if arcade_built: log("arcade: content built before (%s)" % content)
        else:
            with stage("arcade"), contextlib.redirect_stdout(buf):
                stage_arcade(root, list(arcade), disc, content, log)
    T = Tools(root, disc, record, log)
    with stage("disc"), contextlib.redirect_stdout(buf):
        ov = stage_disc(T, list(flags), content, ap8, list(arcade))
        ver = version_text(flags=flags)
    buf.flush()
    T.save_manifest()
    if (arcade or ap8) and os.environ.get("MSHB_NODUAL") != "1":
        # (2026-11-24, 1.1 final mshvsf_ap8_f11) DUAL image: the 2 MB build with the same options (= the 2 MB release disc)
        # + this 8 MB build appended, switched over only by a boot-time 8 MB test (mshb/dual.py): in 2 MB mode the
        # 8 MB disc runs exactly the 2 MB disc's code and data
        from mshb import dual
        fl = list(flags); k = next(i for i in range(len(fl)) if fl[i:i + len(RELEASE8)] == RELEASE8)
        flags2 = fl[:k] + RELEASE_11 + fl[k + len(RELEASE8):]           # = tool_flags(..., ap8=False) with the same options
        sym8 = json.load(open(gdir(root, "build", INTERNAL["8mb"] + ".patches.json")))["sym"]
        T.seal_time = getattr(T, "seal_time", 0)
        st0 = T.seal_time
        T2 = Tools(root, disc, record, log)
        with stage("disc"), contextlib.redirect_stdout(buf):
            ov2 = stage_disc(T2, flags2)
            ov = dual.compose(ov2, ov, sym8, log)
        buf.flush()
        T2.save_manifest()
        T.seal_time = st0 + T2.seal_time; T.cache_events += T2.cache_events
    times["seal"] = T.seal_time; times["disc"] -= T.seal_time
    info.update(overlay=ov, name=name or output_name(bool(arcade), ver, ap8), blobs=T.cache_events, variant="8mb" if (arcade or ap8) else "2mb")
    info.setdefault("arcade_set", None)
    return info
