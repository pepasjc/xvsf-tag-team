"""On-screen speed meter for MvC hardware tests (source meter.S, description at its top).

    parts(sym, on)   -> (exe_patches, ram_part, symbols): EXE stub + flag (chunk S, hook 0x80022a84 = jal PutDrawEnv
                        in present 0x80022a0c), battle-init copy MCOPY (chunk C; tools/gameplay/tagmode.py jumps to it
                        at its end: tagmode.patches(tail=...)), and the RAM part (linked at MRAM) that mktag.py puts in
                        the loader's strong payload.  sym = the loader's symbols (tl_dbg, tl_strong, flushcache).
Uses the chunk assembler of games/mshvsf/tools/speed/slib.py (read-only).
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "fpsmeter.S" if "--fpsmeter" in sys.argv else "meter.S")   # --fpsmeter: user SPEED METER (dx worker)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "mshvsf", "tools", "speed")))
STRONG_AT, MRAM, MEND = 0x801fd400, 0x801fdc00, 0x801fe000        # loader strong payload: decoder, then the meter
MCOPY_SIZE = None    # bytes MCOPY copies per battle (None = up to MEND); --stageanim: only the meter (its RAM part after it
                     # would get the arena's stale blob tail - tl_main's strong copy is the only correct source)
CHUNKS = {"S": (0x8003bde8, 0x8003be40),      # dead spans: games/mvc/tools/tagload/fnscan.py
          "C": (0x80014128, 0x80014188),
          "R": (MRAM, MEND)}
HOOK = (0x80022a84, 0x0c004825)                # jal PutDrawEnv in present
RANGES = [CHUNKS["S"], CHUNKS["C"], (HOOK[0], HOOK[0] + 4)]


def build(sym, on=True):
    import slib
    defs = dict(TLDBG=sym["tl_dbg"], MRAM=MRAM, MAGIC=0x5254454d, MSIZE=MCOPY_SIZE or (MEND - MRAM), MFLAG0=1 if on else 0,
                BLOBMETER=sym["tl_strong"] + (MRAM - STRONG_AT), FLUSHCACHE=sym["flushcache"],
                KOAT=0x8000F040, KOMAGIC=0x314f434b)          # tools/tagload/kocache.py KO_AT / MAGIC (mktag asserts)
    if "--fpsmeter" in sys.argv:
        defs.update(fps_defs())
    src = SRC
    if os.environ.get("FPSM_DIAG") == "1" and "--fpsmeter" in sys.argv:   # TEST (rc4.8 tester): the meter shows the SPU-
        n = chr(10)                                  # fetch timeout counters (spsfe SPSFE_DIAG, DATA+20): 10 + halfword (loop4 +1, loop5 +0x100 -> shown as 60)
        s = open(SRC).read(); k = "        lw      $t1, 28($s0)" + n; assert s.count(k) == 1
        k2 = k + "        nop" + n; assert s.count(k2) == 1
        s = s.replace(k2, n.join(["        lui     $t1, 0x8001", "        lhu     $t1, -0xac($t1)", "        nop",
                                  "        addiu   $t1, $t1, 10"]) + n)
        src = os.path.join(os.environ.get("TEMP", HERE), "fpsmeter_diag.S"); open(src, "w").write(s)
    out, syms = slib.chunks(src, CHUNKS, defs)
    assert syms["mram"] == MRAM
    return out, syms


def fps_defs():
    """--fpsmeter: option byte OPTB = optrows row "SPEED METER" (fx worker) when it exists, else the next row byte
    (env FPS_OPTB=hex overrides; without the row: 0x8000F01C, test discs poke it); FRAME SKIP byte FSB (FSMASK 0 without that row); place X0 / Y0 (bottom left, above the
    P1 hyper-combo level digit)"""
    sys.path.insert(0, os.path.join(HERE, "..", "gameplay")); import optrows
    names = [l for l, v in optrows.rows()]
    optb = optrows.byte("SPEED METER") if "SPEED METER" in names else 0x8000F01C   # no row yet: kernel byte (achbuild
    # SPANS 0x8000F010-F040, unclaimed; zero at boot, kept until power-off) - test discs poke it
    if "--nosmrow" in sys.argv: optb = optrows.BYTES["SPEED METER"]   # finals: no row; the EX block byte stays 0 (meter off)
    optb = int(os.environ.get("FPS_OPTB", "0"), 16) or optb
    fs = "FRAME SKIP" in names
    return dict(OPTB=optb, FSB=optrows.byte("FRAME SKIP") if fs else optb, FSMASK=0xff if fs else 0, X0=8, Y0=198)


def parts(sym, on=True):
    out, syms = build(sym, on)
    exe = [(CHUNKS["S"][0], out["S"]), (CHUNKS["C"][0], out["C"]),
           (HOOK[0], struct.pack("<I", 0x0c000000 | (syms["mstub"] >> 2 & 0x3ffffff)))]
    return exe, out["R"], syms


def strong(dsh, ram):
    """the loader's strong payload: decoder at STRONG_AT, the meter at MRAM"""
    assert len(dsh) <= MRAM - STRONG_AT
    return dsh + bytes(MRAM - STRONG_AT - len(dsh)) + ram
