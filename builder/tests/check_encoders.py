"""Developer check: re-encode the sprite files with builder/xvb and compare them, byte for byte, with the
files the original hand-run tools left in build/ (git-ignored; only on the development machine).

    python builder/tests/check_encoders.py [ids hex ...]
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "builder"))
from xvb import kernels, nspfile, xvm1, xvh1
kernels.auto_backend()
print("kernel backend:", kernels.backend)
A0 = os.path.join(ROOT, "disc", "files", "A", "A0"); B = os.path.join(ROOT, "build")
mid = json.load(open(os.path.join(ROOT, "builder", "data", "tiles_mid.json")))
fat = json.load(open(os.path.join(ROOT, "builder", "data", "tiles_fat.json")))
ids = [int(x, 16) for x in sys.argv[1:]] or list(range(19))
ok = True; T = {}
def tm(k, t0): T[k] = T.get(k, 0) + time.time() - t0
for c in ids:
    fn = "SP_PL%02X.NSP" % c; k = "%02X" % c
    n = nspfile.NSP(open(os.path.join(A0, fn), "rb").read())
    t0 = time.time(); n.decode_all(); tm("decode", t0)
    ref = lambda d: open(os.path.join(B, d, fn), "rb").read()
    t0 = time.time(); base = xvm1.encode(n); tm("base", t0)
    t0 = time.time(); m = xvm1.encode(n, rle=mid[k]) if mid[k] else base; tm("mid", t0)
    t0 = time.time(); f = xvm1.encode(n, rle=set(mid[k]) | set(fat[k])); tm("fat", t0)
    t0 = time.time(); s = xvh1.encode(n); tm("strong", t0)
    r = [base == ref("nspm"), m == ref("nspm4"), f == ref("nspfat2"), s == ref("nsp")]
    ok &= all(r)
    print(fn, "base/mid/fat/strong identical:", r, flush=True)
n = nspfile.NSP(open(os.path.join(ROOT, "disc", "files", "A", "A2", "SP_EFF1.NSP"), "rb").read())
e = xvm1.encode(n, k=16) == open(os.path.join(B, "nspm_eff", "SP_EFF1.NSP"), "rb").read()
print("SP_EFF1 identical:", e); ok &= e
print({k: round(v, 1) for k, v in T.items()})
print("ALL IDENTICAL" if ok else "DIFFERENCES")
