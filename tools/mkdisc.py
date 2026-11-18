"""Build the patched disc: copy disc/xvsf.bin, apply tagpatch to SLUS_006.27
in place (same LBA, same size), regenerate EDC/ECC of touched sectors.

    python mkdisc.py [out_basename]      -> build/<name>.bin/.cue (+ .chd)
"""
import os, shutil, struct, subprocess, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import tagpatch

import toolenv
CHDMAN = toolenv.chdman()
SRC = os.path.join(ROOT, "disc", "xvsf.bin")
BUILD = os.path.join(ROOT, "build")

# --- EDC/ECC (mode 2 form 1) -------------------------------------------------
edc_lut = []
for i in range(256):
    edc = i
    for _ in range(8):
        edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
    edc_lut.append(edc)
ecc_f = [0] * 256
ecc_b = [0] * 256
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    ecc_f[i] = j
    ecc_b[i ^ j] = i


def edc_compute(data):
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ edc_lut[(edc ^ b) & 0xFF]
    return edc


def ecc_block(src, major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    dest = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ecc_f[a]
        a = ecc_b[ecc_f[a] ^ b]
        dest[major] = a
        dest[major + major_count] = a ^ b
    return dest


def fix_sector(sec):
    """sec: bytearray(2352), mode 2 form 1. Recompute EDC + ECC P/Q."""
    sec[2072:2076] = struct.pack("<I", edc_compute(sec[16:2072]))
    body = bytearray(4) + sec[16:2076]              # header zeroed for mode 2
    p = ecc_block(body, 86, 24, 2, 86)
    sec[2076:2076 + 172] = p
    q = ecc_block(body + p, 52, 43, 86, 88)
    sec[2248:2248 + 104] = q


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "xvsf_tag"
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, name + ".bin")
    shutil.copyfile(SRC, out)
    lba, size = json.load(open(os.path.join(ROOT, "work", "lba_map.json")))["SLUS_006.27"]
    touched = set()
    with open(out, "r+b") as f:
        for addr, data in tagpatch.patches():
            off = addr - tagpatch.EXE_BASE + tagpatch.EXE_HDR
            assert 0 <= off and off + len(data) <= size
            for i, byte in enumerate(data):
                o = off + i
                sec, within = lba + o // 2048, o % 2048
                f.seek(sec * 2352 + 24 + within)
                f.write(bytes([byte]))
                touched.add(sec)
        for sec in sorted(touched):
            f.seek(sec * 2352)
            raw = bytearray(f.read(2352))
            assert raw[15] == 2 and not raw[18] & 0x20, "expected mode 2 form 1"
            fix_sector(raw)
            f.seek(sec * 2352)
            f.write(raw)
    open(os.path.join(BUILD, name + ".cue"), "w").write(
        f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(f"patched {len(touched)} sector(s): {sorted(touched)} -> {out}")
    if "--chd" in sys.argv:
        chd = os.path.join(BUILD, name + ".chd")
        subprocess.check_call([CHDMAN, "createcd", "-i", os.path.join(BUILD, name + ".cue"), "-o", chd, "-f"],
                              stdout=subprocess.DEVNULL)
        print("chd:", chd)


if __name__ == "__main__":
    main()
