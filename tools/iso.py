"""List / extract files from the XvSF PS1 disc (MODE2/2352, data at byte 24).

    python iso.py list
    python iso.py extract            everything -> disc/files, writes work/lba_map.json
"""
import struct, sys, os, json

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BIN = os.path.join(ROOT, "disc", "xvsf.bin")
OUT = os.path.join(ROOT, "disc", "files")
WORK = os.path.join(ROOT, "work")


class Disc:
    def __init__(self, path=BIN):
        self.f = open(path, "rb")

    def raw(self, lba):
        self.f.seek(lba * 2352)
        return self.f.read(2352)

    def rsec(self, lba):
        return self.raw(lba)[24:24 + 2048]

    def read(self, lba, size):
        out = bytearray()
        for s in range((size + 2047) // 2048):
            out += self.rsec(lba + s)
        return bytes(out[:size])

    def listdir(self, lba, ln):
        out = []
        for si in range((ln + 2047) // 2048):
            sec = self.rsec(lba + si)
            i = 0
            while i < 2048:
                l = sec[i]
                if l == 0:
                    break
                e_lba, = struct.unpack_from("<I", sec, i + 2)
                e_sz, = struct.unpack_from("<I", sec, i + 10)
                fl = sec[i + 25]
                nl = sec[i + 32]
                nm = sec[i + 33:i + 33 + nl].decode("ascii", "replace").split(";")[0]
                if nm not in ("\x00", "\x01"):
                    out.append((nm, e_lba, e_sz, fl))
                i += l
        return out

    def walk(self, lba=None, ln=None, path=""):
        if lba is None:
            rec = self.rsec(16)[156:156 + 34]
            lba, = struct.unpack_from("<I", rec, 2)
            ln, = struct.unpack_from("<I", rec, 10)
        for nm, e_lba, e_sz, fl in self.listdir(lba, ln):
            full = f"{path}/{nm}" if path else nm
            if fl & 2:
                yield from self.walk(e_lba, e_sz, full)
            else:
                yield full, e_lba, e_sz, fl


if __name__ == "__main__":
    d = Disc()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    m = {}
    for full, lba, sz, fl in d.walk():
        m[full] = [lba, sz]
        if cmd == "list":
            print(f"{lba:7d} {sz:10d} {fl:02x} {full}")
        elif cmd == "extract":
            dst = os.path.join(OUT, full.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # XA/STR files (form 2 flags) are not plain 2048 data; skip >50MB streams
            open(dst, "wb").write(d.read(lba, sz))
    if cmd == "extract":
        os.makedirs(WORK, exist_ok=True)
        json.dump(m, open(os.path.join(WORK, "lba_map.json"), "w"), indent=0)
        print(f"extracted {len(m)} files")
