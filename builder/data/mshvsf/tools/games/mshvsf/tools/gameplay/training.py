"""TRAINING with real teams - Marvel Super Heroes vs. Street Fighter (USA, SLUS-00793).

Stock: the training dummy gets ONE pick.  The select screen's after-main-pick state (SELECT.BIN state 2 handler
0x80096d24) has a training branch at 0x80096e88: mode 0x800250ac == 2 and the struct is not the player's side
(0x800250ad) -> partner slot (0x800707ec / 0x800707f0) = the main, struct done (0x80097400).  The battle loader
then loads the dummy's "partner" as a cut-down clone of the dummy (assist only).

OPTION SHORT CUT ON (the EXE's text-list select 0x8004e8f8..) has its own copy: pick routine 0x8004ffd4 `bne v1, v0,
0x80050044` (mode != 2 -> normal path) falls into the same partner = main / done code (0x8004ffdc..0x80050040)
in training.

Patch: 0x80096e98 `bne v1, v0, 0x80097494` (not training -> return) becomes `b 0x80097494`: the dummy takes the
normal path - partner pick like the player's side, then done (the after-partner-pick state 0x80097028 already ends
the selection in training).  EXE 0x8004ffd4 -> `b 0x80050044`: the same for SHORT CUT.  The battle loader (tools/tagload/tagload.c, tools/ap8/ap8.c) loads both teams in full
in TRAINING too, and tools/gameplay/tagmode.py gives TRAINING the tag rules when every partner is full.

    patches()          [(addr, bytes)] for SLUS_007.93
    overlay_patches()  [(file, offset, bytes)] (SEL.ARC, SELECT.BIN)
    ram_overlay_patches()  [(addr, bytes)] while SELECT.BIN is resident
"""
import struct

OVLS = (("SEL.ARC", 0x800947d4), ("SELECT.BIN", 0x80094800))      # as tools/gameplay/cyber.py
AT, ORIG, NEW = 0x80096e98, 0x1462017E, 0x1000017E
EXE_AT, EXE_ORIG, EXE_NEW = 0x8004ffd4, 0x1462001B, 0x1000001B


def patches():
    return [(EXE_AT, struct.pack("<I", EXE_NEW))]


def check_orig(read32):
    assert read32(EXE_AT) == EXE_ORIG, "unexpected EXE word at %08x: %08x" % (EXE_AT, read32(EXE_AT))


def ram_overlay_patches():
    return [(AT, struct.pack("<I", NEW))]


def overlay_patches():
    return [(f, a - base, d) for f, base in OVLS for a, d in ram_overlay_patches()]


def check_overlay(read32):
    assert read32(AT) == ORIG, "unexpected SELECT.BIN word at %08x: %08x" % (AT, read32(AT))
