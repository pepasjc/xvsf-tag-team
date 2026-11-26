"""Boot cards of the MvC tag hack (mktag.py --logo): the "PEPA SOFT HOUSE" card and the fan-patch notice, the same
stubs, title card and text style as XvSF (tools/logopatch.py + tools/logo/logo.S + card.bin, tools/card2patch.py +
tools/logo/card2.S) and MSHvSF (games/mshvsf/tools/logo/mshcards.py); only addresses, art and the title differ.

Both stubs run before any game code (bare metal: no BIOS call, no stack, only t0-t9), then zero themselves and their
data again and jump on.  They live in a part of the executable image that is all zeros in the file (0x800f229e-
0x8014e500: run-time character / heap area), below the --ach core's boot images (0x80140000-):

    LOGO_AT 0x80100000  card 1 stub + 1-bit 320x240 bitmap (~10 KB), 2.6 s
    IMG_AT  0x80110000  card 2 picture, 15-bit 320x240 (153,600 B)
    STUB_AT 0x80135800  card 2 stub; card 1's `la $t7, ENTRY` is pointed here.  4.5 s, START / X skip after 1 s.
    PS-EXE header pc0 (file offset 0x10) -> LOGO_AT; card 2 jumps to the PREVIOUS pc0 (the --ach boot stub
    0x80140000, or the game's entry 0x800106e0).  Both wipe routines run from 0x801ff000 (stack area) at boot only.
Nothing stays resident: after card 2 the EXE image is byte-identical to the file without the cards.

Card 2 art: six slanted panels like XvSF's / MSHvSF's card, Marvel left (blue), Capcom right (red), each with the
character's Cross Over VS-screen portrait drawn from the user's disc at build time (SP_SEL4.DSP group 4 + id, the
"left" set; its CLUT rows in SEL01.ARC, measured on the VS screen: work/logo/vsclut.py; file SHA-1s checked).
Text and panel shapes: tools/logo/mvccard2.bin (ours, `render`).  Nothing derived from the disc is committed.

    disc_patches(exe, read, entry) -> [(EXE file offset, bytes)]   (mktag.py writes them into SLUS_010.59 on the image)
    python mvccards.py render    draw tools/logo/mvccard2.bin (PIL + fonts Impact, Arial Bold)
    python mvccards.py preview   games/mvc/work/logo/card2_mvc.png (+ _2x) and card1_mvc.png
"""
import os, struct, subprocess, sys, zlib, hashlib, json
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "common", "dsp")]
import toolenv, logopatch, card2patch
GCC = toolenv.mips_prefix()
OBJ = os.path.join(GAME, "build", "logoobj")
EXE_BASE, EXE_HDR = 0x80010000, 0x800
ENTRY = 0x800106e0                                         # the game's own entry point (stock pc0)
ZERO = (0x800f229e, 0x8014e500)                            # all zeros in the stock executable image
LOGO_AT = 0x80100000
W, H = 320, 240
IMG_AT, IMG_LEN = 0x80110000, W * H * 2
STUB_AT, STUB_END = IMG_AT + IMG_LEN, 0x80140000           # 0x80140000- = the --ach core's boot images
DATA = os.path.join(HERE, "mvccard2.bin")
DISC = os.path.join(GAME, "disc", "mvc.bin")              # the user's disc (files read by LBA, work/lba_map.json)

# SHA-1 of the stock files the art is taken from (US disc SLUS-01059)
SHA1 = {"SP_SEL4.DSP": "62d655fabd4a60f9d315573ce5f014dcb63ce96d", "SEL01.ARC": "fbbbfaac7e69d9bf541eb40a14f9c23f17b2c2ad"}

TOP, BOT, SLANT = card2patch.TOP, card2patch.BOT, card2patch.SLANT
PANELS = card2patch.PANELS
GRAD = card2patch.GRAD
SEL_GROUP0 = 4                                             # SP_SEL4.DSP group 4 + id = the left-side VS portrait of id
# (character id, CLUT rows in SEL01.ARC (3 x 32 B, part flags & 15), mirrored: faces the middle, face point unmirrored)
CHARS = [(0x07, 0x16c00, False, (60, 58)),                 # Spider-Man
         (0x02, 0x168e0, False, (104, 50)),                # Captain America
         (0x04, 0x179c0, True, (36, 58)),                  # Wolverine
         (0x09, 0x17ce0, True, (104, 42)),                 # Ryu
         (0x10, 0x171a0, True, (90, 60)),                  # Mega Man
         (0x0e, 0x18000, True, (112, 58))]                 # Strider Hiryu
TITLE, SUB = "MARVEL VS. CAPCOM", "TAG TEAM HACK"

# ---- layout 2 (mktag --logo --logo2, 2026-11-21 user feedback "faces not aligned, empty space at the bottom"):
# all six eyes on one line, faces centred in their panels, no panel row below a portrait's bottom edge, panels inset
# with equal side margins, whole composition centred vertically (equal top / bottom margin).  Layout 1 = unchanged.
DATA2 = os.path.join(HERE, "mvccard2b.bin")
TOP2, PH2 = 16, 82                                         # panel row y0, height (BOT2 = TOP2 + PH2)
BOT2 = TOP2 + PH2
EYE2 = 41                                                  # eye line, rows below TOP2
PANELS2 = [(11, 58), (60, 107), (109, 156), (164, 211), (213, 260), (262, 308)]   # 10 px ink margins both sides (2 px borders), centre gap 8
EYES2 = [(58, 55), (94, 55), (111, 66), (60, 43), (70, 61), (57, 57)]   # eye midpoint per portrait (as drawn, flips applied)
NUDGE2 = [(0, 0)] * 6                                      # per-panel (dx, dy) after the eye alignment
LINES_TEXT = card2patch.LINES_TEXT
URL = card2patch.URL


def disc_file(name, disc=DISC):
    lba, size = json.load(open(os.path.join(GAME, "work", "lba_map.json")))[name]
    out = bytearray()
    with open(disc, "rb") as f:
        for i in range((size + 2047) // 2048):
            f.seek((lba + i) * 2352 + 24); out += f.read(2048)
    return bytes(out[:size])


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
    """card 1 = XvSF's stub and title card (tools/logo/card.bin), linked for MvC; its jump goes to card 2"""
    os.makedirs(OBJ, exist_ok=True)
    bits = logopatch.card_bits(logopatch.SUB)
    open(os.path.join(OBJ, "card.bin"), "wb").write(bits)
    blob = _link(os.path.join(ROOT, "tools", "logo", "logo.S"), "logo", LOGO_AT,
                 dict(ENTRY=f"0x{ENTRY:08x}", DATA_LEN=len(bits), HBLANKS=logopatch.HBLANKS, ROUNDS=logopatch.ROUNDS), ".logo")
    assert LOGO_AT + len(blob) <= IMG_AT
    k = blob.find(card2patch._la_t7(ENTRY))
    assert k >= 0 and k % 4 == 0 and blob.find(card2patch._la_t7(ENTRY), k + 4) < 0, "card 1: jump to the entry not found"
    return blob[:k] + card2patch._la_t7(STUB_AT) + blob[k + 8:]


def card2_stub(entry):
    blob = _link(os.path.join(ROOT, "tools", "logo", "card2.S"), "card2", STUB_AT,
                 dict(ENTRY=f"0x{entry:08x}", IMG_AT=f"0x{IMG_AT:08x}", IMG_WORDS=IMG_LEN // 4, HOLD_FRAMES=card2patch.HOLD_FRAMES,
                      SKIP_AFTER=card2patch.SKIP_AFTER, LINES=card2patch.LINES), ".card2")
    assert STUB_AT + len(blob) <= STUB_END
    return blob


# ------------------------------------------------------------------------------------------------ the art
def portrait(c, clut, read=disc_file):
    """-> (uint16 HxW 15-bit, bool HxW opaque): the Cross Over VS portrait of character c, as the game draws it"""
    import numpy as np, dsp
    x = dsp.DSP(read("SP_SEL4.DSP"), name="SP_SEL4.DSP")
    sel = read("SEL01.ARC")
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
        pal = np.array(struct.unpack_from("<16H", sel, clut + 32 * (p.flags & 15)), np.uint16)
        c15 = pal[px]; m = c15 != 0                                     # colour 0 = transparent on the PS1
        sl = (slice(p.y - y0, p.y - y0 + t.h), slice(p.x - x0, p.x - x0 + t.w))
        col[sl][m] = c15[m] & 0x7fff; op[sl][m] = True
    return col, op


def layer(layout=1):
    import numpy as np
    raw = zlib.decompress(open(DATA2 if layout == 2 else DATA, "rb").read())
    pmap = np.frombuffer(raw[:W * H], np.uint8).reshape(H, W)
    ov = np.frombuffer(raw[W * H:], "<u2").reshape(H, W)
    return pmap, ov


def place2(k, shape):
    """layout 2: (ox, oy) of portrait k (flipped as drawn): eye midpoint on the eye line, centred in the panel at that
    height (the panel's centre line leans right by SLANT from bottom to top)"""
    xl, xr = PANELS2[k]; ex, ey = EYES2[k]; dx, dy = NUDGE2[k]
    cx = (xl + xr) / 2 + SLANT * (PH2 - EYE2) / PH2
    return int(round(cx - ex)) + dx, TOP2 + EYE2 - ey + dy


def compose(read=disc_file, layout=1):
    import numpy as np
    pmap, ov = layer(layout)
    img = np.zeros((H, W), np.uint16)
    top, bot = (TOP2, BOT2) if layout == 2 else (TOP, BOT)
    for k, (c, clut, flip, (ax, ay)) in enumerate(CHARS):
        col, op = portrait(c, clut, read)
        if flip: col, op, ax = col[:, ::-1], op[:, ::-1], col.shape[1] - 1 - ax
        if layout == 2:
            ox, oy = place2(k, col.shape)
        else:
            xl, xr = PANELS[k]
            ox, oy = (xl + xr) // 2 + 7 - ax, TOP + 42 - ay              # face point -> panel centre, 42 below the top
        pan = np.repeat(card2patch._grad(*GRAD[k], bot - top + 1)[:, None], W, 1)
        full = np.zeros((H, W), np.uint16); full[top:bot + 1] = pan
        y0, x0 = max(oy, 0), max(ox, 0); y1, x1 = min(oy + col.shape[0], H), min(ox + col.shape[1], W)
        sub = (slice(y0 - oy, y1 - oy), slice(x0 - ox, x1 - ox))
        reg = full[y0:y1, x0:x1]; m = op[sub]; reg[m] = col[sub][m]
        sel = pmap == k + 1
        img[sel] = full[sel]
    o = (ov & 0x8000) != 0
    img[o] = ov[o] & 0x7fff
    return img


def render():
    """mvccard2.bin: our text and panel shapes (card2patch.render with this game's title)"""
    saved = (card2patch.TITLE, card2patch.SUB, card2patch.LINES_TEXT, card2patch.URL)
    card2patch.TITLE, card2patch.SUB, card2patch.LINES_TEXT, card2patch.URL = TITLE, SUB, LINES_TEXT, URL
    try:
        return card2patch.render()
    finally:
        card2patch.TITLE, card2patch.SUB, card2patch.LINES_TEXT, card2patch.URL = saved


def render2():
    """mvccard2b.bin (layout 2): panel shapes + borders of PANELS2 / TOP2..BOT2 and the same text as layout 1, spaced so
    the text block's ink ends as far above the screen bottom as the panel row starts below the top"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    F = ImageFont.truetype
    polys = []
    for k, (xl, xr) in enumerate(PANELS2):
        tl = xl if k == 0 else xl + SLANT
        tr = xr if k == len(PANELS2) - 1 else xr + SLANT
        polys.append([(tl, TOP2), (tr, TOP2), (xr, BOT2), (xl, BOT2)])
    im = Image.new("RGB", (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)
    pm = Image.new("L", (W, H), 0); dp = ImageDraw.Draw(pm)
    bm = Image.new("L", (W, H), 0); db = ImageDraw.Draw(bm)
    for k, p in enumerate(polys): dp.polygon(p, fill=k + 1)
    for p in polys:
        d.line(p + [p[0]], fill=(255, 255, 255), width=2); db.line(p + [p[0]], fill=255, width=2)
    rows = [(TITLE, F("impact.ttf", 20), (255, 210, 40), True), (SUB, F("impact.ttf", 15), (240, 50, 40), False)]
    rows += [(s, F("arialbd.ttf", 12), (235, 235, 235), True) for s in LINES_TEXT]
    rows += [(URL, F("arialbd.ttf", 13), (110, 200, 255), True), (card2patch.FOLLOW, F("arialbd.ttf", 11), (255, 210, 40), True)]
    GAPS = TEXT_GAPS2                                       # gap (px) above each row; [0] = below the panel row
    y = BOT2 + 1
    for (s, font, fill, shadow), g in zip(rows, GAPS):
        y += g
        bb = d.textbbox((0, 0), s, font=font); x = W // 2 - (bb[2] - bb[0]) // 2 - bb[0]
        if shadow:
            for dx, dy in ((1, 1), (2, 2), (1, 2), (2, 1)): d.text((x + dx, y + dy - bb[1]), s, font=font, fill=(0, 0, 0))
        d.text((x, y - bb[1]), s, font=font, fill=fill)
        y += bb[3] - bb[1]
    assert y <= H - 12, y
    a = np.asarray(im).astype(np.uint16) >> 3
    c15 = a[..., 0] | a[..., 1] << 5 | a[..., 2] << 10
    pmap = np.asarray(pm).astype(np.uint8)
    opaque = (pmap == 0) | (np.asarray(bm) > 0)
    ov = np.where(opaque, c15 | 0x8000, 0).astype("<u2")
    return zlib.compress(pmap.tobytes() + ov.tobytes(), 9)


TEXT_GAPS2 = [6, 2, 5, 2, 5, 2, 6, 2]                      # title, sub, 4 lines (pair gap at [4]), url, follow


def disc_patches(exe, read=disc_file, entry=ENTRY, layout=1):
    """exe = SLUS_010.59 as the build left it (pc0 = entry) -> [(file offset, bytes)]: header pc0, card 1, card 2
    picture + stub.  entry = where card 2 continues (the build's previous pc0)."""
    off = lambda a: a - EXE_BASE + EXE_HDR
    assert struct.unpack_from("<I", exe, 0x10)[0] == entry
    assert ZERO[0] <= LOGO_AT and STUB_END <= ZERO[1]
    assert not any(exe[off(LOGO_AT):off(STUB_END)]), "the executable is not zero where the cards go"
    for n, h in SHA1.items():
        got = hashlib.sha1(read(n)).hexdigest()
        assert not h or got == h, f"card 2: {n} is not the stock US file (sha1 {got})"
    img = compose(read, layout).astype("<u2").tobytes()
    return [(0x10, struct.pack("<I", LOGO_AT)), (off(LOGO_AT), card1()), (off(IMG_AT), img), (off(STUB_AT), card2_stub(entry))]


def ram_ranges():
    """RAM ranges the cards occupy in the EXE image (boot only; zero again before the game runs)"""
    return [(LOGO_AT, STUB_END)]


def preview(layout=1):
    import numpy as np
    from PIL import Image
    out = os.path.join(GAME, "work", "logo", *(["logo2"] if layout == 2 else [])); os.makedirs(out, exist_ok=True)
    img = compose(layout=layout)
    rgb = np.dstack([(img & 31) << 3, (img >> 5 & 31) << 3, (img >> 10 & 31) << 3]).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(os.path.join(out, "card2_mvc.png"))
    Image.fromarray(rgb, "RGB").resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(out, "card2_mvc_2x.png"))
    Image.frombytes("1", (W, H), bytes(b ^ 0xFF for b in logopatch.card_bits(logopatch.SUB))).save(os.path.join(out, "card1_mvc.png"))
    print(os.path.join(out, "card2_mvc_2x.png"))


if __name__ == "__main__":
    if sys.argv[1:] == ["render"]:
        b = render(); open(DATA, "wb").write(b); print(DATA)
    if sys.argv[1:] == ["preview"]:
        preview()
    if sys.argv[1:] == ["render2"]:
        b = render2(); open(DATA2, "wb").write(b); print(DATA2)
    if sys.argv[1:] == ["preview2"]:
        preview(2)
