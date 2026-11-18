"""Default buttons - MSHvSF (SLUS-00793).  Counterpart of tools/padpatch.py (XvSF).

Nothing to patch: the stock default key config of MSHvSF is already the layout the XvSF hack sets
(HP = R1, HK = R2, 3P = L1, 3K = L2, so the native tag HP + HK = R1 + R2).  Table of eight u16 action
masks at 0x8002477c, pad-bit order L2, R2, L1, R1, triangle, circle, cross, square
(LP 0x10, MP 0x20, HP 0x40, LK 0x100, MK 0x200, HK 0x400, 3P 0x70, 3K 0x700); verified in a Cross
Over fight (work/gameplay/t_btn.py: R1 -> 0x40, R2 -> 0x400, L1 -> 0x70, L2 -> 0x700).
This module only checks that table, so a build notices if it ever changes.
"""
import os, struct

TABLE = 0x8002477c
STOCK = (0x700, 0x400, 0x70, 0x40, 0x20, 0x200, 0x100, 0x10)
EXE_BASE, EXE_HDR = 0x80010000, 0x800


def patches():
    return []


def check_orig(read):
    assert read(TABLE, 16) == struct.pack("<8H", *STOCK), "unexpected default key config"


def apply_ram(emu):
    check_orig(emu.ram)


if __name__ == "__main__":
    exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "disc", "SLUS_007.93"), "rb").read()
    check_orig(lambda a, n: exe[a - EXE_BASE + EXE_HDR:a - EXE_BASE + EXE_HDR + n])
    print("default key config is already HP=R1 HK=R2 3P=L1 3K=L2: nothing to patch")
