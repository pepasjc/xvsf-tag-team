"""The MvC build, from an untouched disc image (+ the user's arcade set for the 8 MB image) to the patched image.

    stage     reads                                        writes (under the work directory)
    --------  -------------------------------------------  -----------------------------------------------------------
    verify    the image (SHA-1, size)                      -
    root      builder/data/mvc/tools (the frozen tools)    <work>/root: the tool files, repository layout
    extract   the image (ISO9660)                          <root>/games/mvc/work/disc_files/* + the stock files the
                                                           tools read where they read them (data/mvc/derived.json)
    derive    the extracted files + data/mvc/derived.json  every file of the game the tools read that is not a stock
                                                           file: the half-res effects A0s, the sprite tiers (codec
                                                           recipes: our models, tile streams re-emitted from the
                                                           user's pixels), the store-once pair files, the assist
                                                           tiers, our own data files
    disc      all of the above, data/mvc/tc                tools/tagload/mktag.py or tools/ap8/mkap8.py, unmodified,
                                                           run in the tool root; the patched image is an Overlay
    seal      -                                            EDC/ECC of every rewritten sector

The tools run UNMODIFIED with their own relative paths.  The harness gives them the user's image as their source, an
Overlay for the output image, defers EDC/ECC, and replaces the MIPS toolchain by its recorded results
(mvcb/toolbake.py: every gcc / as / ld / objcopy / nm command of the build, keyed by its inputs' content).  So whatever
the tools build, this builds, byte for byte (work/mvcb/record_mvc.py checks it against the final images).
"""
import builtins, contextlib, hashlib, json, os, shutil, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(BUILDER, ".."))
if BUILDER not in sys.path: sys.path.insert(0, BUILDER)
from xvb import cdrom                                                                       # noqa: E402
from xvb.pipeline import BuildError, sha1_file, _LineLog, _argv, cue_text                 # noqa: E402

GAME = "mvc"
G_REL = "games/mvc"
DATA = os.path.join(BUILDER, "data", GAME)
SNAP = os.path.join(DATA, "tools")
TC = os.path.join(DATA, "tc")
FILES = os.path.join(DATA, "files")                  # our own data files (content-addressed)
EXE = "SLUS_010.59"
TITLE = "Marvel vs. Capcom (USA)"
SRC_REL = "games/mvc/disc/mvc.bin"


def _j(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else default


def known(): return _j("known.json")


def configs(): return _j("configs.json", {})


def gdir(root, *p): return os.path.join(root, *G_REL.split("/"), *p)


def rp(root, rel): return os.path.join(root, *rel.split("/"))


# ---------------------------------------------------------------- stage: verify
def identify(path, sha1=None, size=None):
    kn = known(); inp = kn["input"]
    if sha1 is None: sha1, size = sha1_file(path)
    if sha1 == inp["sha1"]:
        return dict(status="ok", sha1=sha1, size=size, message=inp["title"], game=GAME)
    for e in kn.get("expected", []) + kn.get("previous", []):
        if sha1 == e["sha1"]:
            return dict(status="patched", sha1=sha1, size=size, game=GAME, message="This image is already patched (it is a %s image this builder made). "
                        "Use the original, unmodified disc image." % ("tag hack 8 MB" if e["variant"] == "8mb" else "tag hack"))
    try:
        if size % cdrom.SECTOR: raise ValueError
        d = cdrom.Disc(path); names = {n.split("/")[-1]: (l, s) for n, l, s in d.walk()}
    except Exception:
        return dict(status="notimage", sha1=sha1, size=size, message="This is not a raw PlayStation disc image (MODE2/2352 .bin).")
    if EXE not in names:
        return dict(status="notgame", sha1=sha1, size=size, message="This disc is not Marvel vs. Capcom (USA, %s)." % inp["serial"])
    if size != inp["size"]:
        return dict(status="patched", sha1=sha1, size=size, game=GAME, message="This looks like an image that already carries the tag hack (or another "
                    "modification): its size differs from the original. Use the original, unmodified disc image.")
    return dict(status="baddump", sha1=sha1, size=size, game=GAME, message="This is the right game (%s) but not the known good dump: its SHA-1 is %s, expected %s "
                "(size %d bytes). It may be modified or badly dumped; the patch is only applied to the exact original." % (inp["serial"], sha1, inp["sha1"], inp["size"]))


# ---------------------------------------------------------------- stage: root
SKIP_DIRS = ("__pycache__",)


def root_files(record=False):
    """[(relative path, path on disk)]: the frozen tool files (data/mvc/tools; record mode: the repository)"""
    lst = _j("rootfiles.json", [])
    base = REPO if record or not os.path.isdir(SNAP) else SNAP
    return [(r, rp(base, r)) for r in lst]


def make_root(root, record=False):
    for rel, p in root_files(record):
        dst = rp(root, rel)
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(p) and open(dst, "rb").read() == open(p, "rb").read(): continue
        os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(p, dst)
    lp = os.path.join(root, "local_paths.json")
    if record and os.path.exists(os.path.join(REPO, "local_paths.json")): shutil.copyfile(os.path.join(REPO, "local_paths.json"), lp)
    elif not record and os.path.exists(lp): os.remove(lp)


def snapshot(disc):
    """record: freeze the tool files the build runs into data/mvc/tools; words of the game in their text become
    references to the disc (mvcb/textref.py, data/mvc/textref.json)"""
    from xvb import gameref
    from mvcb import textref
    d = cdrom.Disc(disc); files = {}
    for full, lba, sz in d.walk(): files[full.split("/")[-1].split(";")[0]] = d.read(lba, sz)
    corpus = gameref.Corpus(files, first=(EXE,), cache_all=True)
    if os.path.isdir(SNAP): shutil.rmtree(SNAP)
    refs = {}
    for rel, p in root_files(record=True):
        b = open(p, "rb").read()
        if rel.endswith((".py", ".c", ".h", ".S", ".s", ".inc", ".json", ".txt", ".md")) and b"\0" not in b:
            b2, runs = textref.strip(b, corpus)
            if runs: refs[rel] = runs; b = b2
        dst = rp(SNAP, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, "wb").write(b)
    json.dump(refs, open(os.path.join(DATA, "textref.json"), "w"), separators=(",", ":"))
    return refs


def fill_root(root):
    """after extract: write the game words of the tool sources back from the user's disc (textref.json)"""
    from mvcb import textref
    refs = _j("textref.json", {})
    if not refs: return 0
    fd = gdir(root, "work", "disc_files"); cache = {}
    def read(name, off, n):
        if name not in cache: cache[name] = open(os.path.join(fd, name), "rb").read()
        return cache[name][off:off + n]
    for rel, runs in refs.items():
        p = rp(root, rel); b = open(p, "rb").read()
        if b"~~~~~~~~" not in b: continue                  # (filled before)
        open(p, "wb").write(textref.fill(b, runs, read))
    return len(refs)


# ---------------------------------------------------------------- stage: extract
def extract(image, root):
    """every file of the disc up to 8 MB -> <root>/games/mvc/work/disc_files/NAME; lba map -> games/mvc/work/lba_map.json
    (the format mktag.py lba_map() writes)"""
    d = cdrom.Disc(image); lmap = {}
    out = gdir(root, "work", "disc_files"); os.makedirs(out, exist_ok=True)
    for full, lba, sz in d.walk():
        n = full.split("/")[-1].split(";")[0]
        lmap[n] = [lba, sz]
        if sz <= 8 << 20:
            with open(os.path.join(out, n), "wb") as f: f.write(d.read(lba, sz))
    with open(gdir(root, "work", "lba_map.json"), "w") as f: json.dump(lmap, f)
    return lmap


# ---------------------------------------------------------------- stage: derive
class Pool:
    """files by name for the recipes: 'disc:NAME' = a file of the user's disc, other names = root-relative paths"""

    def __init__(self, root):
        self.root = root; self.cache = {}

    def path(self, name):
        if name.startswith("disc:"): return gdir(self.root, "work", "disc_files", name[5:])
        return rp(self.root, name)

    def get(self, name):
        if name not in self.cache:
            p = self.path(name)
            if not os.path.isfile(p): raise BuildError("derive: %s is missing" % name, code="toolchain")
            self.cache[name] = open(p, "rb").read()
        return self.cache[name]

    def view(self, spec):
        """'NAME' or 'NAME#dsp' (the DSP part of an A0: from the offset at +12 to the end)"""
        if spec.endswith("#dsp"):
            b = self.get(spec[:-4]); return b[struct.unpack_from("<I", b, 12)[0]:]
        return self.get(spec)

    def put(self, name, data):
        p = rp(self.root, name); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f: f.write(data)
        self.cache[name] = bytes(data)


def _unref(x, read):
    """literals of a recipe that carry words of the game are stored as references to the disc ({"__bref__": segs},
    xvb/gameref.py, made by work/mvcb/record_mvc.py): -> the hex string they stand for"""
    if isinstance(x, dict):
        if "__bref__" in x:
            from xvb import gameref
            return gameref.resolve(x["__bref__"], read).hex()
        return {k: _unref(v, read) for k, v in x.items()}
    if isinstance(x, list): return [_unref(v, read) for v in x]
    return x


def derive_one(e, pool):
    from mvcb import tiers, fxhalf, pairs
    e = _unref(e, lambda name, off, n: pool.get("disc:" + name)[off:off + n])
    k = e["kind"]
    if k == "disc": return pool.get("disc:" + e["name"])
    if k == "data": return _file(e["blob"])
    if k == "fx": return fxhalf.build(pool.get(e["src"]), e["flagged"])
    if k == "pair":
        A, j = pairs.build(pool.get(e["b_a0"]), pool.get(e["u_a0"]), e["b"], e["u"])
        return A if e.get("part") != "json" else j.encode()
    if k == "tier":
        src = {n: pool.view(s) for n, s in e["sources"].items()}
        return tiers.build(e["recipe"], src)
    if k == "diff":
        src = {n: pool.view(s) for n, s in e["sources"].items()}
        return tiers.undiff(e["segs"], src)
    raise BuildError("derive: unknown kind %s" % k, code="toolchain")


def _file(sha):
    b = open(os.path.join(FILES, sha), "rb").read()
    if hashlib.sha1(b).hexdigest() != sha: raise BuildError("builder/data/mvc/files/%s is damaged" % sha, code="toolchain")
    return b


def stage_derive(root, entries, progress=None, log=print, check=True):
    pool = Pool(root); n = len(entries); t0 = time.time()
    for i, e in enumerate(entries):
        b = derive_one(e, pool)
        if check and e.get("sha1") and hashlib.sha1(b).hexdigest() != e["sha1"]:
            raise BuildError("derive: %s does not come out as recorded (%s)" % (e["path"], e["kind"]), code="toolchain")
        pool.put(e["path"], b)
        if progress: progress((i + 1) / n, e["path"].split("/")[-1])
    log("derive: %d files %.1f s" % (n, time.time() - t0))


# ---------------------------------------------------------------- stage: sound
def _snd_job(a):
    root, name, env = a
    os.environ.update(env)
    for q in (gdir(root, "tools", "snd"), os.path.join(root, "tools")):
        if q not in sys.path: sys.path.insert(0, q)
    import sndbank
    t0 = time.time(); sndbank.levels(name)
    return name, time.time() - t0


def stage_sound(root, cfg, jobs=1, progress=None, log=print):
    """every level of every sound bank into the cache tools/snd/sndbank.py keeps (games/mvc/build/snd), in parallel
    processes; mktag.py then finds them (its own key)"""
    env = {"VOICEHQ": "1" if "--voicehq" in cfg["argv"] else "0", "VOICEVOL": "1" if "--voicevol" in cfg["argv"] else "0"}
    p = gdir(root, "tools", "snd")
    if p not in sys.path: sys.path.insert(0, p)
    import importlib.util
    spec = importlib.util.spec_from_file_location("mvcb_sndnames", os.path.join(p, "sndbank.py"))
    old = sys.argv; sys.argv = [sys.argv[0]]
    try:
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    finally: sys.argv = old
    names = m.bank_names(); todo = [(root, n, env) for n in names]; done = 0
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(min(jobs, len(todo))) as ex:
            for n, sec in ex.map(_snd_job, todo):
                done += 1; log("sound: bank %s %.1f s" % (n, sec))
                if progress: progress(done / len(todo), "bank %d of %d" % (done, len(todo)))
    else:
        for j in todo:
            n, sec = _snd_job(j); done += 1; log("sound: bank %s %.1f s" % (n, sec))
            if progress: progress(done / len(todo), "bank %d of %d" % (done, len(todo)))


# ---------------------------------------------------------------- the tools
class Harness:
    """runs a tool's main() in the tool root: the user's image as the source, an Overlay as the output, EDC/ECC deferred,
    the toolchain prebaked (toolbake)"""

    def __init__(self, root, image, record=False, log=print):
        from mvcb import toolbake
        self.root = os.path.abspath(root); self.image = os.path.abspath(image); self.record = record; self.log = log
        self.src_key = os.path.normcase(rp(self.root, SRC_REL))
        self.overlays = {}; self._files = {}; self._corpus = None
        self.tb = toolbake.ToolBake(self.root, record, TC, read_game=self.read_game, ref=self.ref if record else None, log=log)
        self.shim = toolbake.Shim(self.tb)

    def _k(self, p): return os.path.normcase(os.path.abspath(p))

    def read_game(self, name, off, n):
        if name not in self._files:
            p = gdir(self.root, "work", "disc_files", name)
            if os.path.isfile(p): self._files[name] = builtins.open(p, "rb").read()
            else:
                lmap = json.load(builtins.open(gdir(self.root, "work", "lba_map.json")))
                if name not in lmap: raise BuildError("builder/data/mvc refers to %s, which is not a file of the disc image" % name, code="toolchain")
                self._files[name] = tuple(lmap[name])
        f = self._files[name]
        if isinstance(f, bytes): return f[off:off + n]
        lba, size = f
        return cdrom.Disc(self.image).read(lba + off // 2048, off % 2048 + n)[off % 2048:]

    def ref(self, data):
        from xvb import gameref
        if self._corpus is None:
            fd = gdir(self.root, "work", "disc_files")
            self._corpus = gameref.Corpus({n: builtins.open(os.path.join(fd, n), "rb").read() for n in sorted(os.listdir(fd))}, first=(EXE,), cache_all=True)
        return gameref.encode(data, self._corpus)

    @contextlib.contextmanager
    def active(self):
        """global hooks while a tool runs: open() of the source image / the output image, shutil.copyfile, os.path.getsize"""
        H = self
        o_open, o_copy, o_size = builtins.open, shutil.copyfile, os.path.getsize
        o_exists, o_isfile = os.path.exists, os.path.isfile
        import io as _io
        o_io = _io.open

        def _open(path, mode="r", *a, **k):
            if isinstance(path, (str, bytes, os.PathLike)) and not isinstance(path, int):
                p = os.fsdecode(path); kk = H._k(p)
                ov = H.overlays.get(kk)
                if ov is not None: return cdrom.OverlayFile(ov)
                if kk == H.src_key:
                    assert "w" not in mode and "+" not in mode and "a" not in mode, "the source image is read only"
                    return o_open(H.image, mode, *a, **k)
                if H.record: H.tb.note_open(p, mode)
            return o_open(path, mode, *a, **k)

        def _copy(src, dst, *a, **k):
            ks = H._k(src)
            if ks == H.src_key or ks == H._k(H.image):
                H.overlays[H._k(dst)] = cdrom.Overlay(H.image); return dst
            return o_copy(src, dst, *a, **k)

        def _size(p):
            kk = H._k(os.fsdecode(p))
            ov = H.overlays.get(kk)
            if ov is not None: return ov.nsec * cdrom.SECTOR
            if kk == H.src_key: return o_size(H.image)
            return o_size(p)

        def _exists(p):
            try: kk = H._k(os.fsdecode(p))
            except TypeError: return o_exists(p)
            return kk in H.overlays or kk == H.src_key or o_exists(p)

        def _isfile(p):
            try: kk = H._k(os.fsdecode(p))
            except TypeError: return o_isfile(p)
            return kk in H.overlays or kk == H.src_key or o_isfile(p)
        builtins.open = _open; _io.open = _open; shutil.copyfile = _copy; os.path.getsize = _size
        os.path.exists = _exists; os.path.isfile = _isfile
        sys.path.insert(0, os.path.join(self.root, "tools"))
        import mkdisc                                     # (tools/mkdisc.py of the root: fix_sector deferred for every importer)
        o_fix = mkdisc.fix_sector; mkdisc.fix_sector = cdrom.mark_for_seal
        try:
            self.shim.install()
            yield
        finally:
            self.shim.uninstall(); mkdisc.fix_sector = o_fix
            builtins.open = o_open; _io.open = o_io; shutil.copyfile = o_copy; os.path.getsize = o_size
            os.path.exists = o_exists; os.path.isfile = o_isfile

    def finish(self, name):
        ov = self.overlays[self._k(gdir(self.root, "build", name + ".bin"))]
        t0 = time.time(); n = ov.seal_marked(); self.seal_time = time.time() - t0
        self.log("sealed %d sectors (EDC/ECC); %d sectors differ from or follow the original image" % (n, len(ov.dirty)))
        return ov


def _purge(root):
    """forget modules imported from an earlier tool root / the repository (the same module names)"""
    r = os.path.normcase(os.path.abspath(root))
    for n, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None) or ""
        if n.split(".")[0] in ("xvb", "mshb", "mvcb"): continue
        if n == "__main__" or not f: continue
        fn = os.path.normcase(os.path.abspath(f))
        if (fn.startswith(os.path.normcase(REPO) + os.sep) and not fn.startswith(os.path.normcase(BUILDER) + os.sep)) or fn.startswith(r + os.sep):
            del sys.modules[n]


FRAMES_TOOLS = ["games/mvc/tools/ap/build8.py", "games/mvc/tools/ap/keep8.json", "games/mvc/tools/ap/keep8_speed.json",
                "tools/ap/aplib.py", "tools/nsp.py", "tools/iso.py", "common/dsp/dsp.py"]   # build8.py's closure (--frames8)


def frames_files(H, root, arcade, log=print):
    """--frames8 (8 MB arcade frames): games/mvc/tools/ap/build8.py IN-PROCESS on the user's arcade set + disc (the tool runs it
    as a subprocess keyed by file times); cached in <root>/work/fr8/cache_<content key>.  -> {char: PLxx.R8 bytes, 0x100 + x: DAxx.R8}
    (same reading and checks as tools/ap8/mkap8.py r8_files)"""
    import hashlib, runpy
    h = hashlib.sha1()
    for rel in FRAMES_TOOLS: h.update(open(rp(root, rel), "rb").read())
    for f in arcade:
        with open(f, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 22), b""): h.update(b)
    stamp = gdir(root, "work", "extract.stamp")
    h.update(open(stamp).read().encode() if os.path.exists(stamp) else open(H.image, "rb").read(1 << 20))
    h.update(os.environ.get("FR8_STOCKCH", "").encode() + os.environ.get("FR8_KMIN", "").encode())
    out = gdir(root, "work", "fr8", "cache_" + h.hexdigest()[:16]); man = os.path.join(out, "manifest.json")
    if not os.path.exists(man):
        log("arcade frames: build8 (in process) -> %s" % out)
        tmp = out + ".tmp"; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(os.path.dirname(out), exist_ok=True)
        b8 = gdir(root, "tools", "ap", "build8.py")
        old = list(sys.path); sys.path[:0] = [os.path.dirname(b8), os.path.join(root, "tools", "ap"), os.path.join(root, "tools"), os.path.join(root, "common", "dsp")]
        try:
            for n in ("aplib", "dsp", "nsp", "iso", "build8"): sys.modules.pop(n, None)
            g = runpy.run_path(b8, run_name="__mvcb_build8__")
            g["main"](["build8.py", "--arcade"] + list(arcade) + ["--disc", H.image, "--out", tmp])
        finally: sys.path[:] = old
        if os.path.exists(out): shutil.rmtree(out)
        os.rename(tmp, out)
    m = json.load(open(man)); fs = {}
    for c in range(1, 0x17):
        e = m["chars"].get("%02X" % c, {})
        assert "error" not in e and e, ("arcade frames: character %02X not built" % c, e)
        fs[c] = open(os.path.join(out, "PL%02X.R8" % c), "rb").read()
        assert hashlib.sha1(fs[c]).hexdigest() == e["sha1"]["r8"]
    for x in range(0x16):
        e = m.get("assists", {}).get("%02X" % x); assert e, "arcade frames: assist %02X not built" % x
        fs[0x100 + x] = open(os.path.join(out, "DA%02X.R8" % x), "rb").read()
    return fs


def stage_disc(H, cfg, root, arcade=()):
    """the tool's main() in the tool root with the configuration's arguments and environment"""
    env = {k: v.replace("<R>", root.replace("\\", "/")) for k, v in cfg.get("env", {}).items()}
    old_env = {k: os.environ.get(k) for k in env}
    old_path = list(sys.path); old_cwd = os.getcwd()
    tl = gdir(root, "tools", "tagload")
    argv = [cfg["script"]] + [a.replace("<R>", root.replace("\\", "/")) for a in cfg["argv"]]
    if arcade: argv += ["--arcade"] + list(arcade)
    os.environ.update(env)
    old_env.setdefault("XVSF_MIPS_PREFIX", os.environ.get("XVSF_MIPS_PREFIX"))
    if not H.record: os.environ["XVSF_MIPS_PREFIX"] = os.path.join(root, "notools", "mipsel-none-elf-")   # (record: toolenv finds it)
    os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(root, "work", "nbcache"))
    _purge(root)
    try:
        os.chdir(tl)
        sys.path[:0] = [tl, os.path.join(root, "tools"), os.path.join(root, "common", "dsp")]
        import importlib.util
        script = os.path.join(tl, cfg["script"]) if cfg["tool"] == "mktag" else gdir(root, "tools", "ap8", "mkap8.py")
        if cfg["tool"] == "mkap8": sys.path.insert(0, os.path.dirname(script))
        with H.active(), _argv(*argv):
            spec = importlib.util.spec_from_file_location("__mvcb_main__", script)
            m = importlib.util.module_from_spec(spec)
            sys.modules[cfg["tool"]] = m
            spec.loader.exec_module(m)
            if cfg["tool"] == "mkap8" and "--frames8" in argv and hasattr(m, "r8_files"):
                m.r8_files = lambda arc: frames_files(H, root, arc, H.log if hasattr(H, "log") else print)
            m.main(argv)
    finally:
        os.chdir(old_cwd); sys.path[:] = old_path
        for k, v in old_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    return H.finish(cfg["name"])


# ---------------------------------------------------------------- arcade sets (8 MB: the arcade voices)
def arcade_sets(): return _j("arcade_sets.json", {})


def check_arcade(paths):
    """the zip(s) -> set name (data/mvc/arcade_sets.json: CRC of the sound ROMs the voices are read from) or None"""
    import zipfile, zlib
    have = {}
    for p in paths:
        try:
            with zipfile.ZipFile(p) as z:
                for i in z.infolist(): have[i.filename.lower()] = "%08x" % i.CRC
        except Exception as ex: raise BuildError("%s: not a readable zip (%s)" % (os.path.basename(p), ex), code="arcade")
    for name, e in arcade_sets().items():
        if all(have.get(f) == c for f, c in e["roms"].items()): return name
    return None


# ---------------------------------------------------------------- the build
STAGES = [("verify", "Checking the disc image"), ("extract", "Reading the game files"),
          ("derive", "Rebuilding the sprite tiers and data from your disc"), ("sound", "Rebuilding the sound banks"),
          ("disc", "Assembling the patched disc")]
RELEASE = "1.0"


def output_name(variant):
    return "%s [Tag Hack %s%s]" % (TITLE, RELEASE, " 8MB" if variant == "8mb" else "")


def expected(variant, setname=None):
    for e in (known() or {}).get("expected", []):
        if e["variant"] == variant and e.get("arcade_set") == setname: return e
    return None


def run(disc, work, variant="2mb", arcade=(), root=None, name=None, progress=None, log=print, known_sha1=None, record=False, jobs=1, until=None):
    """-> dict(overlay, name, variant, arcade_set, times)"""
    times = {}; info = dict(times=times, variant=variant)
    P_ = (lambda s, f, t="": progress(s, f, t)) if progress else (lambda s, f, t="": None)

    def stage(key):
        @contextlib.contextmanager
        def cm():
            t0 = time.time(); P_(key, 0.0)
            yield
            times[key] = times.get(key, 0) + time.time() - t0; P_(key, 1.0)
        return cm()
    cfgs = configs()
    if variant not in cfgs: raise BuildError("no %s configuration is baked in builder/data/mvc" % variant, code="option")
    cfg = cfgs[variant]
    if cfg.get("arcade") and not arcade: raise BuildError("the 8 MB image needs your arcade set (mvsc.zip): --arcade", code="option")
    os.makedirs(work, exist_ok=True)
    if root is None:
        root = os.path.join(work, "root"); make_root(root, record)
    with stage("verify"):
        idn = identify(disc, *(known_sha1 or sha1_file(disc, lambda f: P_("verify", f))))
        if idn["status"] != "ok": raise BuildError(idn["message"], code=idn["status"])
        log("input: %s  sha1 %s" % (idn["message"], idn["sha1"])); info["input"] = idn
        if arcade:
            info["arcade_set"] = check_arcade(arcade) or "unknown set"; log("arcade set: %s" % info["arcade_set"])
    with stage("extract"):
        stamp = gdir(root, "work", "extract.stamp")
        if os.path.exists(stamp) and open(stamp).read() == idn["sha1"]: log("extract: files are current")
        else:
            lmap = extract(disc, root); log("extracted %d files" % len(lmap)); open(stamp, "w").write(idn["sha1"])
        if not record: log("tool sources: %d filled from the disc" % fill_root(root))
    with stage("derive"):
        ents = _j("derived.json")
        key = hashlib.sha1(idn["sha1"].encode() + open(os.path.join(DATA, "derived.json"), "rb").read()).hexdigest()
        stamp = gdir(root, "work", "derive.stamp")
        if os.path.exists(stamp) and open(stamp).read() == key: log("derive: files are current")
        else:
            stage_derive(root, ents, lambda f, t="": P_("derive", f, t), log); open(stamp, "w").write(key)
    if until == "derive": return info                     # (browser: the sound banks go to sub-workers, then run() again)
    with stage("sound"):
        stage_sound(root, cfg, jobs, lambda f, t="": P_("sound", f, t), log)
    H = Harness(root, disc, record, log)
    buf = _LineLog(log)
    with stage("disc"), contextlib.redirect_stdout(buf):
        ov = stage_disc(H, cfg, root, list(arcade))
    buf.flush()
    times["seal"] = H.seal_time; times["disc"] -= H.seal_time
    if cfg.get("dual"):
        # (2026-11-24, MvC 1.0 8 MB final = dual8(2 MB, 8 MB)) the 2 MB build with the same flags, then mvcb/dual.py: the
        # 8 MB disc runs the 2 MB disc's code and data unless a boot-time 8 MB test passes
        from mvcb import dual
        cfg2 = cfgs["2mb"]
        with stage("sound"):
            stage_sound(root, cfg2, jobs, lambda f, t="": P_("sound", f, t), log)
        H2 = Harness(root, disc, record, log)
        with stage("disc"), contextlib.redirect_stdout(buf):
            ov2 = stage_disc(H2, cfg2, root, [])
            ov = dual.compose(ov2, ov, log)
        buf.flush()
        times["seal"] += H2.seal_time; times["disc"] -= H2.seal_time
    info.update(overlay=ov, name=name or output_name(variant), toolchain=H.tb.n_cmd)
    info.setdefault("arcade_set", None)
    return info
