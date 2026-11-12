"""The build, from an untouched disc image to the patched image.

    stage      reads                                   writes (all under the work directory)
    ---------  --------------------------------------  ------------------------------------------------
    verify     the image (SHA-1, size)                 -
    extract    the image (ISO9660)                     files/...  lba_map.json
    sprites    files/A/A0/SP_PLxx.NSP, A2/SP_EFF1.NSP  build/nspm (base, XVM1)   build/nsp (strong, XVH1)
               + builder/data/tiles_*.json             build/nspm4 (mid)         build/nspfat2 (fat)
                                                       build/nspm_eff/SP_EFF1.NSP
    disc       files/, build/nsp*, tools/ blobs        the patched image as an Overlay (tools/mktagdisc.py)
    arcade     the arcade ROM zip(s), the image        ap8content_base/ (tools/ap/build8.py), then
                                                       ap8content/ (tools/ap/sel2build.py: second select-screen set)
    disc8      everything above                        the 8 MB image as an Overlay (tools/mkap8disc.py)
    seal       -                                       EDC/ECC of every rewritten sector

The disc stages RUN THE PROJECT'S OWN TOOLS (tools/mktagdisc.py, tools/mkap8disc.py and the patch
modules they import), unmodified, inside a small harness (class Tools) that
  * points their path constants at the work directory (nothing is read from disc/, build/ or work/ of
    the repository, nothing is written there),
  * gives them an Overlay instead of a 400 MB copy of the image when they open the output file, and
  * defers their per-sector EDC/ECC to one vectorised pass.
External programs (MIPS compiler, chdman) are located by tools/toolenv.py; neither is needed for the
release configurations, whose compiled code is in builder/data/toolcache.
So whatever those tools build, this builds - with the same bytes.
"""
import builtins, contextlib, hashlib, importlib, io, json, os, shutil, sys, time, zipfile
from . import cdrom

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(BUILDER, ".."))
DATA = os.path.join(BUILDER, "data")
SPRITE_DIRS = dict(base="nspm", strong="nsp", mid="nspm4", fat="nspfat2")
EFF_OUT = ("nspm_eff", "SP_EFF1.NSP")
ARCADE_FLAGS = ["--direct", "--shared"]               # the content set of the reference 8 MB build
ARCADE_KEEP = "keep_v3.json"                           # extra keep-stock animations measured on the built disc (work/ap/SPEC.md 19)
EFF_KEEP = "streak_burst,launch_ring,ring_in,burst_ring,dust_cloud,flame_wisps,electric_arcs,dust_lines,dark_burst"   # effects left stock (SPEC 17/19)


class BuildError(Exception):
    """a problem the user can do something about; str() is the message to show"""
    def __init__(self, msg, code="error"):
        super().__init__(msg); self.code = code


def known():
    return json.load(open(os.path.join(DATA, "known.json")))


# ---------------------------------------------------------------- stage: verify
def sha1_file(path, progress=None):
    h = hashlib.sha1(); size = os.path.getsize(path); done = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b: break
            h.update(b); done += len(b)
            if progress: progress(done / max(1, size))
    return h.hexdigest(), size


def identify(path, sha1=None, size=None):
    """-> dict(status="ok" | ..., message=...).  Statuses other than ok: "patched" (an image this
    builder made), "region" (another release of the game), "notgame", "notimage", "baddump"."""
    kn = known()
    if sha1 is None: sha1, size = sha1_file(path)
    if sha1 == kn["input"]["sha1"]:
        return dict(status="ok", sha1=sha1, size=size, message=kn["input"]["title"])
    for e in kn.get("expected", []):
        if sha1 == e["sha1"]:
            return dict(status="patched", sha1=sha1, size=size, message="This image is already patched (it is a %s image this builder made). Use the original, unmodified disc image."
                        % ("tag hack + restored frames" if e["variant"] == "8mb" else "tag hack"))
    try:
        if size % cdrom.SECTOR: raise ValueError
        d = cdrom.Disc(path)
        with open(path, "rb") as f: sync = f.read(16)
        if sync[:12] != b"\0" + b"\xff" * 10 + b"\0": raise ValueError
        names = {n: (l, s) for n, l, s in d.walk()}
    except Exception:
        return dict(status="notimage", sha1=sha1, size=size, message="This is not a raw PlayStation disc image (MODE2/2352 .bin). "
                    "Compressed formats (CHD, PBP, ECM) and .iso files with 2048-byte sectors are not supported: convert to bin/cue first.")
    exe = kn["input"]["exe"]
    if exe not in names:
        other = {"SLPS_012.84": "the Japanese release (SLPS-01284)", "SLES_009.52": "the European release", "SLES_010.24": "a European release"}
        for n, what in other.items():
            if n in names:
                return dict(status="region", sha1=sha1, size=size, message="This is %s. The patch is made for the USA release, %s." % (what, kn["input"]["serial"]))
        return dict(status="notgame", sha1=sha1, size=size, message="This disc is not X-Men vs. Street Fighter (USA, %s)." % kn["input"]["serial"])
    # the right game, but not the known dump: patched by us, by something else, or a bad dump
    l, s = names["DMY.DAT"] if "DMY.DAT" in names else (None, 0)
    patched = False
    if l is not None:
        for i in range(0, min(s // 2048, 4096)):
            if d.sec(l + i)[2040:2044] == b"XVD1": patched = True; break
    if patched or size != kn["input"]["size"]:
        return dict(status="patched", sha1=sha1, size=size, message="This looks like an image that already carries the tag hack. Use the original, unmodified disc image.")
    return dict(status="baddump", sha1=sha1, size=size, message="This is the right game (%s) but not the known good dump: its SHA-1 is %s, expected %s "
                "(size %d bytes). It may be modified or badly dumped; the patch is only applied to the exact original." % (kn["input"]["serial"], sha1, kn["input"]["sha1"], kn["input"]["size"]))


def resolve_image(path):
    """a .cue names its .bin (single-track discs only)"""
    if path.lower().endswith(".cue"):
        files = [l.split('"')[1] for l in open(path, errors="replace") if l.strip().upper().startswith("FILE") and '"' in l]
        if len(files) != 1: raise BuildError("The cue sheet must name exactly one .bin file (this game is a single-track disc).")
        path = os.path.join(os.path.dirname(os.path.abspath(path)), files[0])
    if not os.path.isfile(path): raise BuildError("File not found: %s" % path)
    return path


# ---------------------------------------------------------------- stage: sprites
def _source_key():
    h = hashlib.sha1()
    for fn in ("kernels.py", "huff.py", "nspfile.py", "xvm1.py", "xvh1.py"):
        h.update(open(os.path.join(HERE, fn), "rb").read())
    for fn in ("tiles_mid.json", "tiles_fat.json"):
        h.update(open(os.path.join(DATA, fn), "rb").read())
    return h.hexdigest()


def encode_character(job):
    """one character: stock file -> the four tiers.  job = (char, source path, build dir); -> (char, seconds per tier)"""
    c, src, bdir = job
    from . import kernels, nspfile, xvm1, xvh1
    if kernels.backend == "python" and not getattr(kernels, "_chosen", False):
        kernels.auto_backend(); kernels._chosen = True
    k = "%02X" % c
    mid = json.load(open(os.path.join(DATA, "tiles_mid.json")))[k]
    fat = json.load(open(os.path.join(DATA, "tiles_fat.json")))[k]
    n = nspfile.NSP(open(src, "rb").read()).decode_all()
    T = {}; fn = "SP_PL%02X.NSP" % c

    def put(tier, make):
        t0 = time.time(); data = make(); T[tier] = time.time() - t0
        with open(os.path.join(bdir, SPRITE_DIRS[tier], fn), "wb") as f: f.write(data)
        return data
    base = put("base", lambda: xvm1.encode(n))                                    # XVM1, 48 tables, run penalty 8
    put("mid", lambda: xvm1.encode(n, rle=mid) if mid else base)                  # + sustained-super tiles as stock RLE
    put("fat", lambda: xvm1.encode(n, rle=set(mid) | set(fat)))                   # + hot tiles as stock RLE
    put("strong", lambda: xvh1.encode(n))                                         # XVH1, 256 tables, 256 classes
    return c, T


def stage_sprites(work, jobs=1, progress=None, log=print):
    from . import kernels, nspfile, xvm1
    bdir = os.path.join(work, "build")
    for d in list(SPRITE_DIRS.values()) + [EFF_OUT[0]]: os.makedirs(os.path.join(bdir, d), exist_ok=True)
    a0 = os.path.join(work, "files", "A", "A0")
    eff_src = os.path.join(work, "files", "A", "A2", "SP_EFF1.NSP")
    srcs = [os.path.join(a0, "SP_PL%02X.NSP" % c) for c in range(19)]
    h = hashlib.sha1(_source_key().encode())
    for p in srcs + [eff_src]: h.update(hashlib.sha1(open(p, "rb").read()).digest())
    stamp = os.path.join(bdir, "sprites.stamp")
    if os.path.exists(stamp) and open(stamp).read() == h.hexdigest():
        log("sprites: encoded files in the work directory are current (cache)")
        return dict(cached=True)
    if os.path.exists(stamp): os.remove(stamp)
    todo = [(c, srcs[c], bdir) for c in range(19)]
    times = {}; done = 0
    if progress: progress(0.0, "")

    def one(res):
        nonlocal done
        c, T = res; times[c] = T; done += 1
        log("sprites: character %2d  base %.1fs  mid %.1fs  fat %.1fs  strong %.1fs" % (c, T["base"], T["mid"], T["fat"], T["strong"]))
        if progress: progress(done / 20.0, "character %d of 19" % done)
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(min(jobs, 19)) as ex:
            for res in ex.map(encode_character, todo): one(res)
    else:
        for j in todo: one(encode_character(j))
    if kernels.backend == "python" and not getattr(kernels, "_chosen", False):
        kernels.auto_backend(); kernels._chosen = True
    n = nspfile.NSP(open(eff_src, "rb").read()).decode_all()
    with open(os.path.join(bdir, *EFF_OUT), "wb") as f: f.write(xvm1.encode(n, k=16))      # effects file: XVM1, 16 tables
    if progress: progress(1.0, "")
    open(stamp, "w").write(h.hexdigest())
    return dict(cached=False, per_tier={t: sum(x[t] for x in times.values()) for t in SPRITE_DIRS})


# ---------------------------------------------------------------- the harness around tools/
def _has_gcc(prefix):
    return bool(prefix) and bool(shutil.which(prefix + "gcc") or os.path.exists(prefix + "gcc") or os.path.exists(prefix + "gcc.exe"))


def _enc(x):
    if isinstance(x, (bytes, bytearray)): return {"__bytes__": bytes(x).hex()}
    if isinstance(x, tuple): return {"__tuple__": [_enc(v) for v in x]}
    if isinstance(x, list): return [_enc(v) for v in x]
    if isinstance(x, dict): return {"__dict__": [[_enc(k), _enc(v)] for k, v in x.items()]}
    assert x is None or isinstance(x, (int, float, str, bool)), type(x)
    return x


def _dec(x):
    if isinstance(x, list): return [_dec(v) for v in x]
    if isinstance(x, dict):
        if "__bytes__" in x: return bytes.fromhex(x["__bytes__"])
        if "__tuple__" in x: return tuple(_dec(v) for v in x["__tuple__"])
        return {_dec(k): _dec(v) for k, v in x["__dict__"]}
    return x


def memo_key(tools_dir, modname, fname, args, kw, sources):
    """name of the blob-cache entry of a compiling function: its arguments + the bytes of its source files"""
    h = hashlib.sha1(json.dumps([modname, fname, _enc(tuple(args)), _enc(dict(kw))], sort_keys=True).encode())
    for s in sorted(sources):
        h.update(s.encode()); h.update(hashlib.sha1(open(os.path.join(tools_dir, s), "rb").read().replace(b"\r\n", b"\n")).digest())
    return h.hexdigest()


LOGO_SOURCES = ["logo/logo.S", "logo/card.bin", "logopatch.py"]      # card.bin: the card itself (tools/logopatch.py render)


def options_available(tools_dir=None):
    """which optional features can be built WITHOUT a MIPS compiler here (their code is in the blob cache)"""
    tools_dir = tools_dir or os.path.join(REPO, "tools"); cache = os.path.join(DATA, "toolcache")
    if tools_dir not in sys.path: sys.path.insert(0, tools_dir)
    out = dict(title=False, logo=False, title_text="")
    try:
        tp = importlib.import_module("titlepatch")
        out["title_text"] = tp.DEFAULT
        out["title"] = os.path.exists(os.path.join(cache, memo_key(tools_dir, "titlepatch", "build", (tp.DEFAULT,), {}, ap8_sources(tools_dir)) + ".json"))
    except Exception: pass
    try:
        lp = importlib.import_module("logopatch")
        out["logo"] = os.path.exists(os.path.join(cache, memo_key(tools_dir, "logopatch", "build", (lp.SUB,), {}, LOGO_SOURCES) + ".json"))
    except Exception: pass
    return out


class Tools:
    """imports the project's disc tools with their paths pointed at `work` and the output image virtual"""

    def __init__(self, image, work, tools_dir=None, mips_prefix=None, use_cache=True, record=False, log=print):
        self.image = os.path.abspath(image); self.work = work; self.log = log
        self.tools = tools_dir or os.path.join(REPO, "tools")
        self.build = os.path.join(work, "build")
        self.overlays = {}                                # normalised output path -> Overlay
        self.use_cache = use_cache; self.record = record
        if mips_prefix: os.environ["XVSF_MIPS_PREFIX"] = mips_prefix          # tools/toolenv.py reads it
        self.cache_dir = os.path.join(DATA, "toolcache")
        self.cache_events = []
        os.makedirs(self.build, exist_ok=True)
        for p in (os.path.join(self.tools, "ap"), self.tools):
            if p not in sys.path: sys.path.insert(0, p)
        os.environ["XV_REGION"] = "us"
        region = importlib.import_module("region")
        assert region.REGION == "us"
        region.BIN = self.image; region.CUE = os.path.splitext(self.image)[0] + ".cue"
        region.FILES = os.path.join(work, "files"); region.LMAP = os.path.join(work, "lba_map.json")
        region.EXEPATH = os.path.join(region.FILES, region.EXE)
        mkdisc = importlib.import_module("mkdisc")
        mkdisc.BUILD = self.build; mkdisc.SRC = self.image
        mkdisc.fix_sector = cdrom.mark_for_seal           # every tool does `from mkdisc import fix_sector, BUILD`
        self.mkdisc = mkdisc; self.region = region
        self.mods = {}

    def _key(self, p): return os.path.normcase(os.path.abspath(p))

    def _open(self, path, mode="r", *a, **k):
        ov = self.overlays.get(self._key(path)) if isinstance(path, str) else None
        if ov is None:
            if isinstance(path, str) and self._key(path) == self._key(self.image) and mode == "rb" and not a and not k:
                return builtins.open(path, "rb", buffering=cdrom.READ_AHEAD)     # the input image: see cdrom.READ_AHEAD
            return builtins.open(path, mode, *a, **k)
        assert "b" in mode
        return cdrom.OverlayFile(ov)

    def _copyfile(self, src, dst):
        if self._key(src) == self._key(self.image):
            self.overlays[self._key(dst)] = cdrom.Overlay(self.image); return dst
        return shutil.copyfile(src, dst)

    def mod(self, name):
        """import a tool module and install the shims in its namespace"""
        if name in self.mods: return self.mods[name]
        m = importlib.import_module(name)
        m.open = self._open
        if hasattr(m, "shutil"):
            sh = type("shutil_shim", (), {"__getattr__": lambda s, n: getattr(shutil, n)})()
            sh.copyfile = self._copyfile; m.shutil = sh
        if hasattr(m, "hashlib"): m.hashlib = cdrom.HashShim()
        if name == "titlepatch": m.ROOT = self.work                       # its object directory: <ROOT>/build/titleobj
        if name == "logopatch": m.OBJ = os.path.join(self.build, "logoobj")
        if hasattr(m, "subprocess"):
            m.subprocess = _Subprocess(self, name)
        self.mods[name] = m
        return m

    # ---- blob cache: results of the functions that run the MIPS compiler -------------------------
    def memo(self, m, fname, sources):
        """wrap m.fname (a function that compiles `sources`): identical arguments and identical source
        files -> the recorded result from builder/data/toolcache, no compiler needed"""
        orig = getattr(m, fname)
        if getattr(orig, "_xvb_memo", False): return

        def wrapped(*args, **kw):
            key = memo_key(self.tools, m.__name__, fname, args, kw, sources); path = os.path.join(self.cache_dir, key + ".json")
            if self.use_cache and os.path.exists(path):
                self.cache_events.append((m.__name__ + "." + fname, "cache")); self.log(f"{m.__name__}.{fname}: recorded blob {key[:12]}")
                return _dec(json.load(open(path))["result"])
            gcc = getattr(m, "GCC", None) if _has_gcc(getattr(m, "GCC", None)) else None       # the prefix tools/toolenv.py resolved
            if not gcc:
                raise BuildError("This combination of options needs code that is not in the blob cache (%s.%s) and no MIPS cross compiler "
                                 "was found. Install one (mipsel-none-elf-gcc on PATH, or set XVSF_MIPS_PREFIX) or use the default options." % (m.__name__, fname),
                                 code="toolchain")
            res = orig(*args, **kw)
            self.cache_events.append((m.__name__ + "." + fname, "compiled")); self.log(f"{m.__name__}.{fname}: compiled ({gcc}gcc), blob {key[:12]}")
            if self.record:
                os.makedirs(self.cache_dir, exist_ok=True)
                json.dump(dict(function=m.__name__ + "." + fname, args=_enc(args), kwargs=_enc(kw), sources=sorted(sources), result=_enc(res)),
                          open(path, "w"), indent=0)
            return res
        wrapped._xvb_memo = True
        setattr(m, fname, wrapped)

    def finish(self, name):
        """the Overlay of build/<name>.bin, sealed"""
        ov = self.overlays[self._key(os.path.join(self.build, name + ".bin"))]
        t0 = time.time(); n = ov.seal_marked(); self.seal_time = time.time() - t0
        self.log("sealed %d sectors (EDC/ECC); %d sectors differ from or follow the original image" % (n, len(ov.dirty)))
        return ov


class _Subprocess:
    """stands in for the subprocess module inside a tool: reports a missing compiler as a BuildError"""
    def __init__(self, tools, name): self.t = tools; self.name = name
    def __getattr__(self, n):
        import subprocess
        f = getattr(subprocess, n)
        if n not in ("check_call", "check_output", "run", "call", "Popen"): return f

        def run(cmd, *a, **k):
            try: return f(cmd, *a, **k)
            except (FileNotFoundError, NotImplementedError, OSError) as ex:
                raise BuildError("%s needs an external program that is not available here (%s): %s" % (self.name, cmd[0] if isinstance(cmd, (list, tuple)) else cmd, ex), code="toolchain")
        return run


@contextlib.contextmanager
def _argv(*args):
    old = sys.argv; sys.argv = list(args)
    try: yield
    finally: sys.argv = old


def ap8_sources(tools_dir):
    d = os.path.join(tools_dir, "ap8")
    return ["ap8/" + f for f in sorted(os.listdir(d)) if f.endswith((".c", ".S", ".h", ".ld"))]


def stage_disc(T, name, flags):
    """tools/mktagdisc.py NAME [flags] -> Overlay"""
    T.mod("iso"); T.mod("mknspdisc"); M = T.mod("mktagdisc")
    if not os.path.exists(os.path.join(M.D, "tagload.sym")):
        raise BuildError("tools/tagload/tagload.sym (prebuilt loader) is missing", code="toolchain")
    if any(f == "--title" or f.startswith("--title=") for f in flags):
        T.memo(T.mod("titlepatch"), "build", ap8_sources(T.tools))
    if "--logo" in flags: T.memo(T.mod("logopatch"), "build", LOGO_SOURCES)
    with _argv("mktagdisc.py", name, *flags): M.main()
    return T.finish(name)


def stage_arcade(T, arcade, outdir, log):
    b8 = T.mod("build8")
    try: setname, prg, roms = b8.read_arcade(arcade)
    except b8.Fail as ex: raise BuildError(str(ex), code="arcade")
    del prg, roms
    base = outdir + "_base"                               # step 1: characters + first select-screen set
    effdir = outdir + "_eff"
    for d in (base, outdir, effdir):
        if os.path.isdir(d): shutil.rmtree(d)
    bk = T.mod("build8k")                                 # build8.py + the measured extra keep-stock list
    with _argv("build8k.py"):
        rc = bk.main(["--keep-file", os.path.join(DATA, ARCADE_KEEP), "--arcade", *arcade, "--disc", T.image, "--out", base, *ARCADE_FLAGS])
    if rc != 0:
        raise BuildError("The arcade content builder failed (see the log).", code="arcade")
    s2 = T.mod("sel2build")                               # step 2: second select-screen set -> the content mkap8disc gets
    if s2.main(["--arcade", *arcade, "--disc", T.image, "--base", base, "--out", outdir]) != 0:
        raise BuildError("The arcade content builder (second select-screen set) failed (see the log).", code="arcade")
    e2 = T.mod("eff2build")                               # step 3: common effects file -> --eff=
    if e2.main(["--arcade", *arcade, "--disc", T.image, "--out", effdir, "--keep", EFF_KEEP]) != 0:
        raise BuildError("The arcade content builder (effects) failed (see the log).", code="arcade")
    return setname


def stage_disc8(T, name, apdir, flags):
    """tools/mkap8disc.py NAME --ap8=DIR [flags] -> Overlay (runs the 2 MB build inside)"""
    T.mod("iso"); T.mod("mknspdisc"); M = T.mod("mktagdisc"); M8 = T.mod("mkap8disc")
    T.memo(M8, "build", ap8_sources(T.tools))
    if "--logo" in flags: T.memo(T.mod("logopatch"), "build", LOGO_SOURCES)
    with _argv("mkap8disc.py", name, "--ap8=" + apdir, "--eff=" + apdir + "_eff", *flags): M8.main()
    return T.finish(name)


def check_arcade(arcade, tools_dir=None):
    """identify an arcade set without building anything -> set name; raises BuildError"""
    for p in (os.path.join(tools_dir or os.path.join(REPO, "tools"), "ap"), tools_dir or os.path.join(REPO, "tools")):
        if p not in sys.path: sys.path.insert(0, p)
    b8 = importlib.import_module("build8")
    try: return b8.read_arcade(arcade)[0]
    except b8.Fail as ex: raise BuildError(str(ex), code="arcade")


# ---------------------------------------------------------------- configurations
def tool_flags(arcade, logo=True, version=True, buttons="modern", version_text=None, extra=()):
    """the builder's options -> flags of tools/mktagdisc.py / tools/mkap8disc.py.

    The defaults are the RELEASE configuration: boot card + version line on the main menu (2 MB: the tag24
    image; with an arcade set: the ap8f image, whose version line is part of the 8 MB loader).
    logo=False, version=False gives the plain build the regression references were made with."""
    f = []
    if logo: f.append("--logo")
    if arcade:
        # tools/mkap8disc.py runs the 2 MB build itself and hands --logo and --nopad through
        if not version: raise BuildError("With an arcade set the version line cannot be switched off: the 8 MB loader always draws it (it carries the 8MB indicator).", code="option")
        if version_text: f.append("--version=" + version_text)
        if buttons == "stock": f.append("--nopad")
    else:
        if version: f.append("--title=" + version_text if version_text else "--title")
        if buttons == "stock": f.append("--nopad")
    return f + list(extra)


def output_name(arcade, tools_dir=None):
    """file name (without extension) of the result, e.g. "X-Men vs. Street Fighter (USA) [Tag Hack 1.0.1]" """
    ver = "TAG HACK"
    try:
        tools_dir = tools_dir or os.path.join(REPO, "tools")
        if tools_dir not in sys.path: sys.path.insert(0, tools_dir)
        ver = importlib.import_module("titlepatch").DEFAULT
    except Exception: pass
    return "X-Men vs. Street Fighter (USA) [%s%s]" % (ver.title(), " + Restored Frames" if arcade else "")


# ---------------------------------------------------------------- the whole thing
STAGES = [("verify", "Checking the disc image"), ("extract", "Reading the game files"), ("sprites", "Re-encoding the character graphics"),
          ("arcade", "Restoring animation frames from the arcade set"), ("disc", "Assembling the patched disc")]


def run(disc, work, arcade=(), flags=(), name=None, jobs=1, progress=None, log=print, tools_dir=None, mips_prefix=None,
        use_cache=True, record=False, known_sha1=None):
    """-> dict(overlay=Overlay, name=..., times={stage: seconds}, sha1 of the result is NOT computed here)

    flags: options handed to tools/mktagdisc.py / tools/mkap8disc.py as they are (--title=TEXT, --logo, --nopad ...).
    progress(stage, fraction, text); log(line)."""
    times = {}; info = dict(times=times, flags=list(flags))
    P = (lambda s, f, t="": progress(s, f, t)) if progress else (lambda s, f, t="": None)

    def stage(key):
        @contextlib.contextmanager
        def cm():
            t0 = time.time(); P(key, 0.0)
            yield
            times[key] = times.get(key, 0) + time.time() - t0; P(key, 1.0)
        return cm()
    disc = resolve_image(disc)
    os.makedirs(work, exist_ok=True)
    with stage("verify"):
        idn = identify(disc, *(known_sha1 or sha1_file(disc, lambda f: P("verify", f))))      # known_sha1 = (sha1, size) when the caller hashed already
        if idn["status"] != "ok": raise BuildError(idn["message"], code=idn["status"])
        log("input: %s  sha1 %s" % (idn["message"], idn["sha1"]))
        info["input"] = idn
        if arcade: info["arcade_set"] = check_arcade(list(arcade), tools_dir); log("arcade set: " + info["arcade_set"])
    with stage("extract"):
        lmap = cdrom.extract(disc, os.path.join(work, "files"))
        json.dump(lmap, open(os.path.join(work, "lba_map.json"), "w"), indent=0)
        log("extracted %d files" % len(lmap))
    with stage("sprites"):
        info["sprites"] = stage_sprites(work, jobs, lambda f, t: P("sprites", f, t), log)
    T = Tools(disc, work, tools_dir, mips_prefix, use_cache, record, log)
    buf = _LineLog(log)
    internal = "image"                                    # the tools' file name in the work directory; not part of the image
    name = name or output_name(bool(arcade), tools_dir)
    if arcade:
        apdir = os.path.join(work, "ap8content")
        with stage("arcade"), contextlib.redirect_stdout(buf):
            stage_arcade(T, list(arcade), apdir, log)
        with stage("disc"), contextlib.redirect_stdout(buf):
            ov = stage_disc8(T, internal, apdir, list(flags))
    else:
        with stage("disc"), contextlib.redirect_stdout(buf):
            ov = stage_disc(T, internal, list(flags))
    buf.flush()
    times["seal"] = T.seal_time; times["disc"] -= T.seal_time
    info.update(overlay=ov, name=name, blobs=T.cache_events, variant="8mb" if arcade else "2mb")
    return info


class _LineLog(io.TextIOBase):
    def __init__(self, log): self.log = log; self.buf = ""
    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            l, self.buf = self.buf.split("\n", 1); self.log(l)
        return len(s)
    def flush(self):
        if self.buf: self.log(self.buf); self.buf = ""


def cue_text(name):
    return f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
