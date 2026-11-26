"""Multitap 2-4 players for XvSF (SLUS-00627), mktagdisc --mtap: common/mtap/mtcore.c with tools/mtap/mtgame.h.
Notes: games/mshvsf/docs/MULTITAP.md "mtap04" (shared design), work/mtap/xvsf_padmap.md (XvSF addresses).

Home: the Psy-Q debug-message strings 0x80010000-0x80010894 (printf / puts arguments only; printf A0 0x3f stub
0x800192d0 and puts B0 0x3f stub 0x80019248 -> jr ra).  Kept: "none" 0x80010108, the 1.4 code 0x80010420-0x800104f8
with "CD001" before it, "." / ".." 0x80010508.  The libcd jump table 0x800102c0 (lw 0x8001311c) moves to 0x80010880.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "common", "mtap")))
import mtpatch

_ob = lambda h: bytes(b ^ 0x5a for b in bytes.fromhex(h))   # stock words, stored masked (no game words in the sources)
CFG = dict(
    dir=HERE,
    spans=[(0x80010510, 0x80010880), (0x8001010c, 0x80010418), (0x80010000, 0x80010108)],
    strings=[(0x80010000, 0x80010108), (0x8001010c, 0x80010418), (0x80010510, 0x80010894)],
    tables=[(0x800102c0, 0x80010880, 0x8001311c, 0x8c2202c0)],
    hook=(0x8002c968, 0x0C00B1CB),                                  # jal 0x8002c72c (per-frame raw-word builder)
    mask=(0x8002c70c, _ob("b2a5e77d4a5ae5f5")),           # addiu sp,sp,-0x18; sw ra,0x10(sp)
    stubs=[(0x800192d0, _ob("fa5a507e525a1a5b")),         # printf (A0 0x3f)
           (0x80019248, _ob("ea5a507e525a1a5b"))],        # puts (B0 0x3f)
)


def apply(exe_read, exe_write):
    p, c = mtpatch.patches(CFG, exe_read)
    for a, d in p:
        exe_write(a, d)
    print("mtap: %d bytes in %s (%d free), mt_tick %08x, mt_mask %08x" % (c["used"], [(hex(a), len(d)) for a, d in c["segs"]],
                                                                          c["free"], c["sym"]["mt_tick"], c["sym"]["mt_mask"]))
    return c


if __name__ == "__main__":
    E = open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "work", "mtap", "x14_c1.exe"), "rb").read()
    p, c = mtpatch.patches(CFG, lambda a, n: E[0x800 + a - 0x80010000:0x800 + a - 0x80010000 + n])
    print(c["used"], c["free"], [(hex(a), len(d)) for a, d in c["segs"]], {k: hex(v) for k, v in c["sym"].items() if k.startswith(("mt_", "V"))})


# ---- vs CPU (mktagdisc --vscpu, needs --mtap): common/mtap/mtcore.c + mtvsui.c with MT_VSCPU.  Resident (incl. the
# .kc fight code and .kz vars: no kernel RAM in XvSF) in the same string-block spans; the select module right after
# SELECT.BIN's 8-aligned end inside a longer SELECT.BIN copy (file table entry 1 repointed; the select init puts its
# heap after the file's end, so it moves up with the copy: work/vscpu_xvmsh.md).
SEL_BASE, SEL_SIZE = 0x80098000, 167108
SEL_END = (SEL_BASE + SEL_SIZE + 7) & ~7                      # 0x800c0cc8
SEL_JAL, SEL_JAL_ORIG = 0x8009c260, 0x0C000000 | (0x8009e4a8 >> 2 & 0x03FFFFFF)    # jal 0x8009e4a8 (per select frame)
FTAB_SELECT = 0x8003d91c + 8 * 1
CFG_V = dict(CFG, spans=CFG["spans"] + [(SEL_END, SEL_END + 0x1000, "vsui")])
DEF_V = dict(MT_VSCPU=1)


def apply_v(exe_read, exe_write):
    import struct
    p, c = mtpatch.patches(CFG_V, exe_read, DEF_V)
    for a, d in p:
        exe_write(a, d)
    assert "ovl" in c and c["ovl"][0] == SEL_END
    print("mtap+vscpu: %d bytes in %s (%d free), module %d B at %08x" % (c["used"], [(hex(a), len(d)) for a, d in c["segs"]],
                                                                         c["free"], len(c["ovl"][1]), SEL_END))
    return c


def select_copy(sel, c):
    """SELECT.BIN as built -> + padding to its 8-aligned end + the module; the per-frame jal -> vs_selmain"""
    import struct
    assert len(sel) == SEL_SIZE
    b = bytearray(sel + bytes(SEL_END - SEL_BASE - len(sel)))
    o = SEL_JAL - SEL_BASE
    assert struct.unpack_from("<I", b, o)[0] == SEL_JAL_ORIG, "SELECT.BIN per-frame jal not stock"
    struct.pack_into("<I", b, o, 0x0C000000 | (c["sym"]["vs_selmain"] >> 2 & 0x03FFFFFF))
    return bytes(b) + c["ovl"][1]


# ---- VERSUS CPU main-menu row (mktagdisc --vsmenu, 2026-11-23: replaces --mtap / --vscpu; no multitap, no SIO, no seat
# panel): the vs CPU core with MT_VSMENU in the string block, mt_select in the SELECT.BIN copy (as --vscpu, but the
# per-frame jal stays stock: no panel); the menu wrapper
# (tools/mtap/mtmenu.h) is reached by EX OPTIONS' ex_menuin through a fixed trampoline at MENU_J (first string-block word).
MENU_J, VSMODE = 0x80010000, 0x80010008            # trampoline (EX calls it), mt_vsmode (the achievements runtime reads it)
CFG_M = dict(CFG, spans=[(MENU_J, MENU_J + 8, "mt_menu_j"), (VSMODE, VSMODE + 4, "vsmbyte"), (VSMODE + 4, 0x80010108)] + CFG["spans"][:2]
             + [(SEL_END, SEL_END + 0x1000, "vsui")],                 # mt_select: in the SELECT.BIN copy, as --vscpu
             keep=("mt_tick", "mt_mask_v", "mt_menu_j"))


def apply_m(exe_read, exe_write, ex_sym, flush):
    defs = dict(MT_VSCPU=1, MT_VSMENU=1, MT_EXACH="0x%08xu" % ex_sym["ex_achmenu"], MT_EXMENUIN="0x%08xu" % ex_sym["ex_menuin"],
                MT_FLUSH="0x%08xu" % flush, MT_MENU_Y7="0x%x" % EX_LAYOUT["EX_MENU_Y"], MT_MENU_STEP7="0x%x" % EX_LAYOUT["EX_MENU_STEP"])
    p, c = mtpatch.patches(CFG_M, exe_read, defs)
    assert "ovl" in c and c["ovl"][0] == SEL_END and c["sym"]["mt_menu_j"] == MENU_J and c["sym"]["mt_vsmode"] == VSMODE and "vs_selmain" not in c["sym"]
    for a, d in p:
        exe_write(a, d)
    print("vsmenu: %d bytes in %s (%d free), mt_tick %08x, mt_vsmenu %08x, V %08x" % (c["used"], [(hex(a), len(d)) for a, d in c["segs"]],
          c["free"], c["sym"]["mt_tick"], c["sym"]["mt_vsmenu"], c["sym"]["V"]))
    return c


DEF_M = None   # (tests: mtpatch.code(CFG_M, DEF_M) needs the EX symbols; use the build log / sym dump instead)
import expatch as _ex   # (layout of the 7-line menu)
EX_LAYOUT = _ex.LAYOUT


def select_copy_m(sel, c):
    """--vsmenu: SELECT.BIN as built -> + padding to its 8-aligned end + the module (no per-frame hook: no panel)"""
    assert len(sel) == SEL_SIZE
    return sel + bytes(SEL_END - SEL_BASE - len(sel)) + c["ovl"][1]
