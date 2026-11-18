"""Boot cards of the MSHvSF tag hack (v10): the "PEPA SOFT HOUSE" card and the fan-patch notice, ported from XvSF
(tools/logopatch.py + tools/logo/logo.S + card.bin, tools/card2patch.py + tools/logo/card2.S - the same stubs and
the same title card; only addresses, art and text differ).

Both stubs run at the executable's entry point before any game code (bare metal: no BIOS call, no stack, only
t0-t9), then zero themselves and their data again and jump to the original entry 0x800106e0.  They live in a part
of the executable image that is all zeros in the file (0x800f18e4-0x801cd200: run-time character / heap area):

    LOGO_AT 0x80100000  card 1 stub + 1-bit 320x240 bitmap (~10 KB), ~2.6 s
    IMG_AT  0x80110000  card 2 picture, 15-bit 320x240 (153,600 B)
    STUB_AT 0x80135800  card 2 stub; card 1's `la $t7, ENTRY` is pointed here.  4.5 s, START / X skip after 1 s.
    PS-EXE header pc0 (file offset 0x10): 0x800106e0 -> LOGO_AT.  Both wipe routines run from 0x801ff000 at boot only.

Card 2 art: six slanted panels like XvSF's card, Marvel left (blue), Street Fighter right (red), each with the
character's own fight sprite drawn from the user's disc at build time (DAT/SP_PLxx.DSP decoded with common/dsp/dsp.py,
its default colours from PLxx_10.A0; the file SHA-1s are checked).  Text and panel shapes: tools/logo/mshcard2.bin
(ours, `render`).  Nothing derived from the disc is committed.

    disc_patches(exe)           -> [(EXE file offset, bytes)]  (mktag.py writes them into SLUS_007.93 on the image)
    python mshcards.py render   draw tools/logo/mshcard2.bin (PIL + fonts Impact, Arial Bold)
    python mshcards.py preview  games/mshvsf/work/v10/card2_msh.png (+ _2x)
"""
import os, struct, subprocess, sys, zlib, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "common", "dsp")]
import toolenv, logopatch, card2patch
GCC = toolenv.mips_prefix()
OBJ = os.path.join(GAME, "build", "logoobj")
EXE_BASE, EXE_HDR = 0x80010000, 0x800
ENTRY = 0x800106e0
ZERO = (0x800f18e4, 0x801cd200)
LOGO_AT = 0x80100000
W, H = 320, 240
IMG_AT, IMG_LEN = 0x80110000, W * H * 2
STUB_AT, STUB_END = IMG_AT + IMG_LEN, 0x80140000
DATA = os.path.join(HERE, "mshcard2.bin")
DISC = os.path.join(GAME, "disc", "mshvsf.bin")              # the user's disc (files read by LBA, work/lba_map.json)


def disc_file(name, disc=DISC):
    import json
    lba, size = json.load(open(os.path.join(GAME, "work", "lba_map.json")))[name]
    out = bytearray()
    with open(disc, "rb") as f:
        for i in range((size + 2047) // 2048):
            f.seek((lba + i) * 2352 + 24); out += f.read(2048)
    return bytes(out[:size])


# SHA-1 of the stock files the art is taken from (US disc SLUS-00793)
SHA1 = {"SP_SEL1.DSP": "00a72963f8c229e594c03257a88a53a2fe058c55", "SELECT.BIN": "ffca27915dc39f3b20c4dcc4cfd483b1429d863f"}

TOP, BOT, SLANT = card2patch.TOP, card2patch.BOT, card2patch.SLANT
PANELS = card2patch.PANELS
GRAD = card2patch.GRAD
# (character, sprite group, offset of the default colours in PLxx_10.A0, mirrored: faces the middle)
# Select-screen portraits: DAT/SP_SEL1.DSP group 292 + c (4bpp tiles), CLUTs in SELECT.BIN at 142756 + 160 * c
# + 32 * (part flags & 15) (the select screen copies them to VRAM (16, 496..); checked against the VRAM of the stock
# select screen).  (character, mirrored, face point in the unmirrored portrait)
SEL_GROUP0, SEL_CLUT0, SEL_CLUT_STRIDE = 292, 142756, 160
CHARS = [(0x07, False, (40, 133)), (0x02, False, (115, 58)), (0x03, True, (35, 48)),       # Spider-Man, Captain America, Hulk
         (0x09, False, (70, 48)), (0x10, False, (70, 64)), (0x0f, False, (98, 52))]         # Ryu, Sakura, Akuma
TITLE, SUB = "MARVEL SUPER HEROES VS. STREET FIGHTER", "TAG TEAM HACK"
LINES_TEXT = card2patch.LINES_TEXT
URL = card2patch.URL


def _link(src, name, at, defs, section):
    os.makedirs(OBJ, exist_ok=True)
    subprocess.check_call([GCC + "gcc", "-mips1", "-G0", "-mno-abicalls", "-fno-pic"] + [f"-D{k}={v}" for k, v in defs.items()] +
                          ["-c", src, "-o", name + ".o"], cwd=OBJ)
    open(os.path.join(OBJ, name + ".ld"), "w").write(f"SECTIONS {{\n  {section} 0x{at:08x} : {{ *({section}) }}\n"
                                                     "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) *(.bss) *(.text) *(.data) }\n}\n")
    subprocess.check_call([GCC + "ld", "-T", name + ".ld", name + ".o", "-o", name + ".elf"], cwd=OBJ)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", section, name + ".elf", name + ".bin"], cwd=OBJ)
    blob = open(os.path.join(OBJ, name + ".bin"), "rb").read()
    assert len(blob) % 4 == 0
    return blob


def card1():
    """card 1 = XvSF's stub and title card (tools/logo/card.bin), linked for MSHvSF"""
    os.makedirs(OBJ, exist_ok=True)
    bits = logopatch.card_bits(logopatch.SUB)
    open(os.path.join(OBJ, "card.bin"), "wb").write(bits)
    blob = _link(os.path.join(ROOT, "tools", "logo", "logo.S"), "logo", LOGO_AT,
                 dict(ENTRY=f"0x{ENTRY:08x}", DATA_LEN=len(bits), HBLANKS=logopatch.HBLANKS, ROUNDS=logopatch.ROUNDS), ".logo")
    assert LOGO_AT + len(blob) <= IMG_AT
    return blob


def card2_stub():
    blob = _link(os.path.join(ROOT, "tools", "logo", "card2.S"), "card2", STUB_AT,
                 dict(ENTRY=f"0x{ENTRY:08x}", IMG_AT=f"0x{IMG_AT:08x}", IMG_WORDS=IMG_LEN // 4, HOLD_FRAMES=card2patch.HOLD_FRAMES,
                      SKIP_AFTER=card2patch.SKIP_AFTER, LINES=card2patch.LINES), ".card2")
    assert STUB_AT + len(blob) <= STUB_END
    return blob


# ------------------------------------------------------------------------------------------------ the art
def portrait(c, read=disc_file):
    """-> (uint16 HxW 15-bit, bool HxW opaque): the select-screen portrait of character c, as the game draws it"""
    import numpy as np, dsp
    x = dsp.DSP(read("SP_SEL1.DSP"), name="SP_SEL1.DSP")
    sel = read("SELECT.BIN")
    parts = x.groups()[SEL_GROUP0 + c][2]
    boxes = [(p, x.tiles[p.tile]) for p in parts if p.tile < len(x.tiles)]
    for p, t in boxes:
        if t.raw is None: t.raw, t.clen, t.over = dsp.rle_decode(x.sec[0], t.off, t.n)
    x0 = min(p.x for p, t in boxes); y0 = min(p.y for p, t in boxes)
    x1 = max(p.x + t.w for p, t in boxes); y1 = max(p.y + t.h for p, t in boxes)
    col = np.zeros((y1 - y0, x1 - x0), np.uint16); op = np.zeros(col.shape, bool)
    for p, t in reversed(boxes):
        px = dsp.tile_pixels(t)
        if p.flags & 0x20: px = px[:, ::-1]
        if p.flags & 0x40: px = px[::-1]
        clut = np.array(struct.unpack_from("<16H", sel, SEL_CLUT0 + SEL_CLUT_STRIDE * c + 32 * (p.flags & 15)), np.uint16)
        c15 = clut[px]; m = c15 != 0                                    # colour 0 = transparent on the PS1
        sl = (slice(p.y - y0, p.y - y0 + t.h), slice(p.x - x0, p.x - x0 + t.w))
        col[sl][m] = c15[m] & 0x7fff; op[sl][m] = True
    return col, op


def layer():
    import numpy as np
    raw = zlib.decompress(open(DATA, "rb").read())
    pmap = np.frombuffer(raw[:W * H], np.uint8).reshape(H, W)
    ov = np.frombuffer(raw[W * H:], "<u2").reshape(H, W)
    return pmap, ov


def compose(read=disc_file):
    import numpy as np
    pmap, ov = layer()
    img = np.zeros((H, W), np.uint16)
    for k, (c, flip, (ax, ay)) in enumerate(CHARS):
        col, op = portrait(c, read)
        if flip: col, op, ax = col[:, ::-1], op[:, ::-1], col.shape[1] - 1 - ax
        xl, xr = PANELS[k]
        ox, oy = (xl + xr) // 2 + 7 - ax, TOP + 42 - ay                  # face point -> panel centre, 42 below the top
        pan = np.repeat(card2patch._grad(*GRAD[k], BOT - TOP + 1)[:, None], W, 1)
        full = np.zeros((H, W), np.uint16); full[TOP:BOT + 1] = pan
        y0, x0 = max(oy, 0), max(ox, 0); y1, x1 = min(oy + col.shape[0], H), min(ox + col.shape[1], W)
        sub = (slice(y0 - oy, y1 - oy), slice(x0 - ox, x1 - ox))
        reg = full[y0:y1, x0:x1]; m = op[sub]; reg[m] = col[sub][m]
        sel = pmap == k + 1
        img[sel] = full[sel]
    o = (ov & 0x8000) != 0
    img[o] = ov[o] & 0x7fff
    return img


def render():
    """mshcard2.bin: our text and panel shapes (card2patch.render with this game's text; the long title in Impact 16)"""
    from PIL import ImageFont
    saved = (card2patch.TITLE, card2patch.SUB, card2patch.LINES_TEXT, card2patch.URL)
    card2patch.TITLE, card2patch.SUB, card2patch.LINES_TEXT, card2patch.URL = TITLE, SUB, LINES_TEXT, URL
    orig = ImageFont.truetype
    def tt(name, size, *a, **k):
        if name == "impact.ttf" and size == 20: size = 16
        return orig(name, size, *a, **k)
    ImageFont.truetype = tt
    try:
        return card2patch.render()
    finally:
        ImageFont.truetype = orig
        card2patch.TITLE, card2patch.SUB, card2patch.LINES_TEXT, card2patch.URL = saved


def disc_patches(exe, read=disc_file):
    """exe = the stock SLUS_007.93 bytes -> [(file offset, bytes)]: header pc0, card 1, card 2 picture + stub"""
    off = lambda a: a - EXE_BASE + EXE_HDR
    assert struct.unpack_from("<I", exe, 0x10)[0] == ENTRY
    assert not any(exe[off(ZERO[0]):off(ZERO[1])]), "the executable is not zero where the cards go"
    assert ZERO[0] <= LOGO_AT and STUB_END <= ZERO[1]
    c1 = card1()
    k = c1.find(card2patch._la_t7(ENTRY))
    assert k >= 0 and k % 4 == 0 and c1.find(card2patch._la_t7(ENTRY), k + 4) < 0, "card 1: jump to the entry not found"
    c1 = c1[:k] + card2patch._la_t7(STUB_AT) + c1[k + 8:]
    for n, h in SHA1.items():
        got = hashlib.sha1(read(n)).hexdigest()
        assert not h or got == h, f"card 2: {n} is not the stock US file (sha1 {got})"
    img = compose(read).astype("<u2").tobytes()
    return [(0x10, struct.pack("<I", LOGO_AT)), (off(LOGO_AT), c1), (off(IMG_AT), img), (off(STUB_AT), card2_stub())]


def ram_ranges():
    """RAM ranges the cards occupy in the EXE image (for the builder's overlap check)"""
    return [(LOGO_AT, IMG_AT), (IMG_AT, STUB_END)]


def preview():
    import numpy as np
    from PIL import Image
    out = os.path.join(GAME, "work", "v10"); os.makedirs(out, exist_ok=True)
    img = compose()
    rgb = np.dstack([(img & 31) << 3, (img >> 5 & 31) << 3, (img >> 10 & 31) << 3]).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(os.path.join(out, "card2_msh.png"))
    Image.fromarray(rgb, "RGB").resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(out, "card2_msh_2x.png"))
    print(os.path.join(out, "card2_msh_2x.png"))


if __name__ == "__main__":
    if sys.argv[1:] == ["render"]:
        b = render(); open(DATA, "wb").write(b); print(DATA)
    if sys.argv[1:] == ["preview"]:
        preview()
