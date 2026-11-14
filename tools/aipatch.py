"""CPU tagging for the tag hack - X-Men vs. Street Fighter (SLUS-00627): the game's own arcade path.

How the CPU tags (arcade program and port alike)
  The CPU "brain" 0x80087858 (script interpreter; arcade twin in the 68000 program) has script
  commands that order a team move instead of pressing buttons: it sets +0x27f = -1 ("command
  pending", cleared at the start of every brain frame) and the team-move number in +0xe2:
      0x8008ac54  +0xe2 = 0x14   TAG OUT              (after the state-permission test 0x8008bbcc(obj,3))
      0x8008ac74  +0xe2 = 0x80   team super (variable combination)
      0x8008b510  +0xe2 = 0x7e   variable counter
  The per-character command parser (0x800d122c-style, in the character code) then calls the
  shared input routines; for a CPU object (+3 == 0) their pattern matcher 0x8007d100 just
  compares +0xe2 with the number in the pattern table and requires +0x27f != 0:
      0x8007cecc  team super   (table 0x80094c94, 0x80)
      0x8007cc4c  counter      (table 0x80094c64/74, 0x7e)
      0x8007cd94  tag          (table 0x80094c84, 0x14) - arcade branch 0x8007cddc: not in the air
                               / leaving (+0xb1 != 4, 6), partner life != 0, phase < 10, lockout
                               +0x262 == 0, veto 0x8006f84c == 0 -> +0xe2 = 0x14, move 0x2a.
  The brain and its scripts are not gated by the PS1 mode flag 0x8004278c.  The only thing the
  port changed is the head of the tag routine: in PS1 mode (flag = 1) a human returns at once and
  a CPU object has its tag command REWRITTEN into a team super (0x8007cdb8: +0xe2 0x14 -> 0x80,
  then 0x8007cecc).  That rewrite is also the old freeze: once a CPU object really is in the
  tag-out move (move 0x2a, +0xe2 = 0x14 - e.g. started by a pad press), the next parser frame
  turned its +0xe2 into 0x80 under the running move script.

Patch (replaces the earlier invented heuristic: nothing at 0x80076a0c / 0x80034034 any more)
  * 0x8007cdb8 `lbu v1,0xe2(s0) / ori v0,zero,0x14` -> `j gate / nop`.
    gate: a CPU object takes the ARCADE branch 0x8007cddc when
            - it is not the attract demo (0x80042770 != 0; the demo stays as shipped),
            - it is not the boss (+0x54 != 0x10) and its partner is not the boss,
            - its partner has the full set (bit of +0x232 clear in 0x800421bc, and +0x74
              "assist only" clear on both objects of the side);
          otherwise the two displaced instructions run and the stock PS1 code continues
          (boss fight / reduced partner: unchanged behaviour).
    The arcade branch itself refuses a partner with 0 life (knocked out).
  * 0x8007ce9c `jal 0x8003252c` (start of the tag-out move in the arcade branch, only reachable
    through the gate) -> `jal lock`: +0x262 = the same lockout tools/tagpatch.py gives a human
    tag, then the move starts.
"""
import hashlib, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # tools/mipsasm.py
from mipsasm import Asm, REG

ORG, LIMIT = 0x80010ff4, 0x800110a0          # 172 bytes, break-tested dead code (old aipatch part 1)
EXE_BASE, EXE_HDR = 0x80010000, 0x800
GATE_AT = 0x8007cdb8                         # PS1-mode CPU path of the tag input routine 0x8007cd94
GATE_ORIG = "757e75947ca3f9df671b37a8260565c9fddb4f05"   # SHA-1 of the 2 stock words (lbu v1,0xe2(s0) / ori v0,zero,0x14)
STOCK_CONT = 0x8007cdc0                      # bne v1,v0,... (stock: tag command -> team super)
ARCADE_BRANCH = 0x8007cddc
MOVE_AT, MOVE_ORIG = 0x8007ce9c, 0x0C00C94B  # jal 0x8003252c (delay slot sh zero,8(a0))
SET_MOVE = 0x8003252c
XMASK = 0x800421bc
BOSS = 0x10
TAG_LOCKOUT = 0x3c + 17                      # as tools/tagpatch.py (arcade: 60 frames after the hand-over)
# places the old heuristic hooked; the builder must leave them original
OLD_HOOKS = {0x80076a0c: 0x0C021E16, 0x80034034: 0x0C00C782}


class A(Asm):
    def srlv(self, rd, rt, rs):
        self._i(lambda pc, L: 0x06 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)


def build():
    a = A(ORG)
    a.label("gate")                               # s0 = CPU main object (+3 == 0), PS1 mode
    a.lui("$t7", 0x8004)
    a.lb("$t0", 0x2770, "$t7")                    # 0 = attract demo
    a.lb("$t1", 0x54, "$s0")                      # own character * 2
    a.beq("$t0", "$zero", "stock")
    a.lw("$t3", 0x234, "$s0")                     # partner object
    a.xori("$t1", "$t1", BOSS)
    a.beq("$t1", "$zero", "stock")                # the boss never tags
    a.lh("$t2", 0x232, "$s0")                     # partner character * 2
    a.lb("$t4", 0x74, "$t3")                      # partner object: assist-only (reduced set)
    a.lb("$t6", 0x74, "$s0")
    a.xori("$t1", "$t2", BOSS)
    a.beq("$t1", "$zero", "stock")                # the boss's dummy partner never comes in
    a.lw("$t5", XMASK & 0xFFFF, "$t7")            # reduced-set mask
    a.or_("$t4", "$t4", "$t6")
    a.bne("$t4", "$zero", "stock")
    a.srl("$t2", "$t2", 1)
    a.srlv("$t5", "$t5", "$t2")
    a.andi("$t5", "$t5", 1)
    a.bne("$t5", "$zero", "stock")                # partner only has the reduced set
    a.nop()
    a.j(ARCADE_BRANCH)
    a.nop()
    a.label("stock")
    a.lbu("$v1", 0xe2, "$s0")                     # the two displaced instructions
    a.j(STOCK_CONT)
    a.ori("$v0", "$zero", 0x14)
    a.label("lock")                               # a0 = object, a1 = 0x2a: the tag-out move starts
    a.ori("$t0", "$zero", TAG_LOCKOUT)
    a.j(SET_MOVE)
    a.sb("$t0", 0x262, "$a0")
    return a


def assemble():
    a = build(); code = a.assemble()
    assert ORG + len(code) <= LIMIT, f"too big: {len(code)}"
    return a, code


def _w(*ws):
    return struct.pack(f"<{len(ws)}I", *ws)


def patches():
    a, code = assemble(); L = a.labels()
    return [
        (ORG, code),
        (GATE_AT, _w(0x08000000 | ((L["gate"] >> 2) & 0x03FFFFFF), 0)),
        (MOVE_AT, _w(0x0C000000 | ((L["lock"] >> 2) & 0x03FFFFFF))),
    ]


def restore_old_hooks():
    """[(addr, bytes)] that put the two hook sites of the earlier heuristic back to the original code
    (only needed when poking a disc that was built with the old aipatch)."""
    return [(a, _w(w)) for a, w in OLD_HOOKS.items()]


def apply_ram(emu):
    """Cold boot, before the first fight (I-cache)."""
    g = emu.ram(GATE_AT, 8)
    assert hashlib.sha1(g).hexdigest() == GATE_ORIG or g == patches()[1][1], "unexpected code at the gate"
    for addr, data in restore_old_hooks() + patches():
        emu.poke(addr, data)


if __name__ == "__main__":
    exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "disc", "files", "SLUS_006.27"), "rb").read()
    rd = lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0]
    assert hashlib.sha1(struct.pack("<2I", rd(GATE_AT), rd(GATE_AT + 4))).hexdigest() == GATE_ORIG and rd(MOVE_AT) == MOVE_ORIG
    assert all(rd(a) == w for a, w in OLD_HOOKS.items())
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data[:16].hex()}")
