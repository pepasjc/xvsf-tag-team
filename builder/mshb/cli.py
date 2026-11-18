"""MSHvSF: one command from your own disc image to the patched image (builder/build.py hands MSHvSF discs here).

    python builder/build.py --disc "Marvel Super Heroes vs. Street Fighter (USA).bin" --out OUTDIR
    python builder/build.py --disc original.bin --arcade mshvsf.zip --out OUTDIR          (+ restored frames, 8 MB)
    python builder/build.py --disc original.bin --arcade mshvsfu.zip mshvsf.zip --out OUTDIR   (a clone + its parent)

The input is checked by SHA-1 first; anything but the known original dump is refused.  See builder/README.md.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from mshb import pipeline                                   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc", required=True, help="your original disc image (.bin, or the .cue that names it)")
    ap.add_argument("--arcade", nargs="+", default=[], help="your arcade ROM set (mshvsf zip, or a clone zip followed by the mshvsf parent zip): adds the restored animation frames")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--name", help='base name of the output files (default "%s [Tag Hack 1.0]", with "+ Restored Frames" for an arcade build)' % pipeline.TITLE)
    ap.add_argument("--work", help="work directory to keep (re-used on the next run: sprite tiers and sound levels are cached); default: a temporary one")
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1), help="processes for the sound encoder and the sprite encoders (default %(default)s)")
    ap.add_argument("--ram8", action="store_true", help="the 8 MB loader without an arcade set (all four characters full from upper RAM on 8 MB machines; "
                    "the image still runs on 2 MB); an arcade set implies it")
    ap.add_argument("--no-logo", action="store_true", help="leave out the two boot cards")
    ap.add_argument("--meter", choices=["off", "on", "none"], default="off",
                    help="speed meter: off = in OPTION MODE, off at boot (default, the release); on = on at boot; none = not built in")
    ap.add_argument("--tool-flag", action="append", metavar="FLAG", help="hand FLAG to tools/tagload/mktag.py / tools/ap8/mkap8.py as it is (developers)")
    ap.add_argument("--no-achievements", action="store_true", help="leave out the built-in achievements (popup, ACHIEVEMENTS page, memory card file; games/mshvsf/docs/ACHIEVEMENTS.md), "
                    "which are part of the release image (they switch themselves off on the PS2 / PS3)")
    ap.add_argument("--achievements", action="store_true", help=argparse.SUPPRESS)      # (older scripts: achievements are always on now; no effect)
    ap.add_argument("--chd", action="store_true", help="also write a .chd (needs chdman: XVSF_CHDMAN, PATH, or --chdman)")
    ap.add_argument("--chdman", help="path of chdman")
    ap.add_argument("--sprites-from", help=argparse.SUPPRESS)          # developers: copy the tiers from games/mshvsf/work/dsp
    ap.add_argument("--verbose", action="store_true", help="print the tools' own output")
    a = ap.parse_args(argv)

    t_all = time.time()
    os.makedirs(a.out, exist_ok=True)
    work = a.work or tempfile.mkdtemp(prefix="mshvsf_build_")
    logf = open(os.path.join(a.out, "build.log"), "w", encoding="utf-8", errors="replace")
    state = dict(stage=None); titles = dict(pipeline.STAGES)

    def log(line):
        logf.write(str(line) + "\n")
        if a.verbose: print("   " + str(line), flush=True, file=sys.__stdout__)

    def progress(stage, frac, text=""):
        if stage != state["stage"]:
            state["stage"] = stage; print("* %s ..." % titles.get(stage, stage), flush=True)
    flags = pipeline.tool_flags(logo=not a.no_logo, meter=a.meter, extra=a.tool_flag or [], achievements=not a.no_achievements)
    try:
        from xvb.pipeline import resolve_image
        disc = resolve_image(a.disc)
        info = pipeline.run(disc, work, arcade=a.arcade, flags=flags, name=a.name, jobs=a.jobs, progress=progress, log=log,
                            sprite_ref=a.sprites_from, ap8=a.ram8)
        ov = info["overlay"]; name = info["name"]
        print("* Writing the image ...", flush=True)
        t0 = time.time()
        binpath = os.path.join(a.out, name + ".bin")
        sha = ov.write(binpath)
        with open(os.path.join(a.out, name + ".cue"), "w", newline="\n") as f: f.write(pipeline.cue_text(name))
        info["times"]["write"] = time.time() - t0
        if a.chd:
            chdman = a.chdman or os.environ.get("XVSF_CHDMAN") or shutil.which("chdman")
            if not chdman:
                sys.path.insert(0, os.path.join(pipeline.REPO, "tools"))
                try:
                    import toolenv; chdman = toolenv.chdman()
                except Exception: chdman = None
            if not (chdman and (shutil.which(chdman) or os.path.exists(chdman))): print("  (no chdman found: skipping the .chd; set XVSF_CHDMAN or give --chdman PATH)")
            else:
                t0 = time.time(); print("* Writing the .chd ...", flush=True)
                subprocess.check_call([chdman, "createcd", "-i", os.path.join(a.out, name + ".cue"), "-o", os.path.join(a.out, name + ".chd"), "-f"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                info["times"]["chd"] = time.time() - t0
    except pipeline.BuildError as ex:
        print("\nERROR: %s" % ex); logf.write("ERROR: %s\n" % ex); return 2
    finally:
        logf.flush()
        if not a.work: shutil.rmtree(work, ignore_errors=True)
    size = os.path.getsize(binpath)
    exp = pipeline.expected(info["variant"], info.get("arcade_set"), flags)
    print("\n%s  (%d bytes, %d sectors; %d rewritten or added)" % (binpath, size, size // 2352, len(ov.dirty)))
    print("SHA-1     %s" % sha)
    if exp: print("expected  %s  %s" % (exp["sha1"], "OK - identical to the reference build" if exp["sha1"] == sha else "*** DIFFERENT ***"))
    else: print("expected  (no reference recorded for these options%s)" % (" / this arcade set" if a.arcade else ""))
    print("\nstage                seconds")
    for k, v in info["times"].items(): print("  %-18s %7.1f" % (k, v))
    print("  %-18s %7.1f" % ("total", time.time() - t_all))
    if info["blobs"]:
        print("our MIPS code: %d pieces, %s" % (len(info["blobs"]), "/".join(sorted(set(k for f, k in info["blobs"])))))
    if os.path.isdir(os.path.join(pipeline.REPO, "games", "mshvsf", "tools")):
        st = pipeline.stale_sources()
        if st: print("NOTE (developers): %d source files changed since builder/data/mshvsf/blobs was baked, e.g. %s - the image is built from the baked "
                     "code and the frozen tool files (builder/data/mshvsf/tools); work/mshvsf_release/record.py re-bakes" % (len(st), ", ".join(st[:4])))
    logf.write("sha1 %s\n" % sha); logf.close()
    return 0 if (not exp or exp["sha1"] == sha) else 1


if __name__ == "__main__":
    sys.exit(main())
