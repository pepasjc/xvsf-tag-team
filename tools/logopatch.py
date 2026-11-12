"""The "PEPA SOFT HOUSE" boot card:  python tools/mktagdisc.py NAME --logo      (also tools/mkap8disc.py ... --logo)

Off by default, so the reference images stay reproducible.  Same card and same method as the user's other PS1
hacks (Snatcher: ps1/tools/bootcard.py): the card is drawn by a bare-metal stub that runs at the executable's
entry point - after the BIOS license screen, before any game code - and then jumps to the original entry.

Why this way and not a separate boot EXE behind SYSTEM.CNF: nothing on the disc moves and no file is added
(no directory change, no extra BIOS LoadExec with its own stack/argument/event state, nothing new at the end of
the disc); the game's executable is loaded by the BIOS exactly as before - same file, same position, same size,
same load address and stack - and only its entry point differs.

    PS-EXE header 0x10 (pc0): 0x800108fc -> LOGO_AT
    LOGO_AT (0x800e8000, file offset 0xd8800): stub + card, 1 bit per pixel, 320 x 240
        The executable image is all zeros from 0x80099000 to 0x800f0000 (the run-time heap; checked here), so the
        stub needs no dead-code range and the file does not grow.  Its last act is to zero itself and the bitmap
        again (from a copy of 7 instructions at 0x801ff000, below the stack top) and to clear the VRAM, so the game
        starts with the memory image and a black screen as on the original disc.
    The stub uses only t0-t9; it makes no BIOS call and leaves the interrupt, event, CD and SPU state alone.
    GPU: reset + 320x240; at the end the VRAM is black and the display on (black picture); timer 1 mode back to 0.  Hold = HOLD_S seconds
    counted in h-blanks on free-running timer 1 (the mode that held correctly on the MiSTer in the other hacks).

    python tools/logopatch.py preview      -> build/logo_preview.png  (from tools/logo/card.bin)
    python tools/logopatch.py render       draw the card again with the fonts below (Windows: Impact, Arial Bold) and
                                           write tools/logo/card.bin; the build itself only reads that file
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import toolenv
GCC = toolenv.mips_prefix()
CARD = os.path.join(HERE, "logo", "card.bin")       # the card, 320 x 240, 1 bit per pixel (our own art, made by render())
OBJ = os.path.join(ROOT, "build", "logoobj")
EXE_BASE, EXE_HDR = 0x80010000, 0x800
LOGO_AT = 0x800e8000
ZERO = (0x80099000, 0x800f0000)          # all zeros in the stock executable image
ENTRY = 0x800108fc
W, H = 320, 240
HOLD_S, ROUNDS = 2.6, 2
HBLANKS = int(HOLD_S / ROUNDS * 15734)   # NTSC line rate; each round below 32768 (sltiu)
assert HBLANKS < 0x8000
TITLE = "PEPA SOFT HOUSE"
SUB = "X-MEN VS. STREET FIGHTER  ·  TAG HACK 1.0"
FONT, SUBFONT = ("impact.ttf", 26), ("arialbd.ttf", 11)


def card(sub=SUB):
    """the card of the other projects (their splash.card()): black title between two bars on white, small grey line below"""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(*FONT)
    bb = d.textbbox((0, 0), TITLE, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    cx, cy = W // 2, H // 2 - 6
    bar_w = tw + 24
    d.rectangle([cx - bar_w // 2, cy - th // 2 - 14, cx + bar_w // 2, cy - th // 2 - 10], fill=(0, 0, 0))
    d.rectangle([cx - bar_w // 2, cy + th // 2 + 10, cx + bar_w // 2, cy + th // 2 + 14], fill=(0, 0, 0))
    d.text((cx - tw // 2 - bb[0], cy - th // 2 - bb[1]), TITLE, font=f, fill=(0, 0, 0))
    if sub:
        fs = ImageFont.truetype(*SUBFONT)
        sb = d.textbbox((0, 0), sub, font=fs)
        d.text((cx - (sb[2] - sb[0]) // 2 - sb[0], cy + th // 2 + 22 - sb[1]), sub, font=fs, fill=(90, 90, 90))
    return im


def card_bits(sub=SUB):
    """the card the build uses: tools/logo/card.bin (rendered with other text only on request)"""
    if sub == SUB: return open(CARD, "rb").read()
    return render_bits(sub)


def render_bits(sub=SUB):
    """draw the card: 1 bit per pixel, rows top to bottom, MSB first, 1 = ink (needs the fonts)"""
    px = card(sub).convert("L").load()
    out = bytearray()
    for y in range(H):
        acc = 0
        for x in range(W):
            acc = (acc << 1) | (1 if px[x, y] < 128 else 0)
            if x % 8 == 7: out.append(acc); acc = 0
    return bytes(out)


def build(sub=SUB):
    os.makedirs(OBJ, exist_ok=True)
    bits = card_bits(sub)
    open(os.path.join(OBJ, "card.bin"), "wb").write(bits)
    subprocess.check_call([GCC + "gcc", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", f"-DENTRY=0x{ENTRY:08x}", f"-DDATA_LEN={len(bits)}", f"-DHBLANKS={HBLANKS}", f"-DROUNDS={ROUNDS}",
                           "-c", os.path.join(HERE, "logo", "logo.S"), "-o", "logo.o"], cwd=OBJ)
    open(os.path.join(OBJ, "logo.ld"), "w").write(f"SECTIONS {{\n  .logo 0x{LOGO_AT:08x} : {{ *(.logo) }}\n"
                                                  "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) *(.bss) *(.text) *(.data) }\n}\n")
    subprocess.check_call([GCC + "ld", "-T", "logo.ld", "logo.o", "-o", "logo.elf"], cwd=OBJ)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".logo", "logo.elf", "logo.bin"], cwd=OBJ)
    blob = open(os.path.join(OBJ, "logo.bin"), "rb").read()
    assert ZERO[0] <= LOGO_AT and LOGO_AT + len(blob) <= ZERO[1] and len(blob) % 4 == 0
    return blob


def apply(exe_read, exe_write, orig_exe, sub=None):
    """exe_read / exe_write as in mktagdisc.main (they address the executable on the disc image by RAM address)"""
    blob = build(SUB if sub is None else sub)
    z = orig_exe[ZERO[0] - EXE_BASE + EXE_HDR:ZERO[1] - EXE_BASE + EXE_HDR]
    assert not any(z), "the executable is not zero where the card goes"
    assert struct.unpack_from("<I", orig_exe, 0x10)[0] == ENTRY and exe_read(LOGO_AT, len(blob)) == bytes(len(blob))
    exe_write(LOGO_AT, blob)
    exe_write(EXE_BASE - EXE_HDR + 0x10, struct.pack("<I", LOGO_AT))     # header field pc0
    print(f"logo: stub + card {len(blob)} bytes at {LOGO_AT:08x}, entry {ENTRY:08x} -> {LOGO_AT:08x}, hold {HOLD_S} s")


if __name__ == "__main__":
    if sys.argv[1:] == ["render"]:
        b = render_bits(); same = os.path.exists(CARD) and open(CARD, "rb").read() == b
        open(CARD, "wb").write(b); print("tools/logo/card.bin:", "unchanged" if same else "REWRITTEN (the --logo images change)")
    if sys.argv[1:] == ["preview"]:
        from PIL import Image
        Image.frombytes("1", (W, H), bytes(b ^ 0xFF for b in card_bits())).save(os.path.join(ROOT, "build", "logo_preview.png"))
        print("build/logo_preview.png")
