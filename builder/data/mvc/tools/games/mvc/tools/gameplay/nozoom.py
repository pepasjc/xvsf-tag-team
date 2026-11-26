"""No camera zoom (user decision for the tag build) - Marvel vs. Capcom (SLUS-01059).

0x80023438(obj, type) is the camera zoom request; it has exactly two callers in the EXE and none in any disc file
(checked with tools/tagload/refscan.blobs):
  0x80035fe0  `jal 0x80023438` (a1 = 1)  every normal throw (zoom study games/mvc/work/zoom)
  0x800512c0  `jal 0x80023438` (a1 = 0)  hit reaction: the victim still has life (+0x138 > 0) and the attacker's move
              data (+0xd8 -> +0xa4 -> byte 0x16) has bit 0x40 = the "zoom on hit" property of strong hits
Both calls -> nop (their delay slots only set a1).  Same routine, same camera zoom: both removed.
"""
import struct
SITES = {0x80035fe0: (0x0C008D0E, 0x00000000), 0x800512c0: (0x0C008D0E, 0x00000000)}


def patches():
    return [(a, struct.pack("<I", n)) for a, (o, n) in SITES.items()]


def check_orig(read32):
    for a, (o, n) in SITES.items():
        assert read32(a) == o, f"unexpected code at {a:08x}: {read32(a):08x}"
