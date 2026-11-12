"""Arcade-style BGM for the tag hack - X-Men vs. Street Fighter (SLUS-00627).

How battle music works in the port (see work/FACTS.md "Music")
  * BGM is XA streamed by the driver at 0x8004e490(cmd, track): track -> (file index, XA channel)
    through the byte pairs at 0x80050638 + 2*track, files in the table at 0x80050854 (24-byte
    records), stream length at 0x80050690 + 4*track; state: 0x80053dc2 playing, 0x80053dc4 track.
  * Themes belong to CHARACTERS: 0x80050378[char] = track.  Round start (phase 2, 0x80081fb0)
    calls 0x8004d844: theme of P1's active character, or of P2's when P1 is human (both human:
    P1's unless bit 0 of 0x80042773 is clear); 0x14 for the boss.
  * A knocked-out character whose partner still has life (hit handler 0x80071be4 and the second
    KO path 0x80072a04): if the BGM option 0x80042781 is on -> 0x8004d69c(0x16) = fade the stream
    out over 60 frames, and then ONLY IN ARCADE MODE (0x8004278c == 0)
        0x8004d950(partner's character): task 0x8004dda8(0x8004d6f0, 60, theme) = after 60 frames
        stop the stream and play the incoming character's theme.
    In the PS1 mode the fade is never followed by anything: silence until the next round start.
  * Voluntary tags do not touch the music (no call in the tag path) - same as the arcade game.

Patch: the two `bnez v0` on the mode flag become nops, so the native theme switch always runs.
  0x80071c18   4 bytes   hit-handler KO
  0x80072a44   4 bytes   second KO path
Nothing is loaded into RAM: the new theme is another XA stream.
"""
import os, struct, sys

EXE_BASE, EXE_HDR = 0x80010000, 0x800
ORIG = {0x80071c18: 0x14400027, 0x80072a44: 0x14400004}


def patches():
    return [(a, struct.pack("<I", 0)) for a in ORIG]


def check_orig(read32):
    for a, w in ORIG.items():
        assert read32(a) == w, f"unexpected code at {a:08x}: {read32(a):08x}"


def apply_ram(emu):
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "disc", "files", "SLUS_006.27"), "rb").read()
    check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data.hex()}")
