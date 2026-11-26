"""EXE patch: DSM1 + RLE tile decoder (common/dsp/dsmdec.S) for MSHvSF and MvC.

The unit .u_entry (dispatch + the game's RLE, rewritten) replaces the game's RLE decoder IN PLACE (same entry
address, so every call site - see games/mshvsf/docs/DSP.md - goes through it).  The DSM1 units go to free code
ranges (GAMES[game]["free"]).  The free ranges are static dead-code candidates (common/dsp/deadscan.py) and must
pass a break-fill boot + fight test before a release uses them (deadtest() below).

    python dsmpatch.py mshvsf|mvc [dsh [addr]]   assemble, print the patch ranges
patches(game, dsh=None) -> [(ram address, bytes)];  apply_ram(emu, game, dsh);  RANGES(game, dsh);  symbols(game, dsh)
dsh: MSHvSF always routes 'DSH1' sections (decoder at 0x801fe200, the argument is ignored).  MvC: None/False = DSM1 +
RLE only; True = also 'DSH1' -> the DSH1 decoder at the default 0x801fd800; an int = at that address (where the battle
loader copies games/mvc/work/dsp/dsh/dshdec.bin, built by `dsh.py build mvc [addr]` for the same address).
dsh_addr(game, dsh) -> the DSH1 decoder address of that build (or None).
"""
import os, sys, struct, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import toolenv
GCC = toolenv.mips_prefix()
SRC = os.path.join(HERE, "dsmdec.S")
UNITS = [".u_entry", ".u_rlit", ".u_setup", ".u_loop", ".u_run", ".u_fill", ".u_long"]

GAMES = {
    # dec = the game's RLE decoder [start, end); tab = per-slot pixel-section pointers (16 x u32)
    # dsh = address of the DSH1 decoder (common/dsp/dshdec.S, loaded by the battle loader; MSHvSF only)
    # 0x80013580-0x80013748 is reserved for the loader glue (games/mshvsf/docs/CODESPACE.md)
    "mshvsf": dict(dec=(0x8001bd68, 0x8001bec8), tab=0x80087d40, nslot=16, dsh=0x801fe200,
                   free=[(0x8001190c, 0x80011c28), (0x80013508, 0x80013580)]),
    # MvC: the allocation of the tag-hack build (games/mvc/tools/tagload/mktag.py, games/mvc/docs/CODESPACE.md):
    # first-fit gives loop -> 0x8001a874, setup -> 0x8001409c, run -> 0x800125f0, fill + long -> 0x80019160,
    # rlit -> 0x8002fa78 (within +-128 KB of the entry unit).  dsh_default = DSH1 decoder for patches("mvc", dsh=True)
    "mvc": dict(dec=(0x8001bd48, 0x8001bea8), tab=0x80092b30, nslot=16, dsh_default=0x801fd800,
                free=[(0x8001a874, 0x8001a96c), (0x8001409c, 0x80014128), (0x800125f0, 0x80012670), (0x80019160, 0x8001924c),
                      (0x8002fa78, 0x8002fafc)]),
}
OBJ = os.path.join(ROOT, "work", "dsp_obj")


def dsh_addr(game, dsh=None):
    cfg = GAMES[game]
    if "dsh" in cfg: return cfg["dsh"]
    if dsh is None or dsh is False: return None
    return cfg["dsh_default"] if dsh is True else int(dsh)


def _place(sizes, cfg):
    """first-fit the units (except entry) into the free ranges -> {unit: address}"""
    at = {".u_entry": cfg["dec"][0]}
    assert sizes[".u_entry"] <= cfg["dec"][1] - cfg["dec"][0], "entry unit %d > %d" % (sizes[".u_entry"], cfg["dec"][1] - cfg["dec"][0])
    free = [[cfg["dec"][0] + sizes[".u_entry"], cfg["dec"][1]]] + [list(r) for r in cfg["free"]]
    for u in sorted([u for u in UNITS[1:] if u in sizes], key=lambda u: -sizes[u]):
        for r in free:
            if r[1] - r[0] >= sizes[u]:
                at[u] = r[0]; r[0] += sizes[u]; break
        else:
            raise RuntimeError("no room for %s (%d bytes); free %s" % (u, sizes[u], free))
    return at


def build(game, dsh=None, dshptr=None, dsaptr=None):
    cfg = GAMES[game]
    os.makedirs(OBJ, exist_ok=True)
    assert dsaptr is None or dshptr is not None, "dsaptr needs dshptr"
    da = None if dshptr is not None else dsh_addr(game, dsh)
    tag = game + ("" if "dsh" in cfg or da is None else "_dsh%08x" % da)
    if dshptr is not None:
        assert "dsh" not in cfg, "pointer routes are for MvC"
        tag += "_hp%08x" % dshptr + ("_ap%08x" % dsaptr if dsaptr is not None else "")
    tag += "_%d" % os.getpid()                   # parallel test processes must not share object files
    o = os.path.join(OBJ, "dsmdec_%s.o" % tag)
    subprocess.check_call([GCC + "gcc", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", "-DTAB=0x%08x" % cfg["tab"],
                           "-DNSLOT=%d" % cfg["nslot"]] + (["-DDSH=0x%08x" % da] if da is not None else []) +
                          (["-DDSHPTR=0x%08x" % dshptr] if dshptr is not None else []) +
                          (["-DDSAPTR=0x%08x" % dsaptr] if dsaptr is not None else []) +
                          ["-c", SRC, "-o", o])
    game = tag
    sizes = {}
    for l in subprocess.check_output([GCC + "objdump", "-h", o]).decode().splitlines():
        p = l.split()
        if len(p) > 3 and p[1] in UNITS: sizes[p[1]] = int(p[2], 16)
    units = [u for u in UNITS if u in sizes]
    at = _place(sizes, cfg)
    ld = os.path.join(OBJ, "dsmdec_%s.ld" % game)
    open(ld, "w").write("SECTIONS {\n" + "".join("  %s 0x%08x : { *(%s) }\n" % (u, at[u], u) for u in units) +
                        "  /DISCARD/ : { *(.text) *(.data) *(.bss) *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.gnu.attributes) }\n}\n")
    elf = os.path.join(OBJ, "dsmdec_%s.elf" % game)
    subprocess.check_call([GCC + "ld", "-T", ld, o, "-o", elf])
    out = []
    for u in units:
        b = os.path.join(OBJ, "dsmdec_%s%s.bin" % (game, u))
        subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", u, elf, b])
        out.append((at[u], open(b, "rb").read()))
    sym = {}
    for l in subprocess.check_output([GCC + "nm", elf]).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16)
    return out, sym


_cache = {}


def _key(game, dsh, dshptr, dsaptr):
    return (game, None if dshptr is not None else dsh_addr(game, dsh), dshptr, dsaptr)


def patches(game, dsh=None, dshptr=None, dsaptr=None):
    """dshptr / dsaptr (MvC): route 'DSH1' / 'DSA1' sections through the decoder address stored in the RAM word at
    dshptr / dsaptr (jr; the decoders are position-independent) instead of a fixed `j` (dsh)"""
    key = _key(game, dsh, dshptr, dsaptr)
    if key not in _cache:
        out, sym = build(game, dsh, dshptr, dsaptr)
        import importlib.util
        spec = importlib.util.spec_from_file_location("dlib", os.path.join(ROOT, "tools", "speed", "decode", "dlib.py"))
        dl = importlib.util.module_from_spec(spec); spec.loader.exec_module(dl)
        for a, b in out:
            bad = dl.hazards(b, a)
            assert not bad, "load-delay hazards:\n" + "\n".join(bad)
        _cache[key] = (out, sym)
    return _cache[key][0]


def symbols(game, dsh=None, dshptr=None, dsaptr=None):
    patches(game, dsh, dshptr, dsaptr); return _cache[_key(game, dsh, dshptr, dsaptr)][1]


def RANGES(game, dsh=None, dshptr=None, dsaptr=None):
    return [(a, a + len(b)) for a, b in patches(game, dsh, dshptr, dsaptr)]


def apply_ram(emu, game, dsh=None, dshptr=None, dsaptr=None):
    for a, b in patches(game, dsh, dshptr, dsaptr): emu.poke(a, b)


# test layout (unicorn tests, in-game checks): MvC = the loader's pointer build, DSH1 at 0x801fd400, DSA1 right after
TEST = {"mvc": dict(dshptr=0x8001b4f0, dsaptr=0x8001b4f4, dsh_at=0x801fd400,
                    dsa_at=int(os.environ.get("DSA_AT", "0x801fd808"), 16))}     # DSA_AT=0x801fd900: room for dsxdec.S


def test_pokes(game):
    """everything a test pokes into RAM: [(addr, bytes)] = EXE patches + decoders + pointer words"""
    if game not in TEST:
        out = list(patches(game))
        a = dsh_addr(game, True)
        if a:
            import dsh as H
            out.append((a, H.decoder(game, a)[0]))
        return out
    t = TEST[game]
    import dsh as H, dsa as A
    hc = H.decoder(game, t["dsh_at"])[0]; ac = A.decoder(t["dsa_at"])[0]
    assert t["dsh_at"] + len(hc) <= t["dsa_at"]
    return list(patches(game, dshptr=t["dshptr"], dsaptr=t["dsaptr"])) + [
        (t["dsh_at"], hc), (t["dsa_at"], ac), (t["dshptr"], struct.pack("<2I", t["dsh_at"], t["dsa_at"]))]


def test_patches(game):
    """the EXE patch list of the test build"""
    return patches(game, **{k: v for k, v in TEST[game].items() if k.endswith("ptr")}) if game in TEST else patches(game)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "ptr":           # python dsmpatch.py mvc ptr DSHPTR [DSAPTR]
        g = sys.argv[1]; hp = int(sys.argv[3], 16); ap = int(sys.argv[4], 16) if len(sys.argv) > 4 else None
        for a, b in patches(g, dshptr=hp, dsaptr=ap): print("%08x-%08x %4d bytes" % (a, a + len(b), len(b)))
        print("total", sum(len(b) for a, b in patches(g, dshptr=hp, dsaptr=ap))); sys.exit()
    g = sys.argv[1]
    d = None if len(sys.argv) < 3 else (int(sys.argv[3], 16) if len(sys.argv) > 3 else True)
    for a, b in patches(g, d): print("%08x-%08x %4d bytes" % (a, a + len(b), len(b)))
    print("total", sum(len(b) for a, b in patches(g, d)), "entry", hex(symbols(g, d)["dec_entry"] & 0xffffffff),
          "dsh1 decoder", hex(dsh_addr(g, d)) if dsh_addr(g, d) else None)
