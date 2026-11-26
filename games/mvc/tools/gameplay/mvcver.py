"""Version line on the main menu - MvC (SLUS-01059), mktag.py --title[=TEXT].  Counterpart of XvSF tools/titlepatch.py and
MSHvSF games/mshvsf/tools/gameplay/menuversion.py (same method: one extra call of the game's own text routine).

    OPDEMO.ARC (menu overlay at 0x8009dfe4) 0x800a2b2c: `jr ra` at the end of the main-menu text routine 0x800a2a50
               (ra and s-registers restored, `addiu sp,sp,0x30` in the delay slot) -> `j menuhook`; menuhook returns to
               that routine's caller.  Runs only while the main menu is drawn (the --ach module's menu words do not
               touch this word).
    menuhook + text: at the END of OPDEMO.ARC's last-sector slack (optrows.SLACK .. SLACK_END = 0x801087e4), after the
               EX OPTIONS screen code (gameplay/exopt.py, from SLACK up); loaded with the menu file, nothing resident.
               Call: font 0x80020f10(text, x << 16 | y, colour << 16 | 0x08000001) = the small font of EX OPTIONS.
With --exopt the same text is also the version line of the EX OPTIONS screen (mktag passes it as --ver).
"""
import os, struct, sys, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))


def _mod(name, path):                              # no sys.path change: mktag's module resolution stays as it was
    if name in sys.modules: return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m; spec.loader.exec_module(m); return m

MENU_AT, MENU_ORIG = 0x800a2b2c, 0x03E00008        # jr ra
FONT = 0x80020f10
DEFAULT = "TAG HACK 1.0"
X_RIGHT, Y, COLOUR = 0x194, 0x14, 0x27             # right edge (font x units, screen centre 0x100), top line (the 7-line
                                                   # menu fills the bottom: EX OPTIONS at y 0xd8), menu colour
CHAR_W = 8
OPD, OPD_BASE, OPD_SIZE = "OPDEMO.ARC", 0x8009dfe4, 434932   # = optrows.OPD / OPD_BASE / OPD_SIZE (asserted in build)
LIMIT = OPD_BASE + (OPD_SIZE + 2047) // 2048 * 2048           # = optrows.SLACK_END 0x801087e4


def text_of(argv):
    t = next((a for a in argv if a == "--title" or a.startswith("--title=")), None)
    return None if t is None else (t[8:] or DEFAULT)


def build(text=DEFAULT, at=None):
    assert text and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-" for c in text) and len(text) <= 24
    n = 13 * 4 + (len(text) + 4) // 4 * 4
    org = LIMIT - n if at is None else at
    x = X_RIGHT - CHAR_W * len(text)
    Asm = _mod("_mvcver_mipsasm", os.path.join(ROOT, "tools", "mipsasm.py")).Asm
    a = Asm(org)
    a.label("menuhook")
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x10, "$sp")
    a.label("str_hi"); a.lui("$a0", 0)
    a.label("str_lo"); a.addiu("$a0", "$a0", 0)
    a.lui("$a1", x)
    a.ori("$a1", "$a1", Y)
    a.lui("$a2", 0x0800 | COLOUR)
    a.jal(FONT)
    a.ori("$a2", "$a2", 1)
    a.lw("$ra", 0x10, "$sp")
    a.nop()
    a.jr("$ra")
    a.addiu("$sp", "$sp", 0x18)
    a.label("text")
    a.blob(text.encode() + b"\0" * (4 - len(text) % 4))
    code = bytearray(a.assemble()); L = a.labels()
    t = L["text"]; hi, lo = ((t + 0x8000) >> 16) & 0xFFFF, t & 0xFFFF
    code[L["str_hi"] - org:L["str_hi"] - org + 4] = struct.pack("<I", 0x3C040000 | hi)
    code[L["str_lo"] - org:L["str_lo"] - org + 4] = struct.pack("<I", 0x24840000 | lo)
    assert len(code) == n and (at is not None or org + len(code) == LIMIT), (len(code), n)
    return bytes(code), org


def overlay_patches(text=DEFAULT):
    """[(file, offset, bytes)] in OPDEMO.ARC: the stub at the slack end + `j menuhook` over the routine's `jr ra`"""
    code, org = build(text)
    return [(OPD, org - OPD_BASE, code),
            (OPD, MENU_AT - OPD_BASE, struct.pack("<I", 0x08000000 | (org >> 2 & 0x3FFFFFF)))]


# --titlefix (rc4.8 tester, 2026-11-21, MiSTer "title -> START -> START -> black"): the hook word (OPDEMO sector 9) is in
# RAM ~80 frames (Beetle; longer on real CD timing) before the slack stub (OPDEMO's last sector).  A START press in that
# window runs the menu text routine -> `j menuhook` into not-yet-loaded RAM -> RI exception (DIAG panel: EPC 0x801087a0,
# Cause RI).  Fix: the stub lives in the EXE (resident from boot) at the END of the unreferenced SDK copyright string
# 0x8001d0f4-0x8001d14c (88 B; mvcmtap's spare span, which only checks its first 16 B), the hook jumps there.
RES, RES_END = 0x8001d0f4, 0x8001d14c
RES_ORIG = b"Library Programs (c) 1993-1997 Sony Computer Entertainment Inc., All Rights Reserved."


def resident_patches(text=DEFAULT):
    """(exe_addr, code) for the EXE + [(file, offset, jump word)] for OPDEMO.ARC"""
    n = 13 * 4 + (len(text) + 4) // 4 * 4             # = build()'s size; the stub sits at the span END so --mtap's
    code, org = build(text, at=RES_END - n)            # spare-span check (first 16 B "Library Programs") still holds
    assert org + len(code) == RES_END and org >= RES + 16, (hex(org), len(code))
    return (org, code), [(OPD, MENU_AT - OPD_BASE, struct.pack("<I", 0x08000000 | (org >> 2 & 0x3FFFFFF)))]


if __name__ == "__main__":
    for f, off, d in overlay_patches(sys.argv[1] if len(sys.argv) > 1 else DEFAULT):
        print(f, hex(off), len(d), d.hex())
