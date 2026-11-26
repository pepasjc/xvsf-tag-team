"""Second boot card (fan-patch notice), shown after the "PEPA SOFT HOUSE" card (tools/logopatch.py).

    on with --logo, except with --nospeed (the 1.0.x configuration keeps its one card: 1.0.1 images unchanged)

What it shows: six slanted panels with select-screen portraits (Wolverine, Cyclops, Storm | Ryu, Chun-Li, Akuma),
the title, "a free fan-made patch, not affiliated with or endorsed by Capcom or Marvel", "if you paid for it, you
were scammed" and the project link.  The portraits are NOT in this repository: they are decoded at build time from
the user's own disc (the extracted original files, also for the 8 MB build, whose restored SP_SEL0.NSP lives elsewhere):

    A/A2/SP_SEL0.NSP   sprite part group 286 + c = the select-screen portrait of character c (4bpp tiles, slot 15 transparent)
    P/P4/SELECT.BIN    its CLUTs: 0x19fcc + c * 0xa0 + 0x20 * (part flags & 15)  (SELECT.BIN 0x8009e8f0: 5 CLUTs to slot 0xa0)
    c: 0 Wolverine 1 Cyclops 2 Storm 9 Ryu 11 Chun-Li 15 Akuma (3 Rogue 4 Gambit 5 Sabretooth 6 Juggernaut 7 Magneto
       8 Apocalypse 10 Ken 12 Dhalsim 13 Zangief 14 Bison 16 Charlie 17 Cammy 18 Chun-Li alt)

tools/logo/card2.bin (ours: text and panel shapes, made by `render`, zlib): 320 x 240 bytes panel map (0 = none,
k = panel k), then 320 x 240 u16 overlay (bit 15 = drawn over the panels: text, background, panel borders).
compose() = gradient + portrait inside each panel, overlay on top -> the 15-bit picture (pure Python + numpy).

Memory (all in the executable image's zero area 0x80099000-0x800f0000, which tools/logopatch.py's card also uses):
    IMG_AT  0x800c0000 .. 0x800e5800   the picture, 15-bit, rows top to bottom (153,600 bytes)
    STUB_AT 0x800e5800 .. < 0x800e8000 the stub (tools/logo/card2.S), right below the first card at 0x800e8000
The first card's stub ends with `la $t7, ENTRY; jr` into its wipe routine: apply() points that `la` at STUB_AT
(the recorded logopatch blob stays as it is).  The card 2 stub uploads the picture to VRAM (0,256) while the
screen is black, shows it (display start), holds HOLD_FRAMES frames (START or X on pad 1 skips after SKIP_AFTER),
blacks the VRAM, puts the display start back to (0,0), timer 1 and the pad port back to their reset state, and zeroes
IMG_AT..its own end from a copy of its wipe routine at 0x801ff000 before it jumps to the game's entry point.  Only
t0-t9 are used (no stack, no BIOS call, no interrupt state), as in the first card.

    python tools/card2patch.py render     draw tools/logo/card2.bin again (needs PIL and the fonts: Impact, Arial Bold)
    python tools/card2patch.py preview    work/splash/card2_final.png (+ _2x) from disc/files
"""
import os, struct, subprocess, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import toolenv
GCC = toolenv.mips_prefix()
DATA = os.path.join(HERE, "logo", "card2.bin")              # 1.3 card (with the "Follow me" line)
DATA_12 = os.path.join(HERE, "logo", "card2_12.bin")        # the 1.1 / 1.2 card: --nosound (the 1.1 image) keeps it, unchanged
OBJ = os.path.join(ROOT, "build", "card2obj")
EXE_BASE, EXE_HDR = 0x80010000, 0x800
ZERO = (0x80099000, 0x800f0000)
W, H = 320, 240
IMG_AT, IMG_LEN = 0x800c0000, W * H * 2
STUB_AT, STUB_END = IMG_AT + IMG_LEN, 0x800e8000
LOGO_AT, ENTRY = 0x800e8000, 0x800108fc            # the first card (tools/logopatch.py) and the game's entry point
HOLD_FRAMES, SKIP_AFTER, LINES = 270, 60, 263       # 4.5 s; START / X work after 1 s; h-blanks per NTSC frame
GROUP0, PAL0 = 286, 0x19fcc
XMEN, SF = (0, 1, 2), (9, 11, 15)
FLIP = {2}                                         # Storm looks left in the art: mirrored, she faces the middle
FACE = {0: (136, 50), 1: (60, 30), 2: (170, 42), 9: (128, 52), 11: (106, 38), 15: (112, 62)}   # face point, unflipped portrait
TOP, BOT, SLANT = 8, 106, 14                         # inside the TV-safe area (SwanStation crops 8 lines top and bottom)
PANELS = [(2, 52), (54, 104), (106, 156), (164, 214), (216, 266), (268, 318)]      # bottom edge x0..x1; tops shifted right by SLANT
GRAD = [((20, 40, 120), (6, 10, 40))] * 3 + [((130, 20, 15), (40, 5, 5))] * 3      # top / bottom colour of each panel
TITLE, SUB = "X-MEN VS. STREET FIGHTER", "TAG TEAM HACK"
LINES_TEXT = ["A free fan-made patch. Not affiliated with", "or endorsed by Capcom or Marvel.",
              "This patch is free. If you paid for it,", "you were scammed."]
URL = "github.com/pepasjc/xvsf-tag-team"
FOLLOW = "Follow me @pepasjc"                    # None = the 1.2 card (no follow line, 1.2 spacing)


def polys():
    out = []
    for k, (xl, xr) in enumerate(PANELS):
        tl = xl if k == 0 else xl + SLANT
        tr = xr if k == len(PANELS) - 1 else xr + SLANT
        out.append([(tl, TOP), (tr, TOP), (xr, BOT), (xl, BOT)])
    return out


# ---------------------------------------------------------------- build time: pure Python + numpy
def portrait(files, c):
    """-> (uint16 HxW 15-bit colours, bool HxW opaque) of character c, as the select screen draws it"""
    import numpy as np
    import nsp
    n = nsp.NSP(os.path.join(files, "A", "A2", "SP_SEL0.NSP"))
    sel = open(os.path.join(files, "P", "P4", "SELECT.BIN"), "rb").read()
    g = None
    for i, (start, parts) in enumerate(n.groups()):
        if i == GROUP0 + c: g = parts; break
    boxes = [(p, n.tiles[p.tile]) for p in g]
    for p, t in boxes:
        if t.raw is None: t.raw, t.clen, t.over = nsp.rle_decode(n.sec[2], t.off, t.wb * t.h)
    x0 = min(p.x for p, t in boxes); y0 = min(p.y for p, t in boxes)
    x1 = max(p.x + t.w for p, t in boxes); y1 = max(p.y + t.h for p, t in boxes)
    col = np.zeros((y1 - y0, x1 - x0), np.uint16); op = np.zeros((y1 - y0, x1 - x0), bool)
    for p, t in reversed(boxes):
        px = nsp.tile_pixels(t)
        if p.flags & 0x20: px = px[:, ::-1]
        if p.flags & 0x40: px = px[::-1]
        pal = np.array(struct.unpack_from("<16H", sel, PAL0 + c * 0xa0 + 0x20 * (p.flags & 0xf)), np.uint16) & 0x7fff
        m = px != 15
        sl = (slice(p.y - y0, p.y - y0 + t.h), slice(p.x - x0, p.x - x0 + t.w))
        col[sl][m] = pal[px[m]]; op[sl][m] = True
    return col, op


def _grad(top, bot, h):
    import numpy as np
    a = np.arange(h, dtype=np.float64)[:, None] / (h - 1)
    rgb = np.floor(np.array(top, np.float64)[None] * (1 - a) + np.array(bot, np.float64)[None] * a).astype(np.uint16) >> 3
    return rgb[:, 0] | rgb[:, 1] << 5 | rgb[:, 2] << 10


def layer():
    import numpy as np
    raw = zlib.decompress(open(DATA_12 if "--nosound" in sys.argv else DATA, "rb").read())
    assert len(raw) == W * H * 3
    pmap = np.frombuffer(raw[:W * H], np.uint8).reshape(H, W)
    ov = np.frombuffer(raw[W * H:], "<u2").reshape(H, W)
    return pmap, ov


def compose(files):
    """the picture: uint16 H x W, 15-bit"""
    import numpy as np
    pmap, ov = layer()
    img = np.zeros((H, W), np.uint16)
    for k, c in enumerate(XMEN + SF):
        col, op = portrait(files, c)
        ax, ay = FACE[c]
        if c in FLIP: col, op, ax = col[:, ::-1], op[:, ::-1], col.shape[1] - 1 - ax
        xl, xr = PANELS[k]
        ox, oy = (xl + xr) // 2 + 7 - ax, TOP + 42 - ay           # face point -> panel centre, 42 below the top
        pan = np.repeat(_grad(*GRAD[k], BOT - TOP + 1)[:, None], W, 1)
        full = np.zeros((H, W), np.uint16); full[TOP:BOT + 1] = pan
        y0, x0 = max(oy, 0), max(ox, 0); y1, x1 = min(oy + col.shape[0], H), min(ox + col.shape[1], W)
        sub = (slice(y0 - oy, y1 - oy), slice(x0 - ox, x1 - ox))
        reg = full[y0:y1, x0:x1]; m = op[sub]; reg[m] = col[sub][m]
        sel = pmap == k + 1
        img[sel] = full[sel]
    o = (ov & 0x8000) != 0
    img[o] = ov[o] & 0x7fff
    return img


def build():
    """the stub (tools/logo/card2.S) at STUB_AT; compiled -> recorded in builder/data/toolcache"""
    os.makedirs(OBJ, exist_ok=True)
    subprocess.check_call([GCC + "gcc", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", f"-DENTRY=0x{ENTRY:08x}", f"-DIMG_AT=0x{IMG_AT:08x}",
                           f"-DIMG_WORDS={IMG_LEN // 4}", f"-DHOLD_FRAMES={HOLD_FRAMES}", f"-DSKIP_AFTER={SKIP_AFTER}", f"-DLINES={LINES}",
                           "-c", os.path.join(HERE, "logo", "card2.S"), "-o", "card2.o"], cwd=OBJ)
    open(os.path.join(OBJ, "card2.ld"), "w").write(f"SECTIONS {{\n  .card2 0x{STUB_AT:08x} : {{ *(.card2) }}\n"
                                                   "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) *(.bss) *(.text) *(.data) }\n}\n")
    subprocess.check_call([GCC + "ld", "-T", "card2.ld", "card2.o", "-o", "card2.elf"], cwd=OBJ)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".card2", "card2.elf", "card2.bin"], cwd=OBJ)
    blob = open(os.path.join(OBJ, "card2.bin"), "rb").read()
    assert len(blob) % 4 == 0 and STUB_AT + len(blob) <= STUB_END
    return blob


SHA1 = {"A/A2/SP_SEL0.NSP": "91528d8851100624f8b79277f4af785107a1af72",          # the US disc's files (the 8 MB build has its own
        "P/P4/SELECT.BIN": "f307faecd168c26dd108f0f146cf054457589eea"}           # SP_SEL0 copy elsewhere; these stay stock)


def _la_t7(addr):
    """lui $t7, hi; ori $t7, $t7, lo (gas `la` of a constant, as in the first card's blob at +0x168)"""
    return struct.pack("<II", 0x3c0f0000 | addr >> 16, 0x35ef0000 | addr & 0xffff)


def apply(exe_read, exe_write, orig, files):
    """after logopatch.apply (same exe_read / exe_write); files = the extracted ORIGINAL disc files"""
    import hashlib
    for rel, want in SHA1.items():
        got = hashlib.sha1(open(os.path.join(files, *rel.split("/")), "rb").read()).hexdigest()
        assert got == want, f"card2: {rel} is not the file of the original disc (sha1 {got})"
    z = orig[ZERO[0] - EXE_BASE + EXE_HDR:ZERO[1] - EXE_BASE + EXE_HDR]
    assert not any(z), "the executable is not zero where the card goes"
    assert struct.unpack_from("<I", exe_read(EXE_BASE - EXE_HDR + 0x10, 4))[0] == LOGO_AT, "card2 needs the first card (--logo)"
    blob = build()
    img = compose(files).astype("<u2").tobytes()
    assert exe_read(IMG_AT, IMG_LEN + len(blob)) == bytes(IMG_LEN + len(blob)), "card2 area is not free"
    card1 = exe_read(LOGO_AT, STUB_END - LOGO_AT + 0x2000)
    k = card1.find(_la_t7(ENTRY))
    assert k >= 0 and k % 4 == 0 and card1.find(_la_t7(ENTRY), k + 4) < 0, "card2: the first card's jump to the entry point not found"
    exe_write(IMG_AT, img)
    exe_write(STUB_AT, blob)
    exe_write(LOGO_AT + k, _la_t7(STUB_AT))
    print(f"card2: picture {IMG_LEN} bytes at {IMG_AT:08x}, stub {len(blob)} bytes at {STUB_AT:08x}, first card -> {STUB_AT:08x}, "
          f"hold {HOLD_FRAMES} frames (skip after {SKIP_AFTER})")


# ---------------------------------------------------------------- development: the committed layer and a preview
def render():
    """tools/logo/card2.bin from the fonts (PIL); only our own drawing: text, background, panel shapes and borders"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    F = ImageFont.truetype
    im = Image.new("RGB", (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)
    pm = Image.new("L", (W, H), 0); dp = ImageDraw.Draw(pm)
    bm = Image.new("L", (W, H), 0); db = ImageDraw.Draw(bm)
    for k, p in enumerate(polys()):
        dp.polygon(p, fill=k + 1)
    for p in polys():
        d.line(p + [p[0]], fill=(255, 255, 255), width=2); db.line(p + [p[0]], fill=255, width=2)

    def text_c(y, s, font, fill, shadow=True):
        bb = d.textbbox((0, 0), s, font=font); x = W // 2 - (bb[2] - bb[0]) // 2 - bb[0]
        if shadow:
            for dx, dy in ((1, 1), (2, 2), (1, 2), (2, 1)): d.text((x + dx, y + dy - bb[1]), s, font=font, fill=(0, 0, 0))
        d.text((x, y - bb[1]), s, font=font, fill=fill)
        return bb[3] - bb[1]
    tight = FOLLOW is not None                         # the follow line needs ~13 px: tighter spacing above it
    y = BOT + (5 if tight else 7)
    y += text_c(y, TITLE, F("impact.ttf", 20), (255, 210, 40)) + (2 if tight else 3)
    y += text_c(y, SUB, F("impact.ttf", 15), (240, 50, 40), shadow=False) + (4 if tight else 6)
    f = F("arialbd.ttf", 12)
    for i, s in enumerate(LINES_TEXT):
        y += text_c(y, s, f, (235, 235, 235)) + ((2 if tight else 3) if i != 1 else (4 if tight else 6))
    y += 3 if tight else 4
    y += text_c(y, URL, F("arialbd.ttf", 13), (110, 200, 255))
    if tight:
        y += 2
        y += text_c(y, FOLLOW, F("arialbd.ttf", 11), (255, 210, 40))
    assert y <= H - 12, y                               # last text row above the bottom 8 lines a TV / SwanStation crops
    a = np.asarray(im).astype(np.uint16) >> 3
    c15 = a[..., 0] | a[..., 1] << 5 | a[..., 2] << 10
    pmap = np.asarray(pm).astype(np.uint8)
    opaque = (pmap == 0) | (np.asarray(bm) > 0)
    ov = np.where(opaque, c15 | 0x8000, 0).astype("<u2")
    return zlib.compress(pmap.tobytes() + ov.tobytes(), 9)


def preview(files=None):
    import numpy as np
    from PIL import Image
    img = compose(files or os.path.join(ROOT, "disc", "files"))
    rgb = np.dstack([(img & 31) << 3, (img >> 5 & 31) << 3, (img >> 10 & 31) << 3]).astype(np.uint8)
    out = os.path.join(ROOT, "work", "splash", "card2_final")
    Image.fromarray(rgb, "RGB").save(out + ".png")
    Image.fromarray(rgb, "RGB").resize((W * 2, H * 2), Image.NEAREST).save(out + "_2x.png")
    print(out + ".png")


if __name__ == "__main__":
    if sys.argv[1:] == ["render"]:
        b = render(); same = os.path.exists(DATA) and open(DATA, "rb").read() == b
        open(DATA, "wb").write(b); print("tools/logo/card2.bin:", "unchanged" if same else "REWRITTEN")
    if sys.argv[1:] == ["preview"]:
        preview()
