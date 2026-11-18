"""On-screen speed meter for hardware tests (source meter/meter.S, description at its top).

    parts(sym, on)   -> (exe_patches, ram_part): EXE stub + flag (chunk S, hook 0x80020940), battle-init copy MCOPY
                        (chunk C; tools/gameplay/tagmode.py jumps to it at its end: tagmode.patches(tail=...)),
                        and the RAM part (linked at MRAM = 0x801fe640) that mktag.py --meter puts behind the DSH1
                        decoder in the loader's strong payload.  sym = the loader's symbols (tl_strong, flushcache).
    symbols(sym)     -> {mflag, mcopy, ...}
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "meter", "meter.S")
STRONG_AT, MRAM, MEND = 0x801fe200, 0x801fe640, 0x801fea00
CHUNKS = {"S": (0x80024378, 0x800243d0),      # break-filled (deadtest attract, versus, cross)
          "C": (0x8003d91c, 0x8003d9c0),      # tail of the tagmode range (gameplay break-fill)
          "R": (MRAM, MEND)}
HOOK = (0x80020940, 0x0c004505)                # jal PutDispEnv in present
RANGES = [CHUNKS["S"], CHUNKS["C"], (HOOK[0], HOOK[0] + 4)]


def build(sym, on=False):
    sys.path.insert(0, HERE)
    import slib
    defs = dict(TLDBG=sym["tl_dbg"], MRAM=MRAM, MAGIC=0x5254454d, MSIZE=MEND - MRAM, MFLAG0=1 if on else 0,
                BLOBMETER=sym["tl_strong"] + (MRAM - STRONG_AT), FLUSHCACHE=sym["flushcache"])
    out, syms = slib.chunks(SRC, CHUNKS, defs)
    assert syms["mram"] == MRAM
    return out, syms


def parts(sym, on=False):
    out, syms = build(sym, on)
    exe = [(CHUNKS["S"][0], out["S"]), (CHUNKS["C"][0], out["C"]),
           (HOOK[0], struct.pack("<I", 0x0c000000 | (syms["mstub"] >> 2 & 0x3ffffff)))]
    return exe, out["R"], syms


def strong(dsh, ram):
    """the loader's strong payload with the meter behind the DSH1 decoder"""
    assert len(dsh) <= MRAM - STRONG_AT
    return dsh + bytes(MRAM - STRONG_AT - len(dsh)) + ram
