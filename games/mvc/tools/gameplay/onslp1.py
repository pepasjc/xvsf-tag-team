"""ARCADE played on the P2 side: the CPU boss Onslaught on P1 (assist bugs lead, 2026-11-22; mktag.py `--onslp1`).

Bug (rc3 .. rc4.11, Beetle work/asbug/asid.py --p2, coldtest.py arcade --p2side): the run never reached / finished the
Onslaught fight.  Two causes:
  1. tagload.c accepted Onslaught (0x11) only as the P2 main (slot 1): with the human on P2 the boss is the P1 main ->
     tl_dbg 0xfc -> stock loading under the tag build -> NOW LOADING hang (main loop counter frozen).
  2. With 1 fixed (tagload.c ONSLP1: slot 0 accepted, TOP_ONSL reserved for either side) the fight ran, then crashed
     mid-battle (EPC 0x8008a8d4, prim-list walker 0x8008a774 called from the stage-9 overlay 0x800a1954 with a list
     node 0x80e20006): the stock stage-9 setup 0x8002b700 takes Onslaught's stage buffers from the side's PARTNER slot
     (stock char slot table 0x8006a6e4: [P1 0x800c5000, P2 0x80161d00, P1 partner 0x8014e500, P2 partner 0x801eb200])
     + 0xc000 / + 0xf000 (0x800a0bd0 / 0x800a0c04).  For the P2 boss that is 0x801f7200.. = TOP_ONSL (reserved by
     the loader); for the P1 boss it was 0x8015a500.. = the middle of the tag loader's character region -> both wrote
     the same RAM (watch: work/asbug/listwatch.py, first bad node 0x8015cd6c).
Fix 2: 0x8002b730 `lw s0,-0x5914(v0)` (table[2], P1 partner slot) -> `lw s0,-0x5910(v0)` (table[3]).  That word runs
ONLY when the P1 main is Onslaught (0x8002b70c / 0x8002b724), so the P1 boss uses the same reserved area as the P2 boss.
"""
import struct
SITE, STOCK, NEW = 0x8002b730, 0x8C50A6EC, 0x8C50A6F0


def check(read32):
    assert read32(SITE) == STOCK, f"onslp1: {SITE:08x} not stock ({read32(SITE):08x})"


def patches():
    return [(SITE, struct.pack("<I", NEW))]
