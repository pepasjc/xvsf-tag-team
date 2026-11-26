"""Build helpers of the MvC sound module for tools/tagload/mktag.py.

    extract(src_bin, lba)          stock sound files from the user's disc -> games/mvc/work/snd/disc (COMMON.SE, CHR*_0.SE,
                                   PLxx_11.A0 for the assist ids)
    objects(GCC, CF, out)          -> snd.o (linked into the loader blob)
    swap_image(GCC, CF, out)       -> (bytes of struct swd + swap code at SWAP_AT, symbols)
    exe_patches(GCC, CF, out)      -> [(addr, bytes)]: play entry 0x80086ae8 -> j sndstub; sndstub 0x80022350; sndrest 0x800178ec
    items()                        -> [(key, bytes)] the level files (every bank, every distinct level)
    directory(pos, msf, image)     -> bytes of struct sdir (snd.c) for the blob
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sndbank as S
SWAP_AT, STUB_AT, REST_AT, PLAY = 0x801fe800, 0x80022350, 0x800178ec, 0x80086ae8
MAGIC = b"SNDC"
SWMAGIC = 0x4d444e53
NSUB = 10
CF0 = ["-mips1", "-G0", "-mno-abicalls", "-fno-pic"]


def extract(src_bin, lba):
    os.makedirs(S.FILES, exist_ok=True)
    want = [n for n in lba if n == "COMMON.SE" or (n.startswith("CHR") and n.endswith("_0.SE")) or
            (n.startswith("PL") and n.endswith("_11.A0"))]
    with open(src_bin, "rb") as f:
        for n in want:
            p = os.path.join(S.FILES, n)
            if os.path.exists(p): continue
            l, size = lba[n][0], lba[n][1]
            b = bytearray()
            for i in range((size + 2047) // 2048):
                f.seek((l + i) * 2352 + 24); b += f.read(2048)
            open(p, "wb").write(bytes(b[:size]))


def objects(GCC, CF, out):
    subprocess.check_call([GCC + "gcc"] + CF + ["-Os", "-ffreestanding", "-msoft-float", "-Wall", f"-DSND_NL={S.NL}"]
                          + (["-DSPUSTORE", "-DSNDX"] if "--spustore" in sys.argv else [])
                          + (["-DSNDVFY"] if "--sndverify" in sys.argv else [])
                          + (["-DASSIST"] if "--assist" in sys.argv else [])
                          + (["-DSPSVERIFY"] if "--spsrdv" in sys.argv else [])
                          + (["-DSPSDRAIN"] if "--spsdrain" in sys.argv else [])
                          + (["-DSPSSENT"] if "--spssent" in sys.argv else []) + (["-DSPSRDDLY", "-DSPSN=\"%s\"" % os.environ.get("SPS_SPIN", "256")] if "--spsrddly" in sys.argv else [])
                          + (["-DVOLROW"] if "--voicevol" in sys.argv else []) + [
                                                "-c", os.path.join(HERE, "snd.c"), "-o", os.path.join(out, "snd.o")])
    return [os.path.join(out, "snd.o")]


def _syms(GCC, elf, cwd):
    sym = {}
    for l in subprocess.check_output([GCC + "nm", "-n", elf], cwd=cwd).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    return sym


def swap_image(GCC, CF, out):
    os.makedirs(out, exist_ok=True)
    subprocess.check_call([GCC + "gcc"] + CF0 + ["-Os", "-ffreestanding", "-Wall"] + (["-DSNDVFY"] if "--sndverify" in sys.argv else [])
                          + (["-DSPSSENT"] if "--spssent" in sys.argv else []) + (["-DSPSRDDLY", "-DSPSN=\"%s\"" % os.environ.get("SPS_SPIN", "256")] if "--spsrddly" in sys.argv else [])
                          + ["-c", os.path.join(HERE, "swap.c"), "-o", "swap.o"], cwd=out)
    subprocess.check_call([GCC + "gcc"] + CF0 + ["-c", os.path.join(HERE, "swentry.S"), "-o", "swentry.o"], cwd=out)
    open(os.path.join(out, "swap.ld"), "w").write(
        f"SECTIONS {{\n  .sw 0x{SWAP_AT:08x} : {{ *(.swd) . = ALIGN(4); *(.text.entry) *(.text) *(.text.*) *(.rodata*) *(.data*) *(.sdata*) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); }}\n"
        "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }\n}\n")
    subprocess.check_call([GCC + "ld", "-T", "swap.ld", "swap.o", "swentry.o", "-o", "swap.elf"], cwd=out)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".sw", "swap.elf", "swap.bin"], cwd=out)
    img = open(os.path.join(out, "swap.bin"), "rb").read()
    sym = _syms(GCC, "swap.elf", out)
    assert sym["sw"] == SWAP_AT and len(img) <= 1024 and SWAP_AT + len(img) <= 0x801fec00, len(img)
    return img + bytes(-len(img) % 4), sym


def exe_patches(GCC, CF, out):
    img, sym = swap_image(GCC, CF, out)
    subprocess.check_call([GCC + "gcc"] + CF0 + ["-c", os.path.join(HERE, "stubs.S"), "-o", "stubs.o"], cwd=out)
    open(os.path.join(out, "stubs.ld"), "w").write(
        f"SECTIONS {{\n  .stub 0x{STUB_AT:08x} : {{ *(.stub) }}\n  .rest 0x{REST_AT:08x} : {{ *(.rest) }}\n"
        "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }\n}\n")
    subprocess.check_call([GCC + "ld", "-T", "stubs.ld", "--defsym", f"MAGIC={SWMAGIC:#x}", "--defsym", f"SWENTRY={sym['swentry']:#x}",
                           "stubs.o", "-o", "stubs.elf"], cwd=out)
    st = {}
    for sec in (".stub", ".rest"):
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", sec, "stubs.elf", "stubs" + sec + ".bin"], cwd=out)
        st[sec] = open(os.path.join(out, "stubs" + sec + ".bin"), "rb").read()
    assert len(st[".stub"]) <= 68 and len(st[".rest"]) <= 72, (len(st[".stub"]), len(st[".rest"]))
    j = 0x08000000 | (STUB_AT >> 2) & 0x3ffffff
    return [(PLAY, struct.pack("<2I", j, 0)), (STUB_AT, st[".stub"]), (REST_AT, st[".rest"])], img


def items():
    out = []
    for name in S.bank_names():
        ls = S.levels(name)
        for L, bk in enumerate(ls):
            if L == 0 or bk.data != ls[L - 1].data:
                out.append((("snd", name, L), bk.data))
    return out


def subs():
    """assist ids per character: the ids of the stock partner bank (section 3 of PLxx_11.A0)"""
    out = {}
    for c in range(1, 0x17):
        p = os.path.join(S.FILES, "PL%02X_11.A0" % c)
        if not os.path.exists(p): out[c] = []; continue
        a = open(p, "rb").read(); n, = struct.unpack_from("<I", a)
        o, s = struct.unpack_from("<2I", a, 4 + 8 * (n - 1))
        ents, _ = S.parse(a[o:o + s])
        out[c] = [e["id"] for e in ents][:NSUB]
    return out


def directory(pos, msf, image, split=None):
    """struct sdir image; split = (msf bytes, ...) placeholder: SNDX layout -> (sdir, level table item)"""
    rec = b""
    for name in S.bank_names():
        ls = S.levels(name); last = None
        for L, bk in enumerate(ls):
            if ("snd", name, L) in pos: last = pos["snd", name, L]
            assert last is not None and bk.dsize % 16 == 0 and bk.n < 256
            rec += struct.unpack("<I", msf(last))[0].to_bytes(4, "little") + struct.pack("<HBB", bk.dsize >> 4, bk.n, 0)
    table = rec
    if split is not None:                            # SNDX: table = disc item, the struct holds its {msf, size}
        rec = split + struct.pack("<I", len(table))
    sb = subs()
    for c in range(0x17):
        ids = sb.get(c, []) + [0] * NSUB
        rec += struct.pack("<%dH" % NSUB, *ids[:NSUB])
    rec += bytes(-len(rec) % 4)
    sw = image + bytes(1024 - len(image))
    out = MAGIC + struct.pack("<I", len(image)) + rec + sw
    return (out, table) if split is not None else out
