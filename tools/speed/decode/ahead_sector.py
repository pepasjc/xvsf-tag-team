"""The decode-ahead predictor as a per-battle area: 2 sectors read together with the loader's directory sector
(tools/mktagdisc.py: the directory entry's size covers 3 sectors), landing at 0x801fe804-0x801ff600.

    build(vc=(lookup, prefetch)) -> 4096 bytes (code + zeroed work area, checksum filled)
    python ahead_sector.py        size report

Resident part: the check stub `ahcb` in tools/speed/decode/nspdec.S (chunk R): magic at 0x801fe804 -> jumps to
0x801fe818 (ah_entry); the frame worker's idle hook word EBV+12 points at ahcb (tools/speed/decode.py hook_patches)."""
import os, sys, struct, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ORG, LIMIT, MAGIC = 0x801fe804, 0x801ff600, 0x50410000
ENTRY = ORG + 0x14
LD = """SECTIONS {
  . = 0x%08x;
  .text : { *(.text.head) *(.text*) *(.rodata*) *(.data*) *(.sdata*) . = ALIGN(4); *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); ah_end = .; }
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }
}
"""


def build(vc=(0, 0)):
    import dlib as D
    obj = os.path.join(D.WORK, "obj"); os.makedirs(obj, exist_ok=True)
    pid = os.getpid()
    o1, o2 = os.path.join(obj, "ahead_s_%d.o" % pid), os.path.join(obj, "ahead_h_%d.o" % pid)
    elf, b, ld = os.path.join(obj, "ahead_s_%d.elf" % pid), os.path.join(obj, "ahead_s_%d.bin" % pid), os.path.join(obj, "ahead_s_%d.ld" % pid)
    open(ld, "w").write(LD % ORG)
    cf = ["-mips1", "-G0", "-mno-abicalls", "-fno-pic"]
    subprocess.check_call([D.GCC + "gcc", "-Os", "-ffreestanding", *cf, "-DSECTOR", "-c", os.path.join(HERE, "ahead.c"), "-o", o1])
    subprocess.check_call([D.GCC + "gcc", *cf, "-c", os.path.join(HERE, "ahead_head.S"), "-o", o2])
    subprocess.check_call([D.GCC + "ld", "-T", ld, o2, o1, "-o", elf])
    subprocess.check_call([D.GCC + "objcopy", "-O", "binary", "-j", ".text", elf, b])
    sym = {}
    for l in subprocess.check_output([D.GCC + "nm", elf]).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xffffffff
    img = bytearray(open(b, "rb").read())
    assert sym["ah_start"] == ORG and sym["ah_entry"] == ENTRY and ORG + len(img) == sym["ah_end"] <= LIMIT, (hex(sym["ah_end"]), len(img))
    bad = D.hazards(bytes(img), ORG)
    assert not bad, bad
    struct.pack_into("<2I", img, 4, *vc)
    s = sum(struct.unpack_from("<%dI" % (len(img) // 4), img)) - struct.unpack_from("<I", img, 12)[0] - struct.unpack_from("<I", img, 16)[0]
    struct.pack_into("<I", img, 12, s & 0xffffffff)
    return bytes(img) + bytes(4096 - len(img)), sym


if __name__ == "__main__":
    img, sym = build()
    print("predictor area %08x-%08x (%d bytes of %d), entry %08x" % (ORG, sym["ah_end"], sym["ah_end"] - ORG, LIMIT - ORG, sym["ah_entry"]))
