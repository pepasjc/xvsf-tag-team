"""Build a disc with the XVH1 re-encoded character sprite files (build/nsp/SP_PLxx.NSP) and the
decoder patch.  Files are replaced in place (same LBA, smaller size); their size is updated in the
ISO9660 directory record and in the game's own file table (EXE, 0x8003d91c + 8*index, size at +4).
EDC/ECC is regenerated for every touched sector.

    python mknspdisc.py [name] [--dir=nspf] [--tag] [--chd]     -> build/<name>.bin/.cue
    --dir=X takes the files from build/X (default build/nsp = XVH1; build/nspm = XVM1)
    --eff1=PATH (relative to build/) also replaces A/A2/SP_EFF1.NSP, e.g. --eff1=nspm_eff/SP_EFF1.NSP
    --tag also applies tools/tagpatch.py (tag-switch hook)
"""
import os, shutil, struct, subprocess, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import nsppatch
from mkdisc import fix_sector, CHDMAN, BUILD
import region
SRC = region.BIN                                       # US: disc/xvsf.bin (same file mkdisc.SRC names)
FTABLE = region.A(0x8003d91c)
NSPDIR = os.path.join(BUILD, "nsp")
EXE_BASE, EXE_HDR = 0x80010000, 0x800


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    nspdir = NSPDIR
    for x in sys.argv[1:]:
        if x.startswith("--dir="): nspdir = os.path.join(BUILD, x[6:])
    name = args[0] if args else "xvsf_nsp"
    out = os.path.join(BUILD, name + ".bin")
    lmap = json.load(open(region.LMAP))
    exe_lba, exe_size = lmap[region.EXE]
    shutil.copyfile(SRC, out)
    touched = set()
    with open(out, "r+b") as f:
        def rd(sec):
            f.seek(sec * 2352); return bytearray(f.read(2352))

        def wr_data(sec, within, data):
            f.seek(sec * 2352 + 24 + within); f.write(data); touched.add(sec)

        def exe_write(addr, data):
            off = addr - EXE_BASE + EXE_HDR
            assert 0 <= off and off + len(data) <= exe_size
            for i in range(len(data)):
                o = off + i
                wr_data(exe_lba + o // 2048, o % 2048, data[i:i + 1])

        def exe_read(addr, n):
            off = addr - EXE_BASE + EXE_HDR; b = bytearray()
            for i in range(n):
                o = off + i
                f.seek((exe_lba + o // 2048) * 2352 + 24 + o % 2048); b += f.read(1)
            return bytes(b)

        # sectors of the A/A0 directory (walk root -> A -> A0)
        from iso import Disc
        d = Disc(SRC)

        def dir_sectors(*parts):
            rec = d.rsec(16)[156:156 + 34]
            dl, dn = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
            for part in parts:
                dl, dn = [(l, z) for nm, l, z, fl in d.listdir(dl, dn) if nm == part and fl & 2][0]
            return {s: rd(s)[24:24 + 2048] for s in range(dl, dl + (dn + 2047) // 2048)}

        def replace(discpath, findex, new):
            """Replace a file in place (same LBA, smaller): data, ISO directory record, game file table."""
            parts = discpath.split("/"); fn = parts[-1]
            dirsecs = dir_sectors(*parts[:-1])
            lba, osize = lmap[discpath]
            assert len(new) <= osize and len(new) % 4 == 0
            nsec = (len(new) + 2047) // 2048
            pad = new + b"\0" * (nsec * 2048 - len(new))
            for i in range(nsec):
                raw = rd(lba + i)
                assert raw[15] == 2 and not raw[18] & 0x20, "expected mode 2 form 1"
                wr_data(lba + i, 0, pad[i * 2048:(i + 1) * 2048])
            # end-of-file submode on the new last sector (both copies of the subheader)
            last = lba + nsec - 1
            raw = rd(last); sm = raw[18] | 0x81
            f.seek(last * 2352 + 18); f.write(bytes([sm]))
            f.seek(last * 2352 + 22); f.write(bytes([sm]))
            # ISO9660 directory record: extent LE/BE then size LE/BE
            pat = struct.pack("<I", lba) + struct.pack(">I", lba) + struct.pack("<I", osize) + struct.pack(">I", osize)
            hits = [(s, dd.find(pat)) for s, dd in dirsecs.items() if pat in dd]
            assert len(hits) == 1 and all(dd.count(pat) == 1 for s, dd in dirsecs.items() if pat in dd), (fn, hits)
            s, o = hits[0]
            assert dirsecs[s][o + 31:o + 31 + len(fn)] == fn.encode(), "directory record name mismatch"
            wr_data(s, o + 8, struct.pack("<I", len(new)) + struct.pack(">I", len(new)))
            # game file table
            ent = FTABLE + 8 * findex
            assert struct.unpack("<I", exe_read(ent + 4, 4))[0] == osize, fn
            exe_write(ent + 4, struct.pack("<I", len(new)))
            print("%s lba %d: %d -> %d bytes (%d -> %d sectors)" % (fn, lba, osize, len(new), (osize + 2047) // 2048, nsec))

        for cid in ([] if '--nofiles' in sys.argv else range(0x13)):
            fn = "SP_PL%02X.NSP" % cid
            replace("A/A0/" + fn, 0x5a + cid, open(os.path.join(nspdir, fn), "rb").read())
        for x in sys.argv[1:]:
            if x.startswith("--eff1="):               # resident effects file (sprite set 0x26, file index 0x80)
                replace("A/A2/SP_EFF1.NSP", 0x5a + 0x26, open(os.path.join(BUILD, x[7:]), "rb").read())
        pl = [] if '--noexe' in sys.argv else list(nsppatch.patches())
        if "--tag" in sys.argv:
            import tagpatch
            pl += tagpatch.patches()
        for addr, data in pl:
            exe_write(addr, data)
            print("exe patch %08x %d bytes" % (addr, len(data)))
        for sec in sorted(touched):
            raw = rd(sec)
            assert raw[15] == 2 and not raw[18] & 0x20, "expected mode 2 form 1"
            fix_sector(raw)
            f.seek(sec * 2352); f.write(raw)
    open(os.path.join(BUILD, name + ".cue"), "w").write(
        f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(f"touched {len(touched)} sectors -> {out}")
    if "--chd" in sys.argv:
        chd = os.path.join(BUILD, name + ".chd")
        subprocess.check_call([CHDMAN, "createcd", "-i", os.path.join(BUILD, name + ".cue"), "-o", chd, "-f"],
                              stdout=subprocess.DEVNULL)
        print("chd:", chd)


if __name__ == "__main__":
    main()
