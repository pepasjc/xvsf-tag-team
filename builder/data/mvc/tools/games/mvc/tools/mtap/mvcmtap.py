"""Multitap 2-4 players for MvC (SLUS-01059), mktag.py --mtap: common/mtap/mtcore.c with tools/mtap/mtgame.h.
Notes: games/mshvsf/docs/MULTITAP.md "mtap04" (shared design), games/mvc/work/mtap/mvc_padmap.md (MvC addresses).

Home: the Psy-Q debug-message strings 0x80010000-0x80010620 (printf / puts arguments only; printf A0 0x3f stub
0x800145c8 and puts B0 0x3f stub 0x80014560 -> jr ra).  The two libcd jump tables in the block (0x80010490, lw
0x80015074; 0x800105b0, lw 0x800177a8) move to 0x800105f8 / 0x8001060c.  Second span: the SDK copyright string
0x8001d0f4-0x8001d14c (no reference).  0x80010620.. is live (jump tables, start code).
Hook 0x80024d44 (the builder's own `jal 0x8002489c` key-mapper call) -> mt_tick, which writes our raw words and then
runs the mapper (mtgame.h MT_AFTER).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "common", "mtap")))
import mtpatch

CFG = dict(
    dir=HERE,
    spans=[(0x80010000, 0x800105f8), (0x8001d0f4, 0x8001d14c)],
    strings=[(0x80010000, 0x80010620)],
    tables=[(0x80010490, 0x800105f8, 0x80015074, 0x8c220490), (0x800105b0, 0x8001060c, 0x800177a8, 0x8c2205b0)],
    hook=(0x80024d44, 0x0C009227),                                  # jal 0x8002489c (key mapper, end of the builder)
    mask=(0x80024c08, bytes.fromhex("~~~~~~~~~~~~~~~~")),           # addiu sp,sp,-0x18; sw ra,0x14(sp)
    stubs=[(0x800145c8, bytes.fromhex("~~~~~~~~~~~~~~~~")),         # printf (A0 0x3f)
           (0x80014560, bytes.fromhex("~~~~~~~~~~~~~~~~"))],        # puts (B0 0x3f)
    spare=[(0x8001d0f4, 0x8001d14c, b"Library Programs")],
)


def code(defines=None): return mtpatch.code(CFG, defines)
def patches(read, defines=None): return mtpatch.patches(CFG, read, defines)


if __name__ == "__main__":
    E = open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "disc", "SLUS_010.59"), "rb").read()
    p, c = patches(lambda a, n: E[0x800 + a - 0x80010000:0x800 + a - 0x80010000 + n])
    print(c["used"], c["free"], [(hex(a), len(d)) for a, d in c["segs"]], {k: hex(v) for k, v in c["sym"].items() if k.startswith(("mt_", "V"))})


# ---- vs CPU (mktag --vscpu, needs --mtap): common/mtap/mtcore.c + mtvsui.c with MT_VSCPU.
# Spans: the same EXE block (resident); the select module after SEL01's sector-rounded end (0x801edcec, a SEL01 copy at
# the disc end carries it: games/mvc/work/vscpu/select_re.md); kernel 0x8000A040-0x8000A100 (.kc: fight code copied by
# the select module) and 0x8000C790-0x8000C7F0 (.kz: vars, zero at boot): the top of achbuild span C110-C7F0 (real-PS1
# proven), cut from dxahead's side-1 stash pool C100-C800 when --vscpu (tools/speed4/dxahead.py); rc4.12's achievements
# core took the A040 / FEE0 spans planned first.
SEL_BASE, SEL_SIZE, SEL_LIMIT = 0x8018dcec, 392352, 0x801fa000
SEL_END = SEL_BASE + ((SEL_SIZE + 2047) & ~2047)              # 0x801edcec
FTAB_SEL01 = 0x8002617c                                       # file table entry 371 (MSF + size)
# The module lives INSIDE SEL01 (written in place, same size / file table entry): the tail of entry 1's DSP buffer.  This
# hack always loads SP_SEL4 (selscreen.py) to 0x801c3da0-0x801e35a0; stock VERSUS loaded SP_SEL3 over the whole range up to
# 0x801ee5a0, so those file bytes are dead.  (A grown SEL01 broke ARCADE: every SEL01 read between matches wrote past its
# end into RAM the ARCADE fights keep.)
MOD_AT = 0x801ed180
CFG_V = dict(CFG, spans=[CFG["spans"][0], (MOD_AT, SEL_BASE + SEL_SIZE, "vsui"), (0x8000C6D0, 0x8000C790, ".kc"),
                         (0x8000C790, 0x8000C7F0, ".kz")])
DEF_V = dict(MT_VSCPU=1)


def code_v(): return mtpatch.code(CFG_V, DEF_V)
def patches_v(read): return mtpatch.patches(CFG_V, read, DEF_V)
SELMAIN, SELMAIN_PTR = 0x8018e948, 0x801b017c                 # select main, reached through this SEL01 table word


def _unused_vsel_len():
    """bytes after SEL01's sector-rounded end: the select module + the kernel-code copy source"""
    c = code_v()
    sp = lambda a: next(s for s in CFG_V["spans"] if s[0] <= a < s[1])
    return sum(len(d) for a, d in c["segs"] if len(sp(a)) > 2 and sp(a)[2] in ("vsui", ".kc"))


TRAMP = 0x8019bcd4                                            # SEL01 function never referenced (124 B; static scan in SEL01 + EXE)


def trampoline(sym):
    """select main's table word -> here: module magic intact ? j vs_selmain : j select main (the module area is
    overwritten on the ARCADE stage screen: a bigger DSP load)"""
    import struct
    m = sym["vs_magic"]; hi = (m + 0x8000) >> 16; lo = m & 0xffff
    j = lambda t: 0x08000000 | (t >> 2 & 0x03FFFFFF)
    w = [0x3C080000 | hi, 0x8D080000 | lo,                        # lui t0, hi; lw t0, lo(t0)
         0x3C095550, 0x35295356,                                   # t1 = 'VSPU'
         0x15090003, 0,                                            # bne t0, t1, +3; nop
         j(sym["vs_selmain"]), 0, j(SELMAIN), 0]
    return struct.pack("<%dI" % len(w), *w)


def sel01_patches(mtc):
    """[(file offset, bytes)] for SEL01 (in place): the module, the trampoline, select main's table word -> trampoline"""
    import struct
    oa, od = mtc["ovl"]
    assert oa == MOD_AT and oa + len(od) <= SEL_BASE + SEL_SIZE
    return [(oa - SEL_BASE, od), (SELMAIN_PTR - SEL_BASE, struct.pack("<I", TRAMP)), (TRAMP - SEL_BASE, trampoline(mtc["sym"]))]


# ---- (rc4.15) VERSUS CPU main-menu row without multitap (mktag --vscpu without --mtap; common/mtap MT_VSMENU): no SIO
# driver, no setup panel, no SEL01 module (its bytes were the VS screen's bottom-left texture), no kernel RAM: everything
# resident in the EXE debug-string block (the copyright spare span is --titlefix's: not used).  mt_select = mtmenu.h's lean one.
CFG_M = dict(CFG, spans=[CFG["spans"][0]], keep=("mt_tick", "mt_mask_v", "mt_vsconf"))
DEF_M = dict(MT_VSCPU=1, MT_VSMENU=1, MT_OWN_SELECT=1)


def code_m(): return mtpatch.code(CFG_M, DEF_M)
def patches_m(read): return mtpatch.patches(CFG_M, read, DEF_M)


def sel01_patches_m(mtc):
    """[(file offset, bytes)] for SEL01 (in place): only the module (mt_tick calls it while its magic is there)"""
    oa, od = mtc["ovl"]
    assert oa == MOD_AT and oa + len(od) <= SEL_BASE + SEL_SIZE
    return [(oa - SEL_BASE, od)]
