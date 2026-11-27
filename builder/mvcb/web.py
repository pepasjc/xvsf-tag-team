"""The browser side of the MvC build: what patcher/src/worker.js calls inside Pyodide (the twin of mshb/web.py).

Pyodide has no numba: the codec modules (common/dsp dsh / dsm / dsa, tools/nsp_*, games/mvc/tools/codec2/dsr.py) are
imported with a stub `numba` (njit = identity) and their hot loops are replaced by the JavaScript twins
(patcher/src/kernels_mvc.js MVK: DSR1 encoder + decoder, MvC DSH1 decoder; kernels_msh.js MSK: DSH1 / DSM1 emitters,
DSM1 decoder; kernels.js XVK: parses, sound).  Single worker (no sub-workers yet).  The bytes are the command line's.
"""
import json, os, shutil, sys, types
import numpy as np
os.environ.setdefault("MVCB_ENABLE", "1")         # builder/games.py: MvC supported (on by default since 1.0)

if "numba" not in sys.modules:
    try:
        import numba  # noqa: F401
    except Exception:
        nb = types.ModuleType("numba")
        def njit(*a, **k):
            if a and callable(a[0]) and len(a) == 1 and not k: return a[0]
            return lambda f: f
        nb.njit = njit; nb.jit = njit; nb.prange = range
        sys.modules["numba"] = nb

if "capstone" not in sys.modules:             # the tools' load-delay self-checks (tools/speed/decode/dlib.py hazards: verified when
    try:                                        # the code was baked): nothing to disassemble in the browser
        import capstone  # noqa: F401
    except Exception:
        cs = types.ModuleType("capstone"); csm = types.ModuleType("capstone.mips")
        class _Cs:
            def __init__(self, *a, **k): self.detail = False
            def disasm(self, *a, **k): return iter(())
        cs.Cs = _Cs; cs.CS_ARCH_MIPS = cs.CS_MODE_MIPS32 = cs.CS_MODE_LITTLE_ENDIAN = 0
        csm.MIPS_OP_REG, csm.MIPS_OP_MEM, csm.MIPS_OP_IMM = 1, 3, 2; cs.mips = csm
        sys.modules["capstone"] = cs; sys.modules["capstone.mips"] = csm

for _m in ("lzma",):                         # unvendored in Pyodide; imported but not used on the build path (tools/nsp_codec.py)
    try: __import__(_m)
    except Exception: sys.modules[_m] = types.ModuleType(_m)

from xvb import web as xweb                                                     # noqa: E402
from . import pipeline                                                          # noqa: E402

ROOT = "/xvsf"
WORK = "/work"


def use_js_kernels(mvk, msk, xvk):
    """the codec / sound kernels -> the JavaScript twins (MVK, MSK, XVK .forPyodide() objects)"""
    xweb.use_js_kernels(xvk)
    import snd, snd.adpcm, snd.resample                 # games/mvc/tools/snd/sndhq.py imports them as tools.snd.*: the same (patched) modules
    sys.modules.setdefault("tools.snd", snd); sys.modules["tools.snd.adpcm"] = snd.adpcm; sys.modules["tools.snd.resample"] = snd.resample
    from mshb import kernels as MK
    MK.use_js(msk, xvk)
    from . import kern
    R32 = np.ascontiguousarray(kern.R16, np.int32)
    rb = np.zeros(260, np.int32)
    cache = {}

    def i32(a):
        k = id(a)
        if k not in cache or cache[k][0] is not a: cache[k] = (a, np.ascontiguousarray(np.asarray(a).ravel(), np.int32))
        return cache[k][1]

    def dsh_ref_decode(mem, src, n, model, RUNS, out, wm=0):
        assert wm == 1, "MvC DSH1 (width code 1) only"
        r = str(mvk.dsh_ref_decode_mvc(mem, int(src), int(n), int(model), R32, out, rb)).split(",")
        return int(r[0]), int(r[1])

    def dsm_ref_decode(mem, src, n, model, out):
        return int(msk.dsm_ref_decode(mem, int(src), int(n), int(model), out))

    def dsr_ref_decode(mem, src, n, nodes, pairs, jump, cont, lp, probs, out):
        return int(mvk.dsr_ref_decode(mem, int(src), int(n), i32(nodes), i32(pairs), i32(jump), i32(cont), i32(lp), i32(probs),
                                      int(np.asarray(probs).shape[1]), out))

    def dsr_tile_decisions(px, nodes, pairs, jump, cont, lp, probs, outp, outb):
        H, W = px.shape
        op = np.zeros(len(outp), np.float64); ob = np.zeros(len(outb), np.int32)
        k = int(mvk.dsr_tile_decisions(np.ascontiguousarray(px, np.int32).ravel(), int(H), int(W), i32(nodes), i32(pairs), i32(jump),
                                       i32(cont), i32(lp), i32(probs), int(np.asarray(probs).shape[1]), op, ob))
        outp[:k] = op[:k]; outb[:k] = ob[:k]
        return k

    def dsr_rc_encode(ps, bs, n, out):
        o = np.zeros(len(out), np.int32)
        m = int(mvk.dsr_rc_encode(np.ascontiguousarray(ps[:n], np.float64), np.ascontiguousarray(bs[:n], np.int32), int(n), o))
        out[:m] = o[:m]
        return m
    kern.dsh_ref_decode, kern.dsm_ref_decode = dsh_ref_decode, dsm_ref_decode
    kern.dsr_ref_decode, kern.dsr_tile_decisions, kern.dsr_rc_encode = dsr_ref_decode, dsr_tile_decisions, dsr_rc_encode
    _MVK[0] = mvk
    # the 8 MB arcade voices (sn8build, inside mkap8) import tools/snd after stage_disc's purge: keep the modules that
    # carry the JavaScript encoder / resampler (else a pure Python ADPCM search: hours)
    pipeline.PURGE_KEEP.update({"snd", "snd.adpcm", "snd.resample", "tools", "tools.snd", "tools.snd.adpcm", "tools.snd.resample", "sndhq"})
    _patch_sound(mvk)
    _patch_disc()


_MVK = [None]                                       # (the JavaScript kernels: MVK.overlap)


def _ov(x, y):
    """largest k < min(len(x), len(y)) with x.endswith(y[:k]) (prefix function over y + sentinel + x)"""
    if _MVK[0] is not None and hasattr(_MVK[0], "overlap"):
        return int(_MVK[0].overlap(np.frombuffer(x, np.uint8), np.frombuffer(y, np.uint8)))
    s = list(y) + [-1] + list(x); pi = [0] * len(s)
    for i in range(1, len(s)):
        k = pi[i - 1]
        while k and s[i] != s[k]: k = pi[k - 1]
        if s[i] == s[k]: k += 1
        pi[i] = k
    k = pi[-1]; m = min(len(x), len(y))
    while k >= m: k = pi[k - 1] if k else 0
    return k


def _patch_disc():
    """(2026-11-26) the disc stage in the browser, same bytes: (1) games/mvc/tools/sec3/l1b.pack's greedy overlap merge
    with cached pairwise overlaps (prefix function) instead of rescanning every pair after every merge; (2) mktag
    chk_apply: the stock DSP's decode + checker-tile list once per source (it was redone for every tier file).
    MVCB_CHECKPATCH=1: run the originals too and assert equality."""
    check = os.environ.get("MVCB_CHECKPATCH") == "1"
    for q in (pipeline.gdir(ROOT, "tools", "sec3"), pipeline.gdir(ROOT, "tools", "speed5"), pipeline.gdir(ROOT, "tools", "tagload"),
              os.path.join(ROOT, "common", "dsp")):
        if q not in sys.path: sys.path.insert(0, q)
    def fast_l1b(L1):
        if L1 is None or getattr(L1, "_mvcb_fast", False): return
        _pack0 = L1.pack
        def pack(s3, rd):
            import struct as _st
            iv = sorted(rd.items()); mx = []
            for o, e in sorted(iv, key=lambda x: (x[0], -x[1])):
                if mx and e <= mx[-1][1]: continue
                mx.append((o, e))
            ends = [e for o, e in mx]; assert ends == sorted(ends) and len(set(o for o, e in mx)) == len(mx)
            strs = sorted({s3[o:e] for o, e in mx}, key=lambda s_: (-len(s_), s_))
            keep = []
            for s_ in strs:
                if not any(s_ in k_ for k_ in keep): keep.append(s_)
            ov = {}
            def get(x, y):
                k_ = (x, y)
                if k_ not in ov: ov[k_] = _ov(x, y)
                return ov[k_]
            while True:
                best = (0, None, None)
                for i, x in enumerate(keep):
                    for j, y in enumerate(keep):
                        if i == j: continue
                        k_ = get(x, y)
                        if k_ > best[0]: best = (k_, i, j)
                k_, i, j = best
                if not k_: break
                x, y = keep[i], keep[j]; keep = [s_ for n_, s_ in enumerate(keep) if n_ not in (i, j)] + [x + y[k_:]]
            body = b"".join(keep); H = 8 + 4 * len(mx); ent = []
            for o, e in mx:
                p_ = body.find(s3[o:e]); assert p_ >= 0 and H + p_ < 0x10000
                ent.append(_st.pack("<HH", o, H + p_))
            sec = _st.pack("<IHH", L1.MAGIC, len(mx), 0) + b"".join(ent) + body
            for o, e in rd.items():
                r = L1.remap_sim(sec, o); assert sec[r:r + (e - o)] == s3[o:e], (o, e)
            out = (sec, len(mx))
            if check: assert out == _pack0(s3, rd), "l1b.pack fast != original"
            return out
        L1.pack = pack; L1._mvcb_fast = True
    try:
        import l1b as L1
    except Exception:
        L1 = None
    fast_l1b(L1)
    import chkform, dsp as D_
    _cc = {}
    def hook(tool, M):
        if tool == "mktag": patch_mk(M)
        elif tool == "mkap8":                          # (the 8 MB tool imports mktag itself, later: patch it when it loads)
            import importlib.abc, importlib.util
            class _F(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path, target=None):
                    if name != "mktag": return None
                    sys.meta_path.remove(self)
                    spec = importlib.util.find_spec(name)
                    if spec is None: return None
                    ex = spec.loader.exec_module
                    def exec_module(m):
                        ex(m); patch_mk(m)
                    spec.loader.exec_module = exec_module
                    return spec
            sys.meta_path[:] = [f for f in sys.meta_path if type(f).__name__ != "_F"]
            sys.meta_path.insert(0, _F())

    def patch_mk(MK):
        if not hasattr(MK, "chk_apply"): return
        D1 = sys.modules.get("dsp")                     # common/dsp/dsp.py DSP.decode_all: one JavaScript call per section
        if D1 is not None and hasattr(D1, "DSP") and not getattr(D1.DSP, "_mvcb", False) and _MVK[0] is not None and hasattr(_MVK[0], "rle_batch"):
            _da0 = D1.DSP.decode_all
            def decode_all(self):
                todo = [t for t in self.tiles if t.raw is None]
                if todo:
                    mem = np.frombuffer(bytes(self.sec[0]) + bytes(32), np.uint8)
                    offs = np.array([t.off for t in todo], np.int32); ns = np.array([t.n for t in todo], np.int32)
                    oo = np.concatenate([[0], np.cumsum(ns)]).astype(np.int32)
                    out = np.zeros(int(oo[-1]) + 1, np.uint8); res = np.zeros(2 * len(todo), np.int32)
                    _MVK[0].rle_batch(mem, offs, ns, oo[:-1].copy(), out, res)
                    ob = out.tobytes()
                    for k, t in enumerate(todo):
                        t.raw, t.clen, t.over = ob[oo[k]:oo[k + 1]], int(res[2 * k]), int(res[2 * k + 1])
                if check:
                    for t in self.tiles:
                        assert (t.raw, t.clen, t.over) == D1.rle_decode(self.sec[0], t.off, t.n), "decode_all fast != original"
                return self.tiles
            D1.DSP.decode_all, D1.DSP._mvcb = decode_all, True
        q = pipeline.gdir(ROOT, "tools", "sec3")       # stage_disc purges the tool modules; mktag imports l1b later,
        if q not in sys.path: sys.path.insert(0, q)   # inside a function: import (and patch) it first, the same module
        try:
            import l1b as _L1
        except Exception:
            _L1 = None
        fast_l1b(_L1)
        q = pipeline.gdir(ROOT, "tools", "l2")
        if q not in sys.path: sys.path.insert(0, q)
        try:
            import g2pack as G2                       # (mktag imports it later: the same module)
        except Exception:
            G2 = None
        if G2 is not None and not getattr(G2, "_mvcb", False):   # split(): the stock reference's groups once per file
            _sc = {}; _split0 = G2.split
            def split(sec1, starts=None):
                k_ = (bytes(sec1), tuple(starts) if starts is not None else None)
                if k_ not in _sc:
                    if len(_sc) > 256: _sc.clear()
                    _sc[k_] = _split0(sec1, starts)
                return _sc[k_]
            G2.split, G2._mvcb = split, True
        if hasattr(MK, "Img") and not getattr(MK.Img, "_mvcb", False):     # byte-at-a-time image access -> per sector
            def wbytes(self, lba, off, data):
                i = 0
                while i < len(data):
                    o = off + i; k = min(len(data) - i, 2048 - o % 2048)
                    self.f.seek((lba + o // 2048) * 2352 + 24 + o % 2048); self.f.write(data[i:i + k])
                    self.touched.add(lba + o // 2048); i += k
            def rbytes(self, lba, off, n):
                out = bytearray(); i = 0
                while i < n:
                    o = off + i; k = min(n - i, 2048 - o % 2048)
                    self.f.seek((lba + o // 2048) * 2352 + 24 + o % 2048); out += self.f.read(k); i += k
                return bytes(out)
            if check:
                _rb0 = MK.Img.rbytes; _rb1 = rbytes
                def rbytes(self, lba, off, n):
                    r = _rb1(self, lba, off, n); assert r == _rb0(self, lba, off, n), "Img.rbytes fast != original"; return r
            MK.Img.wbytes, MK.Img.rbytes, MK.Img._mvcb = wbytes, rbytes, True
        def chk_apply(x, src):
            if "--chk" not in sys.argv: return x
            k_ = bytes(src)
            if k_ not in _cc:
                d = D_.DSP(src); _cc[k_] = (d, chkform.tiles(d))
            d, idx = _cc[k_]
            return chkform.apply(x, d, idx) if idx else x
        MK.chk_apply = chk_apply
    if not any(getattr(h, "_mvcb", False) for h in pipeline.TOOL_HOOKS):
        hook._mvcb = True; pipeline.TOOL_HOOKS.append(hook)


_SND_MEMOS = []


def _patch_sound(mvk):
    """(2026-11-26) the MvC sound ladder in the browser: (1) voice_hq / resample_hq are pure functions of (sample, k,
    rate, settings) and the ladder asks for the same ones at many levels -> memoised per worker; (2) limit()'s per-sample
    envelope loop -> MVK.limiter_env (same float64 arithmetic).  Output bytes unchanged."""
    for q in (pipeline.gdir(ROOT, "tools", "snd"), os.path.join(ROOT, "tools")):
        if q not in sys.path: sys.path.insert(0, q)
    try:
        import sndhq as HQ
    except Exception:
        return
    if getattr(HQ, "_mvcb_patched", False) or os.environ.get("MVCB_NOSNDPATCH") == "1": return
    from numpy.lib.stride_tricks import sliding_window_view

    def limit(y, ceil=HQ.CEIL, fs=11025):
        y = np.asarray(y, np.float64)
        if not len(y): return y
        g = np.minimum(1.0, ceil / np.maximum(np.abs(y), 1e-9))
        n = max(1, int(fs * 0.0015))
        gp = np.pad(g, (n, n), mode="edge")
        gm = np.ascontiguousarray(sliding_window_view(gp, 2 * n + 1).min(axis=1), np.float64)
        a = np.exp(-1.0 / max(1.0, fs * 0.010))
        env = np.empty_like(gm)
        mvk.limiter_env(gm, float(a), env)
        return y * env
    HQ.limit = limit

    def memo(f):
        cache = {}; _SND_MEMOS.append(cache)                          # (cleared after a plan pass: its encoder wrote nothing)
        def g(blk, k, fs0, *a, **kw):
            key = (bytes(blk), k, float(fs0), a, tuple(sorted(kw.items())))
            if key not in cache: cache[key] = f(blk, k, fs0, *a, **kw)
            return cache[key]
        return g
    HQ.voice_hq = memo(HQ.voice_hq); HQ.resample_hq = memo(HQ.resample_hq)
    _dc = {}; _design = HQ.design
    def design(fs0, fs1, cap_db=HQ.CAP_DB, nt=HQ.NT, shelf_db=0.0):     # (filter taps: same inputs -> same array; copies out)
        k = (float(fs0), float(fs1), cap_db, nt, shelf_db)
        if k not in _dc: _dc[k] = _design(fs0, fs1, cap_db, nt, shelf_db)
        return _dc[k].copy()
    HQ.design = design
    RS = HQ.resample                                                   # (the tools.snd.resample sndhq uses)
    if not getattr(RS, "_mvcb_memo", False):
        _pc = {}; _p2r = RS.pow2_ratio
        def pow2_ratio(d, *a, **kw):
            k = (d, a, tuple(sorted(kw.items())))
            if k not in _pc: _pc[k] = _p2r(d, *a, **kw)
            return _pc[k]
        RS.pow2_ratio = pow2_ratio; RS._mvcb_memo = True
    HQ._mvcb_patched = True


def options_available():
    exp = pipeline.known().get("expected", [])
    return json.dumps(dict(ram8=any(e["variant"] == "8mb" for e in exp), version=pipeline.output_name("2mb"),
                           variants=sorted({e["variant"] for e in exp})))


def check_arcade(paths_json):
    try:
        name = pipeline.check_arcade(json.loads(paths_json))
        return json.dumps(dict(status="ok", message=name or "arcade set (not one of the sets the reference hashes were made with)", known=bool(name)))
    except pipeline.BuildError as ex:
        return json.dumps(dict(status="bad", message=str(ex)))


def expected(variant, setname, flags_json="[]"):
    e = pipeline.expected(variant, setname or None)
    return e["sha1"] if e else ""


# ---------------------------------------------------------------- sound banks in sub-workers (as mshb/web.py)
def prepare(disc, arcade_json, sha1, size, progress, log):
    """verify + extract + derive (the sound stage's inputs) -> JSON [[bank, env], ...] for the sub-workers"""
    arcade = json.loads(arcade_json); variant = "8mb" if arcade else "2mb"
    info = pipeline.run(disc, WORK, variant=variant, arcade=arcade, root=ROOT, progress=lambda s, f, t="": progress(s, float(f), t), log=log,
                        known_sha1=(sha1, int(size)) if sha1 else None, until="extract")
    _derive_start(info["input"]["sha1"], log)
    cfg = pipeline.configs()[variant]
    env = {"VOICEHQ": "1" if "--voicehq" in cfg["argv"] else "0", "VOICEVOL": "1" if "--voicevol" in cfg["argv"] else "0"}
    os.environ.update(env)                         # (sndbank reads VOICEHQ / VOICEVOL at import: before its first import here)
    sb = _sndbank()
    return json.dumps([[n, env] for n in sb.bank_names()])


_dv = {}


def _deps(e, produced):
    out = set()
    for k in ("sources",):
        for v in (e.get(k) or {}).values(): out.add(v.split("#")[0])
    for k in ("src", "b_a0", "u_a0"):
        if k in e: out.add(e[k].split("#")[0])
    return {d for d in out if d in produced}


def _derive_start(sha1, log):
    """(2026-11-26) derive in steps (derive_step), so the worker can feed the sub-workers meanwhile: the disc copies
    first (the sound banks' sources are among them), here at once.  (2026-11-27) the sprite tiers (most of the work)
    can go to the Python sub-workers: derive_step(seconds, remote) hands out every tier whose inputs exist, does the
    rest here in dependency order (any order gives the same files: each is checked against its recorded SHA-1)"""
    import time
    ents = pipeline._j("derived.json"); key, stamp = pipeline.derive_key(ROOT, sha1)
    _dv.clear()
    if os.path.exists(stamp) and open(stamp).read() == key: log("derive: files are current"); return
    produced = {e["path"] for e in ents}
    first = [e for e in ents if e["kind"] == "disc"]
    rest = [e for e in ents if e["kind"] != "disc"]
    _dv.update(pool=pipeline.Pool(ROOT), ents=rest, deps=[_deps(e, produced) for e in rest], state=[0] * len(rest),
               done=set(), key=key, stamp=stamp, n=len(ents), nfirst=len(first), ndone=0, t=0.0, log=log, jobs={})
    t0 = time.time()
    for e in first: _derive_put(e); _dv["done"].add(e["path"])
    _dv["t"] += time.time() - t0


def _derive_put(e, b=None):
    import hashlib
    if b is None: b = pipeline.derive_one(e, _dv["pool"])
    if e.get("sha1") and hashlib.sha1(b).hexdigest() != e["sha1"]:
        raise pipeline.BuildError("derive: %s does not come out as recorded (%s)" % (e["path"], e["kind"]), code="toolchain")
    _dv["pool"].put(e["path"], b)


def derive_step(seconds, remote=False):
    """derive for about `seconds` -> JSON {frac, jobs: [new remote job ids], wait: nothing to do here until a remote
    job comes back}; frac 1.0 = all done (stamp written)"""
    import time
    if not _dv: return json.dumps(dict(frac=1.0, jobs=[], wait=False))
    t0 = time.time(); ents, deps, st, done = _dv["ents"], _dv["deps"], _dv["state"], _dv["done"]
    jobs = []; progress = True
    while progress and time.time() - t0 < seconds:
        progress = False
        for i, e in enumerate(ents):
            if st[i] or not deps[i] <= done: continue
            if remote and e["kind"] == "tier":
                st[i] = 1; _dv["jobs"][i] = True; jobs.append(i); progress = True; continue
            _derive_put(e); st[i] = 2; done.add(e["path"]); _dv["ndone"] += 1; progress = True
            if time.time() - t0 >= seconds: break
    _dv["t"] += time.time() - t0
    left = sum(1 for x in st if x != 2)
    if not left:
        open(_dv["stamp"], "w").write(_dv["key"])
        _dv["log"]("derive: %d files, %.1f s here (in steps), %d tiers in sub-workers" % (_dv["n"], _dv["t"], _dv.get("nremote", 0)))
        _dv.clear(); return json.dumps(dict(frac=1.0, jobs=jobs, wait=False))
    ready_here = any(not x and deps[i] <= done and not (remote and ents[i]["kind"] == "tier") for i, x in enumerate(st))
    return json.dumps(dict(frac=(_dv["nfirst"] + len(st) - left) / _dv["n"], jobs=jobs, wait=not ready_here))


def derive_job(i):
    """a remote tier job -> (entry JSON with the disc references resolved, JSON source names, [source bytes])"""
    i = int(i); e = pipeline._unref(_dv["ents"][i], lambda name, off, n: _dv["pool"].get("disc:" + name)[off:off + n])
    names = sorted(e["sources"])
    return json.dumps(dict(recipe=e["recipe"])), json.dumps(names), [bytes(_dv["pool"].view(e["sources"][n])) for n in names]


def derive_result(i, data):
    i = int(i); e = _dv["ents"][i]; b = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    _derive_put(e, b); _dv["state"][i] = 2; _dv["done"].add(e["path"]); _dv["ndone"] += 1; _dv["nremote"] = _dv.get("nremote", 0) + 1
    _dv["jobs"].pop(i, None)


def tier_job(entry_json, names_json, srcs):
    """in a sub-worker: one sprite tier (mvcb/tiers.py build) from its sources"""
    from mvcb import tiers
    e = json.loads(str(entry_json)); names = json.loads(str(names_json))
    src = {n: (d.to_bytes() if hasattr(d, "to_bytes") else bytes(d)) for n, d in zip(names, srcs)}
    return tiers.build(e["recipe"], src)


# ---------------------------------------------------------------- 8 MB arcade frames in sub-workers (2026-11-27)
_fr8 = {}


def frames_plan(disc, arcade_json):
    """main worker, after prepare: -> JSON [[kind, index], ...] of the frame jobs for the sub-workers ("c" character
    1..0x16, "a" assist 0..0x15), [] when pipeline.frames_files will find them in its cache"""
    arcade = json.loads(arcade_json); _fr8.clear()
    if not arcade: return "[]"
    out = pipeline.frames_dir(ROOT, str(disc), arcade)
    if os.path.exists(os.path.join(out, "manifest.json")): return "[]"
    _fr8.update(out=out, tmp=out + ".tmp", man=dict(chars={}, assists={}))
    shutil.rmtree(_fr8["tmp"], ignore_errors=True); os.makedirs(_fr8["tmp"])
    return json.dumps([["c", c] for c in range(1, 0x17)] + [["a", x] for x in range(0x16)])


def frames_put(kind, x, name, data, entry_json, desc_json, chtab):
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    if name: open(os.path.join(_fr8["tmp"], str(name)), "wb").write(d)
    _fr8["man"]["chars" if str(kind) == "c" else "assists"]["%02X" % int(x)] = json.loads(str(entry_json))
    _fr8["man"]["arcade"] = json.loads(str(desc_json)); _fr8["man"]["chtab"] = int(chtab)


def frames_done():
    m = _fr8["man"]
    man = dict(arcade=m["arcade"], chtab=m["chtab"], chars={k: m["chars"][k] for k in sorted(m["chars"])},
               assists={k: m["assists"][k] for k in sorted(m["assists"])})
    json.dump(man, open(os.path.join(_fr8["tmp"], "manifest.json"), "w"), indent=1)
    if os.path.exists(_fr8["out"]): shutil.rmtree(_fr8["out"])
    os.rename(_fr8["tmp"], _fr8["out"]); _fr8.clear()


_b8 = {}


def fr8_job(kind, x, paths_json, disc):
    """in a sub-worker: one character's or assist's PLxx.R8 / DAxx.R8 (games/mvc/tools/ap/build8.py, the functions its
    main() runs) -> JSON [name or "", entry, desc, chtab] + the file bytes"""
    import runpy
    paths = json.loads(str(paths_json)); key = (tuple(paths), str(disc))
    if _b8.get("key") != key:
        b8 = pipeline.gdir(ROOT, "tools", "ap", "build8.py")
        for q in (os.path.dirname(b8), os.path.join(ROOT, "tools", "ap"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "common", "dsp")):
            if q not in sys.path: sys.path.insert(0, q)
        for n in ("aplib", "dsp", "nsp", "iso", "build8"): sys.modules.pop(n, None)
        g = runpy.run_path(b8, run_name="__mvcb_build8__")
        ctx, ps1, chtab, desc = g["setup"](paths, str(disc))
        _b8.clear(); _b8.update(key=key, g=g, ctx=ctx, ps1=ps1, chtab=chtab, desc=desc)
    g = _b8["g"]; out = "/tmp/fr8job"; shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    man = dict(chars={}, assists={}); x = int(x)
    if str(kind) == "c": g["char_r8"](_b8["ctx"], _b8["ps1"], x, _b8["chtab"], out, man)
    else: g["assist_r8"](_b8["ctx"], _b8["ps1"], x, _b8["chtab"], out, man)
    ent = (man["chars"] if str(kind) == "c" else man["assists"])["%02X" % x]
    fs = os.listdir(out); name = fs[0] if fs else ""
    data = open(os.path.join(out, name), "rb").read() if name else b""
    return json.dumps([name, ent, _b8["desc"], _b8["chtab"]], default=str), data


def _sndbank():
    for q in (pipeline.gdir(ROOT, "tools", "snd"), os.path.join(ROOT, "tools")):
        if q not in sys.path: sys.path.insert(0, q)
    import sndbank
    return sndbank


def sound_src(name):
    """the bank's source file (main worker, after prepare)"""
    return _sndbank().se_source(str(name))


_snd = {}


def _bank_src(name, data, env_json):
    name = str(name); d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    os.environ.update(json.loads(env_json))
    sb = _sndbank()
    os.makedirs(sb.FILES, exist_ok=True)
    open(os.path.join(sb.FILES, "COMMON.SE" if name == sb.COMMON else "CHR%s_0.SE" % name), "wb").write(d)
    return name, sb


def sound_bank_plan(name, data, env_json):
    """(2026-11-26) in a sub-worker, pass 1 of a bank: every level built with the ADPCM encoder only noting its jobs
    (xvb/web.py sound_plan format) -> (JSON meta, int32 inputs).  No encoder output steers the bank build (sizes come
    from the lengths), so pass 2 (sound_bank with the results) asks for the same jobs; one it does not find is encoded
    in place (same kernel, same bytes)."""
    name, sb = _bank_src(name, data, env_json)
    out = "/tmp/mvplan_" + name; shutil.rmtree(out, ignore_errors=True)
    real = sb.CACHE; sb.CACHE = out; xweb._snd["plan"] = {}
    try:
        sb.levels(name); jobs = xweb._snd["plan"]
    finally:
        xweb._snd["plan"] = None; sb.CACHE = real; shutil.rmtree(out, ignore_errors=True)
        for c in _SND_MEMOS: c.clear()
    meta, parts, o = [], [], 0
    for key, (x, prm) in jobs.items():
        meta.append([key, o, len(x)] + prm); parts.append(x); o += len(x)
    return json.dumps(meta), (np.concatenate(parts) if parts else np.zeros(0, np.int32))


def sound_bank(name, data, env_json, meta_json="", results=None):
    """in a sub-worker: every level of one bank -> JSON names of the cache files; meta_json + results: the encoder
    jobs of sound_bank_plan, done by the JavaScript pool"""
    name, sb = _bank_src(name, data, env_json)
    xweb._snd["memo"].clear()
    if meta_json: xweb.sound_results(str(meta_json), results)
    out = "/tmp/mvsnd_" + name; shutil.rmtree(out, ignore_errors=True)
    real = sb.CACHE; sb.CACHE = out
    try: sb.levels(name)
    finally: sb.CACHE = real; xweb._snd["memo"].clear()
    _snd["dir"] = out
    return json.dumps(sorted(os.listdir(out)))


def sound_file(name):
    return open(os.path.join(_snd["dir"], str(name)), "rb").read()


def sound_put(name, data):
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    sb = _sndbank(); os.makedirs(sb.CACHE, exist_ok=True)
    open(os.path.join(sb.CACHE, str(name)), "wb").write(d)


def build(disc, arcade_json, name, sha1, size, progress, log):
    xweb._result.clear()
    arcade = json.loads(arcade_json)
    prof = None
    if os.environ.get("MVCB_PROFILE"):                  # (developer) cProfile of the build -> the given file
        import cProfile; prof = cProfile.Profile(); prof.enable()
    try:
        info = pipeline.run(disc, WORK, variant="8mb" if arcade else "2mb", arcade=arcade, root=ROOT, name=name or None,
                            progress=lambda s, f, t="": progress(s, float(f), t), log=log, known_sha1=(sha1, int(size)) if sha1 else None, jobs=1)
        if prof:
            prof.disable(); import pstats, io; out = io.StringIO()
            st = pstats.Stats(prof, stream=out); st.sort_stats("cumulative").print_stats(60); st.sort_stats("tottime").print_stats(40)
            open(os.environ["MVCB_PROFILE"], "w").write(out.getvalue())
    except pipeline.BuildError as ex:
        return json.dumps(dict(ok=False, code=ex.code, message=str(ex)))
    ov = info.pop("overlay")
    xweb._result.update(ov=ov, runs=ov.runs(), name=info["name"])
    info.pop("input", None)
    info.update(ok=True, sectors=ov.nsec, changed=len(ov.dirty), cue=pipeline.cue_text(info["name"]))
    return json.dumps(info, default=str)


result_run_count = xweb.result_run_count
result_run = xweb.result_run
result_digest = xweb.result_digest
