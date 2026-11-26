"""EX OPTIONS (fx worker 2026-11-20, mktag.py --exopt; rc4.1+): our own options screen on the MAIN MENU, in the style of
the stock hidden EX OPTION screen; every custom option lives there, the stock OPTION MODE is back to stock (no optrows).

Main menu: the last line (menus.py: 6th, the old version line; with --ach mvcach.py: 7th) reads EX OPTIONS and is
selectable; its state-table entry -> exst (exopt.S).  The version text moves to the bottom of the EX OPTIONS screen.
The stock hidden EX OPTION (SELECT + START on OPTION) is unchanged.

Value bytes (fixed, optrows.BYTES; 0 = cold boot unless the build sets a power-on value):
    STAGE ANIM 0x800858c9, FRAME SKIP 0x800858ca, INTRO 0x800858cb, SPEED METER 0x8001175c, ACHIEVEMENT POPUP 0x8001175d,
    HI-RES FX 0x8001175e, ASSIST 0x8001175f, ASSIST MODE 0x80011760
Rows (a build shows a row when its feature flag is on):
    STAGE ANIM  FULL / REDUCED / OFF     --stageanim
    FRAME SKIP  OFF / AUTO / MAX         --frameskip
    INTRO       STOCK / SIMPLE           --introopt     (--introsimple: power-on SIMPLE, hw / intro worker)
    SPEED METER OFF / ON                 --fpsmeter     (dx worker's fps counter, tools/speed/meter.py, reads the byte)
    HI-RES FX   AUTO / OFF               --hiresfx      (rc4.2: full-res effects when the loader fits them; read at load)
    ACHIEVEMENT POPUP  ON / OFF          --ach          (freeze worker's popup reads the byte; unlocking unaffected)
    ASSIST      ON / OFF                 --asopt        (select + VS screen read it: OFF = no assist bits -> no assists loaded)
    ASSIST MODE NORMAL / ROULETTE        --asopt        (select: stock grid picker / stock roulette; tools/gameplay/asopt.py)
                ROULETTE / NORMAL        --asrou        (rc4.9: byte 0 = ROULETTE default, full arcade roulette rules)
Code: OPDEMO.ARC last-sector slack (optrows.SLACK, 1,292 B), loaded with the menu file.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "mshvsf", "tools", "speed")))
sys.path.insert(0, HERE)
import optrows
SRC = os.path.join(HERE, "exopt.S")
OPD, OPD_BASE = optrows.OPD, optrows.OPD_BASE
FONT, ICON, STRLEN, PAD = 0x80020f10, 0x80020bd4, 0x800145a8, 0x8002518c
SND_MOVE, SND_VAL, SND_EXIT = 0x80085a7c, 0x80085ae4, 0x80085828
FOOTER = 0x800a9d24                                   # "PRESS START OR   BUTTON TO EXIT" (stock EX OPTION string)
EXOPT = "--exopt" in sys.argv


def rows(argv=None):
    argv = sys.argv if argv is None else argv
    r = []
    if "--stageanim" in argv: r.append(("STAGE ANIM", ["FULL", "REDUCED", "OFF"]))
    if any(a == "--frameskip" for a in argv) and "--nofskip" not in argv:   # --nofskip (user 2026-11-24): no FRAME SKIP row
        r.append(("FRAME SKIP", ["OFF", "AUTO", "MAX"]))
    if "--introopt" in argv: r.append(("INTRO", ["STOCK", "SIMPLE"]))
    if "--fpsmeter" in argv and "--nosmrow" not in argv:   # --nosmrow (user 2026-11-24, finals): meter built, no row
        r.append(("SPEED METER", ["OFF", "ON"]))
    if "--hiresfx" in argv: r.append(("HI-RES FX", ["AUTO", "OFF"]))   # rc4.2: read at battle load (CPU / memory worker)
    if "--ach" in argv: r.append(("ACHIEVEMENT POPUP", ["ON", "OFF"]))
    if "--asopt" in argv and "--asrow1" in argv:     # (assists row, rc4.16): ONE row on the ASSIST MODE byte (0x80011760):
        r.append(("ASSISTS", ["ROULETTE", "NORMAL", "OFF"]))   # 0 ROULETTE (default) / 1 NORMAL / 2 OFF; the screen mirrors
    elif "--asopt" in argv:                      # OFF into the old ASSIST byte (exopt.S ASROW1) for asopt clr / asarc
        r.append(("ASSIST", ["ON", "OFF"]))
        r.append(("ASSIST MODE", ["ROULETTE", "NORMAL"] if "--asrou" in argv else ["NORMAL", "ROULETTE"]))   # rc4.9 --asrou
    if "--arcbal" in argv: r.append(("ARCADE BALANCE", ["OFF", "ON"]))   # arcbal.py: arcade meter / red-life / Onslaught rules (default OFF)
    if "--arcspeed" in argv: r.append(("ARCADE SPEED", ["OFF", "ON"]))   # arcbal.py: TURBO period 10 -> 6 (arcade 7/6)
    if "--infmeter" in argv: r.append(("INFINITE SUPER METER", ["OFF", "ON"]))   # (infinite meter) refill + no unlock: ach/core core.S INFB
    if "--voicehi" in argv: r.append(("VOICE QUALITY", ["NORMAL", "HIGH"]))
    if "--voicevol" in argv: r.append(("VOICE VOLUME", ["NORMAL", "+3 DB", "+6 DB"]))   # (voice 3) snd.c VOLROW at battle load   # (voice 2) tagload.c VOICEHI: read at battle load
    return r


def build(argv=None, ver=None):
    import slib, tempfile, menus
    argv = sys.argv if argv is None else argv
    R = rows(argv)
    assert 1 <= len(R) <= 9
    ver = ver or next((a.split("=", 1)[1] for a in argv if a.startswith("--ver=")), None) or menus.DEFAULT
    tab, strs = "", ""
    share = "--arcbal" in argv                       # arcbal: identical value strings emitted once (the 8th row must fit
    seen = {}                                        # before the --title stub at the slack end); without it = rc4.11 bytes
    for i, (lab, vals) in enumerate(R):
        assert 1 <= len(vals) <= 3
        if not share:
            ws = ["0x%08x" % optrows.BYTES[lab], "%d" % len(vals), "L%d" % i] + ["V%d_%d" % (i, j) for j in range(len(vals))] + ["0"] * (3 - len(vals))
            tab += "        .word   " + ", ".join(ws) + "\n"
            strs += 'L%d:     .asciz  "%s"\n' % (i, lab) + "".join('V%d_%d:   .asciz  "%s"\n' % (i, j, v) for j, v in enumerate(vals))
            continue
        vl = []
        strs += 'L%d:     .asciz  "%s"\n' % (i, lab)
        for j, v in enumerate(vals):
            if v not in seen:
                seen[v] = "V%d_%d" % (i, j)
                strs += '%s:   .asciz  "%s"\n' % (seen[v], v)
            vl.append(seen[v])
        ws = ["0x%08x" % optrows.BYTES[lab], "%d" % len(vals), "L%d" % i] + vl + ["0"] * (3 - len(vals))
        tab += "        .word   " + ", ".join(ws) + "\n"
    strs += 'TITLE:  .asciz  "EX OPTIONS"\nVER:    .asciz  "%s"\n' % ver
    lw = max(len(l) for l, v in R); vw = max(sum(len(x) + 1 for x in v) - 1 for l, v in R)
    CX = 0x100                                       # screen centre in the font's x (stock: title "EX OPTION" at 0xb8,
    LX = (CX - (lw + 2 + vw) * 4) & ~7               # footer at 0x84; Beetle shots: x 0x84 lands ~77 px into the image)
    VX = LX + (lw + 2) * 8
    DY = 0x14 if len(R) <= 5 else 0x10 if len(R) <= 8 else 0x0e   # 8-9 rows (--arcbal / --arcspeed): start higher, 9 tighter
    Y0 = 0x58 if len(R) <= 7 else 0x48
    src = open(SRC).read().replace("ROWS:   ROWTAB", "ROWS:\n" + tab + strs)
    defs = dict(FONT=FONT, ICON=ICON, STRLEN=STRLEN, PAD=PAD, SND_MOVE=SND_MOVE, SND_VAL=SND_VAL, SND_EXIT=SND_EXIT,
                FOOTER=FOOTER, NROWS=len(R), ASROW1=int("--asrow1" in argv), Y0=Y0, DY=DY, LX=LX, VX=VX, TITLEX=0xb4,
                VERX=CX - 4 * len(ver), VERY=0xc8)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "exopt.S"); open(p, "w").write(src)
        out, syms = slib.chunks(p, {"O": (optrows.SLACK, optrows.SLACK_END)}, defs)
    return out["O"], syms


def stub(argv=None):
    """state-table target of the EX OPTIONS menu item"""
    return build(argv)[1]["exst"]


def overlay_patches(argv=None, ver=None):
    """[(file, offset, bytes)]: the screen code in the OPDEMO slack (the menu entry: menus.py / mvcach.py)"""
    code, syms = build(argv, ver)
    return [(OPD, optrows.SLACK - OPD_BASE, code)]


def exe_patches():
    """EXE: the EX OPTIONS value block 0x8001175c-0x8001176c zeroed (fnscan dead span; cold boot = 0)"""
    return [(optrows.EXBLK, bytes(optrows.EXBLK_END - optrows.EXBLK))]


if __name__ == "__main__":
    code, syms = build(sys.argv[1:] or ["--stageanim", "--frameskip", "--introopt", "--fpsmeter", "--ach"])
    print(len(code), "of", optrows.SLACK_END - optrows.SLACK, "B; exst %08x" % syms["exst"])
