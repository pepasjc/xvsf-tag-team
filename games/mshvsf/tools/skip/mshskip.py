"""START skips the end of a match - Marvel Super Heroes vs. Street Fighter (SLUS-00793), 1.0 (default on,
mktag.py --noskip).

Like stock MvC: after a match is decided, START (a new press on a human player's pad) cuts the win pose and the
bonus tally short and skips the win-quote screen with its loading; the game goes straight to the map (next
opponent, its own loading) and the next fight.

Stock flow (games/mshvsf/work/skip; docs/ENGINE_NOTES.md "START skip"):
  scene s16 0x80070a94 (dispatch jalr 0x800515d0, table 0x8006ae64[scene/4]): 8 battle, 12 after-match
  (0x800581a0), 4 map / select, 0x10 continue / game over.  Mode 0x800250ac: 0 arcade, 1 versus.
  Battle phases (0x80070778: +0 phase, +5 result, +6 s16 timer): 10 K.O. display, 12 win pose ("WIN"), 14
  PERFECT + VITAL/TIME/BONUS tally (computed at timer 0x3b, added to the score at 0x36), 16, 18 -> scene 12
  (arcade) or 4 (versus).
  Scene 12, win branch (0x80025070 == 0): sub 0x80071ad2 = 0 loads the quote overlay and the winner's portrait
  (NOW LOADING, ~590 frames); sub 1 runs the overlay (0x8009815c, its state 0x80070a96, exit state 0x0e =
  0x80098694: 0x800850d4, +0x38 of the match struct = 0, 0x80070aaf = 3, human flags of the two player objects
  from 0x80070a91, then 0x8004d60c = scene 4 (map)).

What the hook does (each frame, wrapping the scene dispatch; arcade and versus only; pads whose bit is set in
the human mask 0x80070a91):
  * battle, phase >= 10, match decided (+5 != 0): a START press latches; while latched phase 12's timer is
    zeroed, phase 14's once the bonus is in the score (timer < 0x35; the tally object keeps its own clock, so the
    PERFECT / tally display stays ~65 frames).
  * scene 12 win branch, latched or pressed: on its first frame (sub 0, before the loading) the quote overlay's
    exit is done here (same stores and calls, then 0x8004d60c) and the frame's dispatch is skipped; while the
    quote overlay runs (sub 1) its state is set to the exit state.
  * anything else clears the latch.  Pause is battle phase 8 only; the attract demo has no humans.

Code: kernel RAM 0x80007e00-0x80008000 (BIOS-unused; see games/mvc/docs/CODESPACE.md), copied at boot by a stub
in the EXE image's zero area 0x8014fc00 (achievements' copy uses 0x80140000..), chained to the previous pc0.
"""
import os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "..", "..", "..", "..", "tools"), os.path.join(HERE, "..", "..", "tools"), os.path.join(HERE, "..")):
    if os.path.exists(os.path.join(_p, "mipsasm.py")):
        sys.path.insert(0, os.path.abspath(_p)); break
from mipsasm import Asm, REG
REG.setdefault("$s6", 22); REG.setdefault("$s7", 23)

BASE, LIMIT = 0x80007cc0, 0x80008000            # kernel RAM (code + BSS; the boot copy zeroes the rest); achievements use 0x80007620-0x80007cc0
COPY_AT, COPY_END = 0x8014f800, 0x80150000
HOOK_AT, HOOK_ORIG = 0x800515d0, 0x0040F809      # jalr v0 (scene handler)
EXE_BASE, EXE_HDR = 0x80010000, 0x800
SRC = os.path.join(HERE, "mshskip.c")
OBJ = os.path.join(HERE, "obj")
NOTICE = dict(NOTICE_X=131, NOTICE_Y=0xcc, NOTICE_COL=0x26, VCOUNT_ADDR=0x8001d210)   # centred (255 - 4 * 31), picture y ~199 above the gauges (MvC ~200); blue (no green in the font CLUTs); vblank counter


def _jal(t): return 0x0C000000 | ((t >> 2) & 0x03FFFFFF)


def build_c():
    """compile mshskip.c at BASE -> (image bytes, symbols)"""
    import toolenv
    gcc = toolenv.mips_prefix()
    os.makedirs(OBJ, exist_ok=True)
    ld = os.path.join(OBJ, "skip.ld")
    open(ld, "w").write("SECTIONS { . = 0x%08x; .text : { *(.text.skip_entry) *(.text*) } .rodata : { *(.rodata*) } "
                        ".data : { *(.data*) *(.sdata*) } .bss : { *(.bss*) *(.sbss*) *(COMMON) } /DISCARD/ : { *(.comment) *(.MIPS.*) *(.reginfo) *(.pdr) *(.gnu.attributes) } }" % BASE)
    defs = ["-D%s=%d" % kv for kv in NOTICE.items()] + (["-DCYBERFIX"] if "--cyberfix" in sys.argv else [])   # 1.1: final-boss bench fix
    subprocess.check_call([gcc + "gcc", "-Os", "-G0", "-mips1", "-mno-abicalls", "-fno-pic", "-ffreestanding", "-nostdlib",
                           "-ffunction-sections", "-msoft-float", "-c", SRC, "-o", os.path.join(OBJ, "mshskip.o")] + defs)
    subprocess.check_call([gcc + "ld", "-T", ld, "-o", os.path.join(OBJ, "mshskip.elf"), os.path.join(OBJ, "mshskip.o")])
    subprocess.check_call([gcc + "objcopy", "-O", "binary", "-R", ".bss", os.path.join(OBJ, "mshskip.elf"), os.path.join(OBJ, "mshskip.bin")])
    img = open(os.path.join(OBJ, "mshskip.bin"), "rb").read()
    sym = {}
    for l in subprocess.check_output([gcc + "nm", os.path.join(OBJ, "mshskip.elf")]).decode().splitlines():
        q = l.split()
        if len(q) == 3: sym[q[2]] = int(q[0], 16) & 0xffffffff
    assert sym["skip_entry"] == BASE, "entry not first"
    assert BASE + len(img) <= LIMIT and sym["V"] + 8 <= LIMIT, "skip code too big"
    return img + bytes((-len(img)) % 4), sym


def copy_stub(prev_pc0, code):
    """boot copy: code -> BASE (whole 0x200 area, vars zeroed), FlushCache, jump to prev_pc0; sp/gp/a0/a1 kept"""
    blob = code + bytes(LIMIT - BASE - len(code))
    a = Asm(COPY_AT)
    a.lui("$t0", 0); a.ori("$t0", "$t0", 0)       # la t0, blob (patched below)
    a.lui("$t1", BASE >> 16)
    a.ori("$t1", "$t1", BASE & 0xffff)
    a.lui("$t2", LIMIT >> 16)
    a.ori("$t2", "$t2", LIMIT & 0xffff)
    a.label("loop")
    a.lw("$t3", 0, "$t0")
    a.addiu("$t0", "$t0", 4)
    a.sw("$t3", 0, "$t1")
    a.addiu("$t1", "$t1", 4)
    a.bne("$t1", "$t2", "loop")
    a.nop()
    a.addu("$s7", "$a0", "$zero")
    a.addu("$s6", "$a1", "$zero")
    a.addiu("$t2", "$zero", 0xa0)                # FlushCache
    a.jalr("$t2")
    a.addiu("$t1", "$zero", 0x44)
    a.addu("$a0", "$s7", "$zero")
    a.addu("$a1", "$s6", "$zero")
    a.addu("$s7", "$zero", "$zero")
    a.addu("$s6", "$zero", "$zero")
    a.j(prev_pc0)
    a.nop()
    a.label("blob")
    a.blob(blob)
    out = bytearray(a.assemble())
    src = a.labels()["blob"]
    struct.pack_into("<2I", out, 0, 0x3C080000 | (src >> 16), 0x35080000 | (src & 0xffff))
    return bytes(out)


def code():
    """our code only, independent of the image (prebaked by the release builder; link() puts the previous pc0 in) -> dict(copy=(addr, bytes), hook=(addr, bytes), ram=(addr, bytes))"""
    c, sym = build_c()
    cp = copy_stub(0, c)
    assert COPY_AT + len(cp) <= COPY_END
    return dict(copy=(COPY_AT, cp), hook=(HOOK_AT, struct.pack("<I", _jal(BASE))), ram=(BASE, c + bytes(LIMIT - BASE - len(c))), size=len(c))


def apply_ram(emu):
    """harness: the code + the hook into a running emulator (no copy stub)"""
    c = code()
    emu.poke(*c["ram"]); emu.poke(*c["hook"])


if __name__ == "__main__":
    c, sym = build_c()
    print("%d bytes" % len(c), {k: hex(v) for k, v in sym.items()})


CYFIX_AT = 0x800222cc            # EXE 0x800222cc-0x80022310: an 8 MB-menu chunk (dead in 2 MB builds; CODESPACE.md)


CYFIX2_AT = 0x8004c6e4           # second part: EXE 0x8004c6e4-0x8004c724 (8 MB-menu chunk too)


def cyfix_patch():
    """(1.1 / 1.0.1 hotfix, --cyberfix; 2 MB builds only) after the ARCADE final boss (stage 7) the stock game loads P1
    main's character into the P2 slot at its fixed addresses 0x801448e0.. (to 0x801f81e0) from match phase 16 while the
    battle is still drawn.  The tag layout can put P1's partner there (P1 main is packed first, always below) and the
    tag win pose has it on screen -> its sprites are overwritten while drawn -> VRAM allocator crash (1.0 user report).
    Called every frame by the START skip entry stub (jal after tick):
        if phase >= 16 && mode == ARCADE && stage >= 7 (8 once the boss is beaten): P1 partner active = 0   (even when on point: blank P1 for the
        ~240 frames before the post-boss scene beats a crash)
    Hand-assembled (7 + 13 words), load delays / delay slots checked.  -> [(addr, bytes), (addr, bytes)]"""
    q = [0x3c098007,              # lui   t1, 0x8007
         0x91280778,              # lbu   t0, 0x778(t1)      match phase
         0x3c0b8002,              # lui   t3, 0x8002
         0x816a50ac,              # lb    t2, 0x50ac(t3)     menu mode (0 ARCADE)
         0x912b07c4,              # lbu   t3, 0x7c4(t1)      ARCADE stage
         0x08000000 | (CYFIX2_AT >> 2 & 0x3ffffff),    # j part 2
         0x8d2c1560]              # lw    t4, 0x1560(t1)     (delay) P1 partner +0x250 (character data base)
    r = [0x2d080010,              # sltiu t0, t0, 16
         0x15000009,              # bnez  t0, 9f
         0x256bfff9,              # addiu t3, t3, -7         (delay)
         0x15400007,              # bnez  t2, 9f
         0x3c0d8014,              # lui   t5, 0x8014         (delay)
         0x05600005,              # bltz  t3, 9f             (stage >= 7: the counter is already 8 after the boss win)
         0x35ad48e0,              # ori   t5, t5, 0x48e0     (delay)
         0x00000000,              # nop   (no range test: P1 main is packed first from the region start and ends
         0x00000000,              # nop    below 0x801448e0; the partner always reaches into the load window - team 7,8:
                                  #        base 0x8012afb0, sprites above.  Stock's partner is an inactive assist anyway)
         0x00000000,              # nop
         0xa1201310,              # sb    zero, 0x1310(t1)   P1 partner benched
         0x03e00008,              # 9: jr ra
         0x00000000]              # nop
    assert len(q) * 4 <= 0x80022310 - CYFIX_AT and len(r) * 4 <= 0x8004c724 - CYFIX2_AT
    return [(CYFIX_AT, struct.pack("<%dI" % len(q), *q)), (CYFIX2_AT, struct.pack("<%dI" % len(r), *r))]


def link(code_result, prev_pc0):
    """the boot copy's last jump -> prev_pc0 (a plain j word; no assembling)"""
    at, cp = code_result["copy"]
    i = cp.index(struct.pack("<I", 0x08000000))                  # j 0 (placeholder), the stub's only one
    cp = cp[:i] + struct.pack("<I", 0x08000000 | ((prev_pc0 >> 2) & 0x03FFFFFF)) + cp[i + 4:]
    return dict(code_result, copy=(at, cp))
