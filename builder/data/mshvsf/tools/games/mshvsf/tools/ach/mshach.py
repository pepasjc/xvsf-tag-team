"""MSHvSF built-in achievements: build the blob and the patches (tools/ach runtime, port.c, set.py).

Used by tools/tagload/mktag.py --ach.  See docs/ACHIEVEMENTS.md.

    parts(read_exe, read_ovl)  -> dict(exe=[(addr, bytes)], ovl=[(addr, bytes)], pc0=new pc0 (or None),
                                       ram=[(addr, bytes)] (the two images + zeroed BSS, for savestate tests), info)
read_exe(addr, n) reads the EXE image as it is about to be written (after every other patch), read_hdr(off, n) its
header (pc0 at +0x10: the boot copy chains to it), stock_ovl(addr, n) the stock main-menu overlay (OPDEMO.BIN at
0x80094800), to check the words that are replaced.
"""
import hashlib, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "ach")]
import achbuild
import importlib.util
_spec = importlib.util.spec_from_file_location("msh_ach_set", os.path.join(HERE, "set.py"))
SET = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(SET)

HOOK_IDLE = (0x800208d4, "6d057716c0c25b4ec8c430a70f35c30ea74611fc")    # present: jal DrawSync (a0 = 0) -> jal ach_idle (A + 0x10); SHA-1 of the stock word
HOOK_FRAME = (0x80020c64, "f34c9c4c755480e1e5ad85c705a3d13b5f182592")   # main frame: jal frame begin (ClearOTag) -> jal ach_frame (A + 0x00)
MENU_SHA = "966a55e4ed80d50becd7933713b6acad960b29fe"                     # stock menu words at 0x8009942c, 0x80099434, 0x800994c0
COPY_AT, COPY_END = 0x80140000, 0x80150000 # zero in the stock EXE image, above the boot cards (0x80100000-0x80140000)
OVL = 0x80094800
# main menu (OPDEMO.BIN / OPE.ARC entry 0): text table, 7 entries drawn at stride 13 from our copy
MENU = ["BATTLE", "VERSUS", "TRAINING", "HERO BATTLE", "ACHIEVEMENTS", "OPTION", "GALLERY"]
STOCK_TAB = 0x800b5e3c
OPT_H = 0x80099e44; GAL_H = OPT_H + 0x4c          # (written as an offset: the game-data scan flags two adjacent literals equal to OPDEMO words)
jal = lambda t: struct.pack("<I", 0x0C000000 | (t >> 2 & 0x03FFFFFF))
w32 = lambda *v: struct.pack("<%dI" % len(v), *v)


OVL_AT = [0x8009942c, 0x80099434, 0x800994b8, 0x800994c0, 0x80099c8c, 0x80099c90, 0x800b6274, 0x800b6278, 0x800b627c]   # port.c ovl_at
# MSHvSF's START skip lives at 0x80007c00-0x80008000: our span below it may reach 0x80007c00
SPANS = [(a, 0x80007CC0 if b == 0x80007A00 else b) for a, b in achbuild.SPANS]      # (the START skip starts at 0x80007cc0)


def build(defines=None):
    return achbuild.build_spans(HERE, SET, SPANS, defines=defines)


def code(prev_pc0, ovl_sum):
    """our code only (the release builder prebakes this: builder/mshb/pipeline.py PREBAKED): prev_pc0 = the EXE entry
    the copy stub chains to, ovl_sum = sum of the menu-overlay words (as the disc has them) the runtime patches in RAM.
    -> dict(exe=[(addr, bytes)] (the boot copy only), ovl=[] (nothing on the disc), pc0, ram, hooks, info)"""
    segs, info = build(dict(PORT_OVL_SUM="0x%08xu" % ovl_sum, ACH_NOCOST=1, CARD_SIMPLE=1))      # (room: no cost counters, one card message)
    sym = info["sym"]
    A0 = achbuild.SPAN_BASE
    hooks = [(HOOK_IDLE[0], 0x0C000000 | ((A0 + 0x10) >> 2 & 0x03FFFFFF)), (HOOK_FRAME[0], 0x0C000000 | (A0 >> 2 & 0x03FFFFFF))]
    copy = achbuild.copy_stub_spans(COPY_AT, segs, hooks, prev_pc0)
    assert COPY_AT + len(copy) <= COPY_END
    inf = {k: v for k, v in info.items() if k != "size"}
    return dict(exe=[(COPY_AT, copy)], ovl=[], pc0=COPY_AT, ram=segs, hooks=hooks, info=inf)


def parts(read_exe, read_hdr, stock_ovl=None, cur_ovl=None):
    """code() + the checks against the image being written (hook sites, zero copy area, stock menu words);
    cur_ovl(addr, n) reads the menu overlay as the disc will have it (other patches applied)"""
    for at, stock in (HOOK_IDLE, HOOK_FRAME):
        assert hashlib.sha1(read_exe(at, 4)).hexdigest() == stock, "hook site %08x not stock" % at
    if stock_ovl:      # the stock words we replace (menus.py may have changed some already)
        assert hashlib.sha1(stock_ovl(0x8009942c, 4) + stock_ovl(0x80099434, 4) + stock_ovl(0x800994c0, 4)).hexdigest() == MENU_SHA
        st = stock_ovl(STOCK_TAB, 84)
        names = [st[12 * i:12 * i + 12].split(bytes(1))[0].decode() for i in range(7)]
        assert names[:4] == MENU[:4] and names[5:] == ["OPTION", "GALLERY"], names
    rd = cur_ovl or stock_ovl
    ovl_sum = sum(struct.unpack("<I", rd(a, 4))[0] for a in OVL_AT) & 0xffffffff
    c = code(struct.unpack("<I", read_hdr(0x10, 4))[0], ovl_sum)
    copy = c["exe"][0][1]
    assert read_exe(COPY_AT, len(copy)) == bytes(len(copy)), "copy area not zero in the EXE image"
    return c


if __name__ == "__main__":
    segs, info = build(dict(PORT_OVL_SUM="0u", ACH_NOCOST=1, CARD_SIMPLE=1))
    print({k: (hex(v) if isinstance(v, int) and v > 0x80000000 else v) for k, v in info.items() if k not in ("sym", "size")})
