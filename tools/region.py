"""Region configuration for the X-Men vs. Street Fighter tag hack tools.

    XV_REGION=us (default)   SLUS-00627, disc/xvsf.bin               - every address is a US address
    XV_REGION=jp             SLPS-01284, disc/jap/...(Japan).bin     - addresses are mapped from the US
                                                                      ones by tools/regionmap.py

The patch modules and the loader keep US addresses in their source.  For another region
    A(addr)        maps a data address / table / variable          (regionmap.data)
    F(addr)        maps a function entry or jump target            (regionmap.entry)
    C(addr)        maps a position inside code (hook site)         (regionmap.code)
and tools/retarget.py converts the assembled patch lists.  For "us" all three are the identity
and none of that code runs, so the US build cannot change.
"""
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REGION = os.environ.get("XV_REGION", "us").lower()
assert REGION in ("us", "jp"), REGION

CONF = {
    "us": dict(bin=os.path.join(ROOT, "disc", "xvsf.bin"), cue=os.path.join(ROOT, "disc", "xvsf.cue"),
               files=os.path.join(ROOT, "disc", "files"), lmap=os.path.join(ROOT, "work", "lba_map.json"),
               exe="SLUS_006.27", serial="SLUS-00627", disc="xvsf_tag23", tagdir="tagload"),
    "jp": dict(bin=os.path.join(ROOT, "disc", "jap", "X-Men vs. Street Fighter - EX Edition (Japan).bin"),
               cue=os.path.join(ROOT, "disc", "jap", "X-Men vs. Street Fighter - EX Edition (Japan).cue"),
               files=os.path.join(ROOT, "work", "jap", "files"), lmap=os.path.join(ROOT, "work", "jap", "lba_map.json"),
               exe="SLPS_012.84", serial="SLPS-01284", disc="xvsfj_tag23", tagdir=os.path.join("tagload", "jp")),
}
BOOT_ITER = {"us": 23, "jp": 15}[REGION]      # harness: 150-frame steps (start tapped on odd ones) until the title screen waits
BIN, CUE, FILES, LMAP, EXE, SERIAL, DISC, TAGDIR = (CONF[REGION][k] for k in ("bin", "cue", "files", "lmap", "exe", "serial", "disc", "tagdir"))
EXEPATH = os.path.join(FILES, EXE)


def _rm():
    import regionmap
    return regionmap.get(REGION)


def A(addr):
    return addr if REGION == "us" else _rm().data(addr)[0]


def F(addr):
    return addr if REGION == "us" else _rm().entry(addr)[0]


def C(addr):
    return addr if REGION == "us" else _rm().code(addr)[0]


def ram(addr):
    """address used by a test harness: EXE variables are mapped, the dynamic area (stage heap and
    above, 0x80098000..) and the BIOS/low area are the same in every region"""
    if REGION == "us" or addr >= 0x80098000 or addr < 0x80010000: return addr
    r = _rm()
    try: return r.data(addr)[0]
    except Exception: pass
    try: return r.entry(addr)[0]
    except Exception: pass
    # HARNESS ONLY (never used by the build): an unreferenced address inside an array moves with the
    # array, i.e. with the nearest referenced symbol below it (at most 0x100 away)
    import bisect
    k = bisect.bisect_right(r.skeys, addr) - 1
    if k >= 0 and addr - r.skeys[k] <= 0x100: return r.seen[r.skeys[k]][0] + (addr - r.skeys[k])
    raise KeyError(f"{addr:08x}: no mapping for the harness")


_inv = None


def unram(v):
    """a pointer READ from the other region's RAM, turned back into the US address the harness scripts
    expect (only values that are the image of a referenced EXE data address: objects, tables)"""
    global _inv
    if REGION == "us" or not (0x80010000 <= v < 0x80098000): return v
    if _inv is None: _inv = {j: a for a, (j, n) in _rm().seen.items()}
    return _inv.get(v, v)
