"""Our MIPS code, prebaked at the level of the toolchain commands.

The MvC tools compile our code with the GNU toolchain (mipsel-none-elf-gcc / as / ld / objcopy / nm / objdump) through
many small helpers.  Instead of listing those helpers, the builder replaces the toolchain itself:

  record (development machine): every toolchain command runs for real; its key = the tool + its arguments, where every
      input file is replaced by the SHA-1 of its content (text inputs: machine paths normalised) and a C / assembler
      source also brings the content of every file it #includes / .includes; its outputs are kept: an output the
      Python tools read (a .bin from objcopy, nm / objdump text) as a blob, an intermediate one (.o, .elf, the files
      only other toolchain commands read) as a TOKEN (a short placeholder whose content is a function of the key, so
      the next command's key is the same in record and replay).
  replay (the builder): the same key gives the recorded outputs; nothing is run.  A command with no recorded result
      is an error (the configuration was not baked).

Blobs are stored as game references where they contain words of the game (xvb/gameref.py), so no byte of the game is
in builder/data/mvc/tc.
"""
import builtins, hashlib, json, os, re, shutil, subprocess, sys, tempfile
TOOLS = ("gcc", "as", "ld", "objcopy", "nm", "objdump", "ar", "cpp", "strip", "readelf", "size")
TOKEN = b"MVCB-TOKEN "
TEXT_EXT = (".c", ".h", ".s", ".S", ".ld", ".inc", ".lds", ".x")
_OPEN, _ISFILE, _EXISTS = builtins.open, os.path.isfile, os.path.exists   # the real ones (the harness hooks them)
_RUN = subprocess.run                    # the real one (the shim replaces subprocess.run while a build runs)
_PATHISH = re.compile(r"^[A-Za-z]:[\\/]|^/|[\\/]")


_DEF = re.compile(rb"^\s*(\.set|\.equ|#define)\s")


def _sort_defs(b):
    """generated sources list their symbol definitions in set / dict order (hash-randomised between runs): runs of
    consecutive .set / .equ / #define lines are sorted for the key (the assembled bytes do not depend on that order)"""
    lines = b.replace(b"\r\n", b"\n").split(b"\n"); out = []; run = []
    for l in lines + [None]:
        if l is not None and _DEF.match(l): run.append(l); continue
        if run: out += sorted(run); run = []
        if l is not None: out.append(l)
    return b"\n".join(out)


class BakeError(RuntimeError):
    pass


def _sha(b): return hashlib.sha1(b).hexdigest()


class ToolBake:
    def __init__(self, root, record, store_dir, read_game=None, ref=None, log=print):
        self.root = os.path.abspath(root); self.record = record; self.dir = store_dir; self.log = log
        self.read_game = read_game; self.ref = ref
        self.tmp = os.path.abspath(tempfile.gettempdir())
        self.man = self._load()
        self.tokens = {}             # normcase abs path -> token bytes (outputs not kept as blobs)
        self.real = {}               # normcase abs path -> (key, arg index) of a recorded output (record mode)
        self.used = set()            # keys used in this build
        self.py_reads = {}           # record: outputs Python opened -> their content at that moment
        self.n_cmd = 0

    # ---- store
    def _load(self):
        p = os.path.join(self.dir, "manifest.json")
        if os.path.exists(p): return json.load(open(p))
        return dict(format=1, cmds={})

    def save(self):
        if not self.record: return
        os.makedirs(self.dir, exist_ok=True)
        json.dump(self.man, builtins.open(os.path.join(self.dir, "manifest.json"), "w"), indent=0, sort_keys=True)

    def _put(self, data):
        from xvb import gameref
        if self.ref is not None:
            segs = self.ref(data); b = json.dumps(segs, separators=(",", ":")).encode()
        else: b = json.dumps([data.hex()]).encode()
        s = _sha(b)
        os.makedirs(self.dir, exist_ok=True)
        p = os.path.join(self.dir, s)
        if not os.path.exists(p): builtins.open(p, "wb").write(b)
        return s

    def _get(self, s):
        from xvb import gameref
        b = builtins.open(os.path.join(self.dir, s), "rb").read()
        if _sha(b) != s: raise BakeError("builder/data/mvc/tc/%s is damaged" % s)
        return gameref.resolve(json.loads(b), self.read_game)

    # ---- keys
    def _norm_text(self, b):
        for base, tag in ((self.root, "<R>"), (self.tmp, "<T>")):
            for v in {base, base.replace("\\", "/"), base.replace("/", "\\")}:
                for vv in {v, v.lower(), v.upper(), v[:1].lower() + v[1:], v[:1].upper() + v[1:]}:
                    b = b.replace(vv.encode(), tag.encode())
        return b

    def _content_key(self, p):
        k = os.path.normcase(os.path.abspath(p))
        if k in self.tokens: return "tok:" + _sha(self.tokens[k])
        b = builtins.open(p, "rb").read()
        if b.startswith(TOKEN): return "tok:" + _sha(b)
        if p.endswith(TEXT_EXT) or b[:1].isascii() and b"\0" not in b[:4096]: b = _sort_defs(self._norm_text(b))
        return _sha(b)

    def _includes(self, src, incdirs, seen):
        try: txt = builtins.open(src, "rb").read().decode("latin-1")
        except OSError: return
        for m in re.finditer(r'^\s*(?:#\s*include|\.include)\s*[<"]([^>"]+)[>"]', txt, re.M):
            name = m.group(1)
            for d in [os.path.dirname(src)] + incdirs:
                p = os.path.normpath(os.path.join(d, name))
                if os.path.isfile(p):
                    k = os.path.normcase(p)
                    if k not in seen:
                        seen[k] = (name, self._content_key(p)); self._includes(p, incdirs, seen)
                    break

    def _denorm(self, t):
        return t.replace("<R>", self.root).replace("<T>", self.tmp)

    def _norm_arg(self, a):
        return self._norm_text(a.encode()).decode()

    def key(self, argv, cwd):
        tool = re.sub(r"\.exe$", "", os.path.basename(argv[0])).split("-")[-1]
        parts = [tool]; ins = []; incdirs = []
        for i, a in enumerate(argv[1:], 1):
            if a.startswith("-I"): incdirs.append(os.path.join(cwd, a[2:]))
        outs_hint = set()
        for i, a in enumerate(argv[1:], 1):
            if argv[i - 1] in ("-o", "-Map") and i > 1: outs_hint.add(i)
        if tool in ("objcopy", "strip"):                   # objcopy [options] IN [OUT]: the last positional is the output
            pos = [i for i, a in enumerate(argv[1:], 1) if not a.startswith("-") and argv[i - 1] not in ("-O", "-I", "-B", "-j", "--set-section-flags", "-R", "--rename-section", "--add-section")]
            if len(pos) >= 2: outs_hint.add(pos[-1])
        for i, a in enumerate(argv[1:], 1):
            p = os.path.join(cwd, a) if not os.path.isabs(a) else a
            if i in outs_hint: parts.append("@OUT"); continue
            if a.startswith("-T") and len(a) > 2 and os.path.isfile(os.path.join(cwd, a[2:])):
                parts.append("-T@" + self._content_key(os.path.join(cwd, a[2:]))); continue
            if not a.startswith("-") and os.path.isfile(p) and (_PATHISH.search(a) or "." in a):
                parts.append("@" + self._content_key(p)); ins.append(p); continue
            parts.append(self._norm_arg(a))
        if tool in ("gcc", "as", "cpp"):
            seen = {}
            for p in ins:
                if p.endswith((".c", ".S", ".s", ".h")): self._includes(p, incdirs, seen)
            parts.append(sorted(seen.values()))
        return _sha(json.dumps(parts, sort_keys=True).encode()), parts, outs_hint

    # ---- run
    def is_tool(self, cmd):
        if not isinstance(cmd, (list, tuple)) or not cmd: return False
        b = os.path.basename(str(cmd[0]))
        return bool(re.match(r"mipsel-none-elf-(%s)(\.exe)?$" % "|".join(TOOLS), b))

    def call(self, cmd, cwd=None, capture=False):
        """-> (returncode, stdout bytes)"""
        cmd = [str(c) for c in cmd]; cwd = os.path.abspath(cwd or os.getcwd())
        key, parts, outs_hint = self.key(cmd, cwd)
        self.n_cmd += 1; self.used.add(key)
        def ap(a): return a if os.path.isabs(a) else os.path.join(cwd, a)
        if self.record:
            paths = {i: ap(a) for i, a in enumerate(cmd[1:], 1) if not a.startswith("-")}
            before = {i: (os.path.getmtime(p) if os.path.exists(p) else None) for i, p in paths.items()}
            r = _RUN(cmd, cwd=cwd, capture_output=True)
            if r.returncode != 0:
                sys.stderr.write(r.stderr.decode(errors="replace"))
                raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
            outs = sorted(set(i for i, p in paths.items() if os.path.isfile(p) and before[i] != os.path.getmtime(p)) | outs_hint)   # (files: a directory argument such as `-I obj` changes its mtime too)
            prev = self.man["cmds"].get(key, {}).get("outs", {})
            ent = dict(tool=parts[0], outs={}, stdout=r.stdout.decode("latin-1") if r.stdout else "")
            if r.stderr: ent["stderr"] = self._norm_text(r.stderr).decode("latin-1")
            self.last_err = r.stderr
            for i in outs:
                p = ap(cmd[i]); k = os.path.normcase(os.path.abspath(p))
                tok = TOKEN + ("%s %d\n" % (key, i)).encode()
                self.tokens[k] = tok; self.real[k] = (key, i)
                ent["outs"][str(i)] = prev.get(str(i))      # a blob when Python reads it (keep_read_outputs)
                if parts[0] == "objcopy":                   # (objcopy writes what the tools read: kept right away)
                    with _OPEN(p, "rb") as fo: ent["outs"][str(i)] = self._put(fo.read())
            if os.environ.get("MVCB_KEYDBG"):
                ent["parts"] = parts; d = os.path.join(os.environ["MVCB_KEYDBG"], "rec"); os.makedirs(d, exist_ok=True)
                for i, a in enumerate(cmd):
                    pp = ap(a)
                    if i not in outs and os.path.isfile(pp) and pp.endswith((".S", ".s", ".c", ".ld")): shutil.copyfile(pp, os.path.join(d, "%s_%d_%s" % (key[:10], i, os.path.basename(pp))))
            self.man["cmds"][key] = ent
            if capture: return 0, r.stdout
            if r.stdout: sys.stdout.write(r.stdout.decode(errors="replace"))
            return 0, r.stdout
        e = self.man["cmds"].get(key)
        if e is None:                                      # recorded on another OS: path separators inside <R> / <T> arguments
            for a, b in (("/", "\\"), ("\\", "/")):
                alt = [x.replace(a, b) if isinstance(x, str) and ("<R>" in x or "<T>" in x) else x for x in parts]
                k2 = _sha(json.dumps(alt, sort_keys=True).encode()); e = self.man["cmds"].get(k2)
                if e is not None: key = k2; break          # (the outputs' tokens carry the recorded key)
        if e is None and os.environ.get("MVCB_KEYDBG"):
            d = os.environ["MVCB_KEYDBG"]; os.makedirs(d, exist_ok=True)
            json.dump(dict(cmd=cmd, parts=parts), builtins.open(os.path.join(d, "miss.json"), "w"), indent=1)
            for i, a in enumerate(cmd):
                pp = ap(a)
                if os.path.isfile(pp): shutil.copyfile(pp, os.path.join(d, "in%d_%s" % (i, os.path.basename(pp))))
        if e is None:
            raise BakeError("our code: the toolchain command `%s` is not prebaked in builder/data/mvc/tc (the builder never "
                            "compiles; work/mvcb/record_mvc.py bakes it)" % " ".join(os.path.basename(c) if os.path.isabs(c) else c for c in cmd)[:300])
        for i, s in e["outs"].items():
            p = ap(cmd[int(i)])
            if os.path.isdir(p): continue                  # (a directory argument recorded by the old rule: not an output)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            tok = TOKEN + ("%s %s\n" % (key, i)).encode()
            data = self._get(s) if s else tok
            builtins.open(p, "wb").write(data)
            self.tokens[os.path.normcase(os.path.abspath(p))] = tok      # (downstream keys use the token, as in record)
        out = e["stdout"].encode("latin-1")
        self.last_err = self._denorm(e.get("stderr", "")).encode("latin-1")
        if not capture and out: sys.stdout.write(out.decode(errors="replace"))
        return 0, out

    def note_open(self, path, mode):
        """record mode audit: Python opened a toolchain output"""
        if not self.record or "r" not in mode and "+" not in mode: return
        k = os.path.normcase(os.path.abspath(path))
        if k in self.real and k not in self.py_reads and _ISFILE(k):
            with _OPEN(k, "rb") as f: self.py_reads[k] = (self.real[k], f.read())

    def keep_read_outputs(self):
        """record: store the outputs Python read as blobs (their real content)"""
        for k in sorted(self.py_reads):
            (key, i), data = self.py_reads[k]
            if data.startswith(TOKEN): continue
            self.man["cmds"][key]["outs"][str(i)] = self._put(data)


class Shim:
    """subprocess replacement installed in the tool modules (and the subprocess module itself while a build runs)"""

    def __init__(self, tb):
        self.tb = tb; self._orig = {}

    def install(self):
        for n in ("check_call", "check_output", "run", "call"):
            self._orig[n] = getattr(subprocess, n)
        tb = self.tb; orig = self._orig

        def check_call(cmd, *a, **k):
            if tb.is_tool(cmd): tb.call(cmd, k.get("cwd")); return 0
            return orig["check_call"](cmd, *a, **k)

        def call(cmd, *a, **k):
            if tb.is_tool(cmd): tb.call(cmd, k.get("cwd")); return 0
            return orig["call"](cmd, *a, **k)

        def check_output(cmd, *a, **k):
            if tb.is_tool(cmd):
                rc, out = tb.call(cmd, k.get("cwd"), capture=True)
                return out.decode() if (k.get("text") or k.get("universal_newlines") or k.get("encoding")) else out
            return orig["check_output"](cmd, *a, **k)

        def run(cmd, *a, **k):
            if tb.is_tool(cmd):
                cap = k.get("capture_output") or k.get("stdout") == subprocess.PIPE
                rc, out = tb.call(cmd, k.get("cwd"), capture=bool(cap))
                txt = k.get("text") or k.get("universal_newlines") or k.get("encoding")
                err = getattr(tb, "last_err", b"") or b""
                o = (out.decode() if txt else out) if cap else None
                e = (err.decode(errors="replace") if txt else err) if cap or k.get("stderr") == subprocess.PIPE else None
                return subprocess.CompletedProcess(cmd, 0, o, e)
            return orig["run"](cmd, *a, **k)
        subprocess.check_call, subprocess.call, subprocess.check_output, subprocess.run = check_call, call, check_output, run

    def uninstall(self):
        for n, f in self._orig.items(): setattr(subprocess, n, f)
