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
    pipeline.run(disc, WORK, variant=variant, arcade=arcade, root=ROOT, progress=lambda s, f, t="": progress(s, float(f), t), log=log,
                 known_sha1=(sha1, int(size)) if sha1 else None, until="derive")
    cfg = pipeline.configs()[variant]
    env = {"VOICEHQ": "1" if "--voicehq" in cfg["argv"] else "0", "VOICEVOL": "1" if "--voicevol" in cfg["argv"] else "0"}
    os.environ.update(env)                         # (sndbank reads VOICEHQ / VOICEVOL at import: before its first import here)
    sb = _sndbank()
    return json.dumps([[n, env] for n in sb.bank_names()])


def _sndbank():
    for q in (pipeline.gdir(ROOT, "tools", "snd"), os.path.join(ROOT, "tools")):
        if q not in sys.path: sys.path.insert(0, q)
    import sndbank
    return sndbank


def sound_src(name):
    """the bank's source file (main worker, after prepare)"""
    return _sndbank().se_source(str(name))


_snd = {}


def sound_bank(name, data, env_json):
    """in a sub-worker: every level of one bank -> JSON names of the cache files"""
    name = str(name); d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    os.environ.update(json.loads(env_json))
    sb = _sndbank()
    os.makedirs(sb.FILES, exist_ok=True)
    open(os.path.join(sb.FILES, "COMMON.SE" if name == sb.COMMON else "CHR%s_0.SE" % name), "wb").write(d)
    out = "/tmp/mvsnd_" + name; shutil.rmtree(out, ignore_errors=True)
    real = sb.CACHE; sb.CACHE = out
    try: sb.levels(name)
    finally: sb.CACHE = real
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
    try:
        info = pipeline.run(disc, WORK, variant="8mb" if arcade else "2mb", arcade=arcade, root=ROOT, name=name or None,
                            progress=lambda s, f, t="": progress(s, float(f), t), log=log, known_sha1=(sha1, int(size)) if sha1 else None, jobs=1)
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
