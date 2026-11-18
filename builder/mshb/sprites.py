"""The MSHvSF sprite tiers: every character file (DAT/SP_PLxx.DSP) re-encoded with DSH1 / DSM1, with and without
"hot" tiles (tiles decoded in bursts stay stock RLE, up to N KB of streams).  Tier dirs as the disc builder reads
them: <out>/<tier>/SP_PLxx.DSP.

Parameters come from builder/data/mshvsf/: dsh_params.json (the (tables, classes) pair per tier and character:
the winner of the per-file search over common/dsp/dsh.py SEARCH, recorded so the build encodes once) and
hot/SP_PLxx.json (play volume per tile, our measurement; character 00 has none, so it has no hot tiers).
"""
import json, os, time
from . import dsm1, dsh1, kernels
from .dspfile import DSP, hot_tiles

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data", "mshvsf")
TIERS = ["dsh_cut", "dsh", "dsh_hot4", "dsh_hot8", "dsh_hot16", "dsh_hot32", "dsm", "dsm_hot16", "dsm_hot32", "dsm_hot64"]
CHARS = list(range(0x17))
DSM_K = 64
_params = None


def label(char): return "SP_PL%02X" % char


def tier_info(tier):
    """-> (codec "dsh"/"dsm", hot cap in bytes or 0)"""
    if tier == "dsh_cut": return "dsh", 0
    codec, _, hot = tier.partition("_hot")
    return codec, int(hot) * 1024 if hot else 0


def hot_path(char): return os.path.join(DATA, "hot", label(char) + ".json")


_cuts = None


def cuts():
    """dsh_cut.json: the tiles games/mshvsf/tools/tagload/cuttier.py cut per character (indices; our measurement)"""
    global _cuts
    if _cuts is None: _cuts = json.load(open(os.path.join(DATA, "dsh_cut.json")))
    return _cuts


def cut_dsp(x, cut):
    """tools/tagload/cuttier.py cut_dsp: the stock-format file with the tiles in `cut` pointing to all-zero RLE
    streams appended to sec0 (runs of 16 zero bytes)"""
    import struct
    sec0 = bytearray(x.sec[0]); tab = bytearray(x.sec[2]); zero = {}
    for i in sorted(cut):
        n = int(x.nbytes[i])
        if n not in zero:
            zero[n] = len(sec0); sec0 += bytes([0xF0]) * (n // 16)
        w = struct.unpack_from("<I", tab, 4 * i)[0]
        struct.pack_into("<I", tab, 4 * i, (w & ~0x3FFFFF) | zero[n])
    while len(sec0) % 4: sec0 += bytes(1)
    offs = [0x14]; offs.append(offs[0] + len(sec0)); offs.append(offs[1] + len(x.sec[1])); offs.append(offs[2] + len(tab))
    return struct.pack("<5I", x.kind, *offs) + bytes(sec0) + x.sec[1] + bytes(tab) + x.sec[3]


def params():
    global _params
    if _params is None: _params = json.load(open(os.path.join(DATA, "dsh_params.json")))
    return _params


def jobs(files_dir):
    """-> [(tier, char)] for every stock file present in files_dir (hot tiers only where there is hot data)"""
    out = []
    for tier in TIERS:
        codec, cap = tier_info(tier)
        for c in CHARS:
            if not os.path.exists(os.path.join(files_dir, label(c) + ".DSP")): continue
            if cap and not os.path.exists(hot_path(c)): continue
            if tier == "dsh_cut" and label(c) not in cuts(): continue
            out.append((tier, c))
    return out


def encode_job(tier, char, stock_bytes, verify=True, stats=None):
    """one tier file from the stock SP_PLxx.DSP bytes -> new file bytes (stats: dict to receive the encoder stats)"""
    codec, cap = tier_info(tier)
    x = DSP(stock_bytes)
    if tier == "dsh_cut":                                   # the cut source, encoded with the plain DSH1 file's parameters
        x = DSP(cut_dsp(x, cuts()[label(char)]))
        k, c1 = params()["dsh"][label(char)]
        new, st = dsh1.encode(x, k, c1, verify=verify)
        if stats is not None: stats.update(st)
        return new
    rle = ()
    if cap:
        rle = hot_tiles(x, json.load(open(hot_path(char))), cap)
    if codec == "dsm":
        new, st = dsm1.encode(x, DSM_K, rle=rle, verify=verify)
    else:
        k, c1 = params()[tier][label(char)]
        new, st = dsh1.encode(x, k, c1, rle=rle, verify=verify)
    if stats is not None: stats.update(st)
    return new


def _work(a):
    tier, char, path, out_root, verify = a
    t0 = time.time()
    new = encode_job(tier, char, open(path, "rb").read(), verify)
    d = os.path.join(out_root, tier); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, label(char) + ".DSP"), "wb").write(new)
    return tier, char, time.time() - t0


def _init(backend):
    kernels.set_backend(backend)


def encode_all(files_dir, out_root, progress=None, jobs=1, verify=True):
    """encode every job -> out_root/<tier>/SP_PLxx.DSP.  progress(done, total, tier, char, secs).  jobs > 1: a
    process pool (command line only).  -> {(tier, char): seconds}"""
    todo = [(t, c, os.path.join(files_dir, label(c) + ".DSP"), out_root, verify) for t, c in globals()["jobs"](files_dir)]
    times = {}
    if jobs > 1:
        from multiprocessing import Pool
        b = kernels.backend
        assert isinstance(b, str) and b != "external", "a process pool needs the numba or python backend"
        with Pool(jobs, _init, (b,)) as p:
            it = p.imap_unordered(_work, todo)
            for r in it:
                times[r[:2]] = r[2]
                if progress: progress(len(times), len(todo), *r)
    else:
        for a in todo:
            r = _work(a); times[r[:2]] = r[2]
            if progress: progress(len(times), len(todo), *r)
    return times
