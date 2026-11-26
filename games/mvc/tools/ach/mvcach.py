"""MvC built-in achievements: blob + patches (tools/ach runtime, port.c, set.py).  Used by tools/tagload/mktag.py --ach
(after every other EXE / overlay patch; without --ach nothing changes).  See docs/ACHIEVEMENTS.md.

    parts(read_exe, read_hdr, read_ovl, ver) -> dict(exe=[(addr, bytes)], ovl=[(file offset, bytes)], pc0, ram, info)

read_exe(addr, n) / read_hdr(off, n): the EXE image as about to be written; read_ovl(addr, n): OPDEMO.ARC as about to
be written (menus.py already applied: our words are checked against its output); ver: the version line text.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "ach"), os.path.join(HERE, "..", "gameplay")]
import achbuild
import importlib.util
_spec = importlib.util.spec_from_file_location("mvc_ach_set", os.path.join(HERE, "set.py"))
SET = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(SET)
import menus

A0, B0, C0 = achbuild.REGION_A[0], achbuild.REGION_B[0], achbuild.REGION_C[0]
DRAWSYNC, FRAMEBEGIN = 0x80011864, 0x8002097c
HOOK_IDLE, HOOK_FRAME = 0x80022a18, 0x80022fe8      # present 0x80022a0c: jal DrawSync / main frame 0x80022f3c: jal frame begin
COPY_AT, COPY_END = 0x80140000, 0x80148000          # zero in the EXE image (character area at run time)
OVL_FILE, OVL_BASE = "OPDEMO.ARC", 0x8009dfe4
STATES, OPTION_H, NOOP_H = 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~
C_SECS = ("set.o(.rodata.ra_text)", "set.o(.rodata.ra_dict)", "icon.o(.rodata*)")
jal = lambda t: 0x0C000000 | (t >> 2 & 0x03FFFFFF)


def build():
    return achbuild.build(HERE, SET, c_secs=C_SECS)


def parts(read_exe, read_hdr, read_ovl, ver=None):
    u32 = lambda r, a: struct.unpack("<I", r(a, 4))[0]
    assert u32(read_exe, HOOK_IDLE) == jal(DRAWSYNC) and u32(read_exe, HOOK_FRAME) == jal(FRAMEBEGIN), "hook site not stock"
    imgs, info = build()
    sym = info["sym"]
    img = bytearray(imgs[0])
    # version line: the last of our 7 menu strings (menus.py put it as its 6th line)
    t = sym["ach_menutab"] - A0
    text = (ver or menus.DEFAULT).encode()
    if menus.EXOPT: text = b"EX OPTIONS"              # --exopt (fx worker): 7th line = EX OPTIONS item, version on that screen
    assert len(text) <= 12 and img[t + 13 * 6:t + 13 * 7] == bytes(13)
    img[t + 13 * 6:t + 13 * 6 + len(text)] = text
    imgs = (bytes(img),) + tuple(imgs[1:])
    prev_pc0 = struct.unpack("<I", read_hdr(0x10, 4))[0]
    copy = achbuild.copy_stub(HERE, COPY_AT, imgs, info["bss"], prev_pc0)
    assert COPY_AT + len(copy) <= COPY_END and read_exe(COPY_AT, len(copy)) == bytes(len(copy)), "copy area not zero"
    exe = [(HOOK_IDLE, struct.pack("<I", jal(A0 + 0x10))), (HOOK_FRAME, struct.pack("<I", jal(A0))), (COPY_AT, copy)]
    ovl = menu_patch(read_ovl, sym["ach_menutab"], sym["ach_state"], ver)
    ram = [(A0, imgs[0] + bytes(info["bss"])), (B0, imgs[1])] + ([(C0, imgs[2])] if len(imgs) > 2 and imgs[2] else [])
    return dict(exe=exe, ovl=ovl, pc0=COPY_AT, ram=ram, info=info, ovl_file=OVL_FILE)


def vsconf_words():
    """(rc4.15 VERSUS CPU row) OPDEMO 0x800a2d50-0x800a2d70, the main menu's confirm: state = mt_vsconf(cursor)"""
    sys.path.insert(0, os.path.join(HERE, "..", "mtap")); import mvcmtap
    f = mvcmtap.code_m()["sym"]["mt_vsconf"]
    return [0x9204000c,            # lbu a0, 0xc(s0)      cursor
            0x24020384,            # li v0, 0x384
            0xa6020004,            # sh v0, 4(s0)
            0xa2000001,            # sb zero, 1(s0)
            jal(f),                # jal mt_vsconf
            0xa6000002,            # sh zero, 2(s0)       (bytes 2, 3)
            0xa2020000,            # sb v0, 0(s0)         state
            0x08028b7e,            # j 0x800a2df8
            0x00000000]


def menu_patch(read_ovl, tab, state5, ver=None):
    """OPDEMO.ARC words on top of menus.py's output: the main menu draws our 7-line table `tab` (13-byte stride) and
    item ACHIEVEMENTS = state 5 = `state5` (the old runtime's ach_state, the rc4 core's c_state).  -> [(file off, bytes)]"""
    u32 = lambda r, a: struct.unpack("<I", r(a, 4))[0]
    # main menu on top of menus.py: our 13-byte table (7 lines, version last), 18-pixel rows, cursor 0..5,
    # ACHIEVEMENTS = state 5, OPTION = 6, EX OPTION test on cursor 5
    mp = dict(menus.ram_patches(ver or menus.DEFAULT))
    assert read_ovl(STATES, 36) == mp[STATES], "menu state table is not menus.py's"
    for a in (0x800a2c68, 0x800a2c6c, 0x800a2d00):
        assert read_ovl(a, 4) == mp[a], "%08x is not menus.py's" % a
    st = list(struct.unpack("<9I", mp[STATES]))
    st[5:8] = [state5, OPTION_H, NOOP_H]
    if menus.EXOPT:                                   # --exopt: item 6 -> state 7 = EX OPTIONS (gameplay/exopt.py)
        import exopt
        st[7] = exopt.stub()
    words = [(0x800a2a78, [0x3c020000 | ((tab + 0x8000) >> 16) & 0xffff]),     # lui v0, %hi(tab)
             (0x800a2a80, [0x24520000 | (tab & 0xffff)]),                      # addiu s2, v0, %lo(tab)
             (0x800a2afc, [0x26730010]),                                        # rows 16 pixels apart (7 lines; 18 cut the 7th at the bottom)
             (0x800a2b04, [0x2a220007]),                                        # 7 lines
             (0x800a2b0c, [0x2652000d]),                                        # stride 13
             (0x~~~~~~~~, [0x~~~~~~~~, 0x~~~~~~~~] if menus.EXOPT else [0x~~~~~~~~, 0x~~~~~~~~]),   # cursor 0..5 (--exopt 0..6)
             (0x800a2d00, [0x24020005]),                                        # EX OPTION: OPTION is item 5
             (STATES, st)]
    if menus.VSMENU:                                  # (rc4.15) 8 lines: BATTLE VERSUS [VERSUS CPU] TRAINING GALLERY
        assert menus.EXOPT                            # ACHIEVEMENTS OPTION EX OPTIONS; the state table is unchanged:
        words += [(0x800a2a74, [0x24130070]),          # confirm = cursor + 1 below VERSUS CPU, = cursor from it on
                  (0x~~~~~~~~, [0x~~~~~~~~, 0x~~~~~~~~]),   # (VERSUS CPU -> state 2 = VERSUS; the vs CPU core reads
                  (0x800a2d00, [0x24020006]),          # the cursor = 2).  first line y 0x70, 15 px rows; cursor 0..7;
                  (0x800a1878, [0x24020004]),          # EX OPTION on OPTION (6); GALLERY exit -> 4
                  (0x800a2d50, vsconf_words())]        # confirm: state = mt_vsconf(cursor) (tools/mtap/mtmenu.h)
        words = [(a, w) for a, w in words if a not in (0x800a2afc, 0x800a2b04)] + [(0x800a2afc, [0x2673000f]), (0x800a2b04, [0x2a220008])]
        words = [(a, w) for a, w in words if not (a == 0x800a2c68 and w[0] == 0x28420007)]
        words = [(a, w) for a, w in words if not (a == 0x800a2d00 and w[0] == 0x24020005)]
    stock ={0x800a2a78: 0x3c02800b, 0x800a2a80: 0x24525bb4, 0x800a2afc: 0x26730014, 0x800a2b04: 0x2a220006, 0x800a2b0c: 0x2652000b}
    for a, w in stock.items():
        assert u32(read_ovl, a) == w, "OPDEMO.ARC %08x not stock" % a
    return [(a - OVL_BASE, struct.pack("<%dI" % len(w), *w)) for a, w in words]


if __name__ == "__main__":
    imgs, info = build()
    print({k: (hex(v) if isinstance(v, int) and v > 0x80000000 else v) for k, v in info.items() if k not in ("sym", "size")})
