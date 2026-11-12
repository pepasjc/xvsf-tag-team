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


def use_js_kernels(jsk):
    """jsk: the JavaScript object with the kernels (patcher/src/kernels.js, wrapped by the worker so that
    numpy arrays arrive as typed-array views).  numpy integers become plain ints on the way."""
    def wrap(f):
        def call(*args):
            return f(*[int(a) if isinstance(a, np.integer) else a for a in args])
        return call
    kernels.set_backend({n: wrap(getattr(jsk, n)) for n in kernels.NAMES})
    kernels._chosen = True


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
