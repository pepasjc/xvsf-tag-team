"""Main menu - Marvel vs. Capcom (SLUS-01059): CROSS OVER removed + version line.  All patches are in DAT/OPDEMO.ARC
(file 342, read to 0x8009dfe4 by 0x8002c6e0; entry 0 = title / main menu code at 0x8009e000, the only copy of the
menu: no other file holds its strings).  File offset = addr - 0x8009dfe4.  No new code, no EXE change.

Stock menu (state 0 handler 0x800a2b6c, cursor = byte 0x8007b6f4 (= 0x8007b6e8 + 0xc), text routine 0x800a2a50):
6 items BATTLE, VERSUS, CROSS OVER, TRAINING, GALLERY, OPTION, strings 0x800b5bb4 (11-byte stride), y = 0x78 +
0x14 * i, x centred ((10 - len) * 8 + 0xb0), font call 0x80020f10.  Confirm -> state = cursor + 1, state table
0x800b5bf8: 1 BATTLE (mode 0) 0x800a2d74, 2 VERSUS (mode 1) 0x800a2d7c, 3 CROSS OVER (mode 2) 0x800a2d8c,
4 TRAINING (mode 3) 0x800a2d84, 5 GALLERY 0x800a15ec-caller 0x800a2dd0, 6 OPTION 0x800a2de0, 8 EX OPTION (SELECT +
START held on OPTION, 0x800a2d14).

Patched:
  strings      BATTLE, VERSUS, TRAINING, GALLERY, OPTION at the old 11-byte stride, then the version text as a
               6th line (13 bytes left up to the state table: "TAG HACK 0.3" fits); the loop still draws 6 lines,
               the cursor never reaches line 6 (normal colour 0x27, bottom line y 0xdc, centred)
  wrap         0x800a2c68 `slti v0,v0,6` -> 5, 0x800a2c6c `li v0,5` -> 4 (cursor 0..4)
  state table  [3] TRAINING 0x800a2d84, [4] GALLERY 0x800a2dd0, [5] OPTION 0x800a2de0, [6] -> 0x800a2df8 (no-op)
  EX OPTION    0x800a2d00 `li v0,5` -> 4 (cursor on OPTION)
  GALLERY exit 0x800a1878 `li v0,4` (cursor back on GALLERY) -> 3
Mode 2 (CROSS OVER) is set only by 0x800a2d8c, which nothing reaches now.  The VERSUS skip without a second pad
(0x80024c08, cursor index 1) is unchanged.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FILE, BASE = "OPDEMO.ARC", 0x8009dfe4
STR, STATES = 0x800b5bb4, 0x800b5bf8
DEFAULT = "TAG HACK 0.3"
STOCK_STR = b"BATTLE\0\0\0\0\0VERSUS\0\0\0\0\0CROSS OVER\0TRAINING\0\0\0GALLERY\0\0\0\0OPTION\0\0\0\0\0"
STOCK_STATES = (0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~)
# addr: (stock word, new word)
SITES = {
    0x800a2c68: (0x28420006, 0x28420005),
    0x800a2c6c: (0x24020005, 0x24020004),
    0x800a2d00: (0x24020005, 0x24020004),
    0x800a1878: (0x24020004, 0x24020003),
}


EXOPT = "--exopt" in sys.argv                    # EX OPTIONS (exopt.py, fx worker): the 6th line is a selectable item, the
                                                 # version text moves to the bottom of the EX OPTIONS screen
VSMENU = "--vscpu" in sys.argv and "--mtap" not in sys.argv   # (rc4.15) VERSUS CPU main-menu row below VERSUS (needs --ach:
                                                 # the menu module writes the 8-line menu, mvcach.menu_patch); no multitap


def strings(text=DEFAULT):
    assert len(text) <= 12 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-" for c in text)
    s = b"".join(n.encode().ljust(11, b"\0") for n in ("BATTLE", "VERSUS", "TRAINING", "GALLERY", "OPTION"))
    s += (b"EX OPTIONS" if EXOPT else text.encode()) + b"\0"
    assert len(s) <= STATES - STR
    return s.ljust(len(STOCK_STR) + 2, b"\0")[:STATES - STR]


def ram_patches(text=DEFAULT):
    st = list(STOCK_STATES)
    st[3:7] = [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~]
    sites = dict(SITES)
    if EXOPT:                                    # --exopt: cursor 0..5 (the stock wrap words), item 5 -> state 6 = EX OPTIONS
        import exopt
        st[6] = exopt.stub()
        sites[0x800a2c68] = (0x28420006, 0x28420006); sites[0x800a2c6c] = (0x24020005, 0x24020005)
    out = [(STR, strings(text)), (STATES, struct.pack("<9I", *st))]
    out += [(a, struct.pack("<I", n)) for a, (o, n) in sorted(sites.items())]
    return out


def overlay_patches(text=DEFAULT):
    return [(FILE, a - BASE, d) for a, d in ram_patches(text)]


def check_file(data):
    assert data[STR - BASE:STR - BASE + len(STOCK_STR)] == STOCK_STR, "menu strings not stock"
    assert struct.unpack_from("<9I", data, STATES - BASE) == STOCK_STATES, "menu state table not stock"
    for a, (o, n) in SITES.items():
        assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"{FILE} {a:08x} not stock"


def apply_ram(emu, text=DEFAULT):
    """while OPDEMO.ARC is in RAM (title / main menu)"""
    assert emu.u32(0x800a2c68) in (0x28420006, 0x28420005), "main menu overlay not in RAM"
    for a, d in ram_patches(text):
        emu.poke(a, d)


if __name__ == "__main__":
    import os
    ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
    check_file(open(os.path.join(ROOT, "games", "mvc", "work", "gpw", "files", FILE), "rb").read())
    for f, o, d in overlay_patches():
        print(f, hex(o), d.hex())
