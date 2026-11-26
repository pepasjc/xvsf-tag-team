"""Multitap 2-4 players, mtap04 (mktag.py --mtap): common/mtap/mtcore.c built for MSHvSF (SLUS-00793).
Notes: games/mshvsf/docs/MULTITAP.md "mtap04".  Coexists with --ach / --exopt / --l2g: no kernel RAM, no boot stub.

Home: the Psy-Q library debug-message strings (rodata 0x80010000-0x80010620, used only as printf / puts arguments);
printf (A0 0x3f stub 0x800144b8) and puts (B0 0x3f stub 0x80014460) return at once, so nothing reads them.  The two
libcd jump tables in the block move to its end (lw offsets re-pointed).  Spare: SDK copyright string 0x8001d244.
The disconnected-pad mask 0x80023b54 jumps to mt_mask, which replays its two first words.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "common", "mtap")))
import mtpatch

_ob = lambda h: bytes(b ^ 0x5a for b in bytes.fromhex(h))   # stock words, stored masked (no game words in the sources)
CFG = dict(
    dir=HERE,
    spans=[(0x80010000, 0x800105f8), (0x8001d244, 0x8001d298)],
    strings=[(0x80010000, 0x80010620)],
    tables=[(0x800104b0, 0x800105f8, 0x80015364, 0x8c2204b0), (0x800105b0, 0x8001060c, 0x80017728, 0x8c2205b0)],
    hook=(0x80020c8c, 0x0C008EE2),                                  # jal 0x80023b88 (per-frame pad-word update)
    mask=(0x80023b54, _ob("b2a5e77d4e5ae5f5")),           # addiu sp,sp,-0x18; sw ra,0x14(sp)
    stubs=[(0x800144b8, _ob("fa5a507e525a1a5b")),         # printf (A0 0x3f)
           (0x80014460, _ob("ea5a507e525a1a5b"))],        # puts (B0 0x3f)
    spare=[(0x8001d244, 0x8001d298, b"Library Programs")],
)


def code(defines=None): return mtpatch.code(CFG, defines)
def patches(read, defines=None): return mtpatch.patches(CFG, read, defines)


if __name__ == "__main__":
    c = code()
    print("mtap04: %d bytes used, %d free; segs %s" % (c["used"], c["free"], [(hex(a), len(d)) for a, d in c["segs"]]))
    print({k: hex(v) for k, v in c["sym"].items() if k in ("mt_tick", "mt_mask", "V")})


# ---- vs CPU (mktag --vscpu, needs --mtap): common/mtap/mtcore.c + mtvsui.c with MT_VSCPU (research work/vscpu_xvmsh.md).
# Resident: the same EXE block; vars (.kz) in the SDK copyright span (EXE, zeros written) + kernel 0x8000F010-F040 (left
# unused by m11_c4's achievements); select module 8 B after SEL.ARC's end inside a longer SEL.ARC copy (file table entry
# 0x80024ed4 repointed; the select init reads its next file after the copy's end); fight code (.kc, 236 B) copied by the
# module on every select frame to 0x801fea00 (RAM no load writes between a select and the next one: vscpu kcwatch test).
SEL_BASE, SEL_SIZE = 0x800947d4, 1145528
SEL_END = SEL_BASE + SEL_SIZE + 8                             # 0x801ac294
SEL_JAL, SEL_JAL_ORIG = 0x80095168, 0x0C000000 | (0x800a3050 >> 2 & 0x03FFFFFF)    # jal 0x800a3050 (per select frame)
FTAB_SEL = 0x80024ed4
KC_AT, KC_END = 0x801fea00, 0x801ff000
# The module lives INSIDE SEL.ARC (in place, same size / table entry): the select init reads its next file to the fixed
# 0x801ac294, so nothing after the file survives; 0x800bf200-0x800df200 is never read in the VERSUS select (poison test,
# work/vscpu_xvmsh.md) -> the module at its end.
MOD_AT, MOD_END = 0x800de600, 0x800df200
CFG_V = dict(CFG, spans=[CFG["spans"][0], (MOD_AT, MOD_END, "vsui"), (KC_AT, KC_END, ".kc"),
                         (0x8001d244, 0x8001d298, ".kz"), (0x8000F010, 0x8000F040, ".kz"), (0x800094D0, 0x800094F0, ".kz")])
DEF_V = dict(MT_VSCPU=1)


def code_v(): return mtpatch.code(CFG_V, DEF_V)
def patches_v(read): return mtpatch.patches(CFG_V, read, DEF_V)


def _unused_vsel_len():
    c = code_v()
    sp = lambda a: next(s for s in CFG_V["spans"] if s[0] <= a < s[1])
    return SEL_END - SEL_BASE + sum(len(d) for a, d in c["segs"] if len(sp(a)) > 2 and sp(a)[2] in ("vsui", ".kc"))


def sel_patches(c):
    """[(SEL.ARC file offset, bytes)] in place: the module (+ the fight-code copy source) and the per-frame jal"""
    import struct
    oa, od = c["ovl"]
    assert oa == MOD_AT and oa + len(od) <= MOD_END
    return [(oa - SEL_BASE, od), (SEL_JAL - SEL_BASE, struct.pack("<I", 0x0C000000 | (c["sym"]["vs_selmain"] >> 2 & 0x03FFFFFF)))]


def _unused_sel_copy(sel, c):
    import struct
    assert len(sel) == SEL_SIZE
    b = bytearray(sel + bytes(SEL_END - SEL_BASE - len(sel)))
    o = SEL_JAL - SEL_BASE
    assert struct.unpack_from("<I", b, o)[0] == SEL_JAL_ORIG, "SEL.ARC per-frame jal not stock"
    struct.pack_into("<I", b, o, 0x0C000000 | (c["sym"]["vs_selmain"] >> 2 & 0x03FFFFFF))
    assert c["ovl"][0] == SEL_END
    return bytes(b) + c["ovl"][1]


# ---- VERSUS CPU main-menu row (mktag --vsmenu, 2026-11-23: replaces --mtap / --vscpu; no multitap, no SIO, no seat panel):
# the vs CPU core with MT_VSMENU.  Fixed EXE-block slots first (named by the menu overlay patches and the achievements
# runtime before this links: tools/mtap/mtmenu.h), then the rest of the block for the resident code (+ the fight code:
# no RAM copy now), vars in the .kz spans as --vscpu, the select module in SEL.ARC in place (no per-frame jal: no panel).
VT9, VT8, SELJ, VSMODE = 0x80010000, 0x80010078, 0x800100e0, 0x800100f0
CFG_M = dict(CFG, spans=[(VT9, VT8, "vmtab9"), (VT8, SELJ, "vmtab8"), (SELJ, VSMODE, "mt_sel_j"), (VSMODE, VSMODE + 4, "vsmbyte"),
                         (VSMODE + 4, CFG["spans"][0][1]), (MOD_AT, MOD_END, "vsui"),
                         (0x8001d244, 0x8001d298, ".kz"), (0x8000F010, 0x8000F040, ".kz"), (0x800094D0, 0x800094F0, ".kz")],
             keep=("mt_tick", "mt_mask_v", "mt_sel_j", ".rodata.vmtab9", ".rodata.vmtab8"))
DEF_M = dict(MT_VSCPU=1, MT_VSMENU=1)


def patches_m(read):
    p, c = mtpatch.patches(CFG_M, read, DEF_M)
    s = c["sym"]
    assert (s["vm_tab9"], s["vm_tab8"], s["mt_sel_j"], s["mt_vsmode"]) == (VT9, VT8, SELJ, VSMODE), "vsmenu fixed slots"
    assert "vs_selmain" not in s and not c.get("kcram")
    return p, c


def sel_patches_m(c):
    """[(SEL.ARC file offset, bytes)] in place: the module only"""
    oa, od = c["ovl"]
    assert oa == MOD_AT and oa + len(od) <= MOD_END
    return [(oa - SEL_BASE, od)]
