"""Tag-team rules for VERSUS / ARCADE (and every other fight mode) - Marvel Super Heroes vs. Street Fighter
(USA, SLUS-00793).  The MSHvSF counterpart of XvSF's tagpatch + roundpatch + hudpatch + aipatch + bgmpatch.

Why one switch is enough (details: games/mshvsf/docs/GAMEPLAY.md)
  The port kept the whole arcade tag-team game and runs it in CROSS OVER mode.  Every place where the
  other modes differ reads ONE byte, 0x800250c7 (= 0x80025040 + 0x87, "partners are assist-only"),
  written when a main-menu mode is entered: 1 for BATTLE / VERSUS / TRAINING / HERO BATTLE
  (0x80028f44, 0x800290dc, 0x8002910c), 0 for CROSS OVER (0x80029168).  ~60 readers in the EXE and in
  the character code (PLxx_10/_20.A0).  With 0 the engine natively gives, and only needs full partners:
    tag on HP+HK (team move, partner jumps in; arcade lockouts)    each character its own life bar (HUD)
    KO -> partner comes in; KO'd partner cannot be tagged / VC    single round; match ends when both are down,
    only the BENCHED character recovers red life                    time over compares team life
    CPU tags with the arcade AI                                     XA music -> incoming character's theme after a KO
  XvSF needed five modules because its flag (0x8004278c) also stood for things the PS1 port had
  changed for good; here 0 is a fully working, shipped mode.

Patch (no per-frame cost: runs once per battle, after the battle loader and before match / round init)
  0x80051754 in the battle-scene init 0x800516c0: `jal 0x80064e9c` (2 instructions: sh 1,0x800702bc)
  -> `jal stub`.  stub = the original 2 instructions, then
      mode 0x800250ac not 0 (BATTLE = arcade), 1 (VERSUS) or 2 (TRAINING, since 1.0: both teams in full, see
                                                     training.py) -> untouched (CROSS OVER is 0 natively; HERO BATTLE
                                                     keeps its stock rules)
      0x80070a91 == 0 (no human: attract demo)     -> 1 (demo stays as shipped)
      otherwise                                    -> 0x800250c7 = (reduced-partner mask 0x800250c0 != 0)
  So a fight whose partners are all loaded in full (the tag loader, games/mshvsf/tools/tagload) plays
  by the arcade rules, and a fight with any cut-down partner (stock loader, or a fall-back) keeps the
  stock behaviour of its mode - the same key XvSF used (mask 0x800421bc).  The menu re-sets the flag
  on every mode entry, so nothing has to be restored.

Code: 0x8003d8e0.. (dead, break-tested range 0x8003d8e0-0x8003d9c0; see games/mshvsf/docs/CODESPACE.md).
"""
import os, struct, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mipsasm import Asm

EXE_BASE, EXE_HDR = 0x80010000, 0x800
ORG, LIMIT = 0x8003d8e0, 0x8003d9c0
HOOK_AT, HOOK_ORIG = 0x80051754, 0x0C0193A7          # jal 0x80064e9c (delay slot: sh zero,0x4408(v0))
FLAG, MODE, MASK, HUMANS = 0x800250c7, 0x800250ac, 0x800250c0, 0x80070a91

ORIG = {HOOK_AT: HOOK_ORIG, 0x80064e9c: 0x3C038007, 0x80064ea0: 0x24020001, 0x80064ea4: 0x03E00008, 0x80064ea8: 0xA46202BC}


def build(tail=None):
    """tail: address to jump to instead of returning (tools/speed/meter.py MCOPY; it returns for us)"""
    a = Asm(ORG)
    a.label("stub")
    a.lui("$v1", 0x8007)
    a.addiu("$v0", "$zero", 1)
    a.sh("$v0", 0x2bc, "$v1")                     # the replaced call 0x80064e9c: 0x800702bc = 1
    a.lbu("$t2", HUMANS & 0xFFFF, "$v1")          # human players (bit per side); 0 = attract demo
    a.lui("$t0", MASK >> 16)
    a.lb("$t1", MODE & 0xFFFF, "$t0")
    a.sltiu("$t3", "$t1", 3)
    a.beq("$t3", "$zero", "ret")                  # only BATTLE (arcade, 0), VERSUS (1) and TRAINING (2, 1.0: real teams,
    a.lw("$t4", MASK & 0xFFFF, "$t0")             #  tools/gameplay/training.py); CROSS OVER is native, HERO BATTLE stays stock.  mask: bit per char, set by the loader
    a.bne("$t2", "$zero", "set")
    a.sltu("$t4", "$zero", "$t4")                 # 1 = some partner is cut down -> stock rules
    a.addiu("$t4", "$zero", 1)                    # demo: stock rules
    a.label("set")
    a.sb("$t4", FLAG & 0xFFFF, "$t0")
    a.label("ret")
    if tail:
        a.j(tail)
    else:
        a.jr("$ra")
    a.nop()
    return a


def assemble(tail=None):
    a = build(tail); code = a.assemble()
    assert ORG + len(code) <= LIMIT, f"stub too big: {len(code)}"
    return a, code


def patches(tail=None):
    a, code = assemble(tail)
    return [(ORG, code), (HOOK_AT, struct.pack("<I", 0x0C000000 | ((a.labels()["stub"] >> 2) & 0x03FFFFFF)))]


def check_orig(read32):
    for a, w in ORIG.items():
        assert read32(a) == w, f"unexpected code at {a:08x}: {read32(a):08x}"


def apply_ram(emu):
    """Any time before the next battle-scene init (the hook runs once per battle)."""
    w = emu.u32(HOOK_AT)
    assert w in (HOOK_ORIG, struct.unpack("<I", patches()[1][1])[0]), f"unexpected code at {HOOK_AT:08x}: {w:08x}"
    for addr, data in patches():
        emu.poke(addr, data)


def apply_exe(exe: bytearray):
    rd = lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0]
    check_orig(rd)
    for addr, data in patches():
        o = addr - EXE_BASE + EXE_HDR
        exe[o:o + len(data)] = data
    return exe


if __name__ == "__main__":
    exe = open(os.path.join(ROOT, "games", "mshvsf", "disc", "SLUS_007.93"), "rb").read()
    check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data.hex()}")
