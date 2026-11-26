"""Regression check of the universal builder: every game's release builds through builder/build.py, hashed against the
references (XvSF: builder/data/known.json, 1.3; MSHvSF: builder/data/mshvsf/known.json, 1.0).

    python builder/tests/check_universal.py [--only xvsf2,xvsf8u,xvsf8,msh2,msh8] [--keep DIR] [--arcade-dir DIR]

Development machine: the discs from games/<g>/disc and disc/, the arcade sets from work/arcade (XvSF) and --arcade-dir
(MSHvSF).  Prints the time of each build.
"""
import argparse, os, re, subprocess, sys, tempfile, time, shutil
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BUILD = [sys.executable, os.path.join(REPO, "builder", "build.py")]
XV, MSH = os.path.join(REPO, "disc", "xvsf.bin"), os.path.join(REPO, "games", "mshvsf", "disc", "mshvsf.bin")
CASES = {   # name: (arguments, expected SHA-1)
    "xvsf2": (["--disc", XV], "bb5d17131587d205a1d1f26bdb65e3736fbcec5e"),
    "xvsf8u": (["--disc", XV, "--arcade", os.path.join(REPO, "work", "arcade", "xmvsfu.zip"), os.path.join(REPO, "work", "arcade", "xmvsf.zip")], "3342011be91e85aa43d2bdf9895a4b609a517200"),
    "xvsf8": (["--disc", XV, "--arcade", os.path.join(REPO, "work", "arcade", "xmvsf.zip")], "ce5a6df9432121288848728dd5fdba30748e7c01"),
    "msh2": (["--disc", MSH], "fed1e9574799ec777f768f92136ac2f22c0b2f10"),
    "msh8l": (["--disc", MSH, "--ram8"], "48682176df6c609e3411436dfb73742118554043"),
    "msh8": (["--disc", MSH, "--arcade", "{A}/mshvsf.zip"], "8593131485616ce904a5658c425bfcad5a3324b6"),
    "msh8u": (["--disc", MSH, "--arcade", "{A}/mshvsfu.zip", "{A}/mshvsf.zip"], "8593131485616ce904a5658c425bfcad5a3324b6"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="xvsf2,xvsf8u,msh2,msh8l,msh8"); ap.add_argument("--keep"); ap.add_argument("--arcade-dir", default="F:/Isos/fba_novo")
    a = ap.parse_args()
    bad = 0
    for name in a.only.split(","):
        args, want = CASES[name]
        args = [x.replace("{A}", a.arcade_dir) for x in args]
        out = os.path.join(a.keep, name) if a.keep else tempfile.mkdtemp(prefix="univ_" + name + "_")
        t0 = time.time()
        p = subprocess.run(BUILD + args + ["--out", out], capture_output=True, text=True)
        secs = time.time() - t0
        m = re.search(r"^SHA-1\s+([0-9a-f]{40})", p.stdout, re.M)
        got = m.group(1) if m else None
        ok = got == want
        bad += not ok
        print("%-7s %s %6.0f s  %s" % (name, got, secs, "OK" if ok else "*** expected %s\n%s\n%s" % (want, p.stdout[-1500:], p.stderr[-1500:])), flush=True)
        if not a.keep: shutil.rmtree(out, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
