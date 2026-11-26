"""Special partner (assist) disabled in tag battles - Marvel vs. Capcom (SLUS-01059).

User decision: the assist characters may be dropped when full partners are loaded (the tag loader needs their RAM).
Stock behaviour stays wherever tagmode.py leaves the fight alone (cut-down partner, boss fight, Cross Over, demo).

How it is done: the tag battle is put into a state the stock VERSUS code already supports - "no special partner
chosen" (bit per side clear in 0x8007b744 = 0x8007b6e8 + 0x5c) - but only for the code that deals with assists.
Those readers of the versus flag are redirected to ASSIST_GATE 0x800858c8 (was 0x8007b6ea: a live game byte), which tagmode.py's battle-init stub sets
(1 in a tag battle, together with clearing the bits; = the flag otherwise, i.e. unchanged stock behaviour):

  0x80056344  assist call input 0x80056330 (human MP+MK = mask 0x220, and the CPU pattern 0x800723d4):
              `lb v0,0x75(v1)` -> `lb v0,2(v1)`: gate 1 + bit clear -> returns 0, nothing is spawned,
              no stock is spent (decrement at 0x80052c10 is behind this routine).
  0x800432e4  HUD stock counter "xN" 0x800432e0 (draws only in Cross Over rules): `lb v0,-0x48a3(v0)` -> gate.
  0x80043184, 0x80043220  HUD assist portraits 0x80043174 (P1 / P2): `lb ..,0x75(a0)` -> `lb ..,2(a0)`:
              gate 1 + bit clear -> not drawn.

Not touched (verified harmless under the tag rules, flag 0): the effect spawn 0x8004faa4 and the versus-only assist
paths 0x800406ac / 0x8004ebb8 / 0x8005e188 (skipped with flag 0); the KO / team-move readers that test the partner's
life instead (0x80030614, 0x8003ba20, 0x8003bb00, 0x8004bd94, 0x8005287c: Cross Over branch, which uses the PARTNER
object and its own character data, never the DA files).  The partner objects 0x8007c6f0 / 0x8007caf8 are the assist
objects in stock versus (0x8007b8cc / 0x8007b8d4); with tag rules they are always the partner characters, so no
code reaches the assist slots 0x80150d00 / 0x801eda00.  Loader note: the versus loader 0x8002b7a4 loads DAxx_11/_21
when the flag is 1 and the side's bit is set (0x8002ba0c / 0x8002baa8); the tag loader decides that itself.
Selection on the select screen still works but is ignored in a tag battle.
"""
import os, struct, sys
EXE_BASE, EXE_HDR = 0x80010000, 0x800

# addr: (stock word, new word)
SITES = {    # ASSIST_GATE 0x800858c8 (dead EXE span after hcguard, zeroed by mktag; 0x8007b6ea toggles every second in battle).
             # Every site has v0 = 0x80080000 (lui) at that point -> lb .., 0x58c8(v0)
    0x80056344: (0x80620075, 0x804258C8),     # lb v0,0x75(v1)    -> lb v0,0x58c8(v0)
    0x800432e4: (0x8042B75D, 0x804258C8),     # lb v0,-0x48a3(v0) -> lb v0,0x58c8(v0)
    0x80043184: (0x80820075, 0x804258C8),     # lb v0,0x75(a0)    -> lb v0,0x58c8(v0)
    0x80043220: (0x80830075, 0x804358C8),     # lb v1,0x75(a0)    -> lb v1,0x58c8(v0)
}


HUD = (0x800432e4, 0x80043184, 0x80043220)       # --assist (rc4.4): the HUD sites keep the stock flag read (tag rules =
                                                 # Cross Over HUD: assist portrait + stock count); only the call input
                                                 # stays on ASSIST_GATE (1 + the side's bit = per-side assists)


def patches(assist=False):
    return [(a, struct.pack("<I", n)) for a, (o, n) in SITES.items() if not (assist and a in HUD)]


def check_orig(read32):
    for a, (o, n) in SITES.items():
        assert read32(a) == o, f"unexpected code at {a:08x}: {read32(a):08x}"


def apply_ram(emu):
    for a, (o, n) in SITES.items():
        assert emu.u32(a) in (o, n), f"unexpected code at {a:08x}"
    for addr, data in patches():
        emu.poke(addr, data)


def apply_exe(exe: bytearray):
    check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    for addr, data in patches():
        o = addr - EXE_BASE + EXE_HDR
        exe[o:o + len(data)] = data
    return exe


if __name__ == "__main__":
    ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
    exe = open(os.path.join(ROOT, "games", "mvc", "disc", "SLUS_010.59"), "rb").read()
    check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    for addr, data in patches():
        print(f"{addr:08x} {data.hex()}")
