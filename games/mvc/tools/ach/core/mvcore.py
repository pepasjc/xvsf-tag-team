"""MvC built-in achievements on the rc4 line (freeze worker, 2026-11-20): mktag.py --ach uses this (the old runtime's
kernel regions crash a real PS1; see docs/ACHIEVEMENTS.md "rc4 core").

    MOD = module(ver)                     the menu module (bytes), linked at corebuild.MOD_AT = the end of OPDEMO.ARC in RAM
    opd = opdemo(opd_file_bytes, MOD)     a copy of OPDEMO.ARC with the module after its last sector (a disc item; the
                                          game's file table entry OPD_INDEX points at it: the menu loads the module)
    parts(read_exe, read_hdr, read_ovl, ver) -> dict(exe, ovl, pc0, ram, info, ovl_file, sym)

  * resident core (core.S, hand-written MIPS: host/asmdiff.py vs core.c, core.c vs rcheevos) packed into the kernel spans
    corebuild.SPANS (real-PS1 proven; dx stash RAM given up with --ach), copied at boot by the shared guard stub
    (tools/ach/achbuild.copy_stub_spans: ROM-date check = nothing installed on PS2 / PS3, pattern guard, the hook word
    0x80022fe8 written only when installed);
  * OPDEMO.ARC stays menus.py's on the disc: when the main menu is up with menus.py's state table, the core calls the
    module, which writes the menu words (mvcach.menu_patch: 7 lines from its own table, ACHIEVEMENTS = state 5 = its
    stub at MOD_AT + 0x28); a refused guard = the plain menu.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..")]
import corebuild, achbuild
import mvcach
menus = mvcach.menus
COPY_AT, COPY_END = mvcach.COPY_AT, mvcach.COPY_END
OVL_FILE, OVL_BASE = mvcach.OVL_FILE, mvcach.OVL_BASE
assert OVL_BASE == corebuild.OPD_BASE
OPD_INDEX, FTAB = 0x156, 0x800255e4          # the game's file table (8-byte entries: BCD MSF, size); OPDEMO.ARC's entry
STOCK = {0x800a2a78: 0x3c02800b, 0x800a2a80: 0x24525bb4, 0x800a2afc: 0x26730014, 0x800a2b04: 0x2a220006, 0x800a2b0c: 0x2652000b}
if menus.VSMENU:                                  # (rc4.15) VERSUS CPU row: more stock words the module writes
    STOCK.update({0x800a2a74: 0x24130078})
    STOCK.update({0x800a2d50 + 4 * k: w for k, w in enumerate((0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~,
                                                                 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~))})
NLINES = 8 if menus.VSMENU else 7
jal = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)
_core = []
MSYM = {}                                         # the module's symbols (module()), exported as "mod." + name


def menus5(ver=None):
    return struct.unpack("<9I", dict(menus.ram_patches(ver or menus.DEFAULT))[mvcach.STATES])[5]


GATE_ST6, GATE_EXST, GATE_NOOP = 0x800b5c10, 0x801082d8, 0x800a2df8   # --titlefix gate: menus.py state-table [6] = exst (exopt,
                                                                       # slack start), the stock no-op handler (parts() asserts)
# --modreload: the attract intro animation buffers over 0x80102e14-0x8010d614 (OPDEMO's top, the slack, the module) and the
# menu entered from it does not read OPDEMO.ARC again.  The core reads the copy's tail (from the sector holding the end of the
# stock file = the slack) again through a private file-table entry {BCD msf, size} at RL_AT (EXE, SDK copyright string before
# the --titlefix stub; mktag.py writes it once the copy's LBA is known): RD index RL_INDEX (negative: FTAB + 8 * index = RL_AT).
RL_AT = 0x8001d0f4
RL_INDEX = (RL_AT - 0x800255e4) // 8
RL_SECTOR = corebuild.OPD_SIZE // 2048                 # 212: RAM 0x80107fe4 .. (stock bytes up to the slack, read back too)
RL_DEST = corebuild.OPD_BASE + RL_SECTOR * 2048
assert 0x800255e4 + 8 * RL_INDEX == RL_AT
# --menufont (2026-11-25): the main-menu font page (BATTLE.TEX rows 32-63) re-read + LoadImage once per menu entry (core.S mfont)
MF_AT = RL_AT + 8                                      # 2nd private entry right after --modreload's (stock SDK string)
MF_INDEX = (MF_AT - 0x800255e4) // 8
MF_BUF, MF_LATCH, MF_SECTOR, MF_SIZE = 0x80092c40, 0x8000ffdc, 4, 8192
MF_SUM = 0x7cbe1a48                                  # --menufont2: word sum of BATTLE.TEX rows 32-63, VRAM x 920-927 (8x32 sample)


def spans():
    if "--menufont" in sys.argv:          # (2026-11-25) + 256 B of dxahead's side-1 B500 pool (dxahead.py cuts it with the flag)
        return _spans0() + [(0x8000B500, 0x8000B800 if os.environ.get("DIAG_MENU") == "1" else (0x8000B700 if "--modreload2" in sys.argv else 0x8000B600))] +             ([(0x8000C100, 0x8000C300)] if os.environ.get("DIAG_MENU") == "1" else [])
    return _spans0()


def _spans0():
    if "--infmeter" in sys.argv:          # (infinite meter) the core's +20 B no longer pack: + kernel 0x8000C6D0-C7F0 (rc4.14's
        assert ("--vscpu" in sys.argv or os.environ.get("DIAG_NOVSCPU") == "1") and "--mtap" not in sys.argv   # vs-CPU .kc/.kz home; menu-mode --vscpu is all resident in
        # (DIAG_NOVSCPU=1: TEST discs only - a DIAG build without VERSUS CPU keeps the infinite meter in that kernel span)
        return corebuild.SPANS + [(0x8000C6D0, 0x8000C7F0)]          # the EXE; dxahead cuts it from its pool with --vscpu)
    return corebuild.SPANS


def core(ver=None):
    if not _core:
        d_ = {"MENUS5": "0x%08xu" % menus5(ver)}
        if "--titlefix" in sys.argv:                          # rc4.8 tester: main-menu gate until the module is whole (core.S)
            d_.update(MENUGATE="1", GATE_ST6="0x%08x" % GATE_ST6, GATE_EXST="0x%08x" % GATE_EXST, GATE_NOOP="0x%08x" % GATE_NOOP, GATE_ST0="0x800a2b6c")
        if "--modreload" in sys.argv:                         # (2026-11-24) main menu after the attract intro: tail read again
            assert "--titlefix" in sys.argv, "--modreload sits in the --titlefix gate"
            d_.update(MODRELOAD="1", RL_INDEX="%d" % RL_INDEX, RL_DEST="0x%08x" % RL_DEST)
            if "--modreload2" in sys.argv:                    # (2026-11-25) also when [6] is already module-patched (2nd intro)
                d_["MODRELOAD2"] = "1"
        if "--menufont" in sys.argv:                          # (2026-11-25) menu font page re-upload on menu entry
            assert "--modreload" in sys.argv, "--menufont: its file-table entry follows --modreload's"
            d_.update(MENUFONT="1", MF_INDEX="%d" % MF_INDEX, MF_BUF="0x%08x" % MF_BUF, MF_LATCH="0x%08x" % MF_LATCH)
            if "--menufont2" in sys.argv:                     # (2026-11-25) self-checking variant (core.S MENUFONT2)
                d_.update(MENUFONT2="1", MF_SUM="0x%08x" % MF_SUM)
        if os.environ.get("DIAG_MENU") == "1":                # TEST DISCS ONLY: main-menu L1+R1+SELECT probe (core.S DIAGMENU)
            d_["DIAGMENU"] = "1"
        if "--achfix" in sys.argv or os.environ.get("MVC_ACHFIX") == "1":   # (ach audit) hyper move numbers + win gate (core.S,
            d_["ACHFIX"] = "1"; os.environ["MVC_ACHFIX"] = "1"                # set.py FIX: corec reads the set with it)
        if "--infmeter" in sys.argv:                          # (infinite meter) EX row ON = cheat: no evaluation (core.S INFB)
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gameplay")); import optrows
            d_["INFB"] = "0x%08x" % optrows.BYTES["INFINITE SUPER METER"]
        _core.append(corebuild.build(spans(), defines=d_))
    return _core[0]


def expected_ovl(ver=None):
    """OPDEMO.ARC words as menus.py leaves them on the disc (+ the stock words mvcach checks): address -> word"""
    d = dict(STOCK)
    for a, data in menus.ram_patches(ver or menus.DEFAULT):
        for k in range(0, len(data) - 3, 4): d[a + k] = struct.unpack_from("<I", data, k)[0]
    return d


def menu_words(tab, ver=None):
    """-> [(address, word before, word after)]: what the module writes when the main menu is up"""
    exp = expected_ovl(ver)
    rd = lambda a, n: b"".join(struct.pack("<I", exp[a + k]) for k in range(0, n, 4))
    out = []
    for off, data in mvcach.menu_patch(rd, tab, corebuild.MOD_AT + 0x28, ver):
        for k in range(0, len(data), 4):
            a = OVL_BASE + off + k; w = struct.unpack_from("<I", data, k)[0]
            if w != exp[a]: out.append((a, exp[a], w))
    return out


def module(ver=None):
    segs, sym, info = core(ver)
    m0, ms0 = corebuild.build_module(sym)                       # pass 1: where the menu table is
    mw = menu_words(ms0["m_menutab"], ver)
    m, ms = corebuild.build_module(sym, ([(a - OVL_BASE) // 4 for a, o, n in mw], [n for a, o, n in mw]))
    assert ms["m_menutab"] == ms0["m_menutab"] and len(m) == len(m0), "module moved between the passes"
    m = bytearray(m)
    text = (ver or menus.DEFAULT).encode()                      # the 7th line: the version, or EX OPTIONS (--exopt)
    if menus.EXOPT: text = b"EX OPTIONS"
    assert len(text) <= 12
    t = ms["m_menutab"] - corebuild.MOD_AT + 13 * (NLINES - 1)
    m[t:t + len(text)] = text
    m = corebuild.seal_module(bytes(m))
    MSYM.clear(); MSYM.update(ms)
    assert len(m) + 2047 & ~2047 <= corebuild.MOD_MAX
    return m


def opdemo(opd, mod):
    """OPDEMO.ARC (its last sector incl. the slack exopt uses) + the module at MOD_AT"""
    n = len(opd) + 2047 & ~2047
    assert corebuild.OPD_BASE + n == corebuild.MOD_AT, "OPDEMO.ARC size changed: MOD_AT moved"
    return opd.ljust(n, b"\0") + mod


SPURD, SPURD_WRAP = 0x80090434, 0x80008700        # libspu SPU -> RAM read; wrapper in kernel KSAFE 8700-8900 (unused by MvC)


VX_AT, VX_END = 0x8000B500, 0x8000B800       # (--vx) dx side-1 pool bottom (dxahead.py cuts it with --vx); hardware-safe kernel
VXG_AT, VXG_END = 0x8000C100, 0x8000C400     # (--vx) second segment (guard), dx side-1 pool C100-C800 bottom (cut with --vx)
VXF_AT, VXF_END = 0x8000C400, 0x8000C600     # (--vx --vxflash / --vxskip) stage colour flash + Duo frame skip, next 512 B of that pool (dxahead cuts it)


DUO_AT, DUO_END = (0x8000C200, 0x8000C600) if "--duoc200" in sys.argv else (0x8000C100, 0x8000C500)     # (--duofix) dx side-1 pool C100-C6D0 part (dxahead.py cuts it with --duofix); not B100-B800
                                             # (ach span B100-B500 + PS2/PS3 kernel device/fd table B1A0-B7A8)


def duo_seg(read_exe):
    """--duofix (MvC 1.0.1): native Duo cut-in portrait (starter's SPVC both halves) + CPU Duo rule; tools/ach/core/duofix.S.
    -> ((addr, bytes), [(addr, word)])"""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "..", "tools", "speed", "frame")); from gas import gas
    u32 = lambda a: struct.unpack("<I", read_exe(a, 4))[0]
    assert "--vx" not in sys.argv and os.environ.get("DIAG_MENU") != "1", "--duofix shares the C100 span"
    assert u32(0x8006b98c) == 0x80033298, "team-super table entry 2 not stock"
    assert u32(0x80023974) == 0x0c011449, "cut-in load call 0x80023974 not stock"
    assert u32(0x80023b48) == 0x0c008e8c, "cut-in end call 0x80023b48 not stock"
    assert (u32(0x8002dc68), u32(0x8002dc6c)) == (0x~~~~~~~~, 0x~~~~~~~~), "input routine entry not stock"
    cpup = int(os.environ.get("DUO_CPUP", "164"))           # chance per eligible CPU frame, / 65536
    code, sy = gas(open(os.path.join(HERE, "duofix.S")).read(), DUO_AT, {"CPUP": cpup, "MOVEMAX": int(os.environ.get("DUO_MOVEMAX", "0x10"), 0)})
    assert DUO_AT + len(code) <= DUO_END, "duofix.S %d B > span" % len(code)
    print("duofix: %d B at %08x, CPUP %d" % (len(code), DUO_AT, cpup))
    jal = lambda t: 0x0C000000 | (t >> 2 & 0x3FFFFFF)
    nocut = []
    if "--duonocut" in sys.argv:                 # (2026-11-26 user) no Duo cut-in portraits: 0x800305c4 (super start, called only
        assert (u32(0x80030650), u32(0x8003066c)) == (0x0c01a2d5, 0x0c01974a), "Duo cut-in spawn calls not stock"   # by the Duo
        nocut = [(0x80030650, 0), (0x8003066c, 0)]   # start state 0x800332f8): its cut-in spawn calls 0x80068b54 / 0x80065d28 -> nop
                                                 # (installed by the ach guard stub = ROM-gated: PS2/PS3 keep the stock cut-in, 1.1)
    if "--duonohooks" in sys.argv:               # (HW bisect) the segment copied, no hook installed
        return (DUO_AT, code), []
    if "--duocpuonly" in sys.argv:               # (2026-11-26 user) CPU Duo rule only: the cut-in stays stock (portrait swap off)
        return (DUO_AT, code), [(0x8002dc68, 0x08000000 | (sy["duo_in"] >> 2 & 0x3FFFFFF))] + nocut
    return (DUO_AT, code), [(0x8006b98c, sy["duo_case"]), (0x80023974, jal(sy["duo_cut"])), (0x80023b48, jal(sy["duo_end"])),
                            (0x8002dc68, 0x08000000 | (sy["duo_in"] >> 2 & 0x3FFFFFF))]


def vx_seg(read_exe):
    """--vx: tools/ach/core/vx.S at VX_AT; hooks: team controller 0x80031fbc (lb v0,0(a3) -> j vx_ctrl), tag check
    0x80056088 (jal 0x80057c8c -> jal vx_tag).  -> ((addr, bytes), [(addr, word)])"""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "..", "tools", "speed", "frame")); from gas import gas
    u32 = lambda a: struct.unpack("<I", read_exe(a, 4))[0]
    assert u32(0x80031fbc) == 0x80e20000 and u32(0x80031fc0) == 0, "controller site 0x80031fbc not stock"
    assert u32(0x80056088) == 0x0c015f23, "tag check site 0x80056088 not stock (%08x)" % u32(0x80056088)
    assert (u32(0x80031e9c), u32(0x80031ea0)) == (0x~~~~~~~~, 0x~~~~~~~~), "controller wrapper entry not stock"
    assert (u32(0x80055fa8), u32(0x80055fac)) == (0x~~~~~~~~, 0x~~~~~~~~), "tag check entry not stock"
    code, sy = gas(open(os.path.join(HERE, "vx.S")).read(), VX_AT)               # VXS fixed at VXG_AT (vxg.S starts with it)
    gcode, gsy = gas(open(os.path.join(HERE, "vxg.S")).read(), VXG_AT, {"VXSTART": sy["vx_start"]})
    assert VXG_AT + len(gcode) <= VXG_END and gsy["VXS"] == VXG_AT
    print("vx: VXS %08x, guard seg %d B" % (gsy["VXS"], len(gcode)))
    assert VX_AT + len(code) <= VX_END, "vx.S %d B > span" % len(code)
    print("vx: %d B at %08x, vx_ctrl %08x, vx_tag %08x" % (len(code), VX_AT, sy["vx_ctrl"], sy["vx_tag"]))
    extra = []
    if "--vxflash" in sys.argv or "--vxskip" in sys.argv:   # vxf.S at VXF_AT: stage colour flash / Duo-only frame skip
        fcode, fsy = gas(open(os.path.join(HERE, "vxf.S")).read(), VXF_AT, {"VXSKIP": int("--vxskip" in sys.argv)})
        assert VXF_AT + len(fcode) <= VXF_END, "vxf.S %d B > span" % len(fcode)
        print("vx: flash/skip %d B at %08x" % (len(fcode), VXF_AT))
        fh = []
        if "--vxflash" in sys.argv:              # hook: sprite layer 3 call
            assert u32(0x80047b84) == 0x0c011f4e and u32(0x80047b88) == 0x24040003, "sprite draw site 0x80047b84 not stock"
            fh.append((0x80047b84, 0x0C000000 | (fsy["vx_flash"] >> 2 & 0x3FFFFFF)))
        if "--vxskip" in sys.argv:               # hooks: the frameskip.py catch-up sites (stock words asserted)
            assert "--frameskip" not in sys.argv or "--nofskip" in sys.argv, "--vxskip: FRAME SKIP hooks must be off"
            assert (u32(0x80022d74), u32(0x80022ecc), u32(0x80022ed0)) == (0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~), "catch-up sites not stock"
            fh += [(0x80022d74, 0x0C000000 | (fsy["vs_gate"] >> 2 & 0x3FFFFFF)),
                   (0x80022ecc, 0x0C000000 | (fsy["vs_lag"] >> 2 & 0x3FFFFFF)), (0x80022ed0, 0x00021403)]
        extra = [tuple(fh), (VXF_AT, fcode)]
    if os.environ.get("VX_DEBUG") == "1":        # emulator-only: set-move logger (a0, a1, ra) for moves 0x40 / 0x2a at 0x8000C100
        assert (u32(0x8003d04c), u32(0x8003d050)) == (0x~~~~~~~~, 0x~~~~~~~~)
        dsrc = """
dbg:    addiu $k0, $zero, 0x40
        beq   $a1, $k0, 1f
        addiu $k0, $zero, 0x2a
        bne   $a1, $k0, 2f
        nop
1:      lui   $k1, 0x8001
        lw    $k0, -0x3700($k1)        # 0x8000C900 count
        nop
        sltiu $at, $k0, 40
        beqz  $at, 2f
        sll   $at, $k0, 2
        sll   $k0, $k0, 3
        addu  $at, $at, $k0
        addu  $at, $at, $k1
        sw    $a0, -0x36fc($at)
        sw    $a1, -0x36f8($at)
        sw    $ra, -0x36f4($at)
        lw    $k0, -0x3700($k1)
        nop
        addiu $k0, $k0, 1
        sw    $k0, -0x3700($k1)
2:      lui   $v0, 0x8008
        j     0x8003d054
        lb    $v0, -0x48a3($v0)
tr:     lui   $k1, 0x8001
        lw    $k0, -0x3700($k1)
        nop
        sltiu $at, $k0, 40
        beqz  $at, 3f
        sll   $at, $k0, 2
        sll   $k0, $k0, 3
        addu  $at, $at, $k0
        addu  $at, $at, $k1
        sw    $a0, -0x36fc($at)
        ori   $k0, $a1, 0
        sw    $k0, -0x36f8($at)
        li    $k0, 0x1000
        sw    $k0, -0x36f4($at)
        sw    $ra, -0x36f4($at)
        lw    $k0, -0x3700($k1)
        nop
        addiu $k0, $k0, 1
        sw    $k0, -0x3700($k1)
3:      lui   $v0, 0x8008
        j     0x80032268
        lb    $v0, -0x48a3($v0)
tr2:    lui   $k1, 0x8001
        lw    $k0, -0x3700($k1)
        nop
        sltiu $at, $k0, 40
        beqz  $at, 4f
        sll   $at, $k0, 2
        sll   $k0, $k0, 3
        addu  $at, $at, $k0
        addu  $at, $at, $k1
        sw    $s1, -0x36fc($at)
        lui   $k0, 0x8001
        lbu   $k0, -0x4820($k0)        # VXS side 0 'on' (0x8000B7E0)
        nop
        ori   $k0, $k0, 0xee00
        sw    $k0, -0x36f8($at)
        sw    $ra, -0x36f4($at)
        lw    $k0, -0x3700($k1)
        nop
        addiu $k0, $k0, 1
        sw    $k0, -0x3700($k1)
4:      j     0x80032260
        nop
"""
        dc, ds = gas(dsrc, 0x8000C800)
        return (VX_AT, code), [(0x80031fbc, 0x08000000 | (sy["vx_ctrl"] >> 2 & 0x3FFFFFF)), (0x80056088, 0x0C000000 | (sy["vx_tag"] >> 2 & 0x3FFFFFF)),
                               (0x80031e9c, 0x08000000 | (gsy["vx_frame"] >> 2 & 0x3FFFFFF)), (0x80031ea0, 0),
                               (0x80055fa8, 0x08000000 | (sy["vx_tagchk"] >> 2 & 0x3FFFFFF)), (0x80055fac, 0),
                               (0x8003d04c, 0x08000000 | (0x8000C800 >> 2 & 0x3FFFFFF)), (0x8003d050, 0),
                               (0x80032260, 0x08000000 | (ds["tr"] >> 2 & 0x3FFFFFF)), (0x80032264, 0),
                               (0x80032170, 0x0C000000 | (ds["tr2"] >> 2 & 0x3FFFFFF))], (0x8000C800, dc), (VXG_AT, gcode)
    return (VX_AT, code), [(0x80031fbc, 0x08000000 | (sy["vx_ctrl"] >> 2 & 0x3FFFFFF)), (0x80056088, 0x0C000000 | (sy["vx_tag"] >> 2 & 0x3FFFFFF)),
                          (0x80031e9c, 0x08000000 | (gsy["vx_frame"] >> 2 & 0x3FFFFFF)), (0x80031ea0, 0),
                          (0x80055fa8, 0x08000000 | (sy["vx_tagchk"] >> 2 & 0x3FFFFFF)), (0x80055fac, 0)] + [h for h in extra[:1] for h in h],         (VXG_AT, gcode), *extra[1:]


def spurd_wrap(read_exe):
    """--spsfifo: the MiSTer PSX core clears its SPU read FIFO only on a transfer mode 11 -> 00 change, so a read can
    start with the previous read's prefetched tail.  Every SpuRead (0x80090434: the game's own call, snd.c at battle
    load, swap.c at tag-ins) is wrapped: flush (11 -> 00), the original read, flush.  0x80008700 lies in mktag KSAFE (real-console
    kernel set (work/biosmap: 8000BF48-DF80, no BIOS writes) and outside every MvC span (dx pools C100-C800, cutguard
    DA00-DF80).  Hook = the read's first two words (relocated into the wrapper).  -> ((addr, bytes), [(addr, word)])"""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "..", "tools")); from mipsasm import Asm
    u32 = lambda a: struct.unpack("<I", read_exe(a, 4))[0]
    w0, w1 = u32(SPURD), u32(SPURD + 4)
    assert (w0, w1) == (0x~~~~~~~~, 0x~~~~~~~~), ("SpuRead prologue not stock", hex(w0), hex(w1))
    a = Asm(SPURD_WRAP)
    a.addiu("$sp", "$sp", -8); a.sw("$ra", 4, "$sp")
    jl = lambda lab: a._i(lambda pc, L: 0x0C000000 | (L[lab] >> 2 & 0x3FFFFFF))
    jl("flush"); a.nop()
    jl("orig"); a.nop()
    jl("flush"); a.nop()
    a.lw("$ra", 4, "$sp"); a.nop()
    a.jr("$ra"); a.addiu("$sp", "$sp", 8)
    a.label("flush")
    a.lui("$t0", 0x1f80); a.lhu("$t1", 0x1daa, "$t0"); a.nop()
    a.andi("$t1", "$t1", 0xffcf); a.ori("$t2", "$t1", 0x30)
    a.sh("$t2", 0x1daa, "$t0"); a.jr("$ra"); a.sh("$t1", 0x1daa, "$t0")
    a.label("orig")
    a.word(w0); a.word(0x08000000 | ((SPURD + 8) >> 2 & 0x3FFFFFF)); a.word(w1)   # addiu sp; j body+8; (delay) sw s1
    code = a.assemble()
    assert len(code) <= 0x100
    return (SPURD_WRAP, code), [(SPURD, 0x08000000 | (SPURD_WRAP >> 2 & 0x3FFFFFF)), (SPURD + 4, 0)]


def parts(read_exe, read_hdr, read_ovl, ver=None):
    u32 = lambda r, a: struct.unpack("<I", r(a, 4))[0]
    assert u32(read_exe, corebuild.HOOK_FRAME) == jal(corebuild.FRAMEBEGIN), "hook site 0x80022fe8 not stock"
    # the dx stash must not use our spans (dxahead POOLS: --ach drops them)
    sys.path.insert(0, os.path.join(HERE, "..", "..", "speed4")); import dxahead
    for side in dxahead.POOLS:
        for a, b in side:
            for s, e in spans():
                assert b <= s or a >= e, "dx stash pool %08x-%08x overlaps the achievements span %08x-%08x" % (a, b, s, e)
    # the neighbours of the small spans: dx state (grows with --koprefill), the hook gate, dx's aux sector, kocache + pal8
    used = [(dxahead.ST, dxahead.ST_END), (dxahead.AUX_AT, dxahead.AUX_AT + 0x800), (0x8000F040, 0x8000F840)]
    sys.path.insert(0, os.path.join(HERE, "..", "..", "tagload")); import hookgate
    hg, hs = hookgate.build(); used.append((hookgate.HG_AT, hookgate.HG_AT + len(hg)))
    for a, b in used:
        for s, e in spans():
            assert b <= s or a >= e, "%08x-%08x (dx / hookgate / kocache) overlaps the achievements span %08x-%08x" % (a, b, s, e)
    exp = expected_ovl(ver)
    for a in list(STOCK) + [mvcach.STATES + 4 * k for k in range(9)]:
        assert u32(read_ovl, a) == exp[a], "OPDEMO.ARC %08x = %08x, the module expects %08x" % (a, u32(read_ovl, a), exp[a])
    if "--titlefix" in sys.argv:
        assert u32(read_ovl, GATE_ST6) == GATE_EXST, "--titlefix gate: OPDEMO state-table [6] = %08x, not exst" % u32(read_ovl, GATE_ST6)
    segs, sym, info = core(ver)
    prev_pc0 = u32(read_hdr, 0x10)
    hooks = corebuild.hooks(sym)
    if "--vx" in sys.argv:                        # (2026-11-26, MvC 1.1 prototype) Variable Cross: vx.S at VX_AT, two EXE hooks
        r_ = vx_seg(read_exe)
        w, h = r_[0], r_[1]
        segs = list(segs) + [w] + list(r_[2:]); hooks = hooks + h
    if "--duofix" in sys.argv:                    # (2026-11-26, MvC 1.0.1) native Duo: cut-in portrait + CPU Duo rule
        w, h = duo_seg(read_exe)
        segs = list(segs) + [w]; hooks = hooks + h
    if "--spsrdwrap" in sys.argv:                 # (2026-11-25, WIP: hangs Beetle at boot) libspu SPU read 0x80090434 wrapped (spurd_wrap below)
        w, h = spurd_wrap(read_exe)
        segs = list(segs) + [w]; hooks = hooks + h
    copy = achbuild.copy_stub_spans(COPY_AT, segs, hooks, prev_pc0)
    assert COPY_AT + len(copy) <= COPY_END and read_exe(COPY_AT, len(copy)) == bytes(len(copy)), "copy area not zero"
    sym = dict(sym, **{"c_mod." + k: v for k, v in MSYM.items() if k in ("ach_dbg", "ach_bits", "page_open", "card_state", "m_menutab", "mod_menu")})
    info = dict(info, image=info["used"], imageb=0, freeb=0, imagec=0, bss=0, sym=sym)
    return dict(exe=[(COPY_AT, copy)], ovl=[], pc0=COPY_AT, ram=segs, info=info, ovl_file=OVL_FILE, sym=sym)
