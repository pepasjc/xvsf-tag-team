"""MSHvSF 1.1 options (mshfeat 2026-11-20; MvC's EX OPTIONS design, games/mvc/tools/gameplay/exopt.py).

    --exopt      EX OPTIONS: a main-menu item (after GALLERY) with its own screen holding every custom option; the
                 stock OPTION screen is stock again (1.0's SPEED METER line moves here).  Needs --meter.
                 Pause menu (START, then SELECT): rows after QUIT for FRAME SKIP (with --frameskip) and SPEED METER.
    --frameskip  FRAME SKIP OFF / AUTO / MAX (default OFF): in a fight, a pass after a lag runs the logic only
                 (opts.S fs_d .. fs_prs; running fights only).  Needs --exopt.
    --stageanim  STAGE ANIM ON / OFF (default ON): OFF holds the animation frames of the stage's objects in a fight
                 (opts.S sa_tk: the animation step holds; visual only).  Needs --exopt.
    --achpop     ACHIEVEMENT POPUP ON / OFF (default ON): OFF draws no popup and plays no sound; unlocks and the
                 memory-card record are unchanged (tools/ach/port.c PORT_POPBYTE).  Needs --exopt and --ach.
    --arcbal     ARCADE BALANCE OFF / ON (default OFF): the arcade's meter / block meter / counter-hit / per-character
                 defence numbers (arcbal.py; OFF = the stock words).  Needs --exopt.
    --infmeter   INFINITE SUPER METER OFF / ON (default OFF): ON holds every fighter's super meter (both teams, point
                 and partner, human and CPU) at the maximum, level 3 (obj +0x258 = 3, +0x256 = 0, the game's own capped
                 state) while fighting; refilled once per logic pass from the main-frame hook 0x80020ba8 (opts.S
                 im_d, in front of FRAME SKIP's fs_d; with --frameskip at IM2).  A cheat: the
                 achievements see no human side while ON (port.c PORT_INFBYTE).  Needs --exopt.
    --nosmrow    (finals, user 2026-11-24) no SPEED METER row in EX OPTIONS nor in the pause menu; the meter stays built
                 (its flag word holds the option bytes) and is never shown.  Dev / test builds keep the row.
    --afrow      (8 MB discs only, added by tools/ap8/mkap8.py with --exopt; 2026-11-24) last row ARCADE FRAMES ON / OFF
                 (default ON, option byte OPTB + 9 = AFO, 1 = OFF: ap8.c AFOPT loads the stock SP_PLxx.DSP / no AP8 for the
                 next battle's characters); shown only on an 8 MB console (row count NROWS - 1 + tl_dbg[15], exopt.S at
                 16($sp)).  The 2 MB builds (no --afrow) are byte-identical to before.
    --excard     (2026-11-24, user rule for all games) the EX OPTIONS rows are saved with the game's own memory card save
                 and restored on load (excard.S): file BASLUS-00793-MSHVSSF image 0x4f0 = 'X' 'O' 1, STAGE ANIM, ACHIEVEMENT
                 POPUP, ARCADE BALANCE, INFINITE SUPER METER, ARCADE FRAMES (OPTB +2 +3 +6 +7 +9) inside the game's XOR
                 range (0x100..0x4fb, sum at 0x4fc); hooks = the two OPE.ARC / OPDEMO.BIN calls of the XOR setter / checker;
                 stock / older saves load and give the defaults (0); ARCADE BALANCE's words follow the loaded byte
                 (abapply).  One layout for 2 MB and 8 MB.
    (--fpsmeter  the SPEED METER shows game loops / s, + pictures / s while FRAME SKIP drops some: tools/speed/meter.py)

Option bytes (OPTB = the word after the speed meter's flag byte, meter chunk S = dead span 0x80024378-0x800243d0,
docs/CODESPACE.md; EXE bytes, so 0 = default at power-on and kept until power-off):
    OPTB+0 SPEED METER (the meter's flag)  +1 FRAME SKIP  +2 STAGE ANIM  +3 ACHIEVEMENT POPUP  +6 ARCADE BALANCE
    +7 INFINITE SUPER METER (IMO)  +9 ARCADE FRAMES (AFO, 8 MB discs)
    +4 / +5 / +8 FRAME SKIP state (pass skipped, skips in a row, lag baseline)
Code: EXE pieces (opts.S) packed into RANGES (menus.py's OPTION-line ranges: unused with --exopt; the stock pause-menu
draw routines 0x80029404-0x80029554, replaced by one routine in opts.S); the EX OPTIONS screen (exopt.S) in the
last-sector slack of OPE.ARC (RAM SLACK..SLACK_END while the menu is loaded).
"""
import os, sys, struct, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(GAME, "tools", "speed"))
SRC_EXE, SRC_SCR = os.path.join(HERE, "opts.S"), os.path.join(HERE, "exopt.S")
SRC_CARD = os.path.join(HERE, "excard.S")             # --excard: EX OPTIONS rows in the game's card save
CARD_SV, CARD_LD = (0x80098808, 0x80099098), (0x80098998, 0x800990f8)   # OPE.ARC call sites (jal setter / checker)
OPD_BASE = 0x80094800                                  # OPDEMO.BIN (the same overlay as OPE.ARC entry 0)
PRINT, SFX, PAD1 = 0x80022e20, 0x8007b2cc, 0x8002370c
MAXSTR = 0x800283c8                                    # "MAX" (EXE string)
ARC, ARC_BASE, ARC_SIZE = "OPE.ARC", 0x800947cc, 0x15ca94  # loaded whole by the menu (OPDEMO = entry 0 at +0x34)
SLACK, SLACK_END = ARC_BASE + ARC_SIZE, ARC_BASE + (ARC_SIZE + 2047) // 2048 * 2048
EXST = SLACK                                           # the menu state handler (first in exopt.S)
METER_S_END = 0x800243d0                               # end of the meter's chunk S (tools/speed/meter.py CHUNKS["S"])
# EXE ranges: menus.py RANGES (its OPTION lines are not built with --exopt) + the pause-menu draw routines
import menus, arcbal
RANGES = dict(menus.RANGES)
RANGES["p"] = (0x80029404, 0x800296bc)                 # stock pause menu: draw, QUIT GAME! draw, input (opts.S)
PAUSE = {0x80029a00: (0x0c00a555, "pmenu"),            # jal 0x80029554 (input) -> jal pmenu
         0x80029830: (0x0c00a52a, "pconf")}            # jal 0x800294a8 (QUIT GAME! draw) -> jal pconf
FS_SITES = {0x80020ba8: 0x8442075a,                    # lh v0,0x75a(v0) -> jal fs_d
            0x80020c54: 0x0c008232}                    # jal 0x800208c8 (present) -> jal fs_prs
PRE_AT = 0x80020c44                                    # jal 0x8008555c (or decode-ahead's ah_frame) -> jal fs_pre
SK = 0x5ec7a11d                                         # stock words stored masked (no game words in the sources)
SA_AT, SA_ORIG = 0x8004a070, (0x797a5ef5 ^ SK, 0xf178a10d ^ SK)  # animation step entry -> j sa_tk; nop
IMO = 7                                                 # OPTB + 7: INFINITE SUPER METER (0 OFF = power-on, 1 ON)
AFOPT_OPTB = 0x800243c0                                 # tools/ap8/mkap8.py OPTB (ap8.c -DAFOPT = OPTB + AFO)
AFO = 9                                                 # OPTB + 9: ARCADE FRAMES (8 MB discs, --afrow from mkap8.py; 0 ON = power-on, 1 OFF)
TLDBG = None                                            # tl_dbg (set by mkap8.py): the row shows only when [15] != 0 (8 MB found)
IM_AT, IM_ORIG = 0x80020ba8, 0x8442075a                 # main frame: lh v0,0x75a(v0) (or FRAME SKIP's jal fs_d) -> jal im_d
IM2 = (0x8003d978, 0x8003d9c0)                         # im_d (with --frameskip): the unused tail of the meter's chunk C (tools/speed/meter.py:
                                                        # mcopy ends at 0x8003d978; tagmode range 0x8003d8e0-0x8003d9c0, break-filled)


def flags(argv=None):
    argv = sys.argv if argv is None else argv
    f = dict(ex="--exopt" in argv, fs="--frameskip" in argv, sa="--stageanim" in argv, pop="--achpop" in argv,
             ab="--arcbal" in argv, im="--infmeter" in argv, card="--excard" in argv)
    if f["card"]: assert f["ex"], "--excard needs --exopt"
    if f["fs"] or f["sa"] or f["pop"] or f["ab"] or f["im"]:
        assert f["ex"], "--frameskip / --stageanim / --achpop / --arcbal / --infmeter need --exopt"
    if f["ex"]: assert "--meter" in argv, "--exopt: SPEED METER is the meter's flag (needs --meter)"
    if f["pop"]: assert "--ach" in argv, "--achpop needs --ach"
    return f


def rows(argv=None):
    """EX OPTIONS rows: (label, option offset, values)"""
    f = flags(argv)
    r = []
    if f["sa"]: r.append(("STAGE ANIM", 2, ["ON", "OFF"]))
    if f["fs"]: r.append(("FRAME SKIP", 1, ["OFF", "AUTO", "MAX"]))
    if "--nosmrow" not in (sys.argv if argv is None else argv): r.append(("SPEED METER", 0, ["OFF", "ON"]))
    if f["pop"]: r.append(("ACHIEVEMENT POPUP", 3, ["ON", "OFF"]))
    if f["ab"]: r.append(("ARCADE BALANCE", arcbal.OPT, ["OFF", "ON"]))     # last: the other rows keep their places
    if f["im"]: r.append(("INFINITE SUPER METER", IMO, ["OFF", "ON"]))      # after it (same reason)
    if "--afrow" in (sys.argv if argv is None else argv):                    # 8 MB discs only, last: hidden on 2 MB consoles
        r.append(("ARCADE FRAMES", AFO, ["ON", "OFF"]))
    return r


MENU8 = ["BATTLE", "VERSUS", "TRAINING", "HERO BATTLE", "ACHIEVEMENTS", "OPTION", "GALLERY", "EX OPTIONS"]   # (--ach)


def jal(t): return struct.pack("<I", 0x0C000000 | (t >> 2 & 0x3ffffff))


def exe_build(optb, pre, argv=None, abapply=0):
    import slib
    f = flags(argv)
    assert optb % 4 == 0 and optb + 12 <= METER_S_END, hex(optb)
    text = open(SRC_EXE).read()
    P = slib.pieces(text)
    drop = ([] if f["fs"] else ["fs_d", "fs_d1", "fs_d2", "fs_pre", "fs_prs"]) + ([] if f["sa"] else ["sa_tk"]) + (
        [] if f["im"] else ["im_d"])
    src = "".join(v for k, v in P.items() if k not in drop)
    if f["ab"]: src += arcbal.pieces()                  # M4 data (char index, factor rows)
    if f["card"]: src += open(SRC_CARD).read()          # --excard: card save / load hooks (excard.S)
    sm = int("--nosmrow" not in (sys.argv if argv is None else argv))
    npr = 3 + sm + int(f["fs"])                         # + SPEED METER (+ FRAME SKIP)
    defs = dict(OPTB=optb, FS=int(f["fs"]), SM=sm, SA=int(f["sa"]), IMO=IMO, NPR=npr, PRE=pre, PRINT=PRINT, SFX=SFX, PAD1=PAD1,
                MAXSTR=MAXSTR, PLX=0x88, PVX=0x148, SVSET=CARD_SV[1], LDCHK=CARD_LD[1], ABCARD=int(f["ab"] and f["card"]),
                ABAPPLY=abapply)
    im2 = f["im"] and f["fs"]                           # im_d at its own fixed place IM2 (the other pieces keep theirs)
    if im2:
        src = "".join(v for k, v in P.items() if k not in drop + ["im_d"])
        if f["ab"]: src += arcbal.pieces()
        if f["card"]: src += open(SRC_CARD).read()
        defs["im_d"] = IM2[0]
    out, syms, plan = slib.pack(src, RANGES, defs)
    if im2:
        o2, s2, p2 = slib.pack(P["im_d"], {"m": IM2}, dict(defs, fs_d=syms["fs_d"]))
        assert s2["im_d"] == IM2[0]
        out["m"], plan["m"] = o2["m"], p2["m"]; syms.update(s2)
    return out, syms, plan, npr


def exe_patches(optb, word, argv=None):
    """[(addr, bytes)] for the EXE.  word(addr) -> u32 of the EXE as the build has it so far (sites must be stock or,
    for the pre-decode call, a jal)"""
    f = flags(argv)
    w = word(PRE_AT); assert w >> 26 == 3, "pre-decode call site %08x" % w
    pre = 0x80000000 | (w & 0x3ffffff) << 2
    out, syms, plan, npr = exe_build(optb, pre, argv)
    if f["card"] and f["ab"]:                           # ldfin calls abapply (EX OPTIONS screen code): its address from
        ab = screen(optb, syms, argv)[1]["abapply"]     # the screen built with these EXE symbols, then the final pack
        out2, syms2, plan2, npr = exe_build(optb, pre, argv, ab)
        assert plan2 == plan and all(syms2[k] == v for k, v in syms.items() if k != "ABAPPLY"), "excard: second pack moved"
        out, syms, plan = out2, syms2, plan2
        syms["abapply_card"] = ab
    p = [(dict(RANGES, m=IM2)[k][0], b) for k, b in out.items()]
    p.append((optb + 1, bytes(11)))                     # option bytes + FRAME SKIP state: 0 (dead code there)
    for a, (o, s) in PAUSE.items():
        assert word(a) == o, ("pause menu site not stock", hex(a), hex(word(a)))
        p.append((a, jal(syms[s])))
    if f["fs"]:
        for a, o in FS_SITES.items(): assert word(a) == o, ("frame skip site", hex(a), hex(word(a)))
        p += [(0x80020ba8, jal(syms["fs_d"])), (0x80020c54, jal(syms["fs_prs"])), (PRE_AT, jal(syms["fs_pre"]))]
    if f["im"]:                                         # im_d first, then FRAME SKIP's fs_d (or the replaced load)
        assert word(IM_AT) == IM_ORIG, ("infinite meter site", hex(word(IM_AT)))
        p = [x for x in p if x[0] != IM_AT] + [(IM_AT, jal(syms["im_d"]))]
    if f["sa"]:
        assert (word(SA_AT), word(SA_AT + 4)) == SA_ORIG, "animation step site"
        p.append((SA_AT, struct.pack("<2I", 0x08000000 | (syms["sa_tk"] >> 2 & 0x3ffffff), 0)))
    if f["ab"]:                                         # sites must be stock; the EXE keeps them: cold boot = OFF
        arcbal.exe_patches(word, syms)                  # (user 2026-11-22; abapply writes the set on the row's key press)
    return p, syms, plan


def card_hooks(syms):
    """--excard: [(call site, stock word, new word)] in the OPE.ARC / OPDEMO.BIN overlay"""
    return [(CARD_SV[0], jal(CARD_SV[1]), jal(syms["svhook"])), (CARD_LD[0], jal(CARD_LD[1]), jal(syms["ldhook"]))]


def screen(optb, xsyms, argv=None):
    """the EX OPTIONS screen for the OPE.ARC slack -> (bytes, symbols)"""
    import slib
    R = rows(argv)
    assert 1 <= len(R) <= 6
    tab, strs = "", ""
    lw = max(len(l) for l, o, v in R)
    vw = max(sum(len(x) + 1 for x in v) - 1 for l, o, v in R)
    # --infmeter: the value strings are the resident pause-row ones (opts.S pv_*, "MAX" in the EXE): the slack is full
    ev = dict(OFF=xsyms.get("pv_off"), ON=xsyms.get("pv_on"), AUTO=xsyms.get("pv_auto"), MAX=MAXSTR) if flags(argv)["im"] else {}
    vname = lambda i, j, v: "0x%08x" % ev[v] if ev.get(v) else "V%d_%d" % (i, j)
    for i, (lab, off, vals) in enumerate(R):
        xs = [0]
        for v in vals[:-1]: xs.append(xs[-1] + len(v) + 1)
        tab += "        .word   L%d\n        .byte   %d, %d, %d, %d\n        .word   %s\n" % (
            i, off, len(vals), xs[1] if len(xs) > 1 else 0, xs[2] if len(xs) > 2 else 0,
            ", ".join([vname(i, j, v) for j, v in enumerate(vals)] + ["0"] * (3 - len(vals))))
        strs += 'L%d:     .asciz  "%s"\n' % (i, lab) + "".join(
            'V%d_%d:   .asciz  "%s"\n' % (i, j, v) for j, v in enumerate(vals) if not ev.get(v))
    strs += 'TITLE:  .asciz  "EX OPTIONS"\n        .align  2\n'
    if "--ach" in (sys.argv if argv is None else argv):     # the achievements' 8-line main menu (port.c PORT_MENUTAB)
        strs += "MENUTAB:\n" + "".join('        .ascii  "%s"\n        .space  %d\n' % (m, 13 - len(m)) for m in MENU8)
        strs += "        .align  2\n"
    CX = 0x100                                          # the text routine's x of the picture centre (popup: 255 - 4 n)
    LX = (CX - (lw + 2 + vw) * 4) & ~7
    defs = dict(SFX=SFX, PRINT=PRINT, XKEY=xsyms["xkey"], ROWVAL=xsyms["rowval"], NROWS=len(R),
                TITLEX=CX - 8 * len("EX OPTIONS"), FOOTX=CX - 4 * len("PRESS START BUTTON TO EXIT"), FOOTY=0xd0,
                LX=LX, VX=LX + (lw + 2) * 8, Y0=0x60 if len(R) <= 4 else 0x58)
    defs.update(ARCBAL=int(flags(argv)["ab"]), OPTB=optb)
    src = open(SRC_SCR).read().replace("ROWS:   ROWTAB", "ROWS:\n" + tab + strs)
    if "--afrow" in (sys.argv if argv is None else argv):
        # ARCADE FRAMES is the last row and shown only on an 8 MB console (tl_dbg[15] = 1): row count n = NROWS - 1 +
        # tl_dbg[15], kept at 16($sp) for the frame (cursor wrap and the draw loop read it)
        assert R[-1][0] == "ARCADE FRAMES" and TLDBG, "--afrow: last row / tl_dbg"
        assert optb == AFOPT_OPTB, "--afrow: ap8.c AFOPT is OPTB 0x%x + 9, the build has 0x%x" % (AFOPT_OPTB, optb)
        defs["TLDBG15"] = TLDBG + 15
        reps = [("2:      lbu     $s2, 2($s0)                     # cursor",
                 "2:      lui     $t0, %hi(TLDBG15)\n        lbu     $t1, %lo(TLDBG15)($t0)\n        lbu     $s2, 2($s0)\n"
                 "        addiu   $t1, $t1, NROWS - 1\n        sb      $t1, 16($sp)"),
                ("        addiu   $s2, $s2, NROWS - 2             # UP: -1 (mod NROWS)",
                 "        lbu     $t2, 16($sp)\n        addiu   $s2, $s2, -2\n        addu    $s2, $s2, $t2"),
                ("3:      sltiu   $t0, $s2, NROWS", "3:      lbu     $t2, 16($sp)\n        nop\n        sltu    $t0, $s2, $t2"),
                ("        addiu   $s2, $s2, -NROWS", "        subu    $s2, $s2, $t2"),
                ("        addiu   $s3, $s3, 1\n        slti    $t0, $s3, NROWS",
                 "        lbu     $t0, 16($sp)\n        addiu   $s3, $s3, 1\n        slt     $t0, $s3, $t0")]
        for a, b in reps:
            assert src.count(a) == 1, a
            src = src.replace(a, b)
    ab = flags(argv)["ab"]                              # ARCADE BALANCE: the swap call + routine + runs (arcbal.py)
    src = src.replace("ABCALL\n", arcbal.CALL if ab else "").replace(
        "ABCODE\n", arcbal.CODE.replace("ABRUNS_TAB\n", arcbal.runtab(xsyms)) if ab else "")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "exopt.S"); open(p, "w").write(src)
        out, syms = slib.chunks(p, {"X": (SLACK, SLACK_END)}, defs)
    assert syms["exst"] == EXST
    return out["X"], syms


if __name__ == "__main__":
    a = sys.argv[1:] or ["--exopt", "--meter", "--frameskip", "--stageanim", "--achpop", "--ach"]
    stock = {0x80020c44: 0x0c021557}
    W = {**{k: v[0] for k, v in PAUSE.items()}, **FS_SITES, SA_AT: SA_ORIG[0], SA_AT + 4: SA_ORIG[1], **stock}
    X = open(os.path.join(GAME, "disc", "SLUS_007.93"), "rb").read()      # other sites: the stock EXE
    p, syms, plan, = exe_patches(0x800243c0, lambda x: W.get(x, struct.unpack_from("<I", X, x - 0x80010000 + 0x800)[0]), a)
    print("EXE plan:", plan)
    print({k: hex(v) for k, v in syms.items() if not k.startswith(("L", "V", "pv_", "pl_"))})
    scr, ss = screen(0x800243c0, syms, a)
    print("screen", len(scr), "of", SLACK_END - SLACK, "bytes at %08x" % SLACK)
