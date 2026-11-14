"""Build the OPTIONAL 8 MB disc of the tag hack: build/<name>.bin/.cue (default name xvsf_ap8).

    python tools/mkap8disc.py [name] --ap8=work/ap/b8/xmvsfu [--keep]

The disc is the normal 2 MB build (tools/mktagdisc.py, unchanged and bit-identical up to this script's
additions) plus:
  * a boot stub in three more dead ranges of the EXE (tools/ap8/ap8boot.c) and the two battle-loader
    hook words redirected to it.  Without 8 MB of RAM the stub jumps to the 2 MB loader: same code, same files.
  * an extent APPENDED to the image (after the last sector of the original disc; the game reads by absolute
    position, not through the file system), in read order:
        module (MODSECT sectors, tools/ap8/ap8mod.c, runs at 0x80200000) | stock RLE effects file |
        per character 0..18: the PACKED BLOCK = raw deflate (zopfli when the Python module is there, else zlib level 9) of the character's block exactly as it sits in
            RAM: code file (P0 overlay + relocation table), sprite file, PLxx.AP8, PLxx.AD8, PLxx.HT8, each padded with zeros to 2048 bytes |
        then, as the fallback when a packed stream fails: per character the same three files plain
    sprite file = OUT/SP_PLxx.NSP of the restoration builder (tools/ap/build8.py) when the manifest lists the
    character, else the game's stock file.  All stock RLE: no XVM1/XVH1 on the 8 MB path.
    The module reads a packed block with ONE non-blocking CdRead into a scratch area above the arena and decodes it
    while the data is still arriving (tools/ap8/inflate.h); a block is accepted by its size and word sum.
The restored data is derived from the user's arcade ROMs: the output of this script must stay in build/.
"""
import os, sys, struct, subprocess, json, hashlib, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import mktagdisc as M
from mkdisc import fix_sector, BUILD
import region
assert region.REGION == "us", "the 8 MB build exists for the US disc only"

SRC = os.path.join(HERE, "ap8")
OBJ = os.path.join(BUILD, "ap8obj")
GCC = M.GCC
# dead ranges (tools/deadcode.py, break-tested with work/ap8/deadtest8.py), not used by any patch module
CHUNKS = {".chunkh": (0x8002d9c4, 0x8002daec), ".chunki": (0x8006f2e4, 0x8006f3e0), ".chunkj": (0x80019ae8, 0x80019bd4), ".chunkl": (0x80054704, 0x800547d4), ".chunkm": (0x8004e3e0, 0x8004e490)}
VERSION = "TAG HACK 1.2"                                # main-menu line (--version=TEXT); the 8 MB machine shows it with "  8MB" appended
SEL_AT, SEL_FILE = 0x8009bc38, "P/P4/SELECT.BIN"      # jal SPRLOAD(0x27, off) of the select screen -> selhook8
MENU_AT, MENU_FILE = 0x800987b8, "P/P4/OPDEMO.BIN"    # jr ra at the end of the main-menu text routine -> j menuhook
MOD, MODSECT, MOD_MAGIC = 0x80200000, 12, 0x384d5658         # module area 0x80200000-0x80206000; state 0x80206000, undo list +0x400, raw_dec +0x1000
STATEA = MOD + 2048 * MODSECT
OVL_BASE, EFFAREA = 0x80098000, STATEA + 0x1800
EFFHMAX = 400                                                   # pre-decode list of the effects set in the module table (ap8mod.c)
HOT8 = os.path.join(SRC, "hot8.json")                           # per-tile scores for the pre-decode order (work/speed/8mb/mkhot.py)
SLOTPTR, SLOTSIZE = 0x8005c65c, 5 * 2048 + 0x800               # shared-slot table pointers per set; bytes of extended tables per battle (4 characters + effects)
DT_ADDR, LT_ADDR = 0x807f0000, 0x807e0000      # decode tables: 2 x 32768 u16
R = lambda n: (n + 2047) & ~2047


def build(syms, version):
    """compile the boot stub and the module.  Nothing here depends on the content: the memory map goes into the module table."""
    os.makedirs(OBJ, exist_ok=True)
    cf = ["-mips1", "-G0", "-mno-abicalls", "-fno-pic"]
    defs = [f"-DMODWORDS={MODSECT * 512}", f'-DVERSION="{version}"', f"-DSTATEA=0x{STATEA:08x}u", f"-DEFFHMAX={EFFHMAX}"] + (["-DNOCACHE"] if os.environ.get("XV8_NOCACHE") else [])   # developers: no tile cache (A/B)
    for src, opt in (("ap8boot.c", "-Os"), ("ap8mod.c", "-Os")):      # size first; the decoder loop itself is O2 by attribute (inflate.h)
        subprocess.check_call([GCC + "gcc", opt, "-ffreestanding", "-msoft-float", "-fno-tree-loop-distribute-patterns", *cf, *defs,      # no memset/memcpy calls: there is no libc
                               "-c", os.path.join(SRC, src), "-o", os.path.join(OBJ, src[:-2] + ".o")])
    sdefs = [f"-DSTATEA=0x{STATEA:08x}", f"-DEFFHMAX={EFFHMAX}"]
    subprocess.check_call([GCC + "gcc", *cf, *sdefs, "-c", os.path.join(SRC, "ap8glue.S"), "-o", os.path.join(OBJ, "ap8glue.o")])
    subprocess.check_call([GCC + "gcc", *cf, *sdefs, "-DMODULE", "-c", os.path.join(SRC, "ap8glue.S"), "-o", os.path.join(OBJ, "ap8modhead.o")])
    defs = [f"--defsym={n}=0x{syms[n]:08x}" for n in ("effhook", "hook", "flushcache", "tl_dbg", "varload")]
    disc = "/DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) *(.bss) %s }"
    open(os.path.join(OBJ, "boot.ld"), "w").write("SECTIONS {\n" + "".join(
        f"  {s} 0x{a:08x} : {{ *({s}_head) *({s}) *({s}_data) {'*(.rodata*)' if s == '.chunkl' else ''} }}\n" for s, (a, e) in CHUNKS.items()) + "  " + disc % "" + "\n}\n")
    open(os.path.join(OBJ, "mod.ld"), "w").write(f"SECTIONS {{\n  .mod 0x{MOD:08x} : {{ *(.modhead) *(.text) *(.text.*) *(.rodata*) *(.data*) }}\n  " + disc % "*(.chunk*)" + "\n}\n")
    subprocess.check_call([GCC + "ld", "-T", "boot.ld", *defs, "ap8glue.o", "ap8boot.o", "-o", "boot.elf"], cwd=OBJ)
    subprocess.check_call([GCC + "ld", "-T", "mod.ld", *defs, "ap8modhead.o", "ap8mod.o", "-o", "mod.elf"], cwd=OBJ)
    out = {}
    for s in CHUNKS:
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", s, "boot.elf", "boot" + s + ".bin"], cwd=OBJ)
        out[s] = open(os.path.join(OBJ, "boot" + s + ".bin"), "rb").read()
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".mod", "mod.elf", "mod.bin"], cwd=OBJ)
    sym = {}
    for elf in ("boot.elf", "mod.elf"):
        for l in subprocess.check_output([GCC + "nm", "-n", elf], cwd=OBJ).decode().splitlines():
            if len(l.split()) == 3: sym[l.split()[2]] = int(l.split()[0], 16) & 0xFFFFFFFF
    open(os.path.join(OBJ, "ap8.sym"), "w").write("".join(f"{v:08x} {k}\n" for k, v in sorted(sym.items(), key=lambda x: x[1])))
    return out, open(os.path.join(OBJ, "mod.bin"), "rb").read(), sym


_HOT = None
def _hot():
    global _HOT
    if _HOT is None: _HOT = json.load(open(HOT8)) if os.path.exists(HOT8) else {}
    return _HOT


def _order(sfile, scores):
    """every tile of a sprite file, highest score first (then tile index): [(tile, score)]"""
    h = struct.unpack_from("<4I", sfile)
    n = (h[2] - h[1]) // 4
    return sorted(((t, min(65535, int(scores.get(str(t), 0)))) for t in range(n)), key=lambda x: (-x[1], x[0]))


def ht8(c, spr):
    """PLxx.HT8: the order in which rawsetup (ap8mod.c) pre-decodes the character's tiles at the end of a battle load"""
    o = _order(spr, _hot().get("PL%02X" % c, {}))
    return struct.pack("<2I", 0x01385448, len(o)) + b"".join(struct.pack("<I", t | s << 16) for t, s in o)


def effhot(eff):
    """module table: u32 n + EFFHMAX entries, the effects set's pre-decode order (stock SP_EFF1 tiles)"""
    o = _order(eff, _hot().get("EFF", {}))[:EFFHMAX]
    return struct.pack("<I", len(o)) + b"".join(struct.pack("<I", t | s << 16) for t, s in o) + bytes(4 * (EFFHMAX - len(o)))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = args[0] if args else "xvsf_ap8e"
    ap = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--ap8=")]
    assert ap, "--ap8=DIR (output of tools/ap/build8.py) is required"
    apdir = os.path.abspath(ap[0])
    manifest = json.load(open(os.path.join(apdir, "manifest.json")))
    man, mansel, mansel2 = manifest["chars"], manifest.get("select"), manifest.get("select2")
    out = os.path.join(BUILD, name + ".bin")
    # 1. the 2 MB build, untouched
    argv = sys.argv; sys.argv = [argv[0], name] + [a for a in argv if a in ("--logo", "--nopad", "--nopal", "--noai", "--nohud", "--nobgm", "--norank", "--nobal", "--nosound")]; M.main(); sys.argv = argv     # --logo: boot card, see tools/logopatch.py
    base_sha = hashlib.sha1(open(out, "rb").read()).hexdigest()
    print("2 MB base image sha1", base_sha)
    syms = M.symbols()
    orig = open(region.EXEPATH, "rb").read()
    lmap = json.load(open(region.LMAP))
    exe_lba, exe_size = lmap[region.EXE]
    # 2. files of the extent
    restored = {}
    for k, m in man.items():
        c = int(k, 16)
        nsp = open(os.path.join(apdir, m["nsp"]), "rb").read(); a8 = open(os.path.join(apdir, m["ap8"]), "rb").read()
        assert hashlib.sha1(nsp).hexdigest() == m["nsp_sha1"] and hashlib.sha1(a8).hexdigest() == m["ap8_sha1"], f"{k}: files do not match the manifest"
        ov = open(os.path.join(region.FILES, "P", "P0", "PL%02X_10.BIN" % c), "rb").read()
        assert hashlib.sha1(ov).hexdigest() == m["overlay_sha1"], f"{k}: overlay differs from the one the patch was made for"
        assert a8[:4] == b"AP8\x01" and a8[4] == c and ov[m["blob_offset"]:][:16] == a8[24:40] and len(nsp) % 4 == 0
        frames, npatch = struct.unpack_from("<2I", a8, 16)
        assert len(a8) == 40 + 4 * frames + 4 * npatch
        stock = open(os.path.join(M.RLEDIR, "SP_PL%02X.NSP" % c), "rb").read()
        h = struct.unpack_from("<4I", nsp)
        assert nsp[h[2]:h[2] + 4] not in (b"XVM1", b"XVH1"), "sec2 starts with a codec magic"
        ad = b""
        if m.get("direct") and m["direct"].get("ad8"):          # direct-frame-id animations (SPEC section 12)
            ad = open(os.path.join(apdir, m["direct"]["ad8"]), "rb").read(); npd = struct.unpack_from("<I", ad, 12)[0]
            assert ad[:4] == b"AD8\x01" and ad[4] == c and struct.unpack_from("<I", ad, 8)[0] == len(ov) and len(ad) == 16 + 12 * npd, f"{k}: bad AD8"
            for i in range(npd):
                o, old, new = struct.unpack_from("<3I", ad, 16 + 12 * i)
                assert struct.unpack_from("<I", ov, o)[0] == old, f"{k}: AD8 record {i} does not match the overlay"
        restored[c] = (nsp, a8, ad)
    import zlib
    try: import zopfli.zlib as zopfli_zlib
    except ImportError: zopfli_zlib = None
    print("packer:", "zopfli (15 iterations)" if zopfli_zlib else "zlib level 9 (install the zopfli module for about 4 % smaller blocks)")
    items = [("mod", bytes(2048 * MODSECT), "8 MB loader module"), ("eff", open(M.EFFSTOCK, "rb").read(), "SP_EFF1 (stock RLE)")]
    # restored effects file (SPEC section 17): --eff=DIR, an add-on directory of tools/ap/eff2build.py (SP_EFF1.NSP, EFF1.AE8, manifest.json)
    effdir = ([os.path.abspath(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--eff=")] or [None])[0]
    effr = effae = b""; effslots = 0
    if effdir:
        me = json.load(open(os.path.join(effdir, "manifest.json")))
        effr = open(os.path.join(effdir, me["nsp"]), "rb").read(); effae = open(os.path.join(effdir, me["ae8"]), "rb").read()
        assert hashlib.sha1(effr).hexdigest() == me["nsp_sha1"] and hashlib.sha1(effae).hexdigest() == me["ae8_sha1"], "effects files do not match their manifest"
        npe = struct.unpack_from("<I", effae, 12)[0]
        assert effae[:4] == b"AE8\x01" and effae[4] == 0x26 and len(effae) == 32 + 12 * npe and npe <= 250 and len(effr) % 4 == 0
        assert struct.unpack_from("<I", effae, 8)[0] == len(orig) and effae[16:32] == hashlib.sha1(orig).digest()[:16], "EFF1.AE8 was made for another executable"
        for i in range(npe):
            ad, old, new = struct.unpack_from("<3I", effae, 32 + 12 * i)
            assert 0x80091afc <= ad < 0x80092844 and ad % 4 == 0 and struct.unpack_from("<I", orig, ad - M.EXE_BASE + M.EXE_HDR)[0] == old, f"EFF1.AE8 record {i}"
        if effae[5] & 1: effslots = 255
        test = ([a.split("=", 1)[1] for a in sys.argv if a.startswith("--eff-test=")] or [None])[0]      # developers: validation tests
        if test == "record":                                    # one record with a wrong stock id, sums right -> efferr 4, nothing written
            o = 32 + 12 * 40 + 4; effae = effae[:o] + struct.pack("<I", struct.unpack_from("<I", effae, o)[0] ^ 0x10000) + effae[o + 4:]
        effr_disc = effr
        if test == "trunc":                                     # the second half of the file is missing on the disc -> efferr 2 (sums)
            effr_disc = effr[:len(effr) // 2] + bytes(len(effr) - len(effr) // 2)
        items += [("effr", effr_disc, f"RESTORED SP_EFF1 ({len(effr)} bytes)"), ("effae", effae, f"EFF1.AE8 ({npe} patches, slot table {'required' if effslots else 'not needed'})")]

    selsize = 0
    if mansel:                                                  # restored select screen (SPEC section 10)
        sn = open(os.path.join(apdir, mansel["nsp"]), "rb").read(); sa = open(os.path.join(apdir, mansel["ap8"]), "rb").read()
        assert hashlib.sha1(sn).hexdigest() == mansel["nsp_sha1"] and hashlib.sha1(sa).hexdigest() == mansel["ap8_sha1"], "select files do not match the manifest"
        selbin = open(os.path.join(region.FILES, "P", "P4", "SELECT.BIN"), "rb").read()
        npat = struct.unpack_from("<I", sa, 8)[0]
        assert sa[:4] == b"AS8\x01" and struct.unpack_from("<I", sa, 4)[0] == len(selbin) and sa[12:28] == hashlib.sha1(selbin).digest()[:16] and len(sa) == 28 + 8 * npat
        assert len(sn) % 4 == 0
        items += [("sel0", sn, f"RESTORED SP_SEL0 ({len(sn)} bytes)"), ("selap", sa, f"SELECT.AP8 ({npat} patches)")]
        selsize = len(sn)
    wsum = lambda d: sum(struct.unpack(f"<{(len(d) + 15) // 16 * 4}I", d + bytes(-len(d) % 16))) & 0xFFFFFFFF
    sel2sum = selap2sum = 0
    if mansel2:                                                 # second select-screen sprite set (SPEC section 15); needs section 10
        assert mansel, "select2 without select"
        s2 = open(os.path.join(apdir, mansel2["nsp"]), "rb").read(); a2 = open(os.path.join(apdir, mansel2["ap8"]), "rb").read()
        assert hashlib.sha1(s2).hexdigest() == mansel2["nsp_sha1"] and hashlib.sha1(a2).hexdigest() == mansel2["ap8_sha1"], "select2 files do not match the manifest"
        np2, nr2, ns2, nst = struct.unpack_from("<4I", a2, 28)
        assert a2[:4] == b"AS8\x02" and struct.unpack_from("<I", a2, 4)[0] == len(selbin) and a2[8:24] == hashlib.sha1(selbin).digest()[:16] and a2[24] == 0x39 and a2[25] == 0x27
        assert len(a2) == 44 + 8 * np2 + 4 * nr2 + 4 * ns2 + nst and len(s2) % 4 == 0 and len(a2) % 4 == 0
        sites = struct.unpack_from(f"<{ns2}I", a2, 44 + 8 * np2 + 4 * nr2)
        assert all(struct.unpack_from("<I", selbin, o)[0] == 0x0c00c375 for o in sites), "a call site of SELECT2.AP8 is not jal 0x80030dd4"
        # it lives where the game's own SP_SEL0 would have been loaded (free on the 8 MB path): must fit that file's size
        assert R(len(s2)) + R(len(a2)) <= lmap["A/A2/SP_SEL0.NSP"][1], "the second select set does not fit the place of the stock SP_SEL0"
        test = ([a.split("=", 1)[1] for a in sys.argv if a.startswith("--sel2-test=")] or [None])[0]      # developers: validation tests
        sel2sum, selap2sum = wsum(s2), wsum(a2)
        if test == "stub": a2 = a2[:-8] + bytes([a2[-8] ^ 0x5a]) + a2[-7:]            # damaged stub, sum not updated -> error 1
        if test == "site":                                                              # one call site that is not a jal, sum updated -> error 4
            o = 44 + 8 * np2 + 4 * nr2 + 4 * 5; a2 = a2[:o] + struct.pack("<I", sites[5] + 4) + a2[o + 4:]; selap2sum = wsum(a2)
        if test == "nsp": s2 = s2[:5000] + bytes([s2[5000] ^ 0x11]) + s2[5001:]         # damaged sprite file -> error 6
        items += [("sel2", s2, f"SP_SEL2, second select-screen sprite set ({len(s2)} bytes)"), ("selap2", a2, f"SELECT2.AP8 ({np2} patches, {ns2} call sites, stub {nst} bytes)")]
    need, plain, psum = [], [], []
    padr = lambda d: d + bytes(R(len(d)) - len(d))
    for c in range(19):
        cf = M.code_file(11 if c == 18 else c)
        spr, a8, ad = restored.get(c, (open(os.path.join(M.RLEDIR, "SP_PL%02X.NSP" % c), "rb").read(), b"", b""))
        ht = ht8(c, spr)
        img = padr(cf[0]) + padr(spr) + padr(a8) + padr(ad) + padr(ht)      # the block as the module lays it out
        z = zlib.compressobj(9, zlib.DEFLATED, -15, 9); pk = z.compress(img) + z.flush()
        if zopfli_zlib: pk = min(pk, zopfli_zlib.compress(img, numiterations=15)[2:-4], key=len)     # same format, about 4 % smaller
        assert zlib.decompress(pk, -15) == img
        items.append((("pack", c), pk, f"char {c:2d} packed block ({'RESTORED' if c in restored else 'stock RLE'}): {len(img)} -> {len(pk)} bytes ({100 * len(pk) / len(img):.1f}%)"))
        plain.append((("code", c), cf[0], f"char {c:2d} code PL{11 if c == 18 else c:02X} + relocation table (fallback)"))
        plain.append((("spr", c), spr, f"char {c:2d} {'RESTORED' if c in restored else 'stock RLE'} SP_PL{c:02X} (fallback)"))
        if a8: plain.append((("ap8", c), a8, f"char {c:2d} PL{c:02X}.AP8 (fallback)"))
        if ad: plain.append((("ad8", c), ad, f"char {c:2d} PL{c:02X}.AD8 (fallback)"))
        plain.append((("ht8", c), ht, f"char {c:2d} PL{c:02X}.HT8, pre-decode order of {len(ht) // 4 - 2} tiles (fallback)"))
        need.append(len(img)); psum.append(sum(struct.unpack(f"<{len(img) // 4}I", img)) & 0xFFFFFFFF)
    items += plain
    import sndpatch                                         # 1.2 sound banks: the two 8 MB levels (lossless + arcade samples,
    snd8items, snd8ref, snd8ex = [], {}, {}                 #  and the same at the arcade rate) behind the other files
    if sndpatch.enabled():
        sys.path.insert(0, os.path.join(HERE, "ap"))
        import snd8build
        sdir = ([os.path.abspath(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--snd8=")] or [None])[0]
        lv8, snd8ex = sndpatch.level8(snd8build.load(sdir) if sdir else {})
        b0 = sndpatch.banks(); seen = {}
        with open(out, "rb") as f0:                              # the room in the 2 MB image's sound region (its directory's tail)
            def rs(l):
                f0.seek(l * 2352 + 24); return f0.read(2048)
            e0 = sndpatch.code(syms["flushcache"])[1]["sndent"] - M.EXE_BASE + M.EXE_HDR
            se = rs(lmap[region.EXE][0] + e0 // 2048)[e0 % 2048:][:8]
            assert len(se) == 8
            bcd = lambda x: (x >> 4) * 10 + (x & 15)
            dl = (bcd(se[0]) * 60 + bcd(se[1])) * 75 + bcd(se[2]) - 150; dz = struct.unpack_from("<I", se, 4)[0]
            tail = b"".join(rs(dl + i) for i in range((dz + 2047) // 2048))[dz - 8:dz]
            rlba = (bcd(tail[0]) * 60 + bcd(tail[1])) * 75 + bcd(tail[2]) - 150; rsec = struct.unpack_from("<I", tail, 4)[0] // 2048
        snd8room = []                                          # (lba, data, label) written into that room
        for l in (sndpatch.L8, sndpatch.LA):                   # level 4 first: every 8 MB battle of a team with these banks reads it
            for b in [sndpatch.XSB] + list(range(18)):
                files = lv8[(l, b)]; ref = [None, None]
                for kind in (0, 1):
                    if files[kind] == b0[(0, b)][kind]: continue      # the level-0 file of the 2 MB image
                    h = hashlib.sha1(files[kind]).digest()
                    if h not in seen:
                        lab = "sound 8 MB level %d %s %s (%d bytes)" % (l, "XS_MAIN" if b == sndpatch.XSB else "CHR%02X" % b, ("VH", "VB")[kind], len(files[kind]))
                        n = (len(files[kind]) + 2047) // 2048
                        if n <= rsec:
                            seen[h] = ("room", rlba, len(files[kind])); snd8room.append((rlba, files[kind], lab + " (sound region)"))
                            rlba += n; rsec -= n
                        else:
                            seen[h] = ("snd8", l, b, kind); snd8items.append((seen[h], files[kind], lab))
                    ref[kind] = seen[h]
                snd8ref[(l, b)] = ref
        items += snd8items
    maxpack = max(len(d) for k, d, l in items if k[0] == "pack")
    ARENA_END = LT_ADDR - R(maxpack) - 0x800
    eff = open(M.EFFSTOCK, "rb").read()
    SLOTAREA = EFFAREA + max(R(len(eff)), R(len(effr)) + R(len(effae))) + 0x800                    # effects file (set 0x26) resident below the blocks
    ARENA = SLOTAREA + SLOTSIZE                                 # then the extended shared-slot tables
    sel0 = max(lmap["A/A2/SP_SEL0.NSP"][1], selsize)
    assert R(sel0) + 0x800 <= 0x80800000 - ARENA_END, "the select-screen sprite file (+ SELECT.AP8) does not fit the scratch/select area"
    worst = sum(sorted(need)[-4:])
    assert worst <= ARENA_END - ARENA, f"four largest blocks {worst} do not fit the arena {ARENA_END - ARENA}"
    print(f"arena {ARENA_END - ARENA} bytes (to {ARENA_END:08x}); four largest blocks {worst} bytes; largest block {max(need)}; scratch for the largest packed block {R(maxpack)}")
    ver = ([a.split('=', 1)[1] for a in sys.argv if a.startswith('--version=')] or [VERSION])[0]
    # shared VRAM slot tables: the game's pointers, and extended sizes when asked (--slots=SET:N,... ; SET = character number
    # or 38 for the effects set; content that needs more slots than the stock table has - work/ap/SPEC.md)
    o = SLOTPTR - M.EXE_BASE + M.EXE_HDR
    ptr = struct.unpack_from("<60I", orig, o)
    slotstock = list(ptr[:39])
    slots = [0] * 20
    slots[19] = effslots                                        # the effects set's table: always the first of the slot area
    for k, m in man.items():                                    # content with shared-slot frames above the stock table (SPEC 11a)
        if m.get("slot_table"): slots[int(k, 16)] = 255
    for a in sys.argv:
        if a.startswith("--slots="):
            for item in a[8:].split(","):
                k, n = (int(x) for x in item.split(":")); slots[19 if k == 0x26 else k] = n
    assert 8 * (sum(sorted(n + 1 for n in slots[:19] if n)[-4:]) + (slots[19] + 1 if slots[19] else 0)) <= SLOTSIZE, "extended slot tables do not fit"
    if any(slots): print("extended shared-slot tables:", {('effects' if k == 19 else k): n for k, n in enumerate(slots) if n})
    chunks, mod, sym = build(syms, ver)
    # file cache core, AUX.PAK (tools/ap8/ap8mod.c mod_loadfile): files every select / win / VS screen or fight load reads
    # again, taken from THIS image through its own file table (what LOADFILE reads: whole sectors), raw deflate.  Resident
    # in AUXAREA between the slot tables and the arena, out of the room the four largest characters leave; entries are
    # dropped from the end of the list if it ever does not fit.
    AUXCORE = [269, 223, 1, 224, 146, 160, 268]                 # PLFACE.TEX, SE/VH2/XS_MAIN.VH, P/P4/SELECT.BIN, SE/VH2/SELECT.VH,
                                                                # A/A2/SP_SEL1.NSP, SCR0/DEB.SCR, KANJI.TEX (file table indices, USA)
    # KANJI.TEX is read after the select sprites fill the scratch area: its decode tables (128 KB) then go behind the
    # second select set in the place of the stock SP_SEL0
    assert R(len(s2) if mansel2 else 0) + R(len(a2) if mansel2 else 0) + 0x20000 <= lmap["A/A2/SP_SEL0.NSP"][1], "no room for the decode tables at the select screen"
    worst = sum(sorted(need)[-4:])
    with open(out, "rb") as f:
        def rd(lba, n):
            r = b""
            for i in range((n + 2047) // 2048): f.seek((lba + i) * 2352 + 24); r += f.read(2048)
            return r[:n]
        exe = rd(lmap["SLUS_006.27"][0], lmap["SLUS_006.27"][1])
        bcd = lambda x: (x >> 4) * 10 + (x & 15)
        auxe = []
        for idx in AUXCORE:
            o = M.FTABLE - M.EXE_BASE + M.EXE_HDR + 8 * idx
            m, size = exe[o:o + 3], struct.unpack_from("<I", exe, o + 4)[0]
            data = rd((bcd(m[0]) * 60 + bcd(m[1])) * 75 + bcd(m[2]) - 150, R(size))
            if idx == 1:                                        # SELECT.BIN: the select hook goes in below (file_patch) - same here
                o2 = SEL_AT - OVL_BASE; jl = lambda t: struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))
                assert data[o2:o2 + 4] == jl(0x80053f78); data = data[:o2] + jl(sym["selhook8"]) + data[o2 + 4:]
            z = zlib.compressobj(9, zlib.DEFLATED, -15, 9); pk = z.compress(data) + z.flush()
            if zopfli_zlib: pk = min(pk, zopfli_zlib.compress(data, numiterations=15)[2:-4], key=len)
            assert zlib.decompress(pk, -15) == data
            auxe.append((idx, m[0] | m[1] << 8 | m[2] << 16, size, pk))
    while True:
        hdr = 8 + 20 * len(auxe); off = hdr; body = b""; tab = b""
        for idx, mm, size, pk in auxe:
            tab += struct.pack("<5I", idx, mm, size, off, len(pk)); body += pk + bytes(-len(pk) % 4); off = hdr + len(body)
        auxpack = struct.pack("<2I", 0x58554158, len(auxe)) + tab + body if auxe else b""
        if R(len(auxpack)) + worst <= ARENA_END - ARENA: break
        auxe.pop()
    AUXAREA = ARENA
    ARENA = AUXAREA + R(len(auxpack))
    auxsum = wsum(auxpack) if auxpack else 0
    if auxpack:
        items.append(("auxp", auxpack, f"AUX.PAK, file cache core: {len(auxe)} files, {sum(R(e[2]) for e in auxe)} -> {len(auxpack)} bytes"))
    print(f"file cache core: {len(auxe)} of {len(AUXCORE)} files, {len(auxpack)} bytes at {AUXAREA:08x}")
    with open(out, "r+b") as f:
        f.seek(0, 2); end = f.tell() // 2352
        assert f.tell() % 2352 == 0
        f.seek((end - 1) * 2352); last = f.read(2352)
        dmy_lba = lmap["DMY.DAT"][0]
        f.seek(dmy_lba * 2352); tmpl = f.read(24)                # sync, header, subheader of an empty mode 2 form 1 data sector
        assert tmpl[15] == 2 and not tmpl[18] & 0x20
        pos = {}; lba = end
        for key, data, label in items:
            pos[key] = lba; lba += (len(data) + 2047) // 2048
        ent = lambda key: (M.msf(pos[key]) + struct.pack("<I", len(dict((k, d) for k, d, l in items)[key]))) if key in pos else bytes(8)
        size = {k: len(d) for k, d, l in items}
        ent = lambda key: (M.msf(pos[key]) + struct.pack("<I", size[key])) if key in pos else bytes(8)
        # module: tables, magic, checksum
        T = sym["T"] - MOD
        assert (sym["T"] - M.FTABLE) % 8 == 0 and (sym["modent"] - M.FTABLE) % 8 == 0 and mod[T:T + 102 * 8 + 76 + 196 + 28 + 20 + 19 * 8 + 4 + 4 * EFFHMAX] == bytes(102 * 8 + 76 + 196 + 28 + 20 + 19 * 8 + 4 + 4 * EFFHMAX)
        tab = b"".join(ent(("code", c)) for c in range(19)) + b"".join(ent(("spr", c)) for c in range(19)) + b"".join(ent(("ap8", c)) for c in range(19)) + b"".join(ent(("ad8", c)) for c in range(19)) + ent("eff") + ent("sel0") + ent("selap") + ent("sel2") + ent("selap2") + ent("effr") + ent("effae") + b"".join(ent(("pack", c)) for c in range(19)) + struct.pack("<19I", *psum) + struct.pack("<39I", *slotstock) + struct.pack("<20H", *slots) + struct.pack("<7I", ARENA, ARENA_END, SLOTAREA, sel2sum, selap2sum, wsum(effr) if effr else 0, wsum(effae) if effae else 0) + struct.pack("<I", 0) + ent("auxp") + struct.pack("<2I", auxsum, AUXAREA) + b"".join(ent(("ht8", c)) for c in range(19)) + effhot(eff)
        assert len(tab) == 102 * 8 + 76 + 196 + 28 + 20 + 19 * 8 + 4 + 4 * EFFHMAX
        mod = mod[:T] + tab + mod[T + len(tab):]
        assert sym["raw_end"] - sym["raw_dec"] <= 0x1f0, "raw_dec does not fit RUNAT..TRAMP"
        assert len(mod) <= 2048 * MODSECT - 8, f"module too big: {len(mod)}"
        print(f"module {len(mod)} bytes of {2048 * MODSECT - 8}")
        mod += bytes(2048 * MODSECT - 8 - len(mod))
        mod += struct.pack("<2I", MOD_MAGIC, sum(struct.unpack(f"<{len(mod) // 4}I", mod)) & 0xFFFFFFFF)     # sum of the words before the magic
        items[0] = ("mod", mod, items[0][2])
        b = lambda x: (x // 10) << 4 | x % 10
        for key, data, label in items:
            nsec = (len(data) + 2047) // 2048
            pad = data + bytes(nsec * 2048 - len(data))
            for i in range(nsec):
                l = pos[key] + i + 150
                sec = bytearray(tmpl[:12] + bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 2]) + tmpl[16:24] + pad[i * 2048:(i + 1) * 2048] + bytes(280))
                fix_sector(sec)
                f.seek((pos[key] + i) * 2352); f.write(sec)
            print(f"{label}: {len(data)} bytes at lba {pos[key]}, {nsec} sectors")
        if "--logo" in argv:                                    # release layout: never end the disc on data (read-ahead of some players)
            for i in range(150):
                l = lba + i + 150
                sec = bytearray(tmpl[:12] + bytes([b(l // 4500), b(l // 75 % 60), b(l % 75), 2]) + tmpl[16:24] + bytes(2048 + 280))
                fix_sector(sec); f.seek((lba + i) * 2352); f.write(sec)
            print(f"150 empty sectors after the last file (lba {lba}..{lba + 149})")
        print(f"appended {lba - end} sectors ({(lba - end) * 2352 / 1048576:.1f} MB): image now {lba} sectors")
        # 3. EXE: stub chunks + the two hook words
        touched = set()
        def exe_write(addr, data):
            for i in range(len(data)):
                o = addr - M.EXE_BASE + M.EXE_HDR + i
                f.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048); f.write(data[i:i + 1]); touched.add(exe_lba + o // 2048)
        def exe_read(addr, n):
            r = bytearray()
            for i in range(n):
                o = addr - M.EXE_BASE + M.EXE_HDR + i
                f.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048); r += f.read(1)
            return bytes(r)
        jal = lambda t: struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))
        def rd_sec(l):
            f.seek(l * 2352 + 24); return f.read(2048)
        ent8 = lambda key: (M.msf(key[1]) + struct.pack("<I", key[2])) if key[0] == "room" else (M.msf(pos[key]) + struct.pack("<I", size[key]))
        for s, (a, e) in CHUNKS.items():
            d = chunks[s]
            assert a + len(d) <= e, f"{s} too big: {len(d)} > {e - a}"
            assert exe_read(a, e - a) == orig[a - M.EXE_BASE + M.EXE_HDR:e - M.EXE_BASE + M.EXE_HDR], f"{s}: range is not the original code any more"
            if a <= sym["modent"] < a + len(d):
                o = sym["modent"] - a; assert d[o:o + 8] == bytes(8)
                d = d[:o] + ent("mod") + d[o + 8:]
            exe_write(a, d); print(f"exe patch (ap8 stub {s}) {a:08x}-{a + len(d):08x} {len(d)} bytes of {e - a}")
        assert exe_read(M.HOOK_AT, 4) == jal(syms["glue"]) and exe_read(M.EFFHOOK_AT, 4) == jal(syms["effglue"])
        exe_write(M.HOOK_AT, jal(sym["glue8"])); exe_write(M.EFFHOOK_AT, jal(sym["effglue8"]))
        def file_patch(path, addr, old, new):                    # one word of an overlay file on the disc
            o = addr - OVL_BASE; l = lmap[path][0] + o // 2048
            f.seek(l * 2352 + 24 + o % 2048); assert f.read(4) == old, f"{path}+{o:x}: unexpected code"
            f.seek(l * 2352 + 24 + o % 2048); f.write(new); touched.add(l)
            print(f"overlay patch {path} {addr:08x}: {old.hex()} -> {new.hex()}")
        if sndpatch.enabled():                                  # 1.2 sound banks: the 8 MB decision asks ap8ready() too;
            ssym = sndpatch.code(syms["flushcache"])[1]         #  the directory gets the 8 MB levels' entries and lists
            a8 = ssym["ap8fn"]
            assert exe_read(a8, 4) == bytes(4), "sound: ap8fn already set"
            exe_write(a8, struct.pack("<I", sym["ap8ready"])); print(f"sound: ap8fn {a8:08x} = ap8ready {sym['ap8ready']:08x}")
            se = exe_read(ssym["sndent"], 8)
            bcd = lambda x: (x >> 4) * 10 + (x & 15)
            dlba = (bcd(se[0]) * 60 + bcd(se[1])) * 75 + bcd(se[2]) - 150; dsize = struct.unpack_from("<I", se, 4)[0]
            old_dir = b"".join(rd_sec(dlba + i) for i in range((dsize + 2047) // 2048))[:dsize]
            ent = {}
            for l in range(sndpatch.NLEV):
                for b in range(sndpatch.NB):
                    o = sndpatch.ENTOFF + (l * sndpatch.NB + b) * 16
                    e0 = sndpatch.ENTOFF + b * 16
                    ref = snd8ref.get((l, b))
                    if ref is None: ent[(l, b)] = (old_dir[o:o + 8], old_dir[o + 8:o + 16])
                    else: ent[(l, b)] = tuple(old_dir[e0 + 8 * k:e0 + 8 * k + 8] if ref[k] is None else ent8(ref[k]) for k in (0, 1))
            new_dir = sndpatch.dir_sector(ent, sndpatch.code(syms["flushcache"])[2], sndpatch.lists(snd8ex), sndpatch.stash2())
            new_dir = new_dir[:dsize - 8] + old_dir[dsize - 8:]
            assert len(new_dir) == dsize
            for lba0, data, lab in snd8room:
                pad = data + bytes(-len(data) % 2048)
                for i in range(len(pad) // 2048):
                    f.seek((lba0 + i) * 2352 + 24); assert not any(f.read(2048)), "sound: the room is not empty"
                    f.seek((lba0 + i) * 2352 + 24); f.write(pad[2048 * i:2048 * i + 2048]); touched.add(lba0 + i)
                print(f"{lab}: {len(data)} bytes at lba {lba0}")
            for i in range(dsize // 2048):
                f.seek((dlba + i) * 2352 + 24); f.write(new_dir[2048 * i:2048 * i + 2048]); touched.add(dlba + i)
            print(f"sound: directory at lba {dlba}: 8 MB levels {sndpatch.L8}/{sndpatch.LA}, {len(snd8items)} files, extra ids {({hex(b): [hex(i) for i in v] for b, v in snd8ex.items()})}")
        file_patch(SEL_FILE, SEL_AT, jal(0x80053f78), jal(sym["selhook8"]))
        file_patch(MENU_FILE, MENU_AT, struct.pack("<I", 0x03e00008), struct.pack("<I", 0x08000000 | (sym["menuhook"] >> 2 & 0x3ffffff)))
        assert exe_read(syms["tl_dbg"] + 12, 4) == orig[syms["tl_dbg"] + 12 - M.EXE_BASE + M.EXE_HDR:][:4]      # the flag byte: unused dead code so far
        for sec in sorted(touched):
            f.seek(sec * 2352); raw = bytearray(f.read(2352)); fix_sector(raw); f.seek(sec * 2352); f.write(raw)
    json.dump(dict(base_sha1=base_sha, end=end, pos={(k if isinstance(k, str) else f"{k[0]}{k[1]}"): v for k, v in pos.items()},
                   size={(k if isinstance(k, str) else f"{k[0]}{k[1]}"): v for k, v in size.items()}, restored=sorted(restored), sym=sym, need=need, arena=ARENA, arena_end=ARENA_END, effarea=EFFAREA, version=ver, apdir=apdir, slots=slots, slotstock=slotstock, slotarea=SLOTAREA, select=bool(mansel), select2=bool(mansel2), effdir=effdir),
              open(os.path.join(BUILD, name + "_ap8.json"), "w"), indent=1)
    print("->", out)


if __name__ == "__main__":
    main()
