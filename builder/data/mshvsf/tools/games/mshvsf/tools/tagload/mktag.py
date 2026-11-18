"""Build the MSHvSF tag-hack disc (SLUS-00793).

    python mktag.py [name] [--chd] [--nospeed] [--noahead] [--meter] [--meteron] [--stockmeter] [--title=TEXT] [--ach] [--noskip]      -> games/mshvsf/build/<name>.bin/.cue (+ .chd)
    --ach: built-in achievements (games/mshvsf/tools/ach, docs/ACHIEVEMENTS.md); without it the output is unchanged
    --noskip: no START skip of the end of a match (games/mshvsf/tools/skip/mshskip.py; default on since 1.0)

Copies disc/mshvsf.bin and changes it in place (same file positions, same sizes):
  * DMY.DAT (37 MB of padding, never read) gets the new data: the loader blob, then per character
    PLxx_10.A0 + its relocation table, and the DSM1 sprite file (games/mshvsf/work/dsp/dsm/).
  * SLUS_007.93: loader glue + hook (tools/tagload), gameplay switch + version line (tools/gameplay),
    DSM1 decoder (common/dsp/dsmpatch.py), speed modules a0mem + parse (tools/speed).
  * OPDEMO.BIN: the version-line hook word.
EDC/ECC of every changed sector is recomputed.

    python mktag.py --ram     print the EXE patches only (for the emulator harness: apply_ram)
"""
import os, sys, struct, shutil, subprocess, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [HERE, os.path.join(GAME, "tools"), os.path.join(GAME, "tools", "gameplay"),
                os.path.join(GAME, "tools", "speed"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "common", "dsp")]
import importlib.util
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); return m
reloc = _load("msh_reloc", os.path.join(GAME, "tools", "reloc.py"))      # (XvSF has its own tools/reloc.py)
import toolenv
from mkdisc import fix_sector                    # XvSF tools/mkdisc.py (EDC/ECC)
import allpatches, dsmpatch, a0mem, parse as parsemod
import ahead as aheadmod                          # decode-ahead (tools/speed/ahead.py), default on, --noahead
import meter as metermod                          # on-screen speed meter (tools/speed/meter.py), --meter
sys.path.insert(0, os.path.join(GAME, "tools", "snd"))
import sndbank, sndbuild                 # full sound banks for every character (tools/snd, v10)
sys.path.insert(0, os.path.join(GAME, "tools", "logo"))
import mshcards                                   # boot cards: PEPA SOFT HOUSE + fan-patch notice (tools/logo, v10), --nologo
if "--nodsh" in sys.argv:            # the committed DSM1 decoder (common/dsp may hold work in progress of the DSH1 port)
    _o = os.path.join(BUILD if "BUILD" in dir() else os.path.join(GAME, "build"), "dsmdec_head")
    os.makedirs(_o, exist_ok=True)
    _src = os.path.join(_o, "dsmdec.S")
    open(_src, "wb").write(subprocess.check_output(["git", "show", "HEAD:common/dsp/dsmdec.S"], cwd=ROOT))
    _pp = os.path.join(_o, "dsmpatch_head.py")
    open(_pp, "wb").write(subprocess.check_output(["git", "show", "HEAD:common/dsp/dsmpatch.py"], cwd=ROOT))
    dsmpatch = _load("dsmpatch_head", _pp)
    dsmpatch.SRC = _src; dsmpatch.OBJ = _o; dsmpatch.ROOT = ROOT

GCC = toolenv.mips_prefix()
CF = ["-mips1", "-G0", "-mno-abicalls", "-fno-pic"]
SRC_BIN = os.path.join(GAME, "disc", "mshvsf.bin")
LBA = json.load(open(os.path.join(GAME, "work", "lba_map.json")))
FILES = os.path.join(GAME, "work", "loader", "files")
DSM = os.path.join(GAME, "work", "dsp", "dsm")
DSH = os.path.join(GAME, "work", "dsp", "dsh")                  # strong tier (common/dsp DSH1), optional
TIERDIRS = [DSH + "_cut", DSH] + [DSH + "_hot%d" % n for n in (4, 8, 16, 32)] + [DSM] + [os.path.join(GAME, "work", "dsp", f"dsm_hot{n}") for n in (16, 32, 64)]
NCOST = (len(TIERDIRS) + 2) & ~1                                 # u16 costs per record (NT, padded to even: tagload.c)
DSMT = 6                                                         # index of the plain DSM1 tier (always present)
DSHDEC = os.path.join(DSH, "dshdec.bin")                         # its decoder, linked at 0x801fe200
USE_DSH = "--nodsh" not in sys.argv
BUILD = os.path.join(GAME, "build")
EXE_BASE, EXE_HDR = 0x80010000, 0x800
ARENA = 0x80087e10
HOOK = 0x8002af50
HOOK_ORIG = (4, "4df62781b2eb668d00b9d35c760e2407d171c746")       # stock words at HOOK (count, SHA-1: the source carries no game code)
NCHAR = 0x17


def build_blob():
    shrink = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--testshrink=")), 0)
    for c in ("gcc -Os -ffreestanding -msoft-float -Wall -DREGION_SHRINK=%d -c tagload.c -o tagload.o" % shrink,
              "gcc -c glue.S -o glue.o"):
        p = c.split(); subprocess.check_call([GCC + p[0]] + CF + p[1:], cwd=HERE)
    sndbuild.objects(GCC, CF, HERE)
    subprocess.check_call([GCC + "ld", "-T", "link.ld", "glue.o", "tagload.o", "snd.o", "-o", "tagload.elf"], cwd=HERE)
    for sec in (".glue", ".heapcap", ".blob"):
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "tagload.elf", "tagload" + sec + ".bin"], cwd=HERE)
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", "tagload.elf"], cwd=HERE).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    glue = open(os.path.join(HERE, "tagload.glue.bin"), "rb").read()
    heapcap = open(os.path.join(HERE, "tagload.heapcap.bin"), "rb").read()
    assert sym["heapcap"] == 0x80010df8 and sym["heapcap_end"] <= 0x80010e90
    blob = open(os.path.join(HERE, "tagload.blob.bin"), "rb").read()
    assert sym["glue"] == 0x80013580 and sym["glue_end"] <= 0x80013748, "glue outside its range"
    assert blob[:4] == struct.pack("<I", 0x08000000 | ((sym["tl_main"] >> 2) & 0x3FFFFFF))
    assert ARENA + len(blob) < 0x80091e00
    return glue + b"", blob, sym, heapcap


def msf(lba):
    b = lambda x: (x // 10) << 4 | x % 10
    l = lba + 150
    return bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 0])


def a0_file(c):
    r = reloc.get(c)
    tab = r.table()
    a = r.a + bytes(-len(r.a) % 4)
    for base in (0x800bc000 + 0x123450, 0x800bc000 + 0x8c008, 0x800bc000 + 0x3a0):     # check the C model on this char
        f = base - 0x1c
        if r.safe(f):
            assert reloc.apply_table(r.a, tab, f) == r.relocate(f), (c, hex(base))
    iv = r.forbidden()
    assert len(iv) <= 1 and all(lo < hi for lo, hi in iv), (c, iv)
    a = sndbank.patch_a0(c, r.a) + a[len(r.a):]       # section 3 = the reordered level-0 sound bank (same size)
    return a + tab, len(r.a), (iv[0] if iv else (0, 0))


def codefp(a0):
    """DSP offset from the file start: (main, partner).  Main = stock 0x8002a564 rounding with the kind-6 bytes that
    stay in RAM after 0x8008006c stashes the pixels in SPU (set size - pixel section); partner = whole set in RAM."""
    n, = struct.unpack_from("<I", a0); assert n == 3
    s1 = struct.unpack_from("<I", a0, 8)[0]; o2, s2 = struct.unpack_from("<2I", a0, 12)
    kind, off0, off1 = struct.unpack_from("<3I", a0, o2); assert kind == 6
    kept = s2 - (off1 - off0)
    r = lambda x: 0x1c + (((x >> 3) + 1) << 3)
    return r(s1 + kept), r(s1 + s2)


HEAPHOOK = 0x8002aa38
HEAPHOOK_ORIG = (2, "34dbc3b7cef77557b4c7b862716ccfda346fab65")   # move a0,s1 ; jal 0x80020fe4 (count, SHA-1)


def exe_patches(sym, glue, blob_ent, title, speed, heapcap, mparts=None, stockmeter=False):
    """mparts = tools/speed/meter.py parts() when the meter is built in.  stockmeter: the stock game + the loader glue
    (its blob declines every battle) + the battle-init tail + the meter only (A/B gauge disc)"""
    jal = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
    o = sym["blobent"] - 0x80013580
    glue = glue[:o] + blob_ent + glue[o + 8:]
    bnez = 0x14400000 | ((0x8002afe0 - (HOOK + 8 + 4)) >> 2) & 0xFFFF      # bnez v0 at HOOK+8 -> 0x8002afe0
    out = [(HOOK, struct.pack("<4I", jal(sym["glue"]), 0x27a40018, bnez, 0)), (0x80013580, glue)]
    msyms = mparts[2] if mparts else None
    if mparts:
        out += mparts[0]
    if stockmeter:
        import tagmode
        out += tagmode.patches(tail=msyms["mcopy"])
    else:
        out += [(HEAPHOOK, struct.pack("<2I", jal(sym["heapcap"]), 0)), (0x80010df8, heapcap)]
        out += allpatches.patches(title, msyms)
        out += dsmpatch.patches("mshvsf")
        if speed:
            out += a0mem.patches() + parsemod.patches()
            if "--noahead" not in sys.argv:
                out += aheadmod.patches()
    # no two patches may overlap
    iv = sorted((a, a + len(d)) for a, d in out)
    for (a, b), (c, d) in zip(iv, iv[1:]):
        assert b <= c, f"patch overlap {a:08x}-{b:08x} / {c:08x}-{d:08x}"
    return out


class Img:
    def __init__(self, path):
        self.f = open(path, "r+b"); self.touched = set()

    def rsec(self, l):
        self.f.seek(l * 2352 + 24); return self.f.read(2048)

    def wbytes(self, lba, off, data):
        for i in range(len(data)):
            o = off + i
            self.f.seek((lba + o // 2048) * 2352 + 24 + o % 2048); self.f.write(data[i:i + 1])
            self.touched.add(lba + o // 2048)

    def rbytes(self, lba, off, n):
        out = bytearray()
        for i in range(n):
            o = off + i
            self.f.seek((lba + o // 2048) * 2352 + 24 + o % 2048); out += self.f.read(1)
        return bytes(out)

    def wsectors(self, lba, data):
        data = data + bytes(-len(data) % 2048)
        for i in range(len(data) // 2048):
            self.f.seek((lba + i) * 2352)
            raw = bytearray(self.f.read(2352))
            assert raw[18] & 0x20 == 0, "not a form-1 sector"
            raw[24:24 + 2048] = data[i * 2048:(i + 1) * 2048]
            self.f.seek((lba + i) * 2352); self.f.write(raw); self.touched.add(lba + i)

    def extend(self, start, n):
        self.f.seek((start - 1) * 2352); tmpl = bytearray(self.f.read(2352))
        assert tmpl[15] == 2 and not tmpl[18] & 0x20, "last sector is not mode 2 form 1"
        b = lambda x: (x // 10) << 4 | x % 10
        for i in range(n):
            l = start + i + 150
            sec = bytearray(tmpl[:12] + bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 2]) + tmpl[16:24] + bytes(2048 + 280))
            self.f.seek((start + i) * 2352); self.f.write(sec); self.touched.add(start + i)

    def fix(self):
        for l in sorted(self.touched):
            self.f.seek(l * 2352); raw = bytearray(self.f.read(2352))
            fix_sector(raw); self.f.seek(l * 2352); self.f.write(raw)
        self.f.close()


def layout():
    """[(key, bytes)] for DMY.DAT, plus the directory entries"""
    items = []
    chars = {}
    for c in range(NCHAR):
        a0, a0size, iv = a0_file(c)
        tiers = []
        for t, d in enumerate(TIERDIRS):
            p = os.path.join(d, f"SP_PL{c:02X}.DSP")
            tiers.append(open(p, "rb").read() if os.path.exists(p) and (t >= DSMT or USE_DSH) else None)
        assert tiers[DSMT], f"no DSM1 file for {c:02X}"
        chars[c] = dict(a0=a0, a0size=a0size, iv=iv, tiers=tiers, codefp=codefp(a0))
        items += [(("a0", c), a0)] + sndbuild.items([c]) + [(("t", c, t), x) for t, x in enumerate(tiers) if x]
        # (sound bank level files between the A0 and the sprite files: read only by battles that need them)
    return items, chars


def main(argv):
    name = next((a for a in argv[1:] if not a.startswith("--")), "mshvsf_tag")
    title = next((a.split("=", 1)[1] for a in argv if a.startswith("--title=")), allpatches.menuversion.DEFAULT)
    speed = "--nospeed" not in argv
    stockmeter = "--stockmeter" in argv
    glue, blob, sym, heapcap = build_blob()
    mparts = metermod.parts(sym, on="--meteron" in argv or stockmeter) if "--meter" in argv or stockmeter else None
    items, chars = layout()
    dmy_lba, dmy_size = LBA["DMY.DAT"]
    lba = dmy_lba
    nblob = (len(blob) + 2048 + 4 + 2047) // 2048        # + the strong payload (<= 2048 bytes) appended later
    lba += nblob
    pos = {}; dmy_end = dmy_lba + dmy_size // 2048
    img_end = os.path.getsize(SRC_BIN) // 2352
    ext = img_end                                    # files that do not fit in DMY.DAT go after the end of the image
    for key, data in items:
        n = (len(data) + 2047) // 2048
        if lba + n <= dmy_end: pos[key] = lba; lba += n
        else: pos[key] = ext; ext += n
    appended = ext - img_end
    # directory into the blob
    import tiercost
    assert tiercost.TIERDIRS == [os.path.basename(x) for x in TIERDIRS]
    cost = tiercost.table()
    for c in cost: cost[c][0] = 0xfffe                     # the cut tier: last resort, the greedy step leaves it first
    d = sym["tl_dir"] - ARENA
    assert blob[d:d + 4] == b"TAGL"
    ent = lambda key, n: msf(pos[key]) + struct.pack("<I", n) if key in pos else bytes(8)
    tab = b"".join(ent(("a0", c), len(chars[c]["a0"])) + struct.pack("<3I2H", chars[c]["a0size"], *chars[c]["codefp"], *chars[c]["iv"]) +
                   b"".join(ent(("t", c, t), len(x or b"")) for t, x in enumerate(chars[c]["tiers"])) +
                   struct.pack("<%dH" % NCOST, *([cost[c][t] if t == len(TIERDIRS) or chars[c]["tiers"][t] else 0xffff
                                                   for t in range(len(TIERDIRS) + 1)] + [0] * (NCOST - len(TIERDIRS) - 1))) for c in range(NCHAR))
    assert len(tab) == NCHAR * (24 + 8 * len(TIERDIRS) + 2 * NCOST)     # = sizeof(struct chr)
    strong = open(DSHDEC, "rb").read() if any(chars[c]["tiers"][0] for c in chars) else b""
    if mparts:
        strong = metermod.strong(strong, mparts[1])
    assert len(strong) <= 2048 and len(strong) % 4 == 0
    blob = blob[:d + 4] + struct.pack("<I", len(strong)) + tab + blob[d + 8 + len(tab):]
    if stockmeter:
        blob = blob[:d] + b"NONE" + blob[d + 4:]                # tl_main declines every battle (0xfd): stock loader
    ds = sym["snd_dir"] - ARENA                                  # sound directory (tools/snd/snd.c struct sdir)
    sdir = sndbuild.directory(pos, msf, sndbuild.hook(GCC, CF, os.path.join(GAME, "build")))
    assert blob[ds:ds + 4] == sndbuild.MAGIC and ds + len(sdir) <= sym["tl_dir"] - ARENA
    if stockmeter: sdir = b"NONE" + sdir[4:]
    blob = blob[:ds] + sdir + blob[ds + len(sdir):]
    assert len(blob) == sym["blob_end"] - ARENA and sym["tl_strong"] == sym["blob_end"]
    blob += strong
    blob += bytes(-len(blob) % 4)
    blob += struct.pack("<I", -sum(struct.unpack(f"<{len(blob) // 4}I", blob)) & 0xFFFFFFFF)
    blob_ent = msf(dmy_lba) + struct.pack("<I", len(blob))
    patches = exe_patches(sym, glue, blob_ent, title, speed, heapcap, mparts, stockmeter)
    if "--ram" in argv:
        return patches, blob, sym
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, name + ".bin")
    shutil.copyfile(SRC_BIN, out)
    img = Img(out)
    exe_lba, exe_size = LBA["SLUS_007.93"]
    for at, orig in ((HOOK, HOOK_ORIG),) + (() if stockmeter else ((HEAPHOOK, HEAPHOOK_ORIG),)):
        assert hashlib.sha1(img.rbytes(exe_lba, at - EXE_BASE + EXE_HDR, 4 * orig[0])).hexdigest() == orig[1], "hook site not stock"
    for a, data in patches:
        img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
    if "--nologo" not in argv and not stockmeter:       # the two boot cards (file offsets in the EXE; never poked into RAM)
        exe = mshcards.disc_file("SLUS_007.93", SRC_BIN)              # stock executable: zero where the cards go
        for lo, hi in mshcards.ram_ranges():
            for a, data in patches:
                assert a + len(data) <= lo or a >= hi, f"EXE patch {a:08x} inside the boot-card area"
        for off, data in mshcards.disc_patches(exe, lambda n: mshcards.disc_file(n, SRC_BIN)):
            img.wbytes(exe_lba, off, data)
    for f, off, data in ([] if stockmeter else allpatches.overlay_patches(title, mparts[2] if mparts else None)):
        l, n = LBA[f]; img.wbytes(l, off, data)
        if f == "OPDEMO.BIN":       # the game loads the menu overlay from OPE.ARC (entry 0 at +0x34 = OPDEMO.BIN)
            la, na = LBA["OPE.ARC"]
            assert struct.unpack_from("<2I", img.rbytes(la, 4, 8)) == (0x34, n), "OPE.ARC entry 0 is not OPDEMO.BIN"
            img.wbytes(la, 0x34 + off, data)
    ach = None
    if "--ach" in argv:          # built-in achievements (games/mshvsf/tools/ach, docs/ACHIEVEMENTS.md)
        sys.path.insert(0, os.path.join(GAME, "tools", "ach"))
        import mshach
        ol, on = LBA["OPDEMO.BIN"]
        stock = open(SRC_BIN, "rb")
        def stock_ovl(a, n, _f=stock):
            out = bytearray()
            for i in range(n):
                o = a - mshach.OVL + i; _f.seek((ol + o // 2048) * 2352 + 24 + o % 2048); out += _f.read(1)
            return bytes(out)
        ach = mshach.parts(lambda a, n: img.rbytes(exe_lba, a - EXE_BASE + EXE_HDR, n), lambda o, n: img.rbytes(exe_lba, o, n), stock_ovl,
                           lambda a, n: img.rbytes(ol, a - mshach.OVL, n))      # the overlay as written (other patches applied)
        for a, data in ach["exe"]:
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "achievements patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        img.wbytes(exe_lba, 0x10, struct.pack("<I", ach["pc0"]))
        la, na = LBA["OPE.ARC"]
        for a, data in ach["ovl"]:
            img.wbytes(ol, a - mshach.OVL, data); img.wbytes(la, 0x34 + a - mshach.OVL, data)
        print("achievements: runtime %d bytes in %s (free %d), boot copy %08x" % (ach["info"]["image"], ach["info"]["segments"], ach["info"]["free"], mshach.COPY_AT))
    skip = None
    if "--noskip" not in argv:   # START skips the end of a match (games/mshvsf/tools/skip/mshskip.py, docs/ENGINE_NOTES.md); chains pc0
        sys.path.insert(0, os.path.join(GAME, "tools", "skip"))
        import mshskip
        assert struct.unpack("<I", img.rbytes(exe_lba, mshskip.HOOK_AT - EXE_BASE + EXE_HDR, 4))[0] == mshskip.HOOK_ORIG, "START skip hook word"
        prev_pc0 = struct.unpack("<I", img.rbytes(exe_lba, 0x10, 4))[0]
        skip = mshskip.link(mshskip.code(), prev_pc0)
        at, cp = skip["copy"]
        assert img.rbytes(exe_lba, at - EXE_BASE + EXE_HDR, len(cp)) == bytes(len(cp)), "START skip: copy area not zero"
        for a, data in [skip["copy"], skip["hook"]]:
            for b, d in patches:
                assert a + len(data) <= b or a >= b + len(d), "START skip patch %08x overlaps %08x" % (a, b)
            img.wbytes(exe_lba, a - EXE_BASE + EXE_HDR, data)
        img.wbytes(exe_lba, 0x10, struct.pack("<I", at))
        print("START skip: code %08x, copy %08x (%d bytes), hook %08x, pc0 -> %08x (was %08x)" % (mshskip.BASE, at, len(cp), skip["hook"][0], at, prev_pc0))
    if appended:                                     # form-1 data sectors after the last one (+150 empty: read-ahead)
        img.extend(img_end, appended + 150)
    img.wsectors(dmy_lba, blob)
    for key, data in items:
        img.wsectors(pos[key], data)
    img.fix()
    jd = dict(patches=[(a, d.hex()) for a, d in patches], sym=sym)
    if ach:      # tests poke the images first (ach_ram), then the hooks; the boot copy stub is never poked
        jd["ach_ram"] = [(a, d.hex()) for a, d in ach["ram"]]
        jd["patches"] += [(a, struct.pack("<I", w).hex()) for a, w in ach["hooks"]]      # (the boot copy writes them at boot)
        jd["ach_sym"] = {k: v for k, v in ach["info"]["sym"].items() if k.startswith(("ach_", "port_"))}
    if skip:     # tests: the code (kernel RAM) and the hook, poked like the other patches
        jd["patches"] += [(a, d.hex()) for a, d in (skip["ram"], skip["hook"])]
    json.dump(jd, open(os.path.join(BUILD, name + ".patches.json"), "w"))
    open(os.path.join(BUILD, name + ".cue"), "w").write(
        f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(f"blob {len(blob)} bytes, data {lba - dmy_lba} sectors of DMY.DAT + {appended} appended, {len(patches)} EXE patches -> {out}")
    if "--chd" in argv:
        chd = os.path.join(BUILD, name + ".chd")
        subprocess.check_call([toolenv.chdman(), "createcd", "-i", os.path.join(BUILD, name + ".cue"), "-o", chd, "-f"],
                              stdout=subprocess.DEVNULL)
        print("chd:", chd)
    return patches, blob, sym


if __name__ == "__main__":
    main(sys.argv)
