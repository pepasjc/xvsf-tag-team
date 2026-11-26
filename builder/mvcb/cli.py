"""MvC: one command from your own disc image to the patched image (builder/build.py hands MvC discs here).

    python builder/build.py --disc "Marvel vs. Capcom (USA).bin" --out OUTDIR                     (2 MB tag hack)
    python builder/build.py --disc original.bin --arcade mvsc.zip --out OUTDIR                    (8 MB + arcade voices)

The input is checked by SHA-1 first; anything but the known original dump is refused.  See builder/README.md.
"""
import argparse, os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from mvcb import pipeline                                   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc", required=True, help="your original disc image (.bin, or the .cue that names it)")
    ap.add_argument("--arcade", nargs="+", default=[], help="your arcade ROM set (mvsc zip, or a clone zip followed by the mvsc parent zip): "
                    "builds the 8 MB image with the arcade voices")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--name", help='base name of the output files (default "%s")' % pipeline.output_name("2mb"))
    ap.add_argument("--work", help="work directory to keep (re-used on the next run); default: a temporary one")
    ap.add_argument("--chd", action="store_true", help="also write a .chd (needs chdman: XVSF_CHDMAN, PATH, or --chdman)")
    ap.add_argument("--chdman", help="path of chdman")
    ap.add_argument("--verbose", action="store_true", help="print the tools' own output")
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1), help="processes for the sound encoder (default %(default)s)")
    a = ap.parse_args(argv)
    t_all = time.time()
    os.makedirs(a.out, exist_ok=True)
    work = a.work or tempfile.mkdtemp(prefix="mvc_build_")
    logf = open(os.path.join(a.out, "build.log"), "w", encoding="utf-8", errors="replace")
    state = dict(stage=None); titles = dict(pipeline.STAGES)
    variant = "8mb" if a.arcade else "2mb"

    def log(line):
        logf.write(str(line) + "\n")
        if a.verbose: print("   " + str(line), flush=True, file=sys.__stdout__)

    def progress(stage, frac, text=""):
        if stage != state["stage"]:
            state["stage"] = stage; print("* %s ..." % titles.get(stage, stage), flush=True)
    try:
        from xvb.pipeline import resolve_image
        disc = resolve_image(a.disc)
        info = pipeline.run(disc, work, variant=variant, arcade=a.arcade, name=a.name, progress=progress, log=log, jobs=a.jobs)
        ov = info["overlay"]; name = info["name"]
        print("* Writing the image ...", flush=True)
        t0 = time.time()
        binpath = os.path.join(a.out, name + ".bin")
        sha = ov.write(binpath)
        with open(os.path.join(a.out, name + ".cue"), "w", newline="\n") as f: f.write(pipeline.cue_text(name))
        info["times"]["write"] = time.time() - t0
        if a.chd:
            chdman = a.chdman or os.environ.get("XVSF_CHDMAN") or shutil.which("chdman")
            if not (chdman and (shutil.which(chdman) or os.path.exists(chdman))): print("  (no chdman found: skipping the .chd; set XVSF_CHDMAN or give --chdman PATH)")
            else:
                print("* Writing the .chd ...", flush=True)
                subprocess.check_call([chdman, "createcd", "-i", os.path.join(a.out, name + ".cue"), "-o", os.path.join(a.out, name + ".chd"), "-f"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except pipeline.BuildError as ex:
        print("\nERROR: %s" % ex); logf.write("ERROR: %s\n" % ex); return 2
    finally:
        logf.flush()
        if not a.work: shutil.rmtree(work, ignore_errors=True)
    size = os.path.getsize(binpath)
    exp = pipeline.expected(variant, info.get("arcade_set"))
    print("\n%s  (%d bytes, %d sectors; %d rewritten or added)" % (binpath, size, size // 2352, len(ov.dirty)))
    print("SHA-1     %s" % sha)
    if exp: print("expected  %s  %s" % (exp["sha1"], "OK - identical to the reference build" if exp["sha1"] == sha else "*** DIFFERENT ***"))
    else: print("expected  (no reference recorded for %s)" % (("this arcade set (%s)" % info.get("arcade_set")) if a.arcade else "these options"))
    print("\nstage                seconds")
    for k, v in info["times"].items(): print("  %-18s %7.1f" % (k, v))
    print("  %-18s %7.1f" % ("total", time.time() - t_all))
    logf.write("sha1 %s\n" % sha); logf.close()
    return 0 if (not exp or exp["sha1"] == sha) else 1


if __name__ == "__main__":
    sys.exit(main())
