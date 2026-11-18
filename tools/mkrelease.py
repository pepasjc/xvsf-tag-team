"""Release tooling: patch files (original disc image -> built image) for each region.

    python tools/mkrelease.py VERSION [us] [jp]        -> release/<VERSION>/     (default: us only)

For every region it writes
    xvsf-tag-<region>-<VERSION>.xdelta      xdelta3 (VCDIFF) patch against the ORIGINAL .bin (2352-byte sectors)
    manifest.json                           expected hashes/sizes of the original and of the patched image
    README.txt                              features, controls, how to apply, known issues
    apply.py                                stand-alone checker/applier: refuses an image whose hash is not the expected one
and verifies the patch itself: it is applied to the original with xdelta3 and the result must hash
to the built image.  Only differences are stored - no image is copied into the release.
"""
import os, sys, json, hashlib, subprocess, shutil, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import toolenv
XDELTA = toolenv.xdelta()
REGIONS = {
    "us": dict(name="X-Men vs. Street Fighter (USA)", serial="SLUS-00627", orig=os.path.join(ROOT, "disc", "xvsf.bin"),
               built=os.path.join(ROOT, "build", "xvsf_tag23.bin"), out="X-Men vs. Street Fighter (USA) [Tag Hack]"),
    "jp": dict(name="X-Men vs. Street Fighter - EX Edition (Japan)", serial="SLPS-01284",
               orig=os.path.join(ROOT, "disc", "jap", "X-Men vs. Street Fighter - EX Edition (Japan).bin"),
               built=os.path.join(ROOT, "build", "xvsfj_tag23.bin"), out="X-Men vs. Street Fighter - EX Edition (Japan) [Tag Hack]"),
}


def hashes(path):
    md5, sha1, crc = hashlib.md5(), hashlib.sha1(), 0
    import zlib
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b: break
            md5.update(b); sha1.update(b); crc = zlib.crc32(b, crc)
    return dict(size=os.path.getsize(path), md5=md5.hexdigest(), sha1=sha1.hexdigest(), crc32=f"{crc & 0xFFFFFFFF:08x}")


README = """X-Men vs. Street Fighter (PlayStation) - tag hack, version {version}
======================================================================

What it does
  * All four characters of a match are loaded in full, and you can SWITCH to your partner at any
    time, as in the arcade game (the PlayStation original only lets the partner assist).
  * The partner has its own life bar; a knocked-out character is replaced by the partner; the
    benched character recovers the red part of its life; one match = one round, arcade rules.
  * The CPU tags too in arcade mode.  The fight against Apocalypse can be fought as a tag team.
  * Second life bar for the partner, arcade-style music changes, CPU difficulty ticker and balance values as in the arcade game.

Controls (new default shoulder layout; face buttons as in the original; a key config saved on a
memory card or set in the options still overrides it)
  L1 = three punches      R1 = hard punch
  L2 = three kicks        R2 = hard kick
  R1 + R2 (hard punch + hard kick)                  switch to the partner
  quarter-circle forward + R1+R2                    team super (needs super meter)
  quarter-circle back + R1+R2 while guarding        counter with the partner

Files
{files}
How to apply
  You need your own disc image of the matching version as a single .bin file with 2352-byte
  sectors (the usual .bin/.cue dump).  The patch contains only the differences.
    python apply.py "your image.bin"            (checks the image, then runs xdelta3)
  or by hand:
    xdelta3 -d -s "your image.bin" xvsf-tag-<region>-{version}.xdelta "patched.bin"
  If the checksum of your image is not the one in manifest.json the patch will not fit: apply.py
  refuses it.  Write a .cue next to the patched .bin (one MODE2/2352 track) or reuse your own.

Known issues
{issues}
"""

ISSUES = [
    "When memory is tight (large characters on the larger stages) some characters are loaded with a slower sprite "
    "format; long supers of those characters can drop frames.",
    "The Japanese version is built from the US patch set by automatic address mapping and has only been tested in an "
    "emulator, less than the US one.",
    "The patches fit only the dumps listed in manifest.json; other dumps or revisions are refused.",
]

APPLY = r'''"""Check a disc image against the manifest and apply the tag-hack patch with xdelta3."""
import hashlib, json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
man = json.load(open(os.path.join(here, "manifest.json")))
if len(sys.argv) < 2: sys.exit('usage: python apply.py "your image.bin" [xdelta3 executable]')
src = sys.argv[1]; xd = sys.argv[2] if len(sys.argv) > 2 else "xdelta3"
h = hashlib.sha1()
with open(src, "rb") as f:
    for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
sha = h.hexdigest(); size = os.path.getsize(src)
for region, m in man["regions"].items():
    if m["original"]["sha1"] == sha:
        out = os.path.join(os.path.dirname(os.path.abspath(src)), m["output"] + ".bin")
        subprocess.check_call([xd, "-d", "-f", "-s", src, os.path.join(here, m["patch"]), out])
        h = hashlib.sha1()
        with open(out, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
        if h.hexdigest() != m["patched"]["sha1"]: sys.exit("the patched image does not have the expected checksum - do not use it")
        open(out[:-4] + ".cue", "w").write('FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n' % os.path.basename(out))
        print("ok:", out)
        break
else:
    print("This image is not one of the supported dumps (size %d, sha1 %s)." % (size, sha))
    for region, m in man["regions"].items():
        print("  %s: %s  size %d  sha1 %s" % (region, m["name"], m["original"]["size"], m["original"]["sha1"]))
    sys.exit(1)
'''


def main():
    version = sys.argv[1]
    regs = [a for a in sys.argv[2:] if a in REGIONS] or ["us"]        # jp is parked (work/jp/STATUS.md): only on request
    out = os.path.join(ROOT, "release", version); os.makedirs(out, exist_ok=True)
    man = dict(version=version, date=datetime.date.today().isoformat(), tool="xdelta3 (VCDIFF)", regions={})
    files = ""
    for r in regs:
        c = REGIONS[r]
        patch = f"xvsf-tag-{r}-{version}.xdelta"
        pp = os.path.join(out, patch)
        subprocess.check_call([XDELTA, "-e", "-9", "-S", "lzma", "-f", "-s", c["orig"], c["built"], pp])
        tmp = os.path.join(out, "_verify.bin")
        subprocess.check_call([XDELTA, "-d", "-f", "-s", c["orig"], pp, tmp])
        ho, hb, hv = hashes(c["orig"]), hashes(c["built"]), hashes(tmp)
        os.remove(tmp)
        assert hv == hb, f"{r}: the patch does not reproduce the built image"
        man["regions"][r] = dict(name=c["name"], serial=c["serial"], patch=patch, patch_size=os.path.getsize(pp), patch_sha1=hashes(pp)["sha1"],
                                 output=c["out"], original=ho, patched=hb)
        files += f"  {patch}   for {c['name']} [{c['serial']}]\n      original .bin: {ho['size']} bytes, sha1 {ho['sha1']}\n"
        print(f"{r}: {patch} {os.path.getsize(pp)} bytes ({os.path.getsize(pp) / 1048576:.1f} MB), verified: applying it to the original reproduces the built image")
    json.dump(man, open(os.path.join(out, "manifest.json"), "w"), indent=2)
    open(os.path.join(out, "README.txt"), "w").write(README.format(version=version, files=files, issues="".join(f"  * {x}\n" for x in ISSUES if "jp" in regs or "Japanese" not in x)))
    open(os.path.join(out, "apply.py"), "w").write(APPLY)
    print("release in", out)


if __name__ == "__main__":
    main()
