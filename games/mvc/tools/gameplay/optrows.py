"""OPTION MODE rows of the tag build + where their values live (fs05, fx worker 2026-11-19; mktag.py --fs05).

Why: the old option lines kept their value in block[0x11 + cursor] (option block 0x8007b6e8; the stock LEFT / RIGHT
code writes there).  For cursors 15 / 16 that is 0x8007b708 / 0x8007b709 = stock variables: the player-join mask
(0x8005af0c) and the pause-menu cursor (0x8002a08c); and the game's reset (0x8005b778, back to the title) bzero's the
block -> the FRAME SKIP "back to OFF" bug.

Now: row r (cursor 15 + r) keeps its value in 0x800858c9 + r (dead EXE span after ASSIST_GATE 0x800858c8, zeroed by
mktag, never written by stock code -> session RAM until power-off; cold boot = 0 = every row's default).  OPDEMO's
LEFT / RIGHT +-1 is redirected there (rbase); one table-driven drawer draws all rows (optrows).  Both live in
OPDEMO.ARC's last-sector slack (1,292 B, loaded with the file; tools/speed5/slackchk.py), so they cost no EXE bytes.

Rows (order = cursor order; the build includes a row when its flag is on):
    STAGE ANIM  FULL / REDUCED / OFF        --stageanim     (battle reader: stageanim.S, 0x800858c9 = first row)
    FRAME SKIP  OFF / AUTO / MAX            --frameskip     (frameskip.py fsb())
    INTRO       STOCK / SIMPLE              --introopt      (hardware worker's battle side reads byte("INTRO"))
To add a row: append to rows() (label, values); its byte = byte(label).  Values: 0 = default (cold boot).
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "mshvsf", "tools", "speed")))
SRC = os.path.join(HERE, "optrows.S")
OPD, OPD_BASE, OPD_SIZE = "OPDEMO.ARC", 0x8009dfe4, 434932
SLACK = OPD_BASE + OPD_SIZE                       # 0x801082d8 .. sector end (1,292 B)
SLACK_END = OPD_BASE + (OPD_SIZE + 2047) // 2048 * 2048
PRIV = 0x800858c9
Y0 = 0xc8                                          # first row's y (3 rows: 0xc0, clear of the footer)
FONT = 0x80020f10
DRAW_AT, DRAW_ORIG = 0x800a29c4, 0x0c028789                      # jal 0x800a1e24 (stock option-line draw)
WRAP = {0x800a2704: 0x2842000f, 0x800a2708: 0x2402000e}           # slti v0,v0,0xf / li v0,0xe (stock: cursor 0..14)
RSITES = {0x800a263c: 0x00000000, 0x800a2640: 0x02031821,         # nop / addu v1,s0,v1 (RIGHT +1)
          0x800a266c: 0x00000000, 0x800a2670: 0x02031821}         # (LEFT -1)


def rows(argv=None):
    argv = sys.argv if argv is None else argv
    if "--exopt" in argv:                            # EX OPTIONS screen rows (exopt.py), fixed bytes (BYTES)
        import exopt
        return exopt.rows(argv)
    r = []
    if "--stageanim" in argv: r.append(("STAGE ANIM", ["FULL", "REDUCED", "OFF"]))
    if any(a == "--frameskip" for a in argv) and "--nofskip" not in argv:   # --nofskip (user 2026-11-24): no FRAME SKIP row
        r.append(("FRAME SKIP", ["OFF", "AUTO", "MAX"]))
    if "--introopt" in argv: r.append(("INTRO", ["STOCK", "SIMPLE"]))
    return r


# --exopt (EX OPTIONS, rc4.1+): every option byte at a FIXED address (docs/SPEED_TEAM.md byte map); readers use these
EXBLK, EXBLK_END = 0x8001175c, 0x8001176c        # fnscan dead span (the tagmode stub starts at 0x8001176c), zeroed by mktag
BYTES = {"STAGE ANIM": 0x800858c9, "FRAME SKIP": 0x800858ca, "INTRO": 0x800858cb,
         "SPEED METER": EXBLK, "ACHIEVEMENT POPUP": EXBLK + 1, "HI-RES FX": EXBLK + 2,
         "ASSIST": EXBLK + 3, "ASSIST MODE": EXBLK + 4,  # --asopt (asopt.py): 0 ON / 1 OFF, 0 NORMAL / 1 ROULETTE
         "ARCADE BALANCE": EXBLK + 5, "ARCADE SPEED": EXBLK + 6,
         "VOICE QUALITY": EXBLK + 7, "VOICE VOLUME": EXBLK + 7,
         "ASSISTS": EXBLK + 4,
         "INFINITE SUPER METER": EXBLK + 7}               # (infinite meter) --infmeter: 0 OFF / 1 ON (ach core: refill + no eval); excludes --voicehi / --voicevol                            # (assists row) --asrow1: 0 ROULETTE / 1 NORMAL / 2 OFF (= ASSIST MODE byte)   # (voice 3) --voicevol: 0 NORMAL / 1 +3 / 2 +6 dB                      # (voice 2) --voicehi: 0 NORMAL / 1 HIGH (tagload.c VQ_BYTE)   # --arcbal / --arcspeed (arcbal.py): both 0 OFF / 1 ON


def byte(label, argv=None):
    """RAM byte of a row's value (0 = default)"""
    argv = sys.argv if argv is None else argv
    if "--exopt" in argv: return BYTES[label]
    return PRIV + [l for l, v in rows(argv)].index(label)


def build(argv=None):
    import slib, tempfile
    R = rows(argv)
    assert 1 <= len(R) <= 3, "value bytes 0x800858c9..0x800858cb: at most 3 rows"
    tab, strs = "", ""
    for i, (lab, vals) in enumerate(R):
        assert 1 <= len(vals) <= 4
        ws = ["L%d" % i, "%d" % len(vals)] + ["V%d_%d" % (i, j) for j in range(len(vals))] + ["0"] * (4 - len(vals))
        tab += "        .word   " + ", ".join(ws) + "\n"
        strs += 'L%d:     .asciz  "%s"\n' % (i, lab) + "".join('V%d_%d:   .asciz  "%s"\n' % (i, j, v) for j, v in enumerate(vals))
    src = open(SRC).read().replace("ROWS:   ROWTAB", "ROWS:\n" + tab + strs)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "optrows.S"); open(p, "w").write(src)
        out, syms = slib.chunks(p, {"O": (SLACK, SLACK_END)}, dict(Y0=min(Y0, 0xd8 - 8 * len(R)), FONT=FONT, NROWS=len(R)))
    return out["O"], syms


def jal(t): return struct.pack("<I", 0x0C000000 | (t >> 2 & 0x3ffffff))


def overlay_patches(opd_now, argv=None):
    """[(file, offset, bytes)]; opd_now(addr) -> u32 of OPDEMO as the build has it (must be stock at our sites)"""
    n = len(rows(argv))
    code, syms = build(argv)
    for a, o in list(WRAP.items()) + list(RSITES.items()) + [(DRAW_AT, DRAW_ORIG)]:
        assert opd_now(a) == o, ("optrows: OPDEMO site not stock (another option line patch active?)", hex(a), hex(opd_now(a)))
    p = [(0x800a2704, struct.pack("<I", 0x28420000 | (15 + n))),          # cursor 0 .. 14 + n
         (0x800a2708, struct.pack("<I", 0x24020000 | (14 + n))),
         (DRAW_AT, jal(syms["optrows"])),
         (0x800a263c, jal(syms["rbase"])), (0x800a2640, bytes(4)),
         (0x800a266c, jal(syms["rbase"])), (0x800a2670, bytes(4)),
         (SLACK, code)]
    return [(OPD, a - OPD_BASE, d) for a, d in p]
