"""Apocalypse pre-fight dialogue (XvSF 1.4 --apodlg; docs/CUT_CONTENT.md item 1).

The Japanese arcade / JP PS1 show a short conversation between the player's point character and Apocalypse
before the boss fight.  The US disc still has the code (PL08 spawners, text routine) and the Japanese text;
only two `jal`s in the intro were removed.  This module

  * restores the two calls in both links of Apocalypse's code (P/P0/PL08_10.BIN at 0x800d1000, P/P2/PL08_20.BIN
    at 0x80152000) in place, through a 7-word stub that sits in the text routine's freed slot-base code;
  * points the text routine's glyph base at the word APO_PTR (set by the battle loader, tools/tagload -DAPODLG);
  * replaces the Japanese text table (18 entries x 3 boxes x 38 u16 cells) by our own English text.  The English
    lines are rendered proportionally at BUILD time from the upright Latin glyphs of KANJI.TEX on the user's disc
    into 16x16 4bpp tiles (one 16 KB file per character, code 0x0900 + tile index, blank cells 0x0020); the loader
    reads only the speaker's file.  No Capcom data in the tool: glyph pixels come from the user's disc.

Box 1 = player's point character, boxes 2 and 3 = Apocalypse (as the JP disc).
"""
import os, struct
import numpy as np

APO_PTR = 0x8001735c            # tagload .dbg tail (tl_dbg is 12 bytes): glyph base for the text routine
FONT_ADDR = 0x801f0000          # boss fight on the new loader: free during the load + intro (work/apodlg/probe.py)
FONT_SIZE = 0x4000              # 8 strips of 16 tiles x 2 KB
P0_BASE, P2_BASE = 0x800d1000, 0x80152000
TEXT_OFF, TEXT_ENT = 0x947c, 0xE4                       # PL08 text table (0x800da47c in the P0 link), per char id / 2
VOICE = 0x8004e01c
CELLS, LINE_PX = 19, 19 * 16

# ---- glyphs (KANJI.TEX codes; strip formula of the text routine: page (code >> 8) - 9, strip (code >> 4) & 15) ----
def _latin():
    m = {}
    for i, ch in enumerate("ABCDEFGHIJKLMN"): m[ch] = 0x0d92 + i
    for i, ch in enumerate("OPQRSTUVWXYZabcd"): m[ch] = 0x0da0 + i
    for i, ch in enumerate("efghijklmnopqrst"): m[ch] = 0x0db0 + i
    for i, ch in enumerate("uvwxyz0123456789"): m[ch] = 0x0dc0 + i
    m.update({".": 0x0a8b, ",": 0x0a8c, ":": 0x0a8f, "?": 0x0a91, "!": 0x0a92, "'": 0x0a9e})
    m["-"] = (0x0dd3, 2, 9)                         # hyphen: columns 2..8 of the long dash (with its shadow column)
    return m
GLYPH = _latin()
SPACE_PX, GAP_PX = 5, 0                              # glyphs keep their shadow column
BG = 15                                             # background index of KANJI.TEX cells

NAMES = ["Wolverine", "Cyclops", "Storm", "Rogue", "Gambit", "Sabretooth", "Juggernaut", "Magneto", "Apocalypse",
         "Ryu", "Ken", "Chun-Li", "Dhalsim", "Zangief", "M. Bison", "Akuma", "Charlie", "Cammy"]

A3 = ("Behold my true form!", "Now offer your life to me!!")                     # JP: 見るがよい、我が輩の真のすがたを!
B3 = ("Behold the true form of Apocalypse!", "Now offer your life to me!!")      # JP: ...我が輩・アポカリプスの真のすがたを!

# Our own English, translated from the Japanese lines on the disc (box 1 player, box 2 / 3 Apocalypse).
TEXT = [
    (("Apocalypse! So it's you, huh!", "Today's the day you die, bub!"),
     ("Wolverine, you pitiful berserker.", "You think you have me cornered?"), A3),
    (("We've got you cornered, Apocalypse!", "Your schemes end right here!!"),
     ("You think you have me cornered?", "Cyclops, you X-Men have lost!"), A3),
    (("You can't escape now, Apocalypse.", "Release the people you captured!"),
     ("Storm, rider of the mighty winds.", "Sadly, that wish will not be granted."), A3),
    (("So it IS you, Apocalypse.", "C'mon, sugah, bring it on already!!"),
     ("Rogue, you foolish mutant.", "You never had a chance against me."), B3),
    (("Game's over, monsieur.", "You wanna say a little prayer?"),
     ("Gambit, you shallow little thief.", "It is you who will die here."), B3),
    (("Hmph! You don't look like much!", "Birdy, have my dinner ready!"),
     ("Sabretooth, you foolish butcher.", "It is you who walked into my trap."), B3),
    (("Raaaaaaaaaaaaarrgh!!", "So YOU'RE Apocalypse?!"),
     ("Juggernaut, you colossal fool.", "There are those mightier than you."), B3),
    (("Apocalypse, your one mistake was", "angering the Master of Magnetism."),
     ("Laughable, Magneto.", "You think you have me cornered?"), A3),
    (("Apocalypse, your one mistake was", "angering the Master of Magnetism."),       # id 8 (unused): as Magneto
     ("Laughable, Magneto.", "You think you have me cornered?"), A3),
    (("So you are Apocalypse.", "Fight me! Face my fist!!"),
     ("Ryu, the wandering warrior.", "Your fists mean nothing to me."), A3),
    (("So you're the Apocalypse guy?", "KO in one minute. I've got plans."),
     ("Ken, human who knows not his place.", "You dare think you can defeat me?"), A3),
    (("Are you Apocalypse?", "Freeze! You're under arrest!!"),
     ("Arrest? Me? Ha ha ha ha ha!", "Chun-Li, cease this foolishness."), A3),
    (("Apocalypse...", "A lost soul still far from the truth..."),
     ("Dhalsim, you false ascetic.", "You think you have me cornered?"), B3),
    (("Hm? I don't know who you are, but", "you want to test my body of steel?"),
     ("Zangief, you hopeless fool.", "Do you truly think you can win?"), B3),
    (("So you finally show yourself!", "Your era is long over, Apocalypse!!"),
     ("Bison, you are lower than trash.", "You think you can defeat me?"), A3),
    ((".........", ""),
     ("Akuma, however strong you may be,", "a man has his limits..."), B3),
    (("......", "You're coming with me, Apocalypse."),
     ("Pitiful Charlie.", "You think you have me cornered?"), A3),
    (("Target confirmed: Apocalypse...", "Destroy!"),
     ("Cammy. Welcome, and farewell.", "Your fleeting life ends here."), B3),
]
assert len(TEXT) == 18


def kanji_glyph(kanji, code):
    o = (((code >> 8) - 9) << 15) + (((code >> 4) & 15) << 11)
    s = np.frombuffer(kanji[o:o + 2048], np.uint8).reshape(16, 128)
    px = np.zeros((16, 256), np.uint8); px[:, 0::2] = s & 15; px[:, 1::2] = s >> 4
    c = code & 15
    return px[:, c * 16:(c + 1) * 16]


def render_line(kanji, text, check=True):
    """text -> (16, LINE_PX) 4bpp pixel row, proportional, left aligned"""
    row = np.full((16, LINE_PX), BG, np.uint8)
    x = 0
    for ch in text:
        if ch == " ":
            x += SPACE_PX; continue
        gl = GLYPH[ch]
        if isinstance(gl, tuple):
            g = kanji_glyph(kanji, gl[0])[:, gl[1]:gl[2]]
        else:
            g = kanji_glyph(kanji, gl)
            cols = np.nonzero((g != BG).any(axis=0))[0]
            g = g[:, cols[0]:cols[-1] + 1]
        assert not check or x + g.shape[1] <= LINE_PX, f"line too long: {text!r}"
        if x + g.shape[1] <= LINE_PX: row[:, x:x + g.shape[1]] = g
        x += g.shape[1] + GAP_PX
    return row, x


def tiles_and_table(kanji, ch):
    """(16 KB tile file, 228-byte table entry) for character ch"""
    data = bytearray(bytes([0xFF]) * FONT_SIZE)
    codes = []
    for b, lines in enumerate(TEXT[ch]):
        for ln, text in enumerate(lines):
            row, _ = render_line(kanji, text)
            for i in range(CELLS):
                t = row[:, i * 16:(i + 1) * 16]
                k = b * 2 * CELLS + ln * CELLS + i            # tile index
                if (t == BG).all():
                    codes.append(0x0020); continue
                codes.append(0x0900 | k)
                strip, col = k >> 4, k & 15
                for y in range(16):
                    o = strip * 2048 + y * 128 + col * 8
                    data[o:o + 8] = bytes((t[y, 2 * j] | (t[y, 2 * j + 1] << 4)) for j in range(8))
    assert len(codes) == 3 * 38
    return bytes(data), struct.pack("<114H", *codes)


def font_files(kanji):
    """19 tile files (index = character number; 18 = Chun-Li's alternate costume = Chun-Li) + 18 table entries"""
    out, tab = [], []
    for ch in range(18):
        d, t = tiles_and_table(kanji, ch)
        out.append(d); tab.append(t)
    out.append(out[11])
    return out, b"".join(tab)


# ---- code patches (offsets into PL08, link base L) ----
def _jal(t): return 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
def _j(t): return 0x08000000 | ((t >> 2) & 0x03FFFFFF)

STOCK = {   # offset: word as in the US P0 link (L = 0x800d1000); relocated words checked against L
    0x500: 0x02002021, 0x504: 0x34050286, 0x508: 0x94820010, 0x50c: 0x34030480, 0x510: 0xa483000c,
    0x514: 0x24420100, 0x518: _jal(VOICE), 0x51c: 0xa4820010, 0x520: "j L+0x684", 0x524: 0,
    0x28a4: 0x3c028004, 0x28a8: 0x80422a64, 0x28ac: 0, 0x28b0: "bne", 0x28b4: 0x3c020004, 0x28b8: 0x3c108004,
    0x28bc: 0x8e10d814, 0x28c0: "j L+0x28d0", 0x28c4: 0, 0x28c8: 0x3c108004, 0x28cc: 0x8e10d81c, 0x28d0: 0x34422000,
    0x28d4: 0x02028021,
    0x27bc: 0x27bdffe8, 0x2758: 0x27bdffe8,           # the two spawners (JP 0x800d37cc / 0x800d3768)
}


def code_words(L):
    w = {
        # intro (JP: move a0,s0; lhu; ori; sh; addiu; jal spawn1; sh; jal spawn2; move; move; jal voice; ori; j)
        0x500: 0x02002021,                  # move a0, s0
        0x504: 0x96020010,                  # lhu  v0, 0x10(s0)
        0x508: 0x34030480,                  # ori  v1, zero, 0x480
        0x50c: 0xa603000c,                  # sh   v1, 0xc(s0)
        0x510: 0x24420100,                  # addiu v0, v0, 0x100
        0x514: _jal(L + 0x27bc),            # jal  spawn1 (object 0xEC, +0x27 = 2)
        0x518: 0xa6020010,                  # sh   v0, 0x10(s0)
        0x51c: _j(L + 0x28b0),              # j    stub
        0x520: 0x02002021,                  # move a0, s0
        0x524: 0,
        # text routine: glyph base = *APO_PTR (was: slot base by side + 0x42000)
        0x28a4: 0x3c100000 | ((APO_PTR + 0x8000) >> 16),           # lui  s0, %hi(APO_PTR)
        0x28a8: _j(L + 0x28d8),                                    # j    (strip/page offsets)
        0x28ac: 0x8e100000 | (APO_PTR & 0xFFFF),                   # lw   s0, %lo(APO_PTR)(s0)
        # stub (in the freed words): spawn2, then the voice call that was there, then the epilogue
        0x28b0: _jal(L + 0x2758),           # jal  spawn2 (object 0xEC, +0x27 = 0, text speaker = point character)
        0x28b4: 0,
        0x28b8: 0x02002021,                 # move a0, s0
        0x28bc: _jal(VOICE),                # jal  voice
        0x28c0: 0x34050286,                 # ori  a1, zero, 0x286
        0x28c4: _j(L + 0x684),              # j    epilogue
        0x28c8: 0, 0x28cc: 0, 0x28d0: 0, 0x28d4: 0,
    }
    assert APO_PTR & 0x8000 == 0
    return w


def patch_code(data, L, table):
    """PL08 link at L (bytes) -> patched bytes; checks every replaced word is the stock one"""
    b = bytearray(data)
    for off, want in STOCK.items():
        got = struct.unpack_from("<I", b, off)[0]
        if isinstance(want, int):
            assert got == want, f"PL08 {L:08x}+{off:#x}: {got:08x} != stock {want:08x}"
        elif want.startswith("j L+"):
            assert got == _j(L + int(want[4:], 16)), f"PL08 {L:08x}+{off:#x}: {got:08x}"
        elif want == "bne":
            assert got >> 16 == 0x1456, f"PL08 {L:08x}+{off:#x}: {got:08x}"
    for off, w in code_words(L).items():
        struct.pack_into("<I", b, off, w)
    assert len(table) == 18 * TEXT_ENT
    b[TEXT_OFF:TEXT_OFF + len(table)] = table
    return bytes(b)


def kanji_from(files_dir):
    return open(os.path.join(files_dir, "KANJI.TEX"), "rb").read()


if __name__ == "__main__":                          # preview sheet: python tools/apodlg.py OUT.png
    import sys
    from PIL import Image
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import region
    k = kanji_from(region.FILES)
    rows = []
    for ch in range(18):
        for lines in TEXT[ch]:
            for t in lines:
                r, w = render_line(k, t, check=False)
                print(f"{NAMES[ch]:11s} {w:3d}/{LINE_PX} {t}")
                rows.append(r)
            rows.append(np.full((4, LINE_PX), 7, np.uint8))
        rows.append(np.full((8, LINE_PX), 0, np.uint8))
    img = (15 - np.vstack(rows)) * 17
    Image.fromarray(255 - img.astype(np.uint8)).resize((LINE_PX * 2, img.shape[0] * 2), Image.NEAREST).save(sys.argv[1])
