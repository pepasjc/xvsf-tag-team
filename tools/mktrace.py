"""Measurement build: add a file-read tracer to ANY disc image of this game (stock or tag build).

    python mktrace.py SRC.bin OUTNAME        -> build/OUTNAME.bin/.cue

The tracer wraps the game's file read 0x8002dd40(index, dest) (the `jal` at 0x8002de60 inside
0x8002de3c, which every loader uses) and keeps a log in RAM that the harness polls once per frame
(work/loadtrace.py):
    LOG = 0x801fe810:  u32 begins, u32 ends, then 64 x 16 bytes {index, dest, size returned, -}
Code: 96 bytes at 0x80015604 (dead range 0x80015604-0x800156a0; not used by the tag builds any more).
Not for release discs: the log sits in the unused gap between the loader's CD-spill zone and the stack.
"""
import os, shutil, struct, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from mkdisc import fix_sector, BUILD

ORG, LIMIT, HOOK_AT, HOOK_ORIG, LOG = 0x80015604, 0x800156a0, 0x8002de60, 0x0C00B750, 0x801fe810
CODE = [0x3c088020, 0x2508e810, 0x8d090000, 0x27bdffe8, 0x312a003f, 0x000a5100, 0x01485021, 0xad440010,
        0xad450014, 0x25290001, 0xad090000, 0xafbf0010, 0x0c00b750, 0xafaa0014, 0x8faa0014, 0x3c088020,
        0x2508e810, 0x8d090004, 0x8fbf0010, 0xad420018, 0x25290001, 0xad090004, 0x03e00008, 0x27bd0018]


def patches():
    return [(ORG, struct.pack(f"<{len(CODE)}I", *CODE)), (HOOK_AT, struct.pack("<I", 0x0C000000 | (ORG >> 2 & 0x3FFFFFF)))]


def main():
    src, name = sys.argv[1], sys.argv[2]
    out = os.path.join(BUILD, name + ".bin")
    shutil.copyfile(src, out)
    exe_lba, exe_size = json.load(open(os.path.join(ROOT, "work", "lba_map.json")))["SLUS_006.27"]
    orig = open(os.path.join(ROOT, "disc/files/SLUS_006.27"), "rb").read()
    touched = set()
    with open(out, "r+b") as f:
        def rw(addr, data=None, n=0):
            b = bytearray()
            for i in range(len(data) if data is not None else n):
                o = addr - 0x80010000 + 0x800 + i
                f.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048)
                if data is None: b += f.read(1)
                else: f.write(data[i:i + 1]); touched.add(exe_lba + o // 2048)
            return bytes(b)
        assert rw(ORG, n=LIMIT - ORG) == orig[ORG - 0x80010000 + 0x800:LIMIT - 0x80010000 + 0x800], "tracer range is in use on this disc"
        assert struct.unpack("<I", rw(HOOK_AT, n=4))[0] == HOOK_ORIG
        for addr, data in patches(): rw(addr, data)
        for sec in sorted(touched):
            f.seek(sec * 2352); raw = bytearray(f.read(2352)); fix_sector(raw)
            f.seek(sec * 2352); f.write(raw)
    open(os.path.join(BUILD, name + ".cue"), "w").write(f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print("tracer added ->", out)


if __name__ == "__main__":
    main()
