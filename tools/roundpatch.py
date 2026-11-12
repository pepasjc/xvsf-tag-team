"""Single-round matches for the tag hack - X-Men vs. Street Fighter (SLUS-00627).

How the game decides a round (all of it native, see work/FACTS.md "Rounds"):
  match struct 0x80042348: +0 phase (8 = fight), +1 round index, +2 / +3 rounds won by P1 / P2,
  +4 winner of the round (0, 1, -1 = draw), +8 timer seconds, +0xd time-over flag,
  +0x54 (0x8004239c) rounds needed to win the match.
  Phase 8 (0x80082270) already uses TEAM life: a = P1 main +0x224 + P1 partner +0x224, b likewise
  for P2; a side loses the round when its sum is 0, and at time over the larger sum wins (equal
  = draw).  A knocked-out character is replaced while its partner has life (hit handler
  0x80071b60: +0xea = 0x18).  So with both characters alive a "round" is already a whole arcade
  match - the port only repeats it: match init 0x80081c6c stores the rounds needed,
      0x8004278c == 0 (arcade mode flag) -> 1,  mode 0x8004218c == 4 -> 1,  else options + 1.

Patch
  * 0x80081cf8: `lui v0,0x8004 / lbu v0,0x21a6(v0)` (options "rounds") -> `jal stub / nop`.
    stub: v0 = options value when either main character is the boss (0x10, stock fight: the
    partner is the reduced set there), else 0.  The following `addiu v0,v0,1` makes it 1, so the
    options setting can no longer bring rounds back.
  * 0x800828e8: `bnez v0` (mode flag) -> nop.  The match-result code 0x800828b4 has two rules:
    the best-of-N one (0x80082928) and the arcade one (0x800828f0, taken natively when the mode
    flag is 0 or a boss is fighting): result +5 = 1 / 2 for the side that won the round and -2
    (draw game, both sides lose) when the round was a draw.  Now always the arcade rule.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # tools/mipsasm.py
from mipsasm import Asm, REG

ORG, LIMIT = 0x800104c8, 0x80010508          # 64 bytes, free part of the old tag-hook range
EXE_BASE, EXE_HDR = 0x80010000, 0x800
NEED_AT = 0x80081cf8
RESULT_AT = 0x800828e8
BANNER_AT = 0x80034d3c          # round-call object: `beqz v0(mode flag),0x80034d98` -> `b` (arcade call, no "ROUND n")
ORIG = {0x80081cf8: 0x3C028004, 0x80081cfc: 0x904221A6, 0x80081d04: 0x24420001, 0x800828e8: 0x1440000F, 0x80034d3c: 0x10400016}


def build():
    a = Asm(ORG)
    a.label("stub")
    a.lui("$t0", 0x8004)
    a.lh("$t1", 0x23b2, "$t0")                    # P1 main character * 2
    a.lh("$t2", 0x23b6, "$t0")                    # P2 main character * 2
    a.lbu("$v0", 0x21a6, "$t0")                   # options: rounds - 1
    a.xori("$t1", "$t1", 0x10)
    a.beq("$t1", "$zero", "ret")                  # boss fight: stock
    a.xori("$t2", "$t2", 0x10)
    a.beq("$t2", "$zero", "ret")
    a.nop()
    a.addu("$v0", "$zero", "$zero")               # tag team: one round
    a.label("ret")
    a.jr("$ra")
    a.nop()
    return a


def _w(*ws):
    return struct.pack(f"<{len(ws)}I", *ws)


def patches():
    a = build(); code = a.assemble()
    assert ORG + len(code) <= LIMIT, f"stub too big: {len(code)}"
    stub = a.labels()["stub"]
    return [
        (ORG, code),
        (NEED_AT, _w(0x0C000000 | ((stub >> 2) & 0x03FFFFFF), 0)),
        (RESULT_AT, _w(0)),
        (BANNER_AT, _w(0x10000016)),
    ]


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
        print(f"{addr:08x} {len(data):4d} {data[:16].hex()}")
