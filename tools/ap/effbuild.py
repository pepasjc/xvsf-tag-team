"""Common effects (hit sparks, dust, super flash ...): restore the frames the port cut from the animations of sprite set 0x26.

The EXE holds the effect animations as 8-byte records (u16 w0, u16 duration | 0x8000 end, u32 frame id into SP_EFF1; s32 loop
offset after an end record) - the format of the overlays' direct animations.  This tool pairs them with the arcade animations
(dirbuild.pair), appends the missing sprites to a copy of SP_EFF1.NSP (dirbuild.add: only records whose stock frame is a plain
dynamic frame; shared-VRAM-slot records keep their stock frame) and writes the frame-id patches for the EXE image in RAM
(EFF1.AE8, work/ap/SPEC.md section 17).  Nothing here is derived from either game.

    python effbuild.py --arcade SET.zip [PARENT.zip] --disc xvsf.bin --out NEWDIR
    (development: --ctx ctx.pkl --ps1 DIR_WITH_DISC_FILES --anims cache.pkl --exe SLUS_006.27)
"""
import os, sys, struct, hashlib, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aplib, dirbuild
from aplib import NSP

SET = 0x26
# animations kept in their stock form because the restored one measurably costs game speed (work/ap/s2/efftest.py), as EXE file offsets of
# the first record: the super-start streak burst (21 sprites of up to 416x256 pixels, one decode each): both players' supers
# 53.1 -> 51.3 loops per 60 vblanks on average with it restored
KEEP_STOCK = [0x824b0]
EXE_BASE = 0x80010000 - 0x800          # RAM address of EXE file offset 0


class _Img:                            # what dirbuild.add needs of a "blob": the image to scan, no body blob to skip
    def __init__(self, P): self.P = P; self.B = 0; self.h = (0, 0, 0, 0)


def build(ctx, ps1, exe):
    n = NSP(os.path.join(ps1, "A", "A2", "SP_EFF1.NSP")); n.decode_all(); P = open(exe, "rb").read()
    s = [bytearray(x) for x in n.sec]
    env = dict(n=n, pb=_Img(P), s0=s[0], s1=s[1], s2=s[2], s3=s[3], stock3=bytes(n.sec[3]), tilemap={}, bank=None)
    old = os.environ.get("AP_DKEEP"); os.environ["AP_DKEEP"] = ",".join(["%x" % k for k in KEEP_STOCK] + ([old] if old else []))
    try: d = dirbuild.add(ctx, SET, env)
    finally:
        if old is None: del os.environ["AP_DKEEP"]
        else: os.environ["AP_DKEEP"] = old
    for k in (0, 2, 3): s[k].extend(bytes(-len(s[k]) % 4))
    hdr = struct.pack("<4I", 16, 16 + len(s[0]), 16 + len(s[0]) + len(s[1]), 16 + len(s[0]) + len(s[1]) + len(s[2]))
    nsp = hdr + b"".join(bytes(x) for x in s)
    p = sorted(set(d["patches"]))
    ae8 = struct.pack("<4sBBHII16s", b"AE8\x01", SET, 0, 0, len(P), len(p), hashlib.sha1(P).digest()[:16]) + b"".join(struct.pack("<III", EXE_BASE + o, old, new) for o, old, new in p)
    return dict(nsp=nsp, ae8=ae8, direct=d, sec=[len(x) for x in s], stock=n.sizes, tiles=len(s[1]) // 4, patches=p, exe_sha1=hashlib.sha1(P).hexdigest())


def main(argv=None):
    import argparse, pickle, shutil
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arcade", nargs="+"); ap.add_argument("--disc"); ap.add_argument("--out", required=True)
    ap.add_argument("--ctx"); ap.add_argument("--ps1"); ap.add_argument("--anims"); ap.add_argument("--exe")
    a = ap.parse_args(argv)
    if os.path.exists(os.path.join(a.out, "manifest.json")) and not os.path.exists(os.path.join(a.out, "EFF1.AE8")):
        print("ERROR: --out holds another content set; give a new directory"); return 2
    os.makedirs(a.out, exist_ok=True); work = os.path.join(a.out, "_work"); os.makedirs(work, exist_ok=True)
    if a.ctx:
        prg, T, chtab = pickle.load(open(a.ctx, "rb")); ps1 = a.ps1; ctx = aplib.Ctx(prg, T, ps1, chtab); exe = a.exe
        if a.anims: ctx._dir_anims = pickle.load(open(a.anims, "rb"))
    else:
        import build8
        try:
            setname, prg, roms = build8.read_arcade(a.arcade); d = build8.Disc(a.disc); idx = {nm: (lba, sz) for nm, lba, sz in d.walk()}
            ps1 = os.path.join(work, "ps1"); os.makedirs(os.path.join(ps1, "A", "A2"), exist_ok=True)
            open(os.path.join(ps1, "A", "A2", "SP_EFF1.NSP"), "wb").write(d.read(*idx["A/A2/SP_EFF1.NSP"]))
            exe = os.path.join(work, build8.PS1_EXE); open(exe, "wb").write(d.read(*idx[build8.PS1_EXE]))
        except (build8.Fail, KeyError) as ex: print("ERROR:", ex); return 2
        ctx = aplib.Ctx(prg, aplib.gfx_decode(lambda nm: roms[nm]), ps1, aplib.find_chtab(prg))
    r = build(ctx, ps1, exe); tot, bad = dirbuild.check(ctx, r, work)
    stock = open(os.path.join(ps1, "A", "A2", "SP_EFF1.NSP"), "rb").read(); o = struct.unpack_from("<4I", stock, 0) + (len(stock),); o2 = struct.unpack_from("<4I", r["nsp"], 0)
    prefix = all(r["nsp"][o2[k]:o2[k] + (o[k + 1] - o[k]) - 4] == stock[o[k]:o[k + 1] - 4] for k in range(4))
    if bad or not prefix or r["tiles"] > 4096 or r["sec"][0] >= 0x10000 or r["sec"][3] >= 0x10000:
        print("ERROR: self-check failed (%d bad frames, stock prefix %s)" % (bad, prefix)); return 2
    open(os.path.join(a.out, "SP_EFF1.NSP"), "wb").write(r["nsp"]); open(os.path.join(a.out, "EFF1.AE8"), "wb").write(r["ae8"])
    d = r["direct"]
    man = dict(format="AE8 1", set=SET, nsp="SP_EFF1.NSP", nsp_size=len(r["nsp"]), nsp_sha1=hashlib.sha1(r["nsp"]).hexdigest(), sections=r["sec"], sections_stock=r["stock"], tiles=r["tiles"],
               ae8="EFF1.AE8", ae8_size=len(r["ae8"]), ae8_sha1=hashlib.sha1(r["ae8"]).hexdigest(), patches=len(r["patches"]), exe_sha1=r["exe_sha1"], sprites_new=d["stats"].get("new", 0),
               max_rect=d["maxrect"], max_frame_bytes=d["maxraw"], checked=tot, slot_table=False,
               animations=[dict(offset=x["offset"], ram=EXE_BASE + x["offset"], arcade=x["arcade"], records=x["records"], sprites_stock=x["sprites_stock"], sprites_arcade=x["sprites_arcade"],
                                restored=x["restored"], left=x["left"]) for x in d["report"]])
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1, sort_keys=True)
    shutil.rmtree(work, ignore_errors=True)
    print("SP_EFF1 sections", r["sec"], "stock", r["stock"], "tiles", r["tiles"], "file", len(r["nsp"]), "| new sprites", d["stats"].get("new", 0), "| EFF1.AE8", len(r["patches"]), "patches | checked", tot)
    for x in d["report"]:
        print(" +%05x records %2d arcade %s sprites %s -> %s | cut records restored %2d, left %s" % (x["offset"], x["records"], "%06x" % x["arcade"] if x["arcade"] else "  -   ",
                                                                                              x["sprites_stock"], x["sprites_arcade"], x["restored"], x["left"] or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
