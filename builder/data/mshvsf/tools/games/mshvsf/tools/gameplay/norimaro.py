"""Norimaro (char 0x11, team word 0x22) back on the US select screen (mktag --nori; games/mshvsf/docs/NORIMARO.md).

All of his data is on the US disc (code, sprites, sound, portrait, VS / win art, quotes, ending).  The US release only
cut the select-grid links INTO his cell and the SHORT CUT list bound, and drew the game logo in his cell.

  1. grid navigation table 0x800a4060 (SELECT overlay; 4 bytes per char id: up, down, left, right = next id * 2):
     Wolverine down, Blackheart right, Omega Red left -> 0x22 (his own entry is stock: up Wolverine, left Blackheart,
     right Omega Red).  Both overlay copies: SEL.ARC (what the game loads, 0x2c header) and SELECT.BIN.
  2. SHORT CUT (EXE text list): `addiu s2,zero,0x10` at 0x8004f9a4 -> 0x11 (the id -> position table already has him
     at position 17).
  3. grid icon: HIS NATIVE icon, still on the US disc (SP_SEL0 page (896,256) u 68 v 177 + SELECT.BIN CLUT 0x1a124,
     loaded but never drawn by the US release; pixel-exact to the arcade icon), copied unchanged over the logo cell's
     texels (SP_SEL0 raw page for VRAM (960,256), u 4..67, v 129..176) and its CLUT (VRAM (0,497),
     SELECT.BIN 0x1be24).  No Capcom pixels are stored in this tool or the patch data; the tool only knows where to
     look.  SP_SEL0 is inside SEL.ARC at +0x52a2c (the loaded copy) and also DAT/SP_SEL0.DSP (patched too).

  4. ending text: his ENDING.BIN slot (also in END.ARC) held a copy of Dan's text with a "Captain America" tag on one
     page; new English text (written from the Japanese ending's story) + a script that pages through it (see below).

Arcade CPU: the route table (0x8006ac34) never picks him - identical in the Japanese arcade program (mvsj.03i/04i) -
so nothing changes there.

    overlay_patches(read)   [(file, offset, bytes)]   read(name) -> stock file bytes (the user's disc)
    patches()               [(addr, bytes)] EXE
    ram_overlay_patches(read) [(addr, bytes)] while the select overlay is resident (tests)
"""
import os, struct, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))

NORI = 0x11
NAV = 0x800a4060
OVLS = (("SEL.ARC", 0x800947d4), ("SELECT.BIN", 0x80094800))      # as tools/gameplay/cyber.py
NAV_BYTES = [(NAV + 4 * 4 + 1, 0x08, 0x22),      # Wolverine down: self -> Norimaro
             (NAV + 8 * 4 + 3, 0x0c, 0x22),      # Blackheart right: Omega Red -> Norimaro
             (NAV + 6 * 4 + 2, 0x10, 0x22)]      # Omega Red left: Blackheart -> Norimaro
NORI_ENTRY = (NAV + NORI * 4, bytes([0x08, 0x22, 0x10, 0x0c]))     # his own entry (stock, checked)
SC_AT, SC_ORIG, SC_NEW = 0x8004f9a4, 0x24120010, 0x24120011         # SHORT CUT list bound (jr delay slot)

# icon: logo cell SPRT (64 x 48, uv (4,129), CLUT 0x7c40) in the 4bpp page at VRAM (960,256)
SEL0_IN_ARC = 0x52a2c            # DAT/SP_SEL0.DSP inside DAT/SEL.ARC
PAGE960 = 0x38c82                # SP_SEL0: VRAM (960 + x, 256 + y) = file[PAGE960 + 124 * y + 2 * x]
ROW = 124
ICON_U, ICON_V, ICON_W, ICON_H = 4, 129, 64, 48
CLUT_SELBIN = 0x1be24            # 16 colours -> VRAM (0,497); SEL.ARC = + 0x2c
# His NATIVE grid icon is still on the US disc: the texels sit in SP_SEL0's page at VRAM (896,256), u 68..131,
# v 177..224 (uploaded with the page but never drawn), and his icon CLUT is in SELECT.BIN at 0x1a124 (the per-character
# icon CLUT block, never uploaded).  Both are pixel / colour exact to the arcade select icon (CPS2 tiles 0x1b5e6 4 x 3,
# palette 0x11 at program 0x1f998e, colour = nibble * 2; index 15 = transparent, 14 = 0x0800 black like the other
# icons).  We copy them into the logo cell (same 64 x 48 size, same 4bpp format), so nothing new is drawn and no pixel
# is stored in this tool.
PAGE896 = 0x30c82                # SP_SEL0: VRAM (896 + x, 256 + y) = file[PAGE896 + 124 * y + 2 * x]
NAT_U, NAT_V = 68, 177
NAT_CLUT = 0x1a124               # SELECT.BIN (SEL.ARC + 0x2c)
NAT_SHA1 = "faffd7a3"            # first 8 hex of sha1(texel indices + clut bytes): guards against another disc


def _rd(read, name):
    return read(name)


def icon(read):
    """-> (texels uint8 48x64 with values 0..15, clut 16 x u16), cut to the cell frame.  Index 15 = transparent (CLUT 0)."""
    import hashlib
    sp0, sel = read("SP_SEL0.DSP"), read("SELECT.BIN")
    tex = np.zeros((ICON_H, ICON_W), np.uint8)
    for y in range(ICON_H):
        o = PAGE896 + ROW * (NAT_V + y) + NAT_U // 2
        r = np.frombuffer(sp0[o:o + ICON_W // 2], np.uint8)
        tex[y, 0::2] = r & 15; tex[y, 1::2] = r >> 4
    cb = sel[NAT_CLUT:NAT_CLUT + 32]
    clut = list(struct.unpack("<16H", cb))
    h = hashlib.sha1(tex.tobytes() + cb).hexdigest()[:8]
    assert h == NAT_SHA1, "Norimaro native icon: sha1 %s (disc not the US SLUS-00793?)" % h
    assert clut[15] == 0 and all(clut[:15]), "Norimaro icon CLUT: %s" % clut
    return _fit_cell(tex), clut


# The arcade draws the cell frame OVER the 64 x 48 icon; the PS1 draws the frames first and the icons over them, so its
# icons are cut to the frame (transparent outside).  The native texture is the uncut arcade block, and the logo SPRT
# sits at (155,178), 4 px left of / 3 px above where the arcade puts the icon in its frame: drawn as is, his arm and
# sleeve cover the cell's left and bottom frame.  Measured on the stock select screen (frame pixels around the logo
# cell, sprite coordinates): inside the frame = rows 1..38, from column CELL_LEFT[row] to 63; the arcade frame
# interior (FBNeo mshvsfj, icon origin (160,167)) is the same quad shifted by (+4, -3) with the same skew steps.
CELL_ROWS = (1, 39)
CELL_LEFT = [(14, 9), (32, 8), (39, 7)]          # (rows below, first column inside the frame)
SHIFT_X, SHIFT_Y = 4, 3                          # sprite pixel (c, r) shows arcade texel (c - 4, r + 3)


def _fit_cell(tex):
    out = np.full_like(tex, 15)
    for r in range(*CELL_ROWS):
        left = next(c for lim, c in CELL_LEFT if r < lim)
        for c in range(left, ICON_W):
            sr, sc = r + SHIFT_Y, c - SHIFT_X
            if 0 <= sr < ICON_H and 0 <= sc < ICON_W: out[r, c] = tex[sr, sc]
    return out


def _icon_rows(tex):
    """texel rows -> bytes per VRAM row (u 4..67 = words 1..16 = 32 bytes)"""
    assert ICON_U % 4 == 0 and ICON_W % 4 == 0
    return [bytes((tex[y, 0::2] | tex[y, 1::2] << 4).astype(np.uint8)) for y in range(ICON_H)]


# ----------------------------------------------------------------------------------------------- patches
def patches():
    return [(SC_AT, struct.pack("<I", SC_NEW))]


def check_exe(read32):
    assert read32(SC_AT) == SC_ORIG, "SHORT CUT bound word at %08x: %08x" % (SC_AT, read32(SC_AT))


# ----------------------------------------------------------------------------------------------- ending text
# ENDING.BIN (overlay at 0x80094800; also inside END.ARC at +0x24, the same bytes).  Per char id:
#   text   0x800b4da4[id] -> u16 cells, 25 per line, 2 lines per page (page n = cells 50n..50n+49).
#          cell: 0x0020 space; 0x0100 | c for a glyph: 'A'..'Z' = 0x140..0x159 (letter - 1), 'a'..'z' = 0x161..0x17a,
#          ! 0x120, ? 0x121, - 0x12a, . 0x184, , 0x185, ' 0x187 (the glyphs the other endings use).
#   script 0x800b2adc[id] -> list of scene pointers (one scene = one picture; Norimaro's pictures: globe, history
#          book, END card = 3 scenes).  Scene = entries (u16 frames, u8 speaker, u8 page) ... ffff 0000.
#          speaker = char id for the name tag (0x11 = "Norimaro"), 0 = narration (no tag, as Ryu's ending).
# The US disc never translated his ending: his text slot (250 cells = 5 pages) is a copy of Dan's and every scene
# shows page 0 with speaker 2 (a "Captain America" tag), so one wrong line stays up.  New English text below, written
# from the Japanese ending's story (he beats Apocalypse and Cyber-Akuma, gets carried away, unites the Earth as a
# tyrant, and history books remember him as the "Wicked King" (gedou-ou) that exam students suffer over).
END_FILES = (("ENDING.BIN", 0), ("END.ARC", 0x24))
END_BASE = 0x80094800
END_TEXT_TAB, END_SCRIPT_TAB, DAN = 0x800b4da4, 0x800b2adc, 0x12
NORI_TEXT, NORI_CELLS = 0x800b469c, 250
NORI_LIST, NORI_SCENE0 = 0x800b2a70, 0x800b2a38        # 7 scene pointers; scene data 0x800b2a38..0x800b2a6f
NORI_SCRIPT_STOCK = bytes.fromhex("78000200ffff000078000200ffff000478000200ffff000578000200ffff260778000200ffff0008"
                                  "78000200ffff000a2c010200ffff000c382a0b80402a0b80482a0b80502a0b80582a0b80602a0b80"
                                  "682a0b80")
ENDING_PAGES = [                 # (speaker, line 1, line 2); each line <= 25, centred
    (NORI, "I beat Apocalypse and", "Cyber-Akuma! Woof!"),
    (NORI, "I'm the strongest! The", "whole world is mine now!"),
    (0, "Norimaro united the Earth", "and ruled it as a tyrant."),
    (0, "In history books, he is", "known as the Wicked King."),
    (0, "...and students cramming", "for exams curse his name!"),
]
ENDING_SCENES = [[(300, 0), (300, 1)],          # globe + crown: his own words
                 [(300, 2), (300, 3)],          # history book page with his crowned portrait
                 [(360, 4)]]                    # END card
GLYPH = {"!": 0x120, "?": 0x121, "-": 0x12a, ".": 0x184, ",": 0x185, "'": 0x187}


def _cells(s):
    out = []
    for ch in s:
        if ch == " ": out.append(0x20)
        elif "A" <= ch <= "Z": out.append(0x100 | (ord(ch) - 1))
        elif "a" <= ch <= "z": out.append(0x100 | ord(ch))
        else: out.append(GLYPH[ch])
    return out


def ending_text():
    cells = []
    for spk, a, b in ENDING_PAGES:
        for line in (a, b):
            assert len(line) <= 25, line
            cells += _cells(line.center(25))
    assert len(cells) <= NORI_CELLS
    cells += [0x20] * (NORI_CELLS - len(cells))
    return struct.pack("<%dH" % NORI_CELLS, *cells)


def ending_script():
    """-> (scene data at NORI_SCENE0, scene pointer list at NORI_LIST)"""
    data, ptrs = b"", []
    for sc in ENDING_SCENES:
        ptrs.append(NORI_SCENE0 + len(data))
        for frames, page in sc:
            data += struct.pack("<HBB", frames, ENDING_PAGES[page][0], page)
        data += struct.pack("<HH", 0xffff, 0)
    assert NORI_SCENE0 + len(data) <= NORI_LIST - 8    # keep the last old scene (2c01 0200 ffff ..) intact
    ptrs += [ptrs[-1]] * (7 - len(ptrs))               # unused list slots -> the END scene
    return data, struct.pack("<7I", *ptrs)


def ending_patches(read):
    """[(file, offset, bytes)] for ENDING.BIN and its copy in END.ARC"""
    out = []
    end = read("ENDING.BIN")
    arc = read("END.ARC")
    assert arc[0x24:0x24 + len(end)] == end, "END.ARC does not hold ENDING.BIN at +0x24"
    o = lambda a: a - END_BASE
    u32 = lambda a: struct.unpack("<I", end[o(a):o(a) + 4])[0]
    assert u32(END_TEXT_TAB + 4 * NORI) == NORI_TEXT and u32(END_TEXT_TAB + 4 * (NORI + 1)) == NORI_TEXT + 2 * NORI_CELLS
    dan = u32(END_TEXT_TAB + 4 * DAN)
    assert end[o(NORI_TEXT):o(NORI_TEXT) + 2 * NORI_CELLS] == end[o(dan):o(dan) + 2 * NORI_CELLS], "Norimaro ending text not the stock Dan copy"
    assert u32(END_SCRIPT_TAB + 4 * NORI) == NORI_LIST
    assert end[o(NORI_SCENE0):o(NORI_SCENE0) + len(NORI_SCRIPT_STOCK)] == NORI_SCRIPT_STOCK, "Norimaro ending script not stock"
    data, ptrs = ending_script()
    for f, base in END_FILES:
        out += [(f, base + o(NORI_TEXT), ending_text()), (f, base + o(NORI_SCENE0), data), (f, base + o(NORI_LIST), ptrs)]
    return out


def ram_ending_patches():
    """[(addr, bytes)] while the ending overlay is resident (tests)"""
    data, ptrs = ending_script()
    return [(NORI_TEXT, ending_text()), (NORI_SCENE0, data), (NORI_LIST, ptrs)]


def overlay_patches(read):
    """[(file, offset, bytes)]: nav bytes (SEL.ARC, SELECT.BIN), icon texels (SEL.ARC + SP_SEL0.DSP), CLUT (both overlays),
    ending text + script (ENDING.BIN, END.ARC)"""
    out = ending_patches(read)
    sel = {f: read(f) for f, b in OVLS}
    sp0 = read("SP_SEL0.DSP")
    for f, base in OVLS:
        s = sel[f]
        a, want = NORI_ENTRY
        assert s[a - base:a - base + 4] == want, "%s: Norimaro nav entry not stock" % f
        for a, old, new in NAV_BYTES:
            assert s[a - base] == old, "%s: nav byte %08x = %02x" % (f, a, s[a - base])
            out.append((f, a - base, bytes([new])))
    # the logo cell: stock texels must be the US logo page (same bytes in both copies), CLUT the logo's
    arc = sel["SEL.ARC"]
    assert arc[SEL0_IN_ARC:SEL0_IN_ARC + len(sp0)] == sp0, "SEL.ARC does not hold SP_SEL0.DSP at +0x52a2c"
    tex, clut = icon(read)
    rows = _icon_rows(tex)
    for y, row in enumerate(rows):
        o = PAGE960 + ROW * (ICON_V + y) + ICON_U // 2
        out.append(("SP_SEL0.DSP", o, row))
        out.append(("SEL.ARC", SEL0_IN_ARC + o, row))
    cb = struct.pack("<16H", *clut)
    for f, base in OVLS:
        out.append((f, CLUT_SELBIN + (0x2c if f == "SEL.ARC" else 0), cb))
    return out


def ram_overlay_patches(read):
    """[(addr, bytes)] for the select overlay while resident (nav + CLUT source only; VRAM texels are uploaded at load)"""
    out = [(a, bytes([new])) for a, old, new in NAV_BYTES]
    tex, clut = icon(read)
    out.append((0x80094800 + CLUT_SELBIN, struct.pack("<16H", *clut)))
    return out


def vram_icon(read):
    """(tex, clut) for tests that write VRAM in a savestate"""
    return icon(read)


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(GAME, "tools", "logo"))
    import mshcards
    rd = lambda n: mshcards.disc_file(n)
    for f, o, d in overlay_patches(rd)[:8]:
        print(f, hex(o), d.hex())
    tex, clut = icon(rd)
    print("icon colours", [hex(c) for c in clut])
    if "--png" in sys.argv:
        from PIL import Image
        c = np.array(clut, np.uint16)[tex]
        rgb = np.dstack([(c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3]).astype(np.uint8)
        Image.fromarray(rgb).resize((256, 192), Image.NEAREST).save(sys.argv[sys.argv.index("--png") + 1])
