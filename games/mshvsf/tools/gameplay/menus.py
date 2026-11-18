"""Main-menu and OPTION-menu changes - MSHvSF (SLUS-00793).  Source: menus.S (+ the overlay word patches below).

1. CROSS OVER is gone from the main menu (the tag mode replaces it).  OPDEMO.BIN (main menu overlay at 0x80094800):
   - menu text table 0x800b5e3c (7 x 12 bytes: BATTLE VERSUS TRAINING HERO-BATTLE CROSS-OVER OPTION GALLERY):
     entries 4, 5 <- OPTION, GALLERY, entry 6 cleared; the draw loop 0x80099404 draws 6 entries (0x800994b8);
   - cursor 0x8002504c wraps in 0..5 (0x80099c8c / 0x80099c90);
   - state table 0x800b6260 (state = cursor + 1 on START): states 5, 6 (7) -> the OPTION / GALLERY handlers.
     The CROSS OVER handler 0x80099e2c (mode 0x800250ac = 3) is no longer reachable; the attract demo only uses
     mode 0 (checked: 12000 vblanks of attract).
2. Extra OPTION lines (API in menus.S and docs/GAMEPLAY.md): draw hook at the end of the option-screen draw
   routine (0x80099b3c), cursor wrap 0..13 + shown lines (0x8009a1d8..), the exit text moved from y 0xe0 to 0xe8.

    patches(msyms)          EXE [(addr, bytes)]   msyms = tools/speed/meter.py symbols (None: no meter line)
    overlay_patches(msyms)  [(file, offset, bytes)]
    symbols(msyms)          {optlines, ...}
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(GAME, "tools", "speed"))
SRC = os.path.join(HERE, "menus.S")
OVL, OVL_BASE = "OPDEMO.BIN", 0x80094800
# free EXE ranges (break-filled: gameplay deadtest / speed deadtest; see docs/CODESPACE.md)
RANGES = {"a": (0x80010e24, 0x80010e90), "b": (0x800136e0, 0x80013748), "c": (0x8003b7c4, 0x8003b808),
          "d": (0x8001786c, 0x800178b4), "e": (0x80022240, 0x80022288), "f": (0x8002425c, 0x800242ac),
          "g": (0x8005bd28, 0x8005bd74),
          "h": (0x8004a3e8, 0x8004a428)}     # behind ahead.py's chunk N (0x8004a388.., 96 bytes used)
NLINES = 2
AP8 = None          # (flag byte, show-if byte): line 1 "ARCADE FRAMES" of the 8 MB build (set by tools/ap8/mkap8.py)


def build(msyms=None):
    import slib
    defs = dict(NLINES=NLINES, METER=1 if msyms else 0, MFLAG=msyms["mflag"] if msyms else 0,
                AP8=1 if AP8 else 0, AP8FLAG=AP8[0] if AP8 else 0, AP8SHOW=AP8[1] if AP8 else 0)
    out, syms, plan = slib.pack(open(SRC).read(), RANGES, defs)
    return out, syms, plan


def patches(msyms=None):
    out, syms, plan = build(msyms)
    return [(RANGES[k][0], b) for k, b in out.items()]


def symbols(msyms=None):
    return build(msyms)[1]


OPT_H = 0x80099e44                  # the OPTION handler in OPDEMO.BIN
GAL_H = 0x80099e90                  # the GALLERY handler


def overlay_patches(msyms=None):
    S = symbols(msyms)
    W = lambda a, *w: (OVL, a - OVL_BASE, struct.pack("<%dI" % len(w), *w))
    J = lambda op, t: 0x08000000 * (op == 2) + 0x0c000000 * (op == 3) | (t >> 2 & 0x3ffffff)
    txt = lambda s: s.encode().ljust(12, b"\0")
    return [W(0x800994b8, 0x2a220006),                        # main menu: draw 6 entries
            W(0x80099c8c, 0x28420006, 0x24020005),            #   cursor wraps in 0..5
            (OVL, 0x800b5e3c + 48 - OVL_BASE, txt("OPTION") + txt("GALLERY") + bytes(12)),
            W(0x800b6274, OPT_H, GAL_H, GAL_H),               # states 5, 6, 7: OPTION, GALLERY
            W(0x80099b3c, J(2, S["optdraw"])),                # option screen: extra lines
            W(0x8009a1d8, J(3, S["optwrap"])),                #   cursor wrap (delay slot: the stock nop)
            W(0x8009a1e0, J(2, 0x8009a370), 0x24020002),      #   continue as both stock paths (v0 = 2)
            W(0x800995c4, 0x241500e8)]                        #   exit text y 0xe0 -> 0xe8


STOCK = {0x800994b8: 0x2a220007, 0x80099c8c: 0x28420007, 0x80099c90: 0x24020006, 0x800b6274: 0x80099e2c,
         0x800b6278: 0x80099e44, 0x800b627c: 0x80099e90, 0x80099b3c: 0x03e00008, 0x8009a1d8: 0x8202000d,
         0x8009a1dc: 0, 0x8009a1e0: 0x04410004, 0x8009a1e4: 0x2842000e, 0x800995c4: 0x241500e0}


def check_stock(read32):
    for a, w in STOCK.items(): assert read32(a) == w, "%08x: %08x" % (a, read32(a))


if __name__ == "__main__":
    out, syms, plan = build({"mflag": 0x800243c8})
    print(plan, {k: len(v) for k, v in out.items()})
