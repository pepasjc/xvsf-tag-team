"""ARCADE BALANCE (1.3 default; mktagdisc --noarcbal leaves it out; docs/BALANCE.md).

OPTION MODE line 12 "ARCADE BALANCE  ON  OFF", default OFF, kept on the memory card with the game's own options.
OFF = the 1.3 game (same instructions, same cycles).  ON = the arcade rules for the two differences the port gates with
its PS1-mode flag 0x8004278c (always 1 on the PS1):

  meter      0x80075144  meter add (obj, n): n <<= 1 when the flag is set  -> every gain doubled on the PS1
  cancel     0x8007d680  move-start check (from the command matcher 0x8007d100): with the flag set, a super may start
                         while the character is still in a special move or super (state 0x2a) once that move has hit
                         -> special -> super and super -> super chains (Gambit's three Royal Flushes in a row)

Each gate's `lui / lb 0x278c` reads our byte arcbal and its branch is inverted, so arcbal 0 runs the 1.3 path.

Where things live (every 1.3 configuration has the START skip module, so nothing depends on the achievements runtime
or its boot guard):
  * arcbal, bal_optdraw, bal_optinput: tools/skip/xvskip.c -DARCBAL, linked at skippatch.BASE_BAL (0x80007880;
    0x80007600-0x80007a00 is BIOS-free on a real PS1, kernel map in docs/ACHIEVEMENTS.md; the XvSF achievements span
    there ends at 0x80007880, tools/ach/xvach.py).  BSS: OFF at every boot until the options are loaded.
  * the gates: skippatch.code(arcbal=True) hooks (gate_patches below).
  * P/P4/OPDEMO.BIN, patched on the disc (apply):
      option screen   the 8 MB module's ARCADE FRAMES words (tools/ap8/ap8mod.c optpatch) pointing at our functions;
                      the 8 MB module recognises these words and makes a 14-line screen with ARCADE FRAMES as item 13
      options save    0x8009a168 copies the options into the card image at 0x800bb588; byte +9 is never written
                      (padding between +8 and the halfword at +0xa).  The redundant `lui at` of the stores make room:
                      the stores use s0 (= the image) and arcbal goes to +9.
      options load    0x8009a2a4, the reverse: +9 & 1 -> arcbal.  A save from the stock game or an older build has
                      0 there = OFF.
"""
import hashlib, struct
EXE_BASE, EXE_HDR = 0x80010000, 0x800
OVL_BASE, MENU_FILE = 0x80098000, "P/P4/OPDEMO.BIN"
_jal = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)

# (lui address, register, branch address, stock branch word, inverted branch word)
GATES = [(0x80075144, 2, 0x80075150, 0x10400002, 0x14400002),       # meter doubling: beqz v0 -> bnez v0
         (0x8007d680, 3, 0x8007d68c, 0x1060001d, 0x1460001d)]       # super cancel:   beqz v1 -> bnez v1
FLAG_LUI, FLAG_LB = 0x3C008004, 0x8000278C                         # lui rX,0x8004 ; lb rX,0x278c(rX)  (| rX fields)

# OPDEMO.BIN option screen (same words as ap8mod.c optpatch; stock words kept XOR SK there and here)
OPT_AT = [0x80098c1c, 0x80098c44, 0x80098c48, 0x80098c4c, 0x80098c50, 0x8009927c, 0x80099280, 0x800994a8, 0x8009908c]
SK = 0x5ec7a11d
OPT_OLD = [w ^ SK for w in (0x7285a11e, 0x6ac2a185, 0x78e1a115, 0x5ec1951d, 0x5ec1951e, 0x7685a111, 0x6ac5a116, 0x52c71325, 0x6ad6a1b5)]
# options save / load: 8 words each, stock words known by their SHA-1 (no game code in the sources)
SAVE_AT, SAVE_SHA = 0x8009a1f0, "e1a8f1c053740c05db46bdc9c28def6c87ae3495"
LOAD_AT, LOAD_SHA = 0x8009a2dc, "b6bf62474a143e76ca7438c27f5ea35985464c28"
SLOT = 9                                                            # spare byte of the options' card image


def _hilo(a): return ((a + 0x8000) >> 16) & 0xffff, a & 0xffff


def gate_patches(flag):
    out = []
    for at, r, br, old, new in GATES:
        hi, lo = _hilo(flag)
        out += [(at, struct.pack("<2I", 0x3C000000 | r << 16 | hi, 0x80000000 | r << 21 | r << 16 | lo)), (br, struct.pack("<I", new))]
    return out


def check_gates(exe_read):
    for at, r, br, old, new in GATES:
        assert struct.unpack("<2I", exe_read(at, 8)) == (FLAG_LUI | r << 16, FLAG_LB | r << 21 | r << 16), "arcbal: unexpected gate at %08x" % at
        assert struct.unpack("<I", exe_read(br, 4))[0] == old, "arcbal: unexpected branch at %08x" % br


def opt_words(bal):
    return [0x2c420004,                                             # items 5..8 8 apart -> the loop ends 16 higher
            _jal(bal["draw"]), 0x02202021,                          # jal bal_optdraw ; move a0,s1
            0x34050098, 0x26260010,                                 # ori a1,zero,0x98 ; addiu a2,s1,16: the exit line
            0x2842000d, 0x3402000c,                                 # cursor 0..12
            _jal(bal["input"]),
            0x341100a0]                                             # "PRESS X BUTTON" of items 9..11 from y 160


def save_words(flag):
    hi, lo = _hilo(flag)
    return [0xa2030001,                     # sb v1,1(s0)
            0x3c190000 | hi,                # lui t9,hi(arcbal)
            0xa2040002,                     # sb a0,2(s0)
            0x93390000 | lo,                # lbu t9,lo(arcbal)(t9)
            0xa2050003,                     # sb a1,3(s0)
            0xa2060004,                     # sb a2,4(s0)
            0xa2190000 | SLOT,              # sb t9,9(s0)
            0x00000000]


def load_words(flag):
    hi, lo = _hilo(flag)
    return [0x92030001,                     # lbu v1,1(s0)
            0x92190000 | SLOT,              # lbu t9,9(s0)
            0x92040002,                     # lbu a0,2(s0)
            0x33390001,                     # andi t9,t9,1
            0x92050003,                     # lbu a1,3(s0)
            0x3c010000 | hi,                # lui at,hi(arcbal)
            0x92060004,                     # lbu a2,4(s0)
            0xa0390000 | lo]                # sb t9,lo(arcbal)(at)


def save_words_card(sv):
    """--excard (tools/exopt/xvex.c EX_CARD): +9 = every EX OPTIONS row packed by ex_cardsv (keeps all registers, t9 out)"""
    return [0xa2030001, 0xa2040002, 0xa2050003, 0xa2060004,     # sb v1,1(s0) ; sb a0,2(s0) ; sb a1,3(s0) ; sb a2,4(s0)
            _jal(sv), 0x00000000,                               # jal ex_cardsv ; nop
            0xa2190000 | SLOT, 0x00000000]                      # sb t9,9(s0) ; nop


def load_words_card(ld):
    """--excard: ex_cardld unpacks +9 (t9 in) into the rows; a save without our bits = every default"""
    return [0x92030001, 0x92040002, 0x92050003, 0x92060004,     # lbu v1,1(s0) ; lbu a0,2(s0) ; lbu a1,3(s0) ; lbu a2,4(s0)
            0x92190000 | SLOT,                                  # lbu t9,9(s0)
            _jal(ld), 0x00000000, 0x00000000]                   # jal ex_cardld ; nop ; nop


def ovl_patches(bal, optscreen=True, card=None):
    """[(address, word)] for P/P4/OPDEMO.BIN (optscreen False: 1.4 EX OPTIONS has the line, OPTION MODE stays stock;
    card = the EX module's symbols for --excard)"""
    out = list(zip(OPT_AT, opt_words(bal))) if optscreen else []
    sw = save_words_card(card["ex_cardsv"]) if card else save_words(bal["flag"])
    lw = load_words_card(card["ex_cardld"]) if card else load_words(bal["flag"])
    out += [(SAVE_AT + 4 * i, w) for i, w in enumerate(sw)]
    out += [(LOAD_AT + 4 * i, w) for i, w in enumerate(lw)]
    return out


def apply(f, lmap, touched, bal, optscreen=True, card=None):
    """the OPDEMO.BIN words (f = the image, r+b); bal = skippatch.code(arcbal=True)["bal"]"""
    lba = lmap[MENU_FILE][0]
    pos = lambda a: (lba + (a - OVL_BASE) // 2048, (lba + (a - OVL_BASE) // 2048) * 2352 + 24 + (a - OVL_BASE) % 2048)
    def rd(a):
        f.seek(pos(a)[1]); return struct.unpack("<I", f.read(4))[0]
    for a, old in zip(OPT_AT, OPT_OLD):
        assert rd(a) == old, "arcbal: OPDEMO.BIN not as expected at %08x" % a
    for at, sha in ((SAVE_AT, SAVE_SHA), (LOAD_AT, LOAD_SHA)):
        assert hashlib.sha1(b"".join(struct.pack("<I", rd(at + 4 * i)) for i in range(8))).hexdigest() == sha, "arcbal: OPDEMO.BIN options save / load not stock at %08x" % at
    for a, w in ovl_patches(bal, optscreen, card):
        l, p = pos(a)
        f.seek(p); f.write(struct.pack("<I", w)); touched.add(l)
    print("ARCADE BALANCE: flag %08x, optdraw %08x, optinput %08x, gates %s, OPDEMO %ssave / load%s" % (
        bal["flag"], bal["draw"], bal["input"], " ".join("%08x" % g[0] for g in GATES), "option / " if optscreen else "(EX OPTIONS line) ",
        " (--excard: every EX OPTIONS row, ex_cardsv %08x / ex_cardld %08x)" % (card["ex_cardsv"], card["ex_cardld"]) if card else ""))


def apply_ram(emu, flag, on):
    """test helper: gates -> flag byte (before any fight code runs: I-cache), flag = on"""
    for a, d in gate_patches(flag): emu.poke(a, d)
    emu.poke(flag, bytes([1 if on else 0]))
