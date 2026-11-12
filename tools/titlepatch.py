"""Optional version line on the main menu of the 2 MB build:  python tools/mktagdisc.py NAME --title["=TAG HACK 1.0.1"]

Not part of the default build (build/xvsf_tag23 stays as it is).  The 8 MB build (tools/mkap8disc.py) has its
own, larger hook in the same place, which also shows "8MB" when the upper memory and its module are usable.

    EXE   0x80054704  (dead range, break-tested with work/ap8/deadtest8.py)   menuhook(): one call of the game's
                      text routine 0x8002d79c(text, x, y, 8, colour 0x30, 1) + the string
    P/P4/OPDEMO.BIN  0x800987b8  `jr ra` at the end of the main-menu text routine 0x80098728  ->  `j menuhook`
                      (the routine has restored ra and sp there, so menuhook returns to its caller)
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import toolenv
GCC = toolenv.mips_prefix()
RANGE = (0x80054704, 0x800547d4)
MENU_AT, MENU_FILE, OVL_BASE = 0x800987b8, "P/P4/OPDEMO.BIN", 0x80098000
DEFAULT = "TAG HACK 1.0.1"


def build(text):
    obj = os.path.join(ROOT, "build", "titleobj"); os.makedirs(obj, exist_ok=True)
    assert text and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-" for c in text) and len(text) <= 40, "title text: capitals, digits, space, dot, dash; 40 at most"
    subprocess.check_call([GCC + "gcc", "-Os", "-ffreestanding", "-msoft-float", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", "-DTITLE_ONLY", f'-DVERSION="{text}"',
                           "-c", os.path.join(HERE, "ap8", "ap8boot.c"), "-o", os.path.join(obj, "title.o")])
    open(os.path.join(obj, "title.ld"), "w").write(f"SECTIONS {{\n  .chunkl 0x{RANGE[0]:08x} : {{ *(.chunkl) *(.rodata*) }}\n"
                                                   "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) *(.bss) }\n}\n")
    subprocess.check_call([GCC + "ld", "-T", "title.ld", "title.o", "-o", "title.elf"], cwd=obj)
    subprocess.check_call([GCC + "objcopy", "-O", "binary", "-j", ".chunkl", "title.elf", "title.bin"], cwd=obj)
    code = open(os.path.join(obj, "title.bin"), "rb").read()
    assert RANGE[0] + len(code) <= RANGE[1]
    sym = {l.split()[2]: int(l.split()[0], 16) & 0xFFFFFFFF for l in subprocess.check_output([GCC + "nm", "title.elf"], cwd=obj).decode().splitlines() if len(l.split()) == 3}
    return code, sym["menuhook"]


def apply(f, lmap, exe_read, exe_write, orig_exe, touched, text):
    """f: the image opened r+b; exe_read/exe_write as in mktagdisc.main; touched: set of sectors to re-seal"""
    code, hook = build(text or DEFAULT)
    o = RANGE[0] - 0x80010000 + 0x800
    assert exe_read(RANGE[0], RANGE[1] - RANGE[0]) == orig_exe[o:o + RANGE[1] - RANGE[0]], "title range is not the original code"
    exe_write(RANGE[0], code)
    o = MENU_AT - OVL_BASE; l = lmap[MENU_FILE][0] + o // 2048
    f.seek(l * 2352 + 24 + o % 2048); assert f.read(4) == struct.pack("<I", 0x03e00008), "OPDEMO.BIN: unexpected code at the menu hook"
    f.seek(l * 2352 + 24 + o % 2048); f.write(struct.pack("<I", 0x08000000 | (hook >> 2 & 0x3ffffff))); touched.add(l)
    print(f"title patch: \"{text or DEFAULT}\", exe {RANGE[0]:08x}-{RANGE[0] + len(code):08x}, OPDEMO.BIN {MENU_AT:08x} -> j {hook:08x}")
