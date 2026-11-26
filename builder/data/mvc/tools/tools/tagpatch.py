"""Tag-switch patch for X-Men vs. Street Fighter (SLUS-00627).

The whole arcade tag system survived the port; the PS1 mode flag 0x8004278c (=1) and the
partner's missing life bar keep it off.  The arcade input routine 0x8007cd94 (HP+HK ->
0x8006f84c check -> +0xe2 = 0x14, move 0x2a) returns early for a human player in that mode.

The hook (replaces `jalr v0` at 0x80076dd0, the sub-state dispatch of the normal player
state) does what that routine does: on HP+HK in a neutral ground state it starts team move
0x2a with +0xe2 = 0x14 = TAG OUT.  The character code plays the hand-over pose and raises
request 4 (0x8006e3f0): swap, partner comes in with the jump-in kick, the old character
jumps off.  (The previous version raised request 6 = variable COUNTER, whose per-character
entry 0x800422b8[char] is the assist attack script - no body on screen for a full set.)

It also clears +0x74 ("assist-only character") on both objects: the swap exchanges that
byte and the per-character command parser returns at once while it is set, so the
tagged-in character had no specials or supers.

Conditions: HP+HK just pressed, sub-state 0, on the ground, no request pending, partner has
the full set (mask 0x800421bc) and life > 0 (0 = knocked out; full partners get 0x90 at round
init from round_life_stub).  There is NO tag cooldown: measured on tag14 and on this version,
mashing HP+HK re-tags every 78-90 frames, i.e. as soon as the incoming character is neutral.
(+0x262 is tested, but the voluntary tag path never sets it - only 0x8006e59c does, 0x3c.)

A knocked-out partner (life 0, +0x74 == 0) can no longer be called: tag (hook), team super
(variable combination 0x8007cecc: in-place patch) and variable counter / assist (0x8007cc4c:
counter_stub).  Reduced partners (boss fight: mask != 0, +0x74 == 1) keep stock behaviour.
All three are reached by human and CPU through the same routines.

Code: hook + counter stub at 0x80016290.. (dead range 0x80016290-0x800163b8), round_life_stub
at 0x80010420 (32 bytes, below the XVM1 set-up code at 0x80010440).
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # tools/mipsasm.py
from mipsasm import Asm, REG

ORG = 0x80016290            # verified-dead range 0x80016290-0x800163b8 (296 bytes)
LIMIT = 0x800163b8
EXE_BASE, EXE_HDR = 0x80010000, 0x800

XMASK = 0x800421bc          # bit n set = char n is loaded as a reduced partner set
HP_HK = 0x440
FULL_LIFE = 0x90
TAG_LOCKOUT = 0x3c + 17     # arcade's 60 frames after the hand-over; the swap comes ~17 frames after the press
TAG_BLOCKED = 0x8006f84c    # (obj) -> nonzero while the engine forbids a tag (guard stun, opponent in a throw, ...)
SET_MOVE = 0x8003252c       # (obj, move) start a character move script
KO_SWAP_TEST = 0x80071b18   # hit handler: "swapped characters cannot be KO'd" test
MOVE_TEAM, TEAM_TAG_OUT = 0x2a, 0x14    # move 0x2a = team moves, +0xe2 selects which (0x14 = arcade tag out)


def v13(argv=None):
    """1.3 gameplay fixes: on unless the image must reproduce an older release (--nospeed = 1.0.1, --nosound = 1.1)."""
    argv = sys.argv if argv is None else argv
    return "--nospeed" not in argv and "--nosound" not in argv


class A(Asm):               # the two instructions mipsasm lacks
    def srlv(self, rd, rt, rs):
        self._i(lambda pc, L: 0x06 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def xor_(self, rd, rs, rt):
        self._i(lambda pc, L: 0x26 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)


def build():
    """Hook replacing `jalr v0` at 0x80076dd0 (the sub-state dispatch of the
    normal player state): inputs are fresh here and the state code has not
    consumed them yet.  v0 = handler, s0 = player object, a0 set in the delay
    slot.  On a tag we start the arcade tag-out move exactly like the unused
    arcade input routine 0x8007cddc..0x8007cea0 does, then run the handler."""
    a = A(ORG)
    a.label("pre")
    a.lb("$t0", 0x231, "$s0")                         # partner object?
    a.lb("$t1", 0, "$s0")                             # active?
    a.bne("$t0", "$zero", "pre_out")
    a.lw("$t3", 0x234, "$s0")                         # partner object
    a.beq("$t1", "$zero", "pre_out")
    a.nop()
    # No cooldown of our own any more: +0x22e on the benched object is the arcade
    # regeneration timer (now live).  The engine's post-tag timer +0x262 is tested
    # below like the arcade input routine does, but a voluntary tag never sets it,
    # so a re-tag is possible as soon as the incoming character is neutral.
    a.lh("$t0", 6, "$s0")                             # sub state (0 = neutral)
    a.lb("$t1", 0x25e, "$s0")                         # request already pending?
    a.bne("$t0", "$zero", "pre_out")
    a.lb("$t0", 0x262, "$s0")                         # engine's own post-tag timer
    a.nop()                                           # load delay: without this the OR saw the old t0 on real hardware
    a.or_("$t1", "$t1", "$t0")
    a.bne("$t1", "$zero", "pre_out")
    a.lb("$t0", 0xb1, "$s0")                          # 4 = in the air, 6 = leaving (arcade test)
    a.lhu("$t4", 0xdc, "$s0")                         # buttons: same test as 0x8007de90
    a.sltiu("$t0", "$t0", 4)
    a.beq("$t0", "$zero", "pre_out")
    a.lhu("$t5", 0xce, "$s0")
    a.lhu("$t0", 0xcc, "$s0")
    a.xor_("$t4", "$t4", "$t5")
    a.xor_("$t5", "$t5", "$t0")
    a.or_("$t5", "$t5", "$t4")
    if v13():
        # 1.3: the test below sees a CHANGE of both buttons, so RELEASING HP+HK after holding them also
        # tagged: hold the buttons through a team super / counter / tag-in (lockout over) and the release
        # sent the new point character straight back out (forum report "counter / team super don't
        # switch").  Only a press counts: AND with the newest sample (+0xcc) = both buttons down now.
        a.and_("$t5", "$t5", "$t0")
    a.andi("$t5", "$t5", HP_HK)
    a.xori("$t5", "$t5", HP_HK)
    a.bne("$t5", "$zero", "pre_out")
    a.lh("$t1", 0x232, "$s0")                         # partner char id * 2
    a.lui("$t5", XMASK >> 16)
    a.lw("$t5", XMASK & 0xFFFF, "$t5")                # reduced-set mask
    a.srl("$t1", "$t1", 1)
    a.srlv("$t5", "$t5", "$t1")
    a.andi("$t5", "$t5", 1)
    a.bne("$t5", "$zero", "pre_out")                  # partner only has the reduced set
    a.nop()
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x10, "$sp")
    a.jal(TAG_BLOCKED)
    a.sw("$v0", 0x14, "$sp")
    a.bne("$v0", "$zero", "pre_ret")
    a.lw("$t3", 0x234, "$s0")
    a.nop()                                           # load delay: t3 from the delay slot above
    # Partner life is now set at round init (see round_life stub), so 0 means
    # the partner was knocked out: no tag to a dead character.
    a.lh("$t0", 0x224, "$t3")
    a.nop()
    a.beq("$t0", "$zero", "pre_ret")
    a.ori("$t0", "$zero", TEAM_TAG_OUT)
    # +0x74 = "assist-only character" (1 on the partner object, exchanged by the
    # swap).  While it is set the per-character command parser returns at once
    # (0x800d1304 and friends): no specials, no supers.  Both are full characters.
    # (The +0x74 clears that used to be here are gone: the round-init stub
    # already gives full partners +0x74 = 0.)
    # Arcade lockout: the game's own hand-over code (0x8006e63c / 0x8006e6c0)
    # puts 0x3c = 60 frames in +0x262 when a character comes in; the arcade tag
    # input 0x8007ce24 and the team super 0x8007cf2c both refuse while it is
    # non-zero, and 0x80076d74 counts it down.  That hand-over code does not run
    # in the port's swap flow, so set it here: 60 frames from the swap, which
    # happens about 17 frames after the press.
    a.ori("$t1", "$zero", TAG_LOCKOUT)
    a.sb("$t1", 0x262, "$s0")
    a.sb("$t0", 0xe2, "$s0")                          # team move number: tag out
    a.sh("$zero", 6, "$s0")
    a.sh("$zero", 8, "$s0")
    a.addu("$a0", "$s0", "$zero")
    a.jal(SET_MOVE)
    a.ori("$a1", "$zero", MOVE_TEAM)
    a.label("pre_ret")
    a.lw("$ra", 0x10, "$sp")
    a.lw("$v0", 0x14, "$sp")
    a.addu("$a0", "$s0", "$zero")
    a.addiu("$sp", "$sp", 0x18)
    a.label("pre_out")
    a.jr("$v0")                                       # tail-call the handler
    a.nop()
    return a


def assemble():
    asm = build()
    code = asm.assemble()
    assert ORG + len(code) <= LIMIT, f"hook too big: {len(code)}"
    return asm, code


ROUND_LIFE_ORG = 0x80010420      # old hook area (libcd debug strings), free again
ROUND_LIFE_SITE = 0x8006b1ac     # round init 0x8006b0c0: `lui v0,0x8004; lb v0,0x278c(v0)` then
                                 # `nop; beqz v0,+3; nop; sh zero,0x224(s0); sh zero,0x22c(s0)`


def round_life_stub():
    """Round init gives every object 0x90 life and then zeroes the PARTNER's
    when the PS1 mode flag 0x8004278c is set.  Return instead "this partner
    only has the reduced set", so a full partner keeps its own life bar and a
    reduced one (boss fight) behaves as stock."""
    a = A(ROUND_LIFE_ORG)
    a.lb("$t0", 0x54, "$s0")                          # char id * 2
    a.lui("$v0", XMASK >> 16)
    a.lw("$v0", XMASK & 0xFFFF, "$v0")
    a.srl("$t0", "$t0", 1)
    a.srlv("$v0", "$v0", "$t0")
    a.andi("$v0", "$v0", 1)
    # +0x74 = "assist-only" (blocks the command parser: no specials/supers).
    # The stock partner has 1.  A full partner must have 0 from the start,
    # because the KO-replacement swap does not pass through the tag hook that
    # used to clear it - the replacement then had no special moves.
    a.jr("$ra")
    a.sb("$v0", 0x74, "$s0")
    code = a.assemble()
    assert ROUND_LIFE_ORG + len(code) <= 0x80010440, "round stub runs into the XVM1 set-up code"
    return code


COUNTER_SITE = 0x8007cc9c        # variable counter 0x8007cc4c, PS1-mode path: `lui v0,0x8004; lb v0,0x2387(v0)`
COUNTER_FAIL = 0x8007cd78        # its exit (returns v0)


def counter_stub(org, full=None):
    """The PS1-mode path of the variable counter never looks at the partner's
    life (the stock partner has none).  With a full partner, 0 life means it was
    knocked out: no counter.  A reduced partner (+0x74 = 1, boss fight) keeps
    stock behaviour.
    full (1.1, default: not --nospeed): a full partner with life also skips the PS1 "assist is out"
    bit 0x80042387 (set by the counter prep 0x8006d50c; cleared only by the stock swap-back that
    1.1's counter fix no longer takes), as the arcade does - it only tests the partner's life."""
    if full is None: full = "--nospeed" not in sys.argv
    a = A(org)
    a.lw("$t0", 0x234, "$s0")                         # partner object
    a.nop()
    a.lb("$t1", 0x74, "$t0")
    a.lh("$t0", 0x224, "$t0")
    a.bne("$t1", "$zero", "ok")
    a.nop()
    a.bne("$t0", "$zero", "full" if full else "ok")
    a.nop()
    a.j(COUNTER_FAIL)
    a.addu("$v0", "$zero", "$zero")
    if full:
        a.label("full")
        a.j(COUNTER_SITE + 8)                         # v0 = 0: "assist bit clear" for the code at 0x8007cca4..
        a.addu("$v0", "$zero", "$zero")
    a.label("ok")
    a.lui("$v0", 0x8004)                              # the two displaced instructions
    a.j(COUNTER_SITE + 8)
    a.lb("$v0", 0x2387, "$v0")
    return a.assemble()


def patches():
    asm, code = assemble()
    L = asm.labels()
    jal = lambda t: struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))
    jmp = lambda t: struct.pack("<I", 0x08000000 | ((t >> 2) & 0x03FFFFFF))
    stub_org = ORG + len(code)
    stub = counter_stub(stub_org)
    assert stub_org + len(stub) <= LIMIT, "counter stub does not fit after the hook"
    return [
        (ORG, code),
        (stub_org, stub),
        (COUNTER_SITE, jmp(stub_org) + bytes(4)),
        # Variable combination (team super) 0x8007cecc: the partner-life test at 0x8007cefc
        # is skipped in PS1 mode (`lb v0,0x239a(v0); beqz v0 -> skip`), so the team super
        # worked with a knocked-out partner.  Skip it only when a reduced partner is loaded
        # (mask 0x800421bc non-zero, i.e. the boss fight); with full partners always test.
        (0x8007ceec, struct.pack("<I", 0x8C4221BC)),      # lw   v0,0x21bc(v0)
        (0x8007cef4, struct.pack("<I", 0x14400007)),      # bnez v0,0x8007cf14   (was beqz)
        (ROUND_LIFE_ORG, round_life_stub()),
        (ROUND_LIFE_SITE, jal(ROUND_LIFE_ORG) + bytes(4)),
        # Life regeneration, 0x80075414: `lb v0,0x278c(v0)` chose PS1 mode (both ACTIVE
        # characters heal, 0x8007537c) over the arcade rule (only the BENCHED objects
        # heal, 0x80075494).  Test the reduced-set mask instead: all partners full ->
        # arcade rule; a reduced partner (boss fight) -> stock PS1 behaviour.
        (0x8007542c, struct.pack("<I", 0x8C4221BC)),      # lw v0,0x21bc(v0)
        # Same switch for the life bar's "regenerating" look (bar animation + sparkle at the tip,
        # 0x800804e0): in PS1 mode an ACTIVE character with recoverable life took that path,
        # although it no longer heals.  Arcade rule: only the benched character shows it.
        (0x80080584, struct.pack("<I", 0x8C4221BC)),      # lw v0,0x21bc(v0)  (was lb v0,0x278c(v0))
        # Tag-in: the swap (0x8006b340) clears the incoming character's recoverable life
        # (+0x22c = +0x224) only in arcade mode; the arcade always does.  Also the KO replacement.
        (0x8006b348, struct.pack("<I", 0)),               # was: bnez v0,0x8006b36c (PS1 mode: keep it)
        (0x80076dd0, jal(L["pre"])),                 # was: jalr v0 (delay slot move a0,s0 kept)
        # KO test in the hit handler: `lb v0,0x230(s0); bnez -> no KO` made a swapped-in
        # character with 0 life unkillable (it protects the stock variable-counter assist,
        # which arrives with 0 life).  Test the assist-only flag +0x74 instead: the stock
        # assist still has it, a character tagged in by the hook does not.
        (KO_SWAP_TEST, struct.pack("<I", 0x82020074)),   # lb v0,0x74(s0)   (was 0x82020230)
    ] + ([] if "--nospeed" in sys.argv else [
        # 1.1: after a variable combination (team super) the partner who jumped in stays on point, as on
        # the arcade (verified on FBNeo xmvsfu1d, work/teamsuper).  The end-of-team-move resolver
        # 0x8006e59c chose the PS1 branch (partner leaves) by the mode flag; test the reduced-set mask
        # instead (full partners -> arcade branch with the swap; boss fight -> stock).
        (0x8006e6f0, struct.pack("<I", 0x8C4221BC)),      # lw v0,0x21bc(v0)  (was lb v0,0x278c(v0))
        # 1.1: after a variable COUNTER the partner who came in stays on point, as on the arcade
        # (FBNeo: Ryu/Wolverine, Ryu counters -> Wolverine stays at x291; patched port: same).  The
        # counter move's effect object (handler 0x8008ded4) swapped the owner back in PS1 mode
        # (0x8008e07c: 0x8008d868, swap 0x8006b248, 0x8006ee34).  Same mask switch.
        (0x8008dfe8, struct.pack("<I", 0x8C4221BC)),      # lw v0,0x21bc(v0)  (was lb v0,0x278c(v0))
        # 1.1: ...and the counter character must keep its specials/supers.  The counter prep sets the side's
        # bit in 0x80042387 ("assist is out"); only the stock swap-back (the branch the line above skips)
        # clears it.  In PS1 mode the veto 0x8006f84c - called by the command parser, the tag hook and the
        # tag/counter routines - reports "blocked" while that bit is set, so after a counter the new point
        # character had no specials, supers or tag for the rest of the round.  The arcade (flag 0) never
        # tests the bit: same mask switch (full partners -> arcade).  The counter stub skips the bit too.
        (0x8006f850, struct.pack("<I", 0x8C4221BC)),      # lw v0,0x21bc(v0)  (was lb v0,0x278c(v0))
    ])


def apply_ram(emu):
    for addr, data in patches():
        emu.poke(addr, data)


def apply_exe(exe: bytearray):
    for addr, data in patches():
        o = addr - EXE_BASE + EXE_HDR
        exe[o:o + len(data)] = data
    return exe


if __name__ == "__main__":
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data[:16].hex()}")
