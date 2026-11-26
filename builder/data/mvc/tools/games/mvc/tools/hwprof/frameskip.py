"""FRAME SKIP (mktag.py --frameskip[=auto]): the engine's own catch-up (logic-only passes) switched on in battle and
extended to lags of 1..FSMAX vblanks.  Description in frameskip.S.  --frameskip: mode byte 0x8007b709 (OPTION line,
default OFF; OFF / AUTO / MAX); --frameskip=auto|=max: test discs.  Env FS_SMART=0: no sprite-change deferral.
Span: 0x80014774-0x800147dc (glue .rh, unused with --nostagefrag, asserted).  --hwprof discs use other spans.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "mshvsf", "tools", "speed")))
SRC = os.path.join(HERE, "frameskip.S")
CHUNKS = {"F": (0x80014774, 0x800147dc),                 # glue .rh (needs --nostagefrag)
          # the 8 MB build's spans (never in a 2 MB disc).  S1-S4 = the v2 planner (also in --hwprof test discs: the
          # profiler keeps 0x8003cf60 / 0x80030d14 / 0x8003ca3c / 0x8001a9e4), M1-M4 = the OPTION line (menu builds)
          "S1": (0x8005f87c, 0x8005f8bc), "S2": (0x80049c70, 0x80049ca8), "S3": (0x80049d84, 0x80049dbc),
          "S4": (0x8005f808, 0x8005f83c)}
DEBT = 0x8007b70a                     # option block + 0x22: unreferenced on the whole disc (refscan), session RAM
FSB = 0x8007b709                      # with --stageanim (cursor 16); without it 0x8007b708 (cursor 15), see layout()
GATE, LAG = 0x80022d74, 0x80022ecc
STOCK = {GATE: 0x8042b745, LAG: 0x00021403, LAG + 4: 0x24030001}     # lb v0,-0x48bb(v0); sra v0,v0,16; li v1,1


def jal(t): return struct.pack("<I", 0x0C000000 | (t >> 2 & 0x3ffffff))


MCHUNKS = {"M1": (0x8003cf60, 0x8003cfa4), "M2": (0x80030d14, 0x80030d54), "M3": (0x8003ca3c, 0x8003ca78),
           "M4": (0x8001a9e4, 0x8001aa1c)}     # menu builds only (--hwprof keeps these four)
OPD, OPD_BASE = "OPDEMO.ARC", 0x8009dfe4
DRAW_AT, DRAW_ORIG = 0x800a29c4, 0x0c028789                         # jal 0x800a1e24 (stock option-line draw)
WRAP = {0x800a2704: (0x28420010, 0x28420011),                       # stageanim's slti v0,v0,0x10 -> 0x11 (cursor 0..16)
        0x800a2708: (0x2402000f, 0x24020010)}                       # stageanim's li v0,0xf -> 0x10


def layout():
    """menu line slot: cursor 16 / y 0xd0 after STAGE ANIM, else cursor 15 / y 0xc8; FSB = block[0x11 + cursor]"""
    sa = "--stageanim" in sys.argv
    return (16, 0xd0) if sa else (15, 0xc8)


FS05 = "--fs05" in sys.argv           # fs05 (fx worker): value byte = optrows.byte("FRAME SKIP") (0x800858c9..; block + 0x20 /
                                      # 0x21 are the stock join mask / pause cursor); OPTION line drawn by optrows (OPDEMO
                                      # slack); the freed M1-M4 + stageanim's A span hold the PAUSE menu row (fspause.S).
PA = (0x80032964, 0x80032998)          # stageanim chunk A (its OPTION drawer is replaced by optrows under --fs05)
XSH = int(os.environ.get("FS_PXSH", "0x20"), 0)
PM2 = "--exopt" in sys.argv and "--fpsmeter" in sys.argv and "--nosmrow" not in sys.argv   # --nosmrow: no SPEED METER rows
# --nofskip (user 2026-11-24: FRAME SKIP removed from every variant): no catch-up hooks (stock vblank pacing = the old OFF),
# no FRAME SKIP row; with PM2 the PAUSE menu keeps its SPEED METER row alone (fspause2.S with one record, row 3)
NOFS = "--nofskip" in sys.argv   # EX OPTIONS + fps meter: 2nd PAUSE row SPEED METER (fspause2.S)
PB = (0x80032830, 0x80032864)          # stageanim chunk B (free under --fs05, its OPTION drawer is gone): the row's strings
PAUSE = {0x80029fb0: (0x0c0083c4, None),                            # draw: jal FONT -> jal pfont
         0x80029fb8: (0x2a020003, 0x2a020004),                      # slti v0,s0,3 -> 4 rows
         0x8002a1b8: (0x28420003, 0x28420004),                      # cursor wrap: slti v0,v0,3 -> 4
         0x8002a1bc: (0x24020002, 0x24020003)}                      # li v0,2 -> 3


def fsb(cur):
    if FS05:
        sys.path.insert(0, os.path.join(HERE, "..", "gameplay")); import optrows
        return optrows.byte("FRAME SKIP")
    return 0x8007b6f9 + cur


def force_mode():
    """--frameskip=auto -> 1, =max -> 2 (test discs, no OPTION line); --frameskip -> 0 (menu, default OFF)"""
    a = next((x for x in sys.argv if x.startswith("--frameskip")), "--frameskip")
    return {"--frameskip": 0, "--frameskip=auto": 1, "--frameskip=max": 2}[a]


def build(force):
    import slib
    menu = not force
    cur, y = layout()
    ch = dict(CHUNKS, **(MCHUNKS if menu else {}))
    src = open(SRC).read()
    if NOFS:
        assert FS05 and PM2 and menu, "--nofskip: the PAUSE SPEED METER row (--fs05 --exopt --fpsmeter)"
        p2 = open(os.path.join(HERE, "fspause2.S")).read()
        a, b = p2.index("RT:     .word"), p2.index("#@B")
        p2 = p2[:a] + "RT:     .word   SMB, ST1\nST1:    .word   2, PM0, PM1\n\n#@PA\n" + p2[b + 4:]
        ch = dict(MCHUNKS, PA=PA)
        src = p2
    elif not menu: src = src[:src.index("# ---- OPTION line")]
    elif FS05:
        src = src[:src.index("# ---- OPTION line")] + open(os.path.join(HERE, "fspause2.S" if PM2 else "fspause.S")).read()
        ch["PA"] = PA
        if PM2: ch["B"] = PB
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "fs.S"); open(p, "w").write(src)
        smb = 0
        if PM2:
            sys.path.insert(0, os.path.join(HERE, "..", "gameplay")); import optrows
            smb = optrows.byte("SPEED METER")
        return slib.chunks(p, ch, dict(FSB=fsb(cur), SMB=smb, XSH=XSH, FSFORCE=force_mode(), DEBT=DEBT, FSSMART=int(os.environ.get("FS_SMART", "1")),
                                       FONT=0x80020f10, STR_OFF=0x8009e174, FSCUR=cur, FSY=y))


def overlay_patches(opd_now):
    """OPDEMO patches for the menu line; opd_now(addr) -> u32 as the build has it (after --stageanim)"""
    assert "--hwprof" not in sys.argv, "--frameskip menu uses the --hwprof spans"
    if FS05: return []                                              # OPTION line: optrows.py
    cur, y = layout()
    wrap = WRAP if cur == 16 else {0x800a2704: (0x2842000f, 0x28420010), 0x800a2708: (0x2402000e, 0x2402000f)}
    for a, (o, n) in wrap.items(): assert opd_now(a) == o, ("cursor wrap word", hex(a))
    assert opd_now(DRAW_AT) == DRAW_ORIG, "OPDEMO draw call not stock"
    out, syms = build(False)
    p = [(a, struct.pack("<I", n)) for a, (o, n) in wrap.items()] + [(DRAW_AT, jal(syms["fsdraw"]))]
    return [(OPD, a - OPD_BASE, d) for a, d in p]


def exe_patches(force):
    import slib
    exe = open(os.path.join(HERE, "..", "..", "disc", "SLUS_010.59"), "rb").read()
    load = struct.unpack_from("<I", exe, 0x18)[0]
    exe_word = lambda a: struct.unpack_from("<I", exe, a - load + 0x800)[0]
    assert "--nostagefrag" in sys.argv, "--frameskip uses the .rh span 0x80014774: needs --nostagefrag"
    for a, w in STOCK.items(): assert exe_word(a) == w, ("frameskip site not stock", hex(a), hex(exe_word(a)))
    if NOFS and not PM2: return []                                 # --nofskip --nosmrow (finals): stock PAUSE menu, no hooks
    out, syms = build(force)
    if NOFS:                                                        # PAUSE row SPEED METER only, 4 rows
        extra = [(MCHUNKS[k][0], out[k]) for k in MCHUNKS] + [(PA[0], out["PA"])]
        for a, (o, n) in PAUSE.items():
            assert exe_word(a) == o, ("pause menu site not stock", hex(a), hex(exe_word(a)))
            extra.append((a, jal(syms["pfont"]) if n is None else struct.pack("<I", n)))
        return extra
    extra = [(CHUNKS[k][0], out[k]) for k in CHUNKS] + ([] if force else [(MCHUNKS[k][0], out[k]) for k in MCHUNKS])
    if FS05 and not force:                                          # PAUSE menu row
        extra.append((PA[0], out["PA"]))
        if PM2: extra.append((PB[0], out["B"]))
        for a, (o, n) in PAUSE.items():
            assert exe_word(a) == o, ("pause menu site not stock", hex(a), hex(exe_word(a)))
            if PM2 and n is not None: n += 1                    # 5 rows: slti 5 / wrap slti 5, li 4
            extra.append((a, jal(syms["pfont"]) if n is None else struct.pack("<I", n)))
    return extra + [(GATE, jal(syms["fs_gate"])),
            (LAG, jal(syms["fs_lag"]) + struct.pack("<I", 0x00021403))]
