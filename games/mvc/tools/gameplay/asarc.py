"""ARCADE assist bits for the tag loader (assist bugs lead, 2026-11-21; mktag.py `--asarc`, needs --assistsel --fs05).

Bug (user, rc4.6): ARCADE assists dead from stage 2 on.  Root cause: the human's assist bit (and the CPU's) is set only by
assistsel.py's `vsas` (VS-screen portrait init, SEL01).  Pressing START after a win skips the win quote, stage screen
and VS screen: the EXE path 0x80046d3c sets up the next battle (0x80047418 CPU assist id, 0x800472b4 CPU team) and the
loader runs with the bits the post-battle restore cleared (0) -> as_on 0, no assists, no HUD (human on P2: only the
stale CPU bit).  Probe: work/asbug/bittrace.py (CROSS: scene 12 -> 4 -> bits 3; START: scene 12 -> 8, bits 0).

Fix: the loader takes its bits from FN (stageanim chunk C 0x8003c310-0x8003c340, unused with --fs05):
v0 = ASSIST_BITS & 3, or 3 in ARCADE (mode 0) with one human (0x8007bdc9 = 1 / 2) = exactly what vsas would have set;
tagload.c then drops the boss side (Onslaught 0x11 on P1 or P2).
"""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from mipsasm import Asm

FN, FN_END = 0x8003c310, 0x8003c340
MODE, HUMANS, BITS, OFF = 0x8007b740, 0x8007bdc9, 0x8007b744, 0x8001175f   # OFF = optrows ASSIST
TAIL, TAIL_END = 0x8002f7a0, 0x8002f7b0       # stageanim chunk D after ashud.CNT (0x8002f780-0x8002f7a0)


def lo(a):
    return a & 0xFFFF


def build():
    """FN (12 instr, chunk C) + TAIL (4 instr, end of chunk D after ashud's CNT): v0 = (bits | -1 in ARCADE (mode 0)
    with one human (0x8007bdc9 1 / 2)) & (0 when EX OPTIONS ASSIST is OFF (byte 0x8001175f == 0; without --asopt
    it is a zeroed reserved byte = ON)"""
    a = Asm(FN)
    a.lui("$t0", 0x8008)
    a.lbu("$v0", lo(BITS), "$t0")
    a.lb("$t1", lo(MODE), "$t0")
    a.lbu("$t2", lo(HUMANS), "$t0")
    a.lui("$t3", 0x8001)
    a.lbu("$t3", lo(OFF), "$t3")                  # 0 ON / 1 OFF
    a.addiu("$t2", "$t2", -1)
    a.sltiu("$t2", "$t2", 2)                      # 1 = one human
    a.sltiu("$t1", "$t1", 1)                      # 1 = ARCADE
    a.and_("$t2", "$t2", "$t1")
    a.j(TAIL)
    a.subu("$t2", "$zero", "$t2")                 # -1 = ARCADE with one human
    c = bytes(a.assemble())
    assert FN + len(c) <= FN_END, len(c)
    t = Asm(TAIL)
    t.or_("$v0", "$v0", "$t2")
    t.addiu("$t3", "$t3", -1)                     # mask: -1 ON, 0 OFF (OFF: no assist even with a stale bit:
    t.jr("$ra")                                   # the skip path 0x80046d3c leaves the CPU's bit)
    t.and_("$v0", "$v0", "$t3")
    d = bytes(t.assemble())
    assert TAIL + len(d) <= TAIL_END, len(d)
    return c, d


def patches():
    c, d = build()
    return [(FN, c), (TAIL, d)]


if __name__ == "__main__":
    for a_, d_ in patches(): print(hex(a_), d_.hex(), len(d_))
