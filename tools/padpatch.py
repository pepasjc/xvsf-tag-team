"""Default button layout: modern fighting-game shoulders.

The default key config is one table of eight u16 action masks at 0x8003d8f8,
in pad-bit order L2, R2, L1, R1, triangle, circle, cross, square.  It is
copied to the live per-player configs (0x80041df0 P1, 0x80041e90 P2).
Action masks: LP 0x10, MP 0x20, HP 0x40, LK 0x100, MK 0x200, HK 0x400,
3P 0x70, 3K 0x700.

  stock: L2 = 3P, R2 = 3K, L1 = HP, R1 = HK
  new:   L2 = 3K, R2 = HK, L1 = 3P, R1 = HP      (face buttons unchanged)

A key config already saved on a memory card still overrides the default.
"""
import struct

TABLE = 0x8003d8f8
STOCK = (0x70, 0x700, 0x40, 0x400, 0x20, 0x200, 0x100, 0x10)
NEW = (0x700, 0x400, 0x70, 0x40, 0x20, 0x200, 0x100, 0x10)


def patches():
    return [(TABLE, struct.pack("<8H", *NEW))]


def apply_ram(emu):
    assert emu.ram(TABLE, 16) in (struct.pack("<8H", *STOCK), struct.pack("<8H", *NEW))
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data.hex()}")
