"""Developer check: encode the MSHvSF sprite tiers with builder/mshb and compare them, byte for byte, with the files
common/dsp/dsh.py / dsm.py left in games/mshvsf/work/dsp/<tier>/ (only on the development machine).

    python builder/tests/check_msh_sprites.py [--backend numba|python] [--tier T ...] [--char XX ...] [--noverify]
                                              [--search]

--search: for a DSH job that differs, try every (tables, classes) pair of common/dsp/dsh.py SEARCH and print the one
that reproduces the reference (to fix builder/data/mshvsf/dsh_params.json).
"""
import argparse, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "builder"))
from mshb import kernels, sprites, dsh1                       # noqa: E402
from mshb.dspfile import DSP, hot_tiles                       # noqa: E402

SEARCH = [(128, 192), (128, 224), (160, 224), (160, 256), (192, 224), (192, 256)]     # common/dsp/dsh.py
REF = os.path.join(ROOT, "games", "mshvsf", "work", "dsp")

ap = argparse.ArgumentParser()
ap.add_argument("--backend", default="numba", choices=["numba", "python"])
ap.add_argument("--tier", nargs="*"); ap.add_argument("--char", nargs="*")
ap.add_argument("--noverify", action="store_true"); ap.add_argument("--search", action="store_true")
a = ap.parse_args()
kernels.set_backend(a.backend)
print("kernel backend:", kernels.backend, flush=True)
files = os.path.join(REF, "files")
todo = [(t, c) for t, c in sprites.jobs(files) if (not a.tier or t in a.tier) and (not a.char or "%02X" % c in [x.upper() for x in a.char])]
if a.backend == "numba":                                       # compile outside the timings
    sprites.encode_job("dsm", 0, open(os.path.join(files, "SP_PL00.DSP"), "rb").read())
    sprites.encode_job("dsh", 0, open(os.path.join(files, "SP_PL00.DSP"), "rb").read())
ok = 0; bad = []; T = {}; N = {}
t_all = time.time()
for tier, c in todo:
    stock = open(os.path.join(files, sprites.label(c) + ".DSP"), "rb").read()
    ref = open(os.path.join(REF, tier, sprites.label(c) + ".DSP"), "rb").read()
    t0 = time.time()
    new = sprites.encode_job(tier, c, stock, verify=not a.noverify)
    dt = time.time() - t0
    T[tier] = T.get(tier, 0) + dt; N[tier] = N.get(tier, 0) + 1
    same = new == ref
    ok += same
    print("%-10s %s  %s  %7d  %.2fs" % (tier, sprites.label(c), "identical" if same else "DIFFERENT (%d vs %d)" % (len(new), len(ref)), len(new), dt), flush=True)
    if not same:
        bad.append((tier, c))
        if a.search and tier.startswith("dsh"):
            codec, cap = sprites.tier_info(tier)
            for k, c1 in SEARCH:
                x = DSP(stock)
                rle = hot_tiles(x, sprites.json.load(open(sprites.hot_path(c))), cap) if cap else ()
                if dsh1.encode(x, k, c1, rle=rle)[0] == ref:
                    print("    reproduced by (%d, %d)" % (k, c1), flush=True); break
            else:
                print("    no SEARCH pair reproduces it", flush=True)
print("\nper tier: jobs, total s, s/job")
for t in sprites.TIERS:
    if t in T: print("  %-10s %3d  %7.1f  %5.2f" % (t, N[t], T[t], T[t] / N[t]))
print("%d of %d identical, %.0fs" % (ok, len(todo), time.time() - t_all))
if bad: print("DIFFERENT:", " ".join("%s/%02X" % b for b in bad))
print("ALL IDENTICAL" if not bad else "DIFFERENCES")
