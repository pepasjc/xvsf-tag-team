"""8 MB "arcade frames" builder, content side.

    python build8.py --arcade xmvsf.zip [parent.zip ...] --disc xvsf.bin --out OUTDIR [--chars 0,1,2,5,6,12,13,17]

Reads the user's own arcade ROM set (CPS2 X-Men vs. Street Fighter) and the user's own PS1 disc image (SLUS-00627) and
writes, per character, the restored sprite file SP_PLxx.NSP and the animation patch PLxx.AP8 (formats: work/ap/SPEC.md)
plus manifest.json.  Everything in OUTDIR is derived from the two inputs and must not be redistributed.
The tool itself contains no data from either: tables are located by structure, ROMs are recognised by SHA-1.
"""
import sys, os, json, zipfile, hashlib, struct, argparse
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)

# ROMs shared by every supported set: graphics (13m-20m) and the data half of the program (05a-09)
SHARED = {"05a": "2d74f48f83f45359bfaca28ab686625766af12ee", "06a": "929408cb5d98e95cec75ea58e4701b0cbdbcd016", "07": "ef16c376232dba63b0b9bc3aa0640f9001ccb68a",
          "08": "19cf7afbc1daaefec40195e40ba74970f3906a1c", "09": "dcba3482d1ba37ccfb30d402793ee063c6621aed", "13m": "c0a2f3a9e82ab8b084a500aec71ac633e947328c",
          "14m": "838ff24f7e8543a787a55a5d592c9517ce3b8b93", "15m": "898b8f678fd03c462ce0d8eb7fb3441ef601085b", "16m": "cd7c79037b5b4a39bef5156433e984dc4dc2c081",
          "17m": "7b6f4c8ebfdac167b25f35029068b6253c141fe6", "18m": "da3a6705ea7050fc5c2c10d33400ed67be9f455d", "19m": "6579da7145c95b3ad00844a5fc8c2e22c23365e2",
          "20m": "9a981d442132efff09a27408d74646ba357c7357"}
# region program ROMs (03, 04) of the sets this builder has been verified on
SETS = {("c6d8aa1e43fc541e5b4e938258f27ab9ee30ca33", "d3504cb8c38f720b1f4528157266db60c8c6c075"): "xmvsf (Euro 961004)",
        ("2eb5912d3026bed0f720d28e1bf3a7ceb5b80803", "d838199b2767d9f02fa0f103c5d587a4c78c0d21"): "xmvsfu (USA 961023)",
        ("812ebe4063a1c5d8c86200a51e6ab00e57e02869", "f0d409048c9d477ee98e6df92febcd4492a291ee"): "xmvsfu1d (USA 961004, decrypted)"}
PS1_EXE = "SLUS_006.27"
DEFAULT = [0, 1, 2, 3, 4, 5, 6, 7, 12, 13, 17]


class Fail(Exception):
    pass


def read_arcade(paths):
    files = {}
    for p in paths:
        if os.path.isdir(p):
            for n in os.listdir(p): files.setdefault(n.lower(), open(os.path.join(p, n), "rb").read())
        else:
            try: z = zipfile.ZipFile(p)
            except (zipfile.BadZipFile, OSError): raise Fail("arcade set: %s is not a zip file or a folder of ROM files" % p)
            for n in z.namelist(): files.setdefault(os.path.basename(n).lower(), z.read(n))
    roms = {}
    for n, d in files.items():
        ext = n.rsplit(".", 1)[-1]
        if ext in SHARED: roms[ext] = d
        elif ext[:2] in ("03", "04") and len(d) == 0x80000: roms.setdefault(ext[:2], d)      # first zip given wins: SET.zip before PARENT.zip
    miss = [k for k in list(SHARED) + ["03", "04"] if k not in roms]
    if miss: raise Fail("arcade set incomplete: no ROM with extension " + ", ".join("." + m for m in miss) + " (a clone zip needs its parent zip too)")
    badh = [k for k, h in SHARED.items() if hashlib.sha1(roms[k]).hexdigest() != h]
    if badh: raise Fail("unknown arcade set: ROM(s) %s differ from the supported revision (xvs.05a/06a, 961004 or later graphics)" % ", ".join(badh))
    key = (hashlib.sha1(roms["03"]).hexdigest(), hashlib.sha1(roms["04"]).hexdigest())
    if key not in SETS:
        raise Fail("unknown arcade set: program ROMs .03/.04 are not one of the supported sets:\n  " + "\n  ".join(SETS.values()) +
                   "\n(sha1 .03 %s, .04 %s)" % key)

    def sw(d):
        a = np.frombuffer(d, dtype=np.uint8); b = a.copy(); b[0::2] = a[1::2]; b[1::2] = a[0::2]; return b.tobytes()
    prg = b"".join(sw(roms[k]) for k in ("03", "04", "05a", "06a", "07", "08", "09"))
    return SETS[key], prg, roms


class Disc:
    """MODE2/2352 image, ISO9660"""

    def __init__(self, path): self.f = open(path, "rb")

    def sec(self, lba):
        self.f.seek(lba * 2352 + 24); return self.f.read(2048)

    def read(self, lba, size): return b"".join(self.sec(lba + s) for s in range((size + 2047) // 2048))[:size]

    def walk(self, lba=None, ln=None, path=""):
        if lba is None:
            rec = self.sec(16)[156:190]; lba, = struct.unpack_from("<I", rec, 2); ln, = struct.unpack_from("<I", rec, 10)
        for si in range((ln + 2047) // 2048):
            s = self.sec(lba + si); i = 0
            while i < 2048 and s[i]:
                l = s[i]; e_lba, = struct.unpack_from("<I", s, i + 2); e_sz, = struct.unpack_from("<I", s, i + 10); nl = s[i + 32]
                nm = s[i + 33:i + 33 + nl].decode("ascii", "replace").split(";")[0]
                if nm not in ("\x00", "\x01"):
                    if s[i + 25] & 2: yield from self.walk(e_lba, e_sz, path + nm + "/")
                    else: yield path + nm, e_lba, e_sz
                i += l


def read_ps1(path, work, chars):
    d = Disc(path)
    try: idx = {n: (lba, sz) for n, lba, sz in d.walk()}
    except Exception: raise Fail("PS1 image: not a MODE2/2352 ISO9660 image")
    if PS1_EXE not in idx: raise Fail("PS1 image: %s not found - this builder supports the USA disc SLUS-00627 only" % PS1_EXE)
    want = [(f"A/A0/SP_PL{ch:02X}.NSP", ch in chars) for ch in range(18)] + [(f"P/P0/PL{ch:02X}_10.BIN", ch in chars) for ch in range(18)]
    want += [("A/A2/SP_SEL0.NSP", True), ("P/P4/SELECT.BIN", True)]
    for rel, must in want:
        if True:
            if rel not in idx:
                if must: raise Fail("PS1 image: %s missing" % rel)
                continue
            out = os.path.join(work, "ps1", *rel.split("/")); os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(d.read(*idx[rel]))
    return os.path.join(work, "ps1")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arcade", nargs="+", required=True); ap.add_argument("--disc", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--chars", default=",".join(map(str, DEFAULT)))
    ap.add_argument("--no-keep", action="store_true", help="ignore aplib.KEEP_STOCK (speed policy list)")
    ap.add_argument("--direct", action="store_true", help="also restore the direct-frame-id animations (capes, slash trails, beams): writes PLxx.AD8, "
                    "which needs loader support (SPEC.md section 12) - use a separate output folder")
    ap.add_argument("--shared", action="store_true", help="also restore the shared-VRAM-slot frames of the characters in aplib.SHARED_OK: sets slot_table in the "
                    "manifest, which needs loader support (SPEC.md section 11) - use a separate output folder")
    ap.add_argument("--whole", action="store_true", help="restore an animation completely or not at all (aplib.build_whole; 1.4 8 MB final)")
    ap.add_argument("--debug", action="store_true", help="also write PLxx_anim.json (arcade sprite address -> frame id) for the test harness")
    a = ap.parse_args(argv)
    chars = [int(x) for x in a.chars.split(",")]
    _build = (lambda ctx, ch, **kw: __import__("aplib").build_whole(ctx, ch, **kw)) if a.whole else None
    if a.direct and a.chars == ",".join(map(str, DEFAULT)): chars = sorted(chars + [9])       # Ryu: uncut body, three cut sprites in his direct animations
    try:
        setname, prg, roms = read_arcade(a.arcade)
        print("arcade set:", setname)
        work = os.path.join(a.out, "_work"); os.makedirs(work, exist_ok=True)
        ps1 = read_ps1(a.disc, work, chars)
        import aplib
        if a.no_keep: aplib.KEEP_STOCK = {}
        if a.shared: aplib.SHARED_CHARS = set(aplib.SHARED_OK)
        try: chtab = aplib.find_chtab(prg)
        except ValueError as ex: raise Fail(str(ex))
        print("animation pointer table at 0x%x" % chtab)
        ctx = aplib.Ctx(prg, aplib.gfx_decode(lambda n: roms[n]), ps1, chtab)
        man = dict(format="AP8 1", set=setname, chars={}, direct=bool(a.direct), shared=bool(a.shared))
        for ch in chars:
            if a.direct:
                import dirbuild
                bf = _build or aplib.build
                r = bf(ctx, ch, extra=dirbuild.add); first = False
                if any("file limit" in k for x in r["direct"]["report"] for k in x["left"]):          # the file is full: direct animations first (Magneto)
                    r = bf(ctx, ch, extra=dirbuild.add, extra_first=True); first = True
                dtot, dbad = dirbuild.check(ctx, r, work)
                if dbad: raise Fail("character %d: self-check of the direct animations failed (%d bad frames)" % (ch, dbad))
                if ch not in DEFAULT and not r["stats"].get("new"):       # uncut body (Ryu): keep the stock body records, only the direct patches matter
                    r["recpatch"] = []; r["sub2"] = r["sub2"][:r["old_nframes"]]
            else: r = (_build or aplib.build)(ctx, ch)
            tot, bad = aplib.check(ctx, r, work)
            if bad or r["over"] or r["nsp"][16 + r["sec"][0] + r["sec"][1]:][:4] in (b"XVM1", b"XVH1", b"XVF1"):
                raise Fail("character %d: self-check failed (%d bad frames, over limit %s)" % (ch, bad, r["over"]))
            nspn = f"SP_PL{ch:02X}.NSP"; apn = f"PL{ch:02X}.AP8"; pd = aplib.ap8(r)
            open(os.path.join(a.out, nspn), "wb").write(r["nsp"]); open(os.path.join(a.out, apn), "wb").write(pd)
            if a.debug:
                json.dump(dict(sub2=r["sub2"], old_nframes=r["old_nframes"], recpatch=r["recpatch"], newid={str(k): v for k, v in r["newid"].items()},
                               skipped={str(k): v for k, v in r["skipped"].items()}, shared_ids=r["shared_ids"]), open(os.path.join(a.out, f"PL{ch:02X}_anim.json"), "w"))
            man["chars"]["%02X" % ch] = dict(name=aplib.NAMES[ch], nsp=nspn, nsp_size=len(r["nsp"]), nsp_sha1=hashlib.sha1(r["nsp"]).hexdigest(), sections=r["sec"],
                                             ap8=apn, ap8_size=len(pd), ap8_sha1=hashlib.sha1(pd).hexdigest(), overlay_sha1=r["overlay_sha1"], blob_offset=r["blob_file_off"],
                                             frames_stock=r["old_nframes"], frames=len(r["sub2"]), patches=len(r["recpatch"]), tiles=r["ntiles"],
                                             sprites_arcade=r["arc_sprites"], sprites_stock=r["stock_sprites"], sprites_new=r["stats"].get("new", 0),
                                             records=r["records"], records_left_stock=r["unchanged"] + r["unpaired"], records_shared_slot=r["shared"], slot_table=bool(r["shared_new"]), shared_frames_new=len(r["shared_new"]), slot_indices=r["slots"], skipped=len(r["skipped"]),
                                             max_rect=r["maxrect"], max_frame_bytes=r["maxraw"], checked=tot)
            if a.direct:
                d = r["direct"]; m = man["chars"]["%02X" % ch]; m["direct"] = dict(patches=0, sprites_new=d["stats"].get("new", 0), direct_first=first, checked=dtot, animations=[
                    dict(offset=x["offset"], records=x["records"], sprites_stock=x["sprites_stock"], sprites_arcade=x["sprites_arcade"], restored=x["restored"], left=x["left"]) for x in d["report"]])
                if d["patches"]:
                    ad = dirbuild.ad8(ch, d); adn = f"PL{ch:02X}.AD8"; open(os.path.join(a.out, adn), "wb").write(ad)
                    m["direct"].update(ad8=adn, ad8_size=len(ad), ad8_sha1=hashlib.sha1(ad).hexdigest(), patches=len(set(d["patches"])))
                print(f"   direct animations {len(d['report'])}: {d['stats'].get('new', 0)} new sprites, {len(set(d['patches']))} frame-id patches, cut records restored "
                      f"{sum(x['restored'] for x in d['report'])}, left {sum(sum(x['left'].values()) for x in d['report'])}" + (" (direct animations first)" if first else ""))
            m = man["chars"]["%02X" % ch]                     # what the loader must do for this character (SPEC.md sections 3, 11, 12)
            m["loader"] = dict(ap8=True, ad8=bool(m.get("direct", {}).get("patches")), slot_table=m["slot_table"])
            if a.whole: print(f"   whole animations: {len(r['whole_kept'])} records kept stock with their animations (would have mixed)")
            print(f"{ch:2d} {aplib.NAMES[ch]:11s} sprites {r['stock_sprites']} -> {r['arc_sprites']}  file {len(r['nsp'])}  frames {r['old_nframes']} -> {len(r['sub2'])}  "
                  f"patches {len(r['recpatch'])}  left stock {r['unchanged'] + r['unpaired']}  check {tot} frames ok", flush=True)
        import selbuild
        r = selbuild.build(ctx, ps1)
        if r["bad"]: raise Fail("select screen: self-check failed (%d bad frames)" % r["bad"])
        open(os.path.join(a.out, "SP_SEL0.NSP"), "wb").write(r["nsp"]); open(os.path.join(a.out, "SELECT.AP8"), "wb").write(r["ap8"])
        man["select"] = dict(nsp="SP_SEL0.NSP", nsp_size=len(r["nsp"]), nsp_sha1=hashlib.sha1(r["nsp"]).hexdigest(), sections=r["sec"], tiles=r["tiles"], ap8="SELECT.AP8",
                             ap8_size=len(r["ap8"]), ap8_sha1=hashlib.sha1(r["ap8"]).hexdigest(), patches=len(r["patches"]), sprites_new=r["new"],
                             animations={"%04x" % (k - selbuild.BASE): list(v) for k, v in r["report"].items() if v[1] > 1})
        print("select screen: %d new sprites, %d frame-id patches, file %d bytes" % (r["new"], len(r["patches"]), len(r["nsp"])), flush=True)
        json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1, sort_keys=True)
        import shutil; shutil.rmtree(work, ignore_errors=True)
        print("done:", a.out)
    except Fail as ex:
        print("ERROR:", ex); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
