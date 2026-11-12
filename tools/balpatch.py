"""Arcade balance values for the tag hack - X-Men vs. Street Fighter (SLUS-00627).  See work/bal, work/arcade.

Compared against the arcade program (CPS2, USA 961004 decrypted set xmvsfu1d for the code, Euro
xmvsf / USA xmvsfu for the factory settings), statically and by running both games:

  same on both games (nothing to patch)
    * base life 0x90 per character; damage formula 0x80074930 == arcade 0x16492 step by step, with
      identical tables (damage level 1f 24 2a 2e, handicap 10 1c 1e 20.., random blocks, guard /
      counter factors 34 34 30 34); the port's damage level byte 0x8004397e is fixed at 1 = the
      arcade factory "DAMAGE LEVEL" (index 1).  Measured: 16 moves x 5 match-ups, PS1 / arcade
      damage = 0.98 (the arcade spreads +-1 point per hit, the port always rolls the same value).
    * recoverable (red) life per hit, benched regeneration (+1 per 51 game frames, first point
      about 300 game frames after the tag), throw and tag-in kick damage, chip damage.
  different
    * round timer: arcade factory "TIME COUNT SPEED" index 1 = 110 game frames per count (table
      78 6e 64 5a at 0xfb4e); the port uses 100 in PS1 mode (0x800837c4) and 120 in arcade mode.
      -> patched here to 110.
    * game speed: arcade factory setting is TURBO 2 (USA) or FREE SELECT (Europe / Japan); TURBO 2
      skips every 7th frame = the port's own "Turbo Speed" option value 2 (0x800421a7; 0x80042786
      = 7).  The port's default is 0 (normal), which makes every animation, stun and regeneration
      take 17 % more real time than the USA arcade default.  NOT patched (the place that writes
      the option defaults was not found); set Options -> Turbo Speed instead.
"""
import os, struct, sys

EXE_BASE, EXE_HDR = 0x80010000, 0x800
TIMER_AT, TIMER_ORIG = 0x800837c4, 0x34020064        # ori v0,zero,100 (delay slot, PS1-mode value)
TIMER_FRAMES = 110                                   # arcade factory setting


def patches():
    return [(TIMER_AT, struct.pack("<I", 0x34020000 | TIMER_FRAMES))]


def apply_ram(emu):
    """Before the first fight of a session (I-cache)."""
    w = emu.u32(TIMER_AT)
    assert w in (TIMER_ORIG, 0x34020000 | TIMER_FRAMES), f"unexpected code at the timer reload: {w:08x}"
    for addr, data in patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "disc", "files", "SLUS_006.27"), "rb").read()
    assert struct.unpack_from("<I", exe, TIMER_AT - EXE_BASE + EXE_HDR)[0] == TIMER_ORIG
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data.hex()}")
