"""Playable Cyber-Akuma (hold SELECT + confirm on Akuma) + secret characters unlocked - Marvel Super Heroes vs. Street Fighter (USA, SLUS-00793).

What the stock game already has (found in SELECT.BIN and in the EXE's SHORT CUT select, details in docs/GAMEPLAY.md):
  * Cyber-Akuma (char 0x13, team-id word 0x26) and Apocalypse (char 0x00) are playable, solo: the select screen skips
    the partner pick for them and stores the same id in both team slots; the partner object then starts every round
    with life 0 (object init: flag bit 1 << char in +0x2a0 & 0x80001 -> 0x80039c20), so he cannot tag, call or be
    tagged in, and his KO ends the match.  The engine has id checks for 0x26 all over the fight code.
  * They are picked with a code: on Akuma press SELECT 5 times (Cyber-Akuma) or 6 times (Apocalypse), then confirm.
    The code only works when the save flag 0x80025076 (option block, saved on the memory card) has bit 1 / bit 0 set.
  * Mech-Zangief, Dark Sakura, Shadow, U.S. Agent, Mephisto and Armored Spider-Man are picked by holding SELECT while
    confirming Blackheart, Hulk, Dhalsim, Bison, Omega Red, Spider-Man.  Not gated by anything (checked in stock).

Patches (all in place, no new code space; cyber.S):
  SEL.ARC + SELECT.BIN (select-screen overlay at 0x80094800, only resident on the select screen):
    0x80097698-0x800977b4  per-frame code counter rewritten: no save-flag gate, + SELECT held while a confirm button is
                           pressed on Akuma with nothing picked yet -> count 5 in that frame (the stock pick right after
                           it gives Cyber-Akuma), the same "hold SELECT + confirm" pattern as the six stock variants
    0x80097858             pick: `lb v0,0x36(a2)` (flag != 0) -> li v0,1
    0x8009788c, 0x800978b4 pick: `lbu v0,0x5076(v0)` -> li v0,3 (bit 1 Cyber-Akuma, bit 0 Apocalypse)
  SLUS_007.93 (SHORT CUT ON: the EXE's text-list select 0x8004e8f8..):
    0x8004f82c-0x8004f8c4  tail of the input reader 0x8004f64c: same rule (main-pick state 2 only); there the SELECT
                           bit of the result is cleared for that confirm (the stock Cyber-Akuma check needs it clear)
    0x8004fb00, 0x8004fb70 pick: `lbu v0,0x36(a0)` -> li v0,3

    patches()          [(addr, bytes)] for SLUS_007.93
    overlay_patches()  [(file, offset, bytes)] (SEL.ARC, SELECT.BIN)
    check_orig(read32) / check_overlay(read32[, base])   stock words at every patched site
    apply_ram(emu)     EXE part now + SELECT.BIN part if the overlay is resident (it is re-read from the disc on every
                       select screen: use a disc with the overlay patch for anything that leaves the select screen)
"""
import os, struct, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

SRC = os.path.join(HERE, "cyber.S")
OVL, OVL_BASE = "SELECT.BIN", 0x80094800
# the select screen runs from SEL.ARC (file 223, read to 0x800947d4 by 0x8002b338: 0x2c-byte header, then the same
# code as SELECT.BIN); SELECT.BIN (file 0) is patched too so both copies stay equal
OVLS = (("SEL.ARC", 0x800947d4), ("SELECT.BIN", 0x80094800))
SEL_AT, SEL_END = 0x80097698, 0x800977b4
EXE_AT, EXE_END = 0x8004f82c, 0x8004f8c4
LI_V0 = lambda n: 0x24020000 | n
NOP = 0

# stock words (checked before patching)
SEL_WORDS = {0x80097858: 0x80c20036, 0x8009788c: 0x90425076, 0x800978b4: 0x90425076,
             0x80097698: 0x27bdffe8, 0x800976fc: 0x3c028002, 0x800977b0: 0x00000000}
EXE_WORDS = {0x8004fb00: 0x90820036, 0x8004fb70: 0x90820036, 0x8004f82c: 0x3c028002, 0x8004f830: 0x24427d60,
             0x8004f8c0: 0x02401021, 0x8004f8c4: 0x8fbf0024}


def build():
    import toolenv
    gcc = toolenv.mips_prefix()
    with tempfile.TemporaryDirectory(prefix="cyber_") as d:
        return _build(gcc, d)


def _build(gcc, d):
    o, elf = os.path.join(d, "cyber.o"), os.path.join(d, "cyber.elf")
    subprocess.check_call([gcc + "as", "-mips1", "-EL", "-no-mips16", SRC, "-o", o])
    subprocess.check_call([gcc + "ld", "-EL", "--section-start=.sel=%#x" % SEL_AT, "--section-start=.exe=%#x" % EXE_AT,
                           "-e", "0", o, "-o", elf])
    out = {}
    for sec in (".sel", ".exe"):
        b = os.path.join(d, sec[1:] + ".bin")
        subprocess.check_call([gcc + "objcopy", "-O", "binary", "-j", sec, elf, b])
        out[sec] = open(b, "rb").read()
    sel, exe = out[".sel"], out[".exe"]
    assert SEL_AT + len(sel) <= SEL_END, "sel_tick too big: %d" % len(sel)
    assert EXE_AT + len(exe) <= EXE_END - 4 + 4, "exe tail too big: %d" % len(exe)
    sel += bytes(SEL_END - SEL_AT - len(sel))
    # the EXE tail must end with `move v0,s2` at 0x8004f8c0: put the nops before it
    assert exe[-4:] in (struct.pack("<I", 0x02401021), struct.pack("<I", 0x02401025))   # move v0,s2
    exe = exe[:-4] + bytes(EXE_END - EXE_AT - len(exe)) + exe[-4:]
    assert len(exe) == EXE_END - EXE_AT
    return sel, exe


def _w(a, w): return (a, struct.pack("<I", w))


def patches():
    sel, exe = build()
    return [(EXE_AT, exe), _w(0x8004fb00, LI_V0(3)), _w(0x8004fb70, LI_V0(3))]


def ram_overlay_patches():
    """[(addr, bytes)] for SELECT.BIN while it is resident"""
    sel, exe = build()
    return [(SEL_AT, sel), _w(0x80097858, LI_V0(1)), _w(0x8009788c, LI_V0(3)), _w(0x800978b4, LI_V0(3))]


def overlay_patches():
    return [(f, a - base, d) for f, base in OVLS for a, d in ram_overlay_patches()]


def check_orig(read32):
    for a, w in EXE_WORDS.items():
        assert read32(a) == w, "unexpected EXE word at %08x: %08x" % (a, read32(a))


def check_overlay(read32):
    """read32(addr) of the overlay as loaded at 0x80094800"""
    for a, w in SEL_WORDS.items():
        assert read32(a) == w, "unexpected SELECT.BIN word at %08x: %08x" % (a, read32(a))


def apply_ram(emu):
    if emu.u32(EXE_AT + 4) == EXE_WORDS[EXE_AT + 4]:          # not applied yet: the sites must be stock
        check_orig(emu.u32)
    for a, d in patches():
        emu.poke(a, d)
    if emu.u32(0x80097698) in (SEL_WORDS[0x80097698], struct.unpack_from("<I", ram_overlay_patches()[0][1])[0]):
        for a, d in ram_overlay_patches():
            emu.poke(a, d)


def apply_exe(exe: bytearray, base=0x80010000, hdr=0x800):
    rd = lambda a: struct.unpack_from("<I", exe, a - base + hdr)[0]
    check_orig(rd)
    for a, d in patches():
        exe[a - base + hdr:a - base + hdr + len(d)] = d
    return exe


if __name__ == "__main__":
    exe = open(os.path.join(ROOT, "games", "mshvsf", "disc", "SLUS_007.93"), "rb").read()
    check_orig(lambda a: struct.unpack_from("<I", exe, a - 0x80010000 + 0x800)[0])
    sel, x = build()
    print("sel_tick %d bytes (of %d), exe tail %d bytes" % (len(sel.rstrip(b"\0")), SEL_END - SEL_AT, len(x)))
    for a, d in patches():
        print("EXE %08x %3d %s" % (a, len(d), d[:16].hex()))
    for f, off, d in overlay_patches():
        print("%s +%05x %3d %s" % (f, off, len(d), d[:16].hex()))
