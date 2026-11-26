"""Tag-team rules for VERSUS / ARCADE - Marvel vs. Capcom (USA, SLUS-01059).
The MvC counterpart of XvSF's tagpatch + roundpatch + hudpatch + aipatch + bgmpatch (see games/mvc/docs/GAMEPLAY.md).

Why one switch is enough
  The port runs the arcade tag-team game in CROSS OVER mode.  Every battle rule that differs between the modes reads
  ONE byte, 0x8007b75d (= 0x8007b6e8 + 0x75, "versus flag"): 1 for ARCADE / VERSUS (set on menu entry, 0x~~~~~~~~,
  0x~~~~~~~~, 0x~~~~~~~~), 0 for CROSS OVER (0x80029c84).  111 readers in the EXE (74 lui/lb + 37 base+0x75) and a
  few in the character code (PL04/06/07/0C/0E/10/11/12).  With 0 the engine natively gives (only needs full partners):
    tag on HP+HK (partner jumps in, lock timer)          each character its own life bar (4-bar HUD)
    KO -> partner comes in (0x800319bc / 0x80030bcc)     KO'd partner cannot be tagged / called for team moves
    single round, match ends when both are down          time over compares team life (0x8004b544)
    only the BENCHED character recovers red life         CPU tags with its own pattern table (0x800723b0)
    XA music -> incoming character's theme after a KO (0x80031e5c / 0x800867f4, track table 0x8008849c)

Patch (no per-frame cost)
  H1  0x80045fc8 in the battle-scene init 0x80045df4, right after the battle loader and the object-list init and
      BEFORE object init 0x8002d0a0 and life init 0x8002d920: `jal 0x80021ec8` -> `jal stub`.
      stub = the two stores of 0x80021ec8, then
        mode 0x8007b740 == 2 (CROSS OVER)                 -> untouched (0 natively); TRAINING (3) like VERSUS
        no human side (0x8007bdc9 == 0: attract demo)    -> untouched
        both partners full (LOADER_FULL == 3)            -> flag 0, assists off (see assist.py), RESTORE = 1
        otherwise                                        -> untouched (stock rules: boss fight, cut-down partner)
      LOADER_FULL 0x800858ac (bit0 P1 partner, bit1 P2 partner) is written by the tag loader games/mvc/tools/tagload
      (cleared at every battle load by its heapcap hook; 3 only when it loaded all four characters full, mode
      VERSUS / ARCADE with a human).  Same key idea as XvSF's reduced-partner mask 0x800421bc.
      ASSIST_GATE 0x800858c8 (dead EXE span after hcguard; 0x8007b6ea toggled every second) = what assist.py's readers see: 1 = "versus, no special partner", else = the flag.
  H2  battle phase table 0x80071900[6] (0x80071918, data word): post-battle phase 0x8004c560 -> restore: if RESTORE,
      flag = 1 again, then jump to 0x8004c560.  That phase runs every frame after the match result (win pose ->
      continue / next fight / select), so the result screens and the next select run with the stock versus/arcade
      value; the result itself was already decided under the tag rules (0x8004b544, wins in 0x8007b82a/b).
      Cost: one byte load per frame in that phase only.  Menu mode entry rewrites the flag anyway.

Code: stub 0x8001176c-0x800117cc, restore 0x8001b988-0x8001b9e0 (games/mvc/docs/CODESPACE.md; dead spans from
games/mvc/tools/tagload/fnscan.py).  It was first placed at 0x80022474, but those three "unreferenced" functions are
called by DAT/BG09.ARC (stage overlay) and DAT/END.ARC.
"""
import os, struct, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mipsasm import Asm

EXE_BASE, EXE_HDR = 0x80010000, 0x800
ORG, LIMIT = 0x8001176c, 0x800117cc               # battle-init stub
ORG2, LIMIT2 = 0x8001b988, 0x8001b9e0             # post-battle restore
H1_AT, H1_ORIG = 0x80045fc8, 0x0C0087B2          # jal 0x80021ec8 (delay: sb zero,-0x421a(v0))
H2_AT, H2_ORIG = 0x80071918, 0x8004C560          # battle phase table 0x80071900[6]: post-battle phase 0x8004c560
POST = 0x8004c560
FLAG, MODE, HUMANS, TEAM = 0x8007b75d, 0x8007b740, 0x8007bdc9, 0x8007b8aa
GATE, LOADER_FULL, RESTORE = 0x800858c8, 0x800858ac, 0x800858ad   # LOADER_FULL / RESTORE: dead EXE span (tagload glue.S); 0x8007b6eb is a live game byte
ASSIST_BITS = 0x8007b744                         # base+0x5c: bit per side "special partner chosen"
ORIG = {H1_AT: H1_ORIG, H2_AT: H2_ORIG, 0x80021ec8: 0x3C028002, 0x80021ecc: 0xAC4464F0, 0x80021ed4: 0x03E00008,
        0x80021ed8: 0xAC4564F4}


def lo(a):
    return a & 0xFFFF                                # all globals are 0x8007xxxx with lo >= 0x8000 -> base 0x8008


AS_SAVE = 0x8001176b                             # --assist (rc4.4): side bits of the assists the tag loader loaded
                                                 # (EX OPTIONS reserved byte, zeroed by mktag; tagload.c AS_SAVE)


def build(tail=None, assist=False):
    a = Asm(ORG)
    a.label("stub")
    a.lui("$v0", 0x8002)
    a.sw("$a0", 0x64f0, "$v0")                       # the replaced call 0x80021ec8
    a.sw("$a1", 0x64f4, "$v0")
    a.lui("$t0", 0x8008)
    a.lb("$t1", lo(FLAG), "$t0")
    a.sb("$zero", lo(RESTORE), "$t0")
    a.sb("$t1", lo(GATE), "$t0")                    # default: assist code sees the stock flag
    a.lb("$t2", lo(MODE), "$t0")
    a.lbu("$t4", lo(LOADER_FULL), "$t0")
    a.xori("$t2", "$t2", 2)
    a.beq("$t2", "$zero", "ret")                     # CROSS OVER (mode 2): stock; ARCADE 0 / VERSUS 1 / TRAINING 3 go on
    a.xori("$t4", "$t4", 3)
    a.bne("$t4", "$zero", "ret")                     # the tag loader did not load both partners full: stock
    a.ori("$t2", "$zero", 1)
    a.sb("$zero", lo(FLAG), "$t0")                   # tag rules
    a.sb("$t2", lo(RESTORE), "$t0")
    a.sb("$t2", lo(GATE), "$t0")                     # assists: "versus without special partner"
    if assist:                                       # --assist: gate 1 + the loaded sides' bits = per-side assists
        a.lui("$t3", AS_SAVE >> 16)
        a.lbu("$t3", AS_SAVE & 0xFFFF, "$t3")
        a.nop()
        a.sb("$t3", lo(ASSIST_BITS), "$t0")
    else:
        a.sb("$zero", lo(ASSIST_BITS), "$t0")
    a.label("ret")
    if tail:
        a.j(tail)                                    # e.g. the speed meter's battle-init copy (ends with jr ra)
    else:
        a.jr("$ra")
    a.nop()
    return a


def build2(assist=False):
    a = Asm(ORG2)
    a.label("restore")                               # battle end: back to the mode's own value
    a.lui("$t0", 0x8008)
    a.lb("$t1", lo(RESTORE), "$t0")
    a.ori("$t2", "$zero", 1)
    a.beq("$t1", "$zero", "snd")
    a.nop()
    a.sb("$t2", lo(FLAG), "$t0")
    a.sb("$zero", lo(RESTORE), "$t0")
    if assist:                                       # --assist: the stage / VS screens after the battle see no assist
        a.sb("$zero", lo(ASSIST_BITS), "$t0")        # (the next battle init takes them from AS_SAVE again)
    a.label("snd")
    a.j(POST)                                        # the phase handler itself (a0 = battle struct, untouched)
    a.nop()
    # H1 entry: a tag battle that ended without its post-battle phase (an ARCADE challenger interrupts the fight)
    # leaves the flag at 0 -> put the mode's value back before deciding (stock loading + tag rules hangs)
    a.label("pre")
    a.lui("$t0", 0x8008)
    a.lb("$t3", lo(RESTORE), "$t0")
    a.ori("$t2", "$zero", 1)
    a.beq("$t3", "$zero", "pre1")
    a.nop()
    a.sb("$t2", lo(FLAG), "$t0")
    a.sb("$zero", lo(RESTORE), "$t0")
    a.label("pre1")
    a.j(ORG)                                         # the stub
    a.nop()
    return a


def assemble(tail=None, assist=False):
    a = build(tail, assist); code = a.assemble()
    assert ORG + len(code) <= LIMIT, f"stub too big: {len(code)}"
    b = build2(assist); code2 = b.assemble()
    assert ORG2 + len(code2) <= LIMIT2, f"restore too big: {len(code2)}"
    L = dict(a.labels()); L.update(b.labels())
    return L, code, code2


def jal(t):
    return struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))


def patches(tail=None, assist=False):
    L, code, code2 = assemble(tail, assist)
    return [(ORG, code), (ORG2, code2), (H1_AT, jal(L["pre"])), (H2_AT, struct.pack("<I", L["restore"]))]


def check_orig(read32):
    for a, w in ORIG.items():
        assert read32(a) == w, f"unexpected code at {a:08x}: {read32(a):08x}"


def apply_ram(emu):
    """Any time before the next battle-scene init (H1 runs once per battle)."""
    pp = patches()
    for at, orig, new in ((H1_AT, H1_ORIG, pp[2][1]), (H2_AT, H2_ORIG, pp[3][1])):  # H2 is a data word
        w = emu.u32(at)
        assert w in (orig, struct.unpack("<I", new)[0]), f"unexpected code at {at:08x}: {w:08x}"
    for addr, data in pp:
        emu.poke(addr, data)


def apply_exe(exe: bytearray):
    rd = lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0]
    check_orig(rd)
    for addr, data in patches():
        o = addr - EXE_BASE + EXE_HDR
        exe[o:o + len(data)] = data
    return exe


if __name__ == "__main__":
    exe = open(os.path.join(ROOT, "games", "mvc", "disc", "SLUS_010.59"), "rb").read()
    check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    L, code, code2 = assemble()
    print("code", len(code), "+", len(code2), "bytes, labels", {k: hex(v) for k, v in L.items()})
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data.hex()}")

