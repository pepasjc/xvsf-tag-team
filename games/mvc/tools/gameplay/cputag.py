"""--cputag (2026-11-24, user report: in ARCADE / VERSUS CPU the CPU almost never tags out): CPU tags in tag battles.

Stock PS1 (work/cputag/NOTES.md): the tag routine A 0x80055fa8 (HP+HK, called from every character's neutral states) has a
CPU branch that (1) asks the AI command matcher 0x800566d0 for command 0x76 - the AI script's tag action (0x8004086c) is
almost never run (0-1 times per fight) - and (2) then returns 0 anyway (0x80056080 `beqz v0 -> 0x8005600c` = exit for the
CPU).  So the CPU never tags (measured: 0 tags in 3 x 6000-9000 frame arcade fights).  The arcade (FBNeo mvscu, same
scripted attacker) tags every few hundred frames at any life.
Patch (EXE words, same on 2 MB and 8 MB discs):
  0x80056048..0x80056058 (the CPU matcher call) -> per call (each frame the CPU point is in a neutral state and the stock
      checks pass: tag battle, not airborne, partner alive, own assist not out, phase < 10, +0x28a clear):
      jal 0x8003bc88 (game RNG) ; lh t0,0x294(s0) (life) ; ori t0,t0,0xf3f ; and v0,v0,t0 ; bnez v0 -> no tag
      = 1/2048 at life >= 64 (of 144), 1/1024 below; measured 1-3 tags per 6000 frames (arcade 1-3), several at low life
  0x80056080 `beqz v0, exit` -> `beqz v0, 0x80056098`: the CPU goes on to the stock veto 0x80034240 and move 0x40 (the
      human path after its button check).
Human sides, VERSUS flag 1 battles (boss fight, stock rules, attract) and routine B (0x80056330) are unchanged."""
import struct
WORDS = {0x80056048: (0x3c058007, 0x0c00ef22),
         0x8005604c: (0x24a523b0, 0x86080294),
         0x80056050: (0x0c0159b4, 0x35080f3f),
         0x80056054: (0x26060210, 0x00481024),
         0x80056058: (0x1040001b, 0x1440001b),
         0x80056080: (0x1040ffe2, 0x10400005)}


def exe_patches(exe_read):
    out = []
    for a, (o, n) in sorted(WORDS.items()):
        assert struct.unpack("<I", exe_read(a, 4))[0] == o, "--cputag: %08x not stock" % a
        out.append((a, struct.pack("<I", n)))
    return out
