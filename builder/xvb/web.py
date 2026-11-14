"""The browser side of the build: what patcher/src/worker.js calls inside Pyodide.

The page mounts the user's files read-only (WORKERFS: they are read in slices, never copied into
memory), calls build(), and assembles the download from result_run(): slices of the user's own file
plus the sectors this build rewrote or added.  Nothing leaves the browser.
"""
import hashlib, json, zlib
import numpy as np
from . import kernels, pipeline, cdrom

WORK = "/work"
_result = {}
_snd = dict(memo={}, plan=None)          # ADPCM encoder results made ahead by sub-workers (sound_plan / sound_results)


def use_js_kernels(jsk):
    """jsk: the JavaScript object with the kernels (patcher/src/kernels.js, wrapped by the worker so that
    numpy arrays arrive as typed-array views).  numpy integers become plain ints on the way."""
    def wrap(f):
        def call(*args):
            return f(*[int(a) if isinstance(a, np.integer) else a for a in args])
        return call
    kernels.set_backend({n: wrap(getattr(jsk, n)) for n in kernels.NAMES})
    kernels._chosen = True
    use_js_sound(jsk, wrap)


def use_js_sound(jsk, wrap):
    """1.2 sound banks (tools/snd/adpcm.py, resample.py): their numba functions -> the JavaScript twins.  The int64
    arrays of the Python code are handed over as int32 copies (all their values fit 16 or 32 bits)."""
    import os, sys
    tools = os.path.join(pipeline.REPO, "tools")
    if tools not in sys.path: sys.path.insert(0, tools)
    from snd import adpcm, resample
    dec, enc, rs = wrap(jsk.snd_decode), wrap(jsk.snd_encode), wrap(jsk.snd_resample)
    h32 = {}

    def decode_core(b, nblk, s1, s2, out):
        t = np.zeros(len(out), np.int32); dec(b, nblk, s1, s2, t); out[:] = t
        return None

    def encode_core(x, nblk, s1, s2, K, M, B, R, out):
        x32 = np.ascontiguousarray(x, np.int32)
        key = hashlib.sha1(x32.tobytes() + np.array([nblk, s1, s2, K, M, B, R], np.int64).tobytes()).hexdigest()
        if key in _snd["memo"]: out[:] = np.frombuffer(_snd["memo"][key], np.uint8); return
        if _snd["plan"] is not None:                  # sound_plan(): note the job, the result is not needed yet
            if key not in _snd["plan"]: _snd["plan"][key] = (x32.copy(), [int(v) for v in (nblk, s1, s2, K, M, B, R)])
            return
        enc(x32, nblk, s1, s2, K, M, B, R, out)

    def resample_core(x, n, num, den, D, nout, H, NTAB, P, out):
        if id(H) not in h32: h32[id(H)] = (H, np.ascontiguousarray(H, np.int32))
        t = np.zeros(len(out), np.int32)
        rs(np.ascontiguousarray(x, np.int32), n, num, den, D, nout, h32[id(H)][1], NTAB, P, t); out[:] = t
    adpcm._decode_core, adpcm._encode_core, resample._resample_core = decode_core, encode_core, resample_core


def use_js_zopfli(deflate):
    """deflate(bytes, iterations) -> raw deflate stream (zopfli compiled to WebAssembly, patcher/vendor/zopfli).
    Installed as the `zopfli` module tools/mkap8disc.py looks for; its output is byte-identical to the
    Python zopfli package the command-line build uses (same library), which keeps the 8 MB image identical."""
    import sys, types

    def compress(data, numiterations=15, **kw):
        assert not kw, "zopfli shim: only numiterations is supported"
        raw = deflate(bytes(data), int(numiterations)).to_py().tobytes()
        return bytes([0x78, 0xDA]) + raw + zlib.adler32(data).to_bytes(4, "big")      # zlib container, as zopfli.zlib.compress
    pkg = types.ModuleType("zopfli"); zl = types.ModuleType("zopfli.zlib")
    zl.compress = compress; pkg.zlib = zl
    sys.modules["zopfli"] = pkg; sys.modules["zopfli.zlib"] = zl


# ---------------------------------------------------------------- 1.2 sound banks, encoded in parallel
# The ADPCM encoder is most of the sound work (tools/sndpatch.py: every resampled sample of every level).  Its jobs
# do not depend on each other, so the worker asks for them first (sound_plan: the bank builds run once with the
# encoder only noting its inputs), hands them to sub-workers that run while the sprites are encoded here, and puts
# the results in the memo (sound_results).  During the build the encoder then takes each result from the memo by
# the SHA-1 of its input; anything not planned (the arcade sample of the 8 MB level) is encoded in place.  The bytes
# are the same either way: the sub-workers run the same kernel.
def prepare(disc):
    """extract the game files (pipeline.run extracts again: same files)"""
    import os
    os.makedirs(WORK, exist_ok=True)
    lmap = cdrom.extract(disc, os.path.join(WORK, "files"))
    json.dump(lmap, open(os.path.join(WORK, "lba_map.json"), "w"), indent=0)


def sound_plan(disc, arcade_json, flags_json):
    """-> (JSON [[key, offset, count, nblk, s1, s2, K, M, B, R], ...], int32 array of all inputs) of the encoder jobs
    the build will run; ([], empty) when the build has no 1.2 sound or its banks are in the cache already"""
    import os, sys
    flags = json.loads(flags_json)
    if "--nosound" in flags or "--nospeed" in flags: return json.dumps([]), np.zeros(0, np.int32)
    T = pipeline.Tools(disc, WORK)
    sp = T.mod("sndpatch")
    argv = sys.argv; sys.argv = ["mktagdisc.py", "x"] + flags
    _snd["plan"] = {}
    try:
        if not sp.enabled(): return json.dumps([]), np.zeros(0, np.int32)
        if not os.path.exists(os.path.join(sp._cache_dir(), sp._src_key() + ".bin")): sp.build_banks(sp.LEVELS)
        if json.loads(arcade_json): sp.level8({})                   # the 8 MB levels (without the arcade sample)
        jobs = _snd["plan"]
    finally:
        _snd["plan"] = None; sys.argv = argv
    meta, parts, o = [], [], 0
    for key, (x, prm) in jobs.items():
        meta.append([key, o, len(x)] + prm); parts.append(x); o += len(x)
    return json.dumps(meta), (np.concatenate(parts) if parts else np.zeros(0, np.int32))


def sound_results(meta_json, data):
    """data: the sub-workers' ADPCM blocks of the planned jobs, concatenated in plan order (16 bytes per block)"""
    d = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data); o = 0
    for key, off, n, nblk, *prm in json.loads(meta_json):
        _snd["memo"][key] = d[o:o + 16 * nblk]; o += 16 * nblk
    assert o == len(d)
    return len(_snd["memo"])


def sprites(progress, log):
    """the sprite stage on its own (pipeline.run finds its results in the work directory: cached)"""
    return json.dumps(pipeline.stage_sprites(WORK, 1, lambda f, t: progress("sprites", float(f), t), log))


def identify(path, progress=None):
    """-> JSON: status ok / patched / region / notgame / notimage / baddump, message, sha1, size"""
    sha, size = pipeline.sha1_file(path, progress)
    return json.dumps(pipeline.identify(path, sha, size))


def check_arcade(paths_json):
    """-> JSON: ok + set name, or the message for the user"""
    try: return json.dumps(dict(status="ok", message=pipeline.check_arcade(json.loads(paths_json))))
    except pipeline.BuildError as ex: return json.dumps(dict(status="bad", message=str(ex)))


def options_available():
    """-> JSON: optional features whose code is in the blob cache (there is no compiler in a browser)"""
    return json.dumps(pipeline.options_available())


def expected(variant, setname, flags_json):
    flags = sorted(json.loads(flags_json))
    for e in pipeline.known().get("expected", []):
        if e["variant"] == variant and e.get("arcade_set") == (setname or None) and e["flags"] == flags: return e["sha1"]
    return ""


def build(disc, arcade_json, flags_json, name, sha1, size, progress, log):
    """-> JSON: ok, name, variant, times ... or ok=False + code + message.  The image stays in this module."""
    _result.clear()
    try:
        info = pipeline.run(disc, WORK, json.loads(arcade_json), json.loads(flags_json), name or None, 1,
                            lambda s, f, t="": progress(s, float(f), t), log, known_sha1=(sha1, int(size)) if sha1 else None)
    except pipeline.BuildError as ex:
        return json.dumps(dict(ok=False, code=ex.code, message=str(ex)))
    ov = info.pop("overlay")
    _result.update(ov=ov, runs=ov.runs(), name=info["name"])
    info.update(ok=True, sectors=ov.nsec, changed=len(ov.dirty), cue=pipeline.cue_text(info["name"]))
    return json.dumps(info)


def result_run_count(): return len(_result["runs"])


def result_run(i):
    """-> ("src", first byte, byte count) or ("new", first byte, bytes)"""
    kind, first, x = _result["runs"][i]
    if kind == "src": return ("src", first * cdrom.SECTOR, x * cdrom.SECTOR)
    return ("new", first * cdrom.SECTOR, x)


def result_digest(progress=None):
    """SHA-1 and CRC-32 (for the zip download) of the finished image, streamed -> JSON"""
    ov = _result["ov"]; h = hashlib.sha1(); crc = 0; done = 0; total = ov.nsec * cdrom.SECTOR
    for b in ov.chunks():
        h.update(b); crc = zlib.crc32(b, crc); done += len(b)
        if progress: progress(done / total)
    return json.dumps(dict(sha1=h.hexdigest(), crc32=crc & 0xFFFFFFFF, size=total))
