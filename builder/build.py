#!/usr/bin/env python3
"""One command from your own disc image to the patched image.

    python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --out OUTDIR
    python builder/build.py --disc original.bin --arcade xmvsfu.zip --out OUTDIR      (+ restored frames, 8 MB setups)

Writes OUTDIR/<name>.bin and .cue (and .chd with --chd when chdman is found).  The input is checked by
SHA-1 first; anything but the known original dump is refused.  Every intermediate file is regenerated in
a work directory (temporary unless --work is given) from the inputs alone.  See builder/README.md.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from xvb import pipeline                                    # noqa: E402


def tool_flags(a, arcade):
    """command-line options -> the flags of tools/mktagdisc.py / tools/mkap8disc.py (pipeline.tool_flags)"""
    logo = not (a.no_logo or a.plain)
    version = not a.no_menu_version and (bool(arcade) or not a.plain)      # --no-menu-version with an arcade set is refused, with the reason
    return pipeline.tool_flags(bool(arcade), logo, version, a.buttons, a.menu_version or None, a.tool_flag or [])


def expected(variant, setname, flags):
    for e in pipeline.known().get("expected", []):
        if e["variant"] == variant and e.get("arcade_set") == setname and e["flags"] == sorted(flags): return e
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc", required=True, help="your original disc image (.bin, or the .cue that names it)")
    ap.add_argument("--arcade", nargs="+", default=[], help="your arcade ROM set (zip; a clone zip followed by its parent zip): adds the restored animation frames")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--name", help='base name of the output files (default "X-Men vs. Street Fighter (USA) [Tag Hack 1.0]", with "+ Restored Frames" for an arcade build)')
    ap.add_argument("--work", help="work directory to keep (re-used on the next run: encoded sprites are cached); default: a temporary one")
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1), help="processes for the sprite encoders (default %(default)s)")
    ap.add_argument("--buttons", choices=["modern", "stock"], default="modern", help="default button layout: modern = HP R1, HK R2, 3P L1, 3K L2 (default); stock = the game's own")
    ap.add_argument("--no-logo", action="store_true", help="leave out the boot card shown before the game starts")
    ap.add_argument("--no-menu-version", action="store_true", help="leave out the version line on the main menu (2 MB build only; the 8 MB loader always draws it)")
    ap.add_argument("--plain", action="store_true", help="no boot card, and no version line on the 2 MB build: the plain images the regression references were made with")
    ap.add_argument("--menu-version", metavar="TEXT", help="your own text for the version line (capitals, digits, space, dot, dash; needs a MIPS compiler)")
    ap.add_argument("--tool-flag", action="append", metavar="FLAG", help="hand FLAG to tools/mktagdisc.py / mkap8disc.py as it is (developers; repeatable)")
    ap.add_argument("--chd", action="store_true", help="also write a .chd (needs chdman: XVSF_CHDMAN, PATH, or --chdman)")
    ap.add_argument("--chdman", help="path of chdman")
    ap.add_argument("--mips-prefix", help='MIPS cross toolchain prefix, e.g. "/opt/gcc/bin/mipsel-none-elf-" (only for options not in the blob cache)')
    ap.add_argument("--no-blob-cache", action="store_true", help="compile the option-dependent MIPS code instead of using builder/data/toolcache")
    ap.add_argument("--record-blobs", action="store_true", help="developers: store freshly compiled MIPS code in builder/data/toolcache")
    ap.add_argument("--record-expected", action="store_true", help="developers: store the resulting SHA-1 in builder/data/known.json")
    ap.add_argument("--verbose", action="store_true", help="print the tools' own output")
    a = ap.parse_args(argv)

    t_all = time.time()
    os.makedirs(a.out, exist_ok=True)
    work = a.work or tempfile.mkdtemp(prefix="xvsf_build_")
    logpath = os.path.join(a.out, "build.log")
    logf = open(logpath, "w", encoding="utf-8", errors="replace")
    state = dict(stage=None)
    titles = dict(pipeline.STAGES)

    def log(line):
        logf.write(str(line) + "\n")
        if a.verbose: print("   " + str(line), flush=True)

    def progress(stage, frac, text=""):
        if stage != state["stage"]:
            state["stage"] = stage; print("* %s ..." % titles.get(stage, stage), flush=True)
    try:
        flags = tool_flags(a, bool(a.arcade))
        info = pipeline.run(a.disc, work, a.arcade, flags, a.name, a.jobs, progress, log, mips_prefix=a.mips_prefix,
                            use_cache=not a.no_blob_cache, record=a.record_blobs)
        ov = info["overlay"]; name = info["name"]
        print("* Writing the image ...", flush=True)
        t0 = time.time()
        binpath = os.path.join(a.out, name + ".bin")
        sha = ov.write(binpath)
        with open(os.path.join(a.out, name + ".cue"), "w", newline="\n") as f: f.write(pipeline.cue_text(name))
        info["times"]["write"] = time.time() - t0
        if a.chd:
            sys.path.insert(0, os.path.join(pipeline.REPO, "tools"))
            import toolenv                                  # XVSF_CHDMAN, PATH, then the development default
            chdman = a.chdman or toolenv.chdman()
            if not (chdman and (shutil.which(chdman) or os.path.exists(chdman))): print("  (no chdman found: skipping the .chd; set XVSF_CHDMAN or give --chdman PATH)")
            else:
                t0 = time.time()
                print("* Writing the .chd ...", flush=True)
                subprocess.check_call([chdman, "createcd", "-i", os.path.join(a.out, name + ".cue"), "-o", os.path.join(a.out, name + ".chd"), "-f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                info["times"]["chd"] = time.time() - t0
    except pipeline.BuildError as ex:
        print("\nERROR: %s" % ex); logf.write("ERROR: %s\n" % ex); return 2
    finally:
        logf.flush()
        if not a.work: shutil.rmtree(work, ignore_errors=True)
    size = os.path.getsize(binpath)
    exp = expected(info["variant"], info.get("arcade_set"), flags)
    print("\n%s  (%d bytes, %d sectors; %d rewritten or added)" % (binpath, size, size // 2352, len(ov.dirty)))
    print("SHA-1     %s" % sha)
    if exp: print("expected  %s  %s" % (exp["sha1"], "OK - identical to the reference build" if exp["sha1"] == sha else "*** DIFFERENT ***"))
    else: print("expected  (no reference recorded for these options)")
    print("\nstage                seconds")
    for k, v in info["times"].items(): print("  %-18s %7.1f" % (k, v))
    print("  %-18s %7.1f" % ("total", time.time() - t_all))
    if info["blobs"]: print("option-dependent MIPS code:", ", ".join("%s (%s)" % b for b in info["blobs"]))
    logf.write("sha1 %s\n" % sha); logf.close()
    if a.record_expected:
        kn = pipeline.known()
        what = ("2 MB tag hack" if info["variant"] == "2mb" else "tag hack + restored frames, " + info["arcade_set"]) + (" [" + " ".join(flags) + "]" if flags else "")
        kn["expected"] = [e for e in kn.get("expected", []) if not (e["variant"] == info["variant"] and e.get("arcade_set") == info.get("arcade_set") and e["flags"] == sorted(flags))]
        kn["expected"].append(dict(variant=info["variant"], arcade_set=info.get("arcade_set"), flags=sorted(flags), sha1=sha, size=size, what=what))
        json.dump(kn, open(os.path.join(HERE, "data", "known.json"), "w"), indent=1)
        print("recorded in builder/data/known.json")
    return 0 if (not exp or exp["sha1"] == sha) else 1


if __name__ == "__main__":
    sys.exit(main())
