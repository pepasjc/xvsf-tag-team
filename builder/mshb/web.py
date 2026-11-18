"""The browser side of the MSHvSF build: what patcher/src/worker.js calls inside Pyodide (the twin of xvb/web.py).

The tool root is the unpacked bundle (/xvsf): the tools run from there with their own relative paths, and their data
directories (games/mshvsf/work, build, disc) are filled from the user's disc in Pyodide's memory file system.

The two long stages are made of independent jobs, which the worker runs in sub-workers:
  * sound: the ADPCM encoder jobs of every level of every character's bank (sound_plan: the bank builds run once
    with the encoder only noting its inputs; xvb/web.py has the memo the build's encoder then reads from);
  * sprites: one job per (tier, character) (sprite_jobs / sprite_job / sprite_put).
The bytes are the same as the command-line build's either way.
"""
import hashlib, json, os, shutil, sys
import numpy as np
from xvb import web as xweb, cdrom
from . import pipeline

ROOT = "/xvsf"
WORK = "/work"


def use_js_kernels(msk, xvk):
    """the sprite encoders' kernels (mshb/kernels.py and the xvb ones they use) -> the JavaScript twins
    (patcher/src/kernels_msh.js MSK, patcher/src/kernels.js XVK)"""
    from . import kernels
    kernels.use_js(msk, xvk)


def options_available():
    """-> JSON: the options whose code is in the blob cache (there is no compiler in a browser)"""
    calls = pipeline.manifest().get("calls", {})
    exp = pipeline.known().get("expected", [])
    has = lambda f: any(sorted(f) == e["flags"] for e in exp)
    ram8 = any(e["variant"] == "8mb" and not e.get("arcade_set") for e in exp)
    return json.dumps(dict(ram8=ram8, logo_off=has(pipeline.tool_flags(logo=False)), meter_on=has(pipeline.tool_flags(meter="on")),
                           meter_none=has(pipeline.tool_flags(meter="none")), version=pipeline.output_name(False), blobs=len(calls)))


def prepare(disc):
    """extract the game files into the tool root (pipeline.run extracts again: same files)"""
    os.makedirs(WORK, exist_ok=True)
    pipeline.extract(disc, ROOT)


# ---------------------------------------------------------------- sound
def sound_plan(flags_json):
    """-> (JSON [[key, offset, count, nblk, s1, s2, K, M, B, R], ...], int32 inputs) of the encoder jobs of every
    level of every bank; the banks built on the way are thrown away (their samples are not encoded yet)"""
    sb = pipeline._import_sndbank(ROOT)
    real = sb.CACHE; tmp = "/tmp/sndplan"
    shutil.rmtree(tmp, ignore_errors=True)
    sb.CACHE = tmp
    xweb._snd["plan"] = {}
    try:
        for c in range(pipeline.NBANK): sb.levels(c)
        jobs = xweb._snd["plan"]
    finally:
        xweb._snd["plan"] = None; sb.CACHE = real; shutil.rmtree(tmp, ignore_errors=True)
    meta, parts, o = [], [], 0
    for key, (x, prm) in jobs.items():
        meta.append([key, o, len(x)] + prm); parts.append(x); o += len(x)
    return json.dumps(meta), (np.concatenate(parts) if parts else np.zeros(0, np.int32))


def sound_results(meta_json, data):
    return xweb.sound_results(meta_json, data)


# ---------------------------------------------------------------- sound, one character per sub-worker job
# (the browser path: every level of one character's bank in a Python sub-worker; the cache files it leaves are the
# ones tools/snd/sndbank.py reads, so the build finds every bank made.  sound_plan above is the JavaScript-only path.)
_snd_dir = {}


def _bank_file(c):
    return "COMMON.SE" if int(c) == pipeline.NCHAR else "PL%02X_10.A0" % int(c)


def a0_of(char):
    """the source of bank `char` (0..0x16: PLxx_10.A0, 0x17: COMMON.SE)"""
    return open(pipeline.gdir(ROOT, "work", "loader", "files", _bank_file(char)), "rb").read()


def sound_char(char, a0):
    """in a sub-worker: every level of bank char (a0 = its source file, a0_of) -> JSON names of the cache files"""
    c = int(char)
    d = a0.to_bytes() if hasattr(a0, "to_bytes") else bytes(a0)
    files = pipeline.gdir(ROOT, "work", "loader", "files"); os.makedirs(files, exist_ok=True)
    open(os.path.join(files, _bank_file(c)), "wb").write(d)
    sb = pipeline._import_sndbank(ROOT)
    out = "/tmp/snd_%02X" % c
    shutil.rmtree(out, ignore_errors=True)
    real = sb.CACHE; sb.CACHE = out
    try: sb.levels(c)
    finally: sb.CACHE = real
    _snd_dir["dir"] = out
    return json.dumps(sorted(os.listdir(out)))


def sound_file(name):
    return open(os.path.join(_snd_dir["dir"], str(name)), "rb").read()


def sound_put(name, data):
    """a sub-worker's bank cache file -> G/build/snd (sndbank.CACHE)"""
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    sb = pipeline._import_sndbank(ROOT)
    os.makedirs(sb.CACHE, exist_ok=True)
    open(os.path.join(sb.CACHE, str(name)), "wb").write(d)


# ---------------------------------------------------------------- sprites
def sprite_jobs():
    """-> JSON [[tier, char], ...] (longest first: the strong tiers)"""
    from . import sprites
    files = pipeline.gdir(ROOT, "work", "dsp", "files")
    return json.dumps([list(j) for j in sprites.jobs(files)])


def stock_dsp(char):
    return open(pipeline.gdir(ROOT, "work", "dsp", "files", "SP_PL%02X.DSP" % int(char)), "rb").read()


def sprite_job(tier, char, data):
    """in a sub-worker: one tier of one character -> bytes"""
    from . import sprites
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    return sprites.encode_job(str(tier), int(char), d)


def sprite_put(tier, char, data):
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    p = pipeline.gdir(ROOT, "work", "dsp", str(tier)); os.makedirs(p, exist_ok=True)
    open(os.path.join(p, "SP_PL%02X.DSP" % int(char)), "wb").write(d)


def sprites_done():
    """all jobs are in: mark the tiers current, so that the build's sprite stage takes them (pipeline.stage_sprites)"""
    open(os.path.join(pipeline.gdir(ROOT, "work", "dsp"), "tiers.stamp"), "w").write(pipeline.sprite_key(ROOT))


def sprites_here(progress, log):
    """the sprite stage in this worker (no sub-workers)"""
    return json.dumps(pipeline.stage_sprites(ROOT, 1, lambda f, t="": progress("sprites", float(f), t), log))


# ---------------------------------------------------------------- arcade set, build, result
def check_arcade(paths_json):
    try:
        name, desc = pipeline.check_arcade(json.loads(paths_json), ROOT)
        return json.dumps(dict(status="ok", message=name or "arcade set (not one of the sets the reference hashes were made with)", known=bool(name)))
    except pipeline.BuildError as ex:
        return json.dumps(dict(status="bad", message=str(ex)))


def expected(variant, setname, flags_json):
    e = pipeline.expected(variant, setname or None, json.loads(flags_json))
    return e["sha1"] if e else ""


def tool_flags(logo, meter):
    return json.dumps(pipeline.tool_flags(logo=bool(logo), meter=str(meter)))


_arc = {}


def arcade_sub(arcade_json, disc, log):
    """in a sub-worker: the 8 MB arcade frames (tools/ap/build8.py) -> JSON ok + the names of the content files"""
    import contextlib
    out = "/tmp/ap8content"
    try:
        with contextlib.redirect_stdout(pipeline._LineLog(log)):
            pipeline.stage_arcade(ROOT, json.loads(arcade_json), disc, out, log)
    except pipeline.BuildError as ex:
        return json.dumps(dict(ok=False, code=ex.code, message=str(ex)))
    _arc["dir"] = out
    return json.dumps(dict(ok=True, files=sorted(os.listdir(out))))


def arcade_file(name):
    return open(os.path.join(_arc["dir"], name), "rb").read()


def arcade_put(name, data):
    """the sub-worker's content files -> G/work/ap/content (where the build expects them: pipeline.run arcade_built)"""
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    p = pipeline.gdir(ROOT, "work", "ap", "content"); os.makedirs(p, exist_ok=True)
    open(os.path.join(p, str(name)), "wb").write(d)


def build(disc, arcade_json, flags_json, name, sha1, size, progress, log, ap8=False):
    xweb._result.clear()
    try:
        info = pipeline.run(disc, WORK, root=ROOT, arcade=json.loads(arcade_json), flags=json.loads(flags_json), name=name or None, jobs=1, arcade_built=bool(json.loads(arcade_json)), ap8=bool(ap8),
                            progress=lambda s, f, t="": progress(s, float(f), t), log=log, known_sha1=(sha1, int(size)) if sha1 else None)
    except pipeline.BuildError as ex:
        return json.dumps(dict(ok=False, code=ex.code, message=str(ex)))
    ov = info.pop("overlay")
    xweb._result.update(ov=ov, runs=ov.runs(), name=info["name"])
    info.pop("input", None)
    info.update(ok=True, sectors=ov.nsec, changed=len(ov.dirty), cue=pipeline.cue_text(info["name"]))
    return json.dumps(info)


result_run_count = xweb.result_run_count
result_run = xweb.result_run
result_digest = xweb.result_digest
