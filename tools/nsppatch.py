"""EXE patch for the XVH1 sprite codec (format: nsp_huff.py, decoder source: nspdec/nspdec.S).

  0x800158f4-0x80015a68  xvf_dec (XVF1 decoder)   }
  0x80015bac-0x80015d9c  nsp_dec main loop        } over uncalled libgpu helper / debug-dump
  0x80015dd4-0x80015f94  run copy, dispatch stub, } functions (no jal/j/pointer in the EXE; verified
                         run-length table         } by booting + fighting with them filled with `break`)
     (0x80015d9c-0x80015dd4 in between is a live function and is not touched)
  0x8001b5b0             first instruction of the game's RLE tile decoder -> `j dec_entry`
                         (delay slot 0x8001b5b4 `addiu t0,t0,-0x49f8` is harmless; the stub redoes both
                          instructions and continues at 0x8001b5b8 for data that is not XVH1)
NOT usable: 0x800146a8-0x80015024 (CdSearchFile, real entry 0x80014698, is called at boot and from 0x8004e2ac).

  python nsppatch.py build     reassemble nspdec.S (needs a MIPS toolchain, see tools/toolenv.py)
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "nspdec")
sys.path.insert(0, HERE)
import toolenv
GCC = toolenv.mips_prefix()
ORG = 0x80010440
HOLES = [(0x80010508, 0x800158f4), (0x80015a68, 0x80015bac), (0x80015d9c, 0x80015dd4)]
LIMIT = 0x80015f94
HOOK = 0x8001b5b0
EXE_BASE, EXE_HDR = 0x80010000, 0x800


def build():
    subprocess.check_call([GCC + "gcc", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", "-c", "nspdec.S", "-o", "nspdec.o"], cwd=D)
    subprocess.check_call([GCC + "ld", "-T", "link.ld", "nspdec.o", "-o", "nspdec.elf"], cwd=D)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "nspdec.elf", "nspdec.bin"], cwd=D)
    out = subprocess.check_output([GCC + "nm", "nspdec.elf"], cwd=D).decode()
    open(os.path.join(D, "nspdec.sym"), "w").write(out)


def symbols():
    s = {}
    for l in open(os.path.join(D, "nspdec.sym")):
        if len(l.split()) != 3: continue
        a, t, n = l.split()
        s[n] = int(a, 16) & 0xFFFFFFFF
    return s


def patches():
    if "--nospeed" not in sys.argv:                 # 1.1: rewritten decoders (tools/speed/decode), same formats
        import speedpatch
        sp = speedpatch.decode_patches()
        if sp is not None: return sp
    b = open(os.path.join(D, "nspdec.bin"), "rb").read()
    s = symbols()
    assert s["xvm_dec"] == ORG and s["holeS_start"] == HOLES[0][0] and s["holeS_end"] == HOLES[0][1] == s["msym"]
    assert s["hole0_start"] == HOLES[1][0] and s["hole0_end"] == HOLES[1][1]
    assert s["hole_start"] == HOLES[2][0] and s["hole_end"] == HOLES[2][1]
    assert ORG + len(b) == s["blob_end"] <= LIMIT and len(b) % 4 == 0
    out = []; a = ORG
    for (lo, hi), end in zip(HOLES + [(ORG + len(b), None)], ("endS", "endZ", "endX", "blob_end")):
        assert a <= s[end] <= lo and not any(b[s[end] - ORG:(hi or lo) - ORG]), "hole must be empty"
        out.append((a, b[a - ORG:s[end] - ORG])); a = hi      # exact end: a trailing nop is code too
    return out + [(HOOK, struct.pack("<I", 0x08000000 | ((s["dec_entry"] >> 2) & 0x03FFFFFF)))]


def apply_ram(emu):
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    for addr, data in patches():
        print(f"{addr:08x}-{addr + len(data):08x} {len(data):4d} bytes")
