"""Build helpers of the sound module for the disc builders (tools/tagload/mktag.py, tools/ap8/mkap8.py).

    objects(GCC, CF, outdir)        -> [snd.o]   (compiled with the loader blob)
    hook(GCC, CF, outdir)           -> the unload hook (unlhook.S linked at 0x801ff000), <= 30 words
    directory(chars_pos, ...)       -> bytes of struct sdir (snd.c) for the blob
    items()                         -> [(key, bytes)] bank level files for the disc (levels whose bytes differ from
                                       level 0, which is section 3 of our PLxx_10.A0 copy)
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sndbank as S
HOOKAT = 0x801ff000
MAGIC = b"SND1"


def objects(GCC, CF, out):
    subprocess.check_call([GCC + "gcc"] + CF + ["-Os", "-ffreestanding", "-msoft-float", "-Wall", f"-DSND_NL={S.NL}"]
                          + (["-DSNDVFY"] if "--sndverify" in sys.argv else []) + [      # SPU upload readback (MvC rc4.1)
                                                "-c", os.path.join(HERE, "snd.c"), "-o", os.path.join(out, "snd.o")])
    return [os.path.join(out, "snd.o")]


def hook(GCC, CF, out):
    o = os.path.join(out, "unlhook.o"); e = os.path.join(out, "unlhook.elf"); b = os.path.join(out, "unlhook.bin")
    subprocess.check_call([GCC + "gcc"] + CF + ["-c", os.path.join(HERE, "unlhook.S"), "-o", o])
    subprocess.check_call([GCC + "ld", f"-Ttext={HOOKAT:#x}", "-e", "unlhook", o, "-o", e])
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".text", e, b])
    code = open(b, "rb").read()
    assert len(code) <= 30 * 4
    return code + bytes(30 * 4 - len(code))


def items(chars=None):
    """level files; mktag.py puts each character's next to its A0 file (short seeks: A0 -> level file -> sprites).
    COMMON's files (every level: the battle always uploads our COMMON) come with character 0's, the first one."""
    out = []
    cs = list(range(S.NCHAR)) if chars is None else list(chars)
    if 0 in cs: cs = [S.COMMON] + cs
    for c in cs:
        ls = S.levels(c)
        for L, bk in enumerate(ls):
            if (L == 0 and c == S.COMMON) or (L and bk.data != ls[0].data and bk.data != ls[L - 1].data)                     or (L and c == S.COMMON and bk.data != ls[L - 1].data):
                out.append((("snd", c, L), bk.data))
    return out


def directory(pos, msf, hookcode):
    """pos = {key: lba} of the items() files on the disc; one record per character, then COMMON"""
    rec = b""
    for c in list(range(S.NCHAR)) + [S.COMMON]:
        ls = S.levels(c); last = 0
        for L, bk in enumerate(ls):
            if c != S.COMMON and (L == 0 or bk.data == ls[0].data): m = 0
            else:
                if ("snd", c, L) in pos: last = pos["snd", c, L]
                assert last, (c, L)
                m = struct.unpack("<I", msf(last))[0]
            assert bk.dall % 16 == 0 and bk.dpart % 16 == 0 and bk.nall < 256
            rec += struct.pack("<I2H2B2x", m, bk.dall >> 4, bk.dpart >> 4, bk.nall, bk.npart)
        rec += struct.pack("<2H", (S.stash_size(c) if c != S.COMMON else 0) >> 4, 0)
    return MAGIC + hookcode + rec
