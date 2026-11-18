"""Which game is this disc?  The entry point of the universal builder and patcher page.

    detect(path) -> dict(game, serial, boot, region_ok, title)   cheap: reads only the ISO directory and SYSTEM.CNF
    identify(path, sha1=None, size=None) -> the game builder's verdict (status ok / patched / region / notgame /
                                            notimage / baddump / unsupported, message, sha1, size) + game

The game is recognised by the files on the disc (each game has its own file set), the release by the boot
executable named in SYSTEM.CNF (= the serial), and the exact dump by the SHA-1 of the whole image (each game's
builder checks that: builder/data/known.json, builder/data/mshvsf/known.json).
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)
from xvb import cdrom          # noqa: E402

# game: (title, files that identify it (basenames), the supported release's boot file, builder module or None)
GAMES = {
    "xvsf": ("X-Men vs. Street Fighter", ("SP_PL00.NSP",), "SLUS_006.27", "xvb"),
    "mshvsf": ("Marvel Super Heroes vs. Street Fighter", ("SP_PL00.DSP", "DMY.DAT"), "SLUS_007.93", "mshb"),
    "mvc": ("Marvel vs. Capcom: Clash of Super Heroes", ("DMY0.DAT", "DMY1.DAT"), "SLUS_010.59", None),     # port in progress
}
ORDER = ["xvsf", "mshvsf", "mvc"]


def serial_of(boot):
    """SLUS_007.93 -> SLUS-00793"""
    m = re.match(r"([A-Z]{4})_(\d{3})\.(\d{2})$", boot or "")
    return "%s-%s%s" % m.groups() if m else (boot or "?")


def detect(path):
    try:
        size = os.path.getsize(path)
        if size % cdrom.SECTOR: raise ValueError("size %d" % size)
        with open(path, "rb") as f: sync = f.read(16)
        if sync[:12] != b"\0" + b"\xff" * 10 + b"\0": raise ValueError("sync %s size %d" % (sync.hex(), size))
        d = cdrom.Disc(path)
        names = {}
        for n, l, s in d.walk(): names[n.split("/")[-1].upper()] = (l, s)
    except Exception as ex:
        return dict(game=None, notimage=True, error="%s: %s" % (type(ex).__name__, ex))
    boot = None
    if "SYSTEM.CNF" in names:
        l, s = names["SYSTEM.CNF"]
        m = re.search(rb"BOOT\s*=\s*cdrom:\\?\\?([^;\r\n]+)", d.read(l, min(s, 2048)), re.I)
        if m: boot = m.group(1).decode("ascii", "replace").strip().upper().lstrip("\\")
    for g in ORDER:
        title, sig, exe, mod = GAMES[g]
        if all(x in names for x in sig):
            return dict(game=g, title=title, boot=boot, serial=serial_of(boot), supported_release=boot == exe, builder=mod)
    return dict(game=None, boot=boot, serial=serial_of(boot) if boot else None)


def identify(path, sha1=None, size=None):
    det = detect(path)
    base = dict(sha1=sha1, size=size)
    if det.get("notimage"):
        return dict(base, status="notimage", game=None, message="This is not a raw PlayStation disc image (MODE2/2352 .bin). "
                    "Compressed formats (CHD, PBP, ECM) and .iso files with 2048-byte sectors are not supported: convert to bin/cue first.", error=det.get("error", ""))
    g = det["game"]
    if g is None:
        what = " (its boot file is %s, serial %s)" % (det["boot"], det["serial"]) if det.get("boot") else ""
        return dict(base, status="notgame", game=None, message="This disc is not one of the games this patcher supports%s: "
                    "X-Men vs. Street Fighter (USA, SLUS-00627) or Marvel Super Heroes vs. Street Fighter (USA, SLUS-00793)." % what)
    title, sig, exe, mod = GAMES[g]
    if mod is None:
        return dict(base, status="unsupported", game=g, serial=det["serial"], message="This is %s (%s). The tag hack for it is still in progress; "
                    "this patcher cannot build it yet." % (title, det["serial"]))
    if not det["supported_release"]:
        return dict(base, status="region", game=g, serial=det["serial"], message="This is %s, but another release (%s). The patch is made for the USA release, %s."
                    % (title, det["serial"], serial_of(exe)))
    if g == "xvsf":
        from xvb import pipeline
        if sha1 is None: sha1, size = pipeline.sha1_file(path)
        r = pipeline.identify(path, sha1, size)
    else:
        from mshb import pipeline
        if sha1 is None: sha1, size = pipeline.sha1_file(path)
        r = pipeline.identify(path, sha1, size)
    r.update(game=g, serial=det["serial"])
    return r


def identify_web(path, progress=None):
    """the patcher page: identify first (cheap), hash only a supported release -> JSON"""
    import json
    det = detect(path)
    if det.get("game") in ("xvsf", "mshvsf") and det.get("supported_release"):
        from xvb import pipeline
        sha1, size = pipeline.sha1_file(path, progress)
        return json.dumps(identify(path, sha1, size))
    return json.dumps(identify(path, None, os.path.getsize(path)))
