"""START skips the end of a match - X-Men vs. Street Fighter (SLUS-00627), 1.3 (default on, mktagdisc --noskip).

Like stock MvC: after a match is decided, START (a new press on a human player's pad) skips the win pose and the
win-quote screen; the game goes on to the next opponent grid / VS screen and the battle loading.

How the stock game runs the end of a match (work/skip, docs/ENGINE_NOTES.md "START skip"):
  scene word 0x80042774 (dispatch 0x80075ac8, table 0x8009487c[scene/4]): 8 battle, 12 after-match (0x80086fc4),
  0x10 continue, 4 select/grid, 0x1c ending, 0x20 versus end.  Sub words 0x80042776 / 0x80042778.
  Battle phases (match struct 0x80042348: +0 phase, +5 result, +6 u16 timer): 10 KO display (waits for both sides
  to settle), 12 0x80082ce4 (130-frame wait, then the win poses), 14 0x80082de8 (win pose timer; survival mode:
  life refill), 16 0x8008303c (round / match bookkeeping), 18 0x80083174 (-> scene 12, or 0x1c after the last boss,
  or 0x20 in versus).
  Scene 12 win branch: loads SELECT.BIN (NOW LOADING), then 0x800986ac (overlay) runs the quote: sub 0x2776 = 2 and
  0x2778 = 0 (wait), 2, 4 (portrait slide), 6 (quote, 300 frames), 8 (exit: 0x800851e8 = grid, or 0x10 when no
  human is left).  The loss branch never shows a quote (-> 0x10 continue).

What the hook does (each frame, before the game's per-frame dispatch 0x80028dc8; only in arcade and versus,
0x8004218c = 1 / 2, and only for pads whose bit is set in the human mask 0x80042771):
  * battle, phase >= 10 and the match decided (+5 != 0): a START press latches.  While latched, phase 12 and 14
    timers are zeroed (the win poses are cut; phase 16/18 bookkeeping runs as usual).  Pause is phase 8 only.
  * scene 12: a press (or the latch) sets the quote's sub-state to 8: the overlay's own exit runs (grid / continue
    decisions untouched).
  * any other scene: the latch is cleared.
The attract demo runs with 0x800421ad = 3 (the hook is on the 0x800421ad = 1 path) and no humans.

Code: kernel RAM 0x80007e00-0x80008000 (BIOS-unused, see docs/ACHIEVEMENTS.md / games/mvc/docs/CODESPACE.md: zero in
all dumps, 4 BIOS images, fill tests; 0x80007600-0x80008400 is used only by MvC's --ach), copied at boot by a stub
in the EXE image's zero area (0x800bfc00), which chains to the previous pc0.  Hook: 0x80028648 `jal 0x80028dc8`.
"""
import hashlib, os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                              # tools/mipsasm.py, toolenv.py
from mipsasm import Asm, REG
REG.setdefault("$s6", 22); REG.setdefault("$s7", 23)

BASE, LIMIT = 0x80007a00, 0x80008000            # kernel RAM (code + BSS; the boot copy zeroes the rest)
BASE_BAL = 0x80007880                           # with ARCADE BALANCE (1.3 default, docs/BALANCE.md): + option code.  The XvSF
                                                # achievements span 0x80007600-0x80007a00 ends here instead (tools/ach/xvach.py)
COPY_AT, COPY_END = 0x800bf800, 0x800c0000      # zero in the EXE image (ach's copy uses 0x800a0000..)
HOOK_AT, HOOK_ORIG = 0x80028648, 0x0C00A372     # jal 0x80028dc8 (game proper, 0x800421ad == 1)
FREE_AT, FREE_SHA1 = 0x80083618, "28c3de92b8b57bae6f99c71b1b0b5565d5d4d1c9"   # free-move after the KO: START bits 0x800428d9 -> our SELECT bits (the stock lui / lbu pair, checked by SHA-1: no game words in this file)
EXE_BASE, EXE_HDR = 0x80010000, 0x800
SRC = os.path.join(HERE, "skip", "xvskip.c")
SRC_DIAG = os.path.join(HERE, "skip", "kdiag.c")     # diagnostic build (mktagdisc --kdiag): kernel RAM map instead of the skip
KDIAG = "--kdiag" in sys.argv
OBJ = os.path.join(HERE, "skip", "obj")
NOTICE = dict(NOTICE_X=130, NOTICE_Y=0xd2, NOTICE_COL=0x10, NOTICE_MODE=1, NOTICE_T10=0x104)   # centred (x 254 - 4 * 31); picture y 201-208: under the WIN text (ends at 195), above the gauge bar; palette 0x10 (yellow, transparent background: 0x3a drew an opaque black cell; no green in the font CLUTs)


def _jal(t): return 0x0C000000 | ((t >> 2) & 0x03FFFFFF)


def build_c(arcbal=False):
    """compile tools/skip/xvskip.c at BASE (BASE_BAL with the ARCADE BALANCE option) -> (image bytes, symbols)"""
    arcbal = arcbal and not KDIAG
    base = BASE_BAL if arcbal else BASE
    import toolenv
    gcc = toolenv.mips_prefix()
    os.makedirs(OBJ, exist_ok=True)
    ld = os.path.join(OBJ, "skip.ld")
    open(ld, "w").write("SECTIONS { . = 0x%08x; .text : { *(.text.skip_entry) *(.text*) } .rodata : { *(.rodata*) } "
                        ".data : { *(.data*) *(.sdata*) } .bss : { *(.bss*) *(.sbss*) *(COMMON) } /DISCARD/ : { *(.comment) *(.MIPS.*) *(.reginfo) *(.pdr) *(.gnu.attributes) } } __base = 0x%08x;" % (base, base))
    defs = ["-D%s=%d" % kv for kv in NOTICE.items()] + (["-DARCBAL"] if arcbal else [])
    subprocess.check_call([gcc + "gcc", "-Os", "-G0", "-mips1", "-mno-abicalls", "-fno-pic", "-ffreestanding", "-nostdlib",
                           "-ffunction-sections", "-msoft-float", "-c", SRC_DIAG if KDIAG else SRC, "-o", os.path.join(OBJ, "xvskip.o")] + defs)
    subprocess.check_call([gcc + "ld", "-T", ld, "-o", os.path.join(OBJ, "xvskip.elf"), os.path.join(OBJ, "xvskip.o")])
    subprocess.check_call([gcc + "objcopy", "-O", "binary", "-R", ".bss", os.path.join(OBJ, "xvskip.elf"), os.path.join(OBJ, "xvskip.bin")])
    img = open(os.path.join(OBJ, "xvskip.bin"), "rb").read()
    sym = {}
    for l in subprocess.check_output([gcc + "nm", os.path.join(OBJ, "xvskip.elf")]).decode().splitlines():
        q = l.split()
        if len(q) == 3: sym[q[2]] = int(q[0], 16) & 0xffffffff
    end = max(v for k, v in sym.items() if k in ("V", "D", "arcbal")) + 64
    assert sym["skip_entry"] == base, "entry not first"
    assert base + len(img) <= LIMIT and end <= LIMIT, "skip code too big"
    return img + bytes((-len(img)) % 4), sym


def copy_stub(prev_pc0, code, call=None, base=BASE):
    """boot copy: code -> BASE (whole 0x200 area, vars zeroed), FlushCache, jump to prev_pc0; sp/gp/a0/a1 kept"""
    blob = code + bytes(LIMIT - base - len(code))
    a = Asm(COPY_AT)
    a.lui("$t0", 0); a.ori("$t0", "$t0", 0)       # patched below (la t0, blob)
    a.lui("$t1", base >> 16)
    a.ori("$t1", "$t1", base & 0xffff)
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
    a.addiu("$t2", "$zero", 0xa0)                 # FlushCache
    a.jalr("$t2")
    a.addiu("$t1", "$zero", 0x44)
    if call:
        a.jal(call)                               # (diagnostic build) kdiag_boot
        a.nop()
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


def code(arcbal=False):
    """our code only, independent of the image (prebaked by the release builder; link() puts the previous pc0 in): -> dict(copy=(addr, bytes), hooks=[(addr, bytes)], ram=(addr, bytes))
    arcbal: + the ARCADE BALANCE option (tools/arcbalpatch.py): the two gate patches join the hooks, and
    bal = dict(flag, draw, input) is what the OPDEMO.BIN patch needs."""
    arcbal = arcbal and not KDIAG
    base = BASE_BAL if arcbal else BASE
    c, sym = build_c(arcbal)
    cp = copy_stub(0, c, sym.get("kdiag_boot"), base)
    assert COPY_AT + len(cp) <= COPY_END
    sel = sym.get("V", 0) + 2                                              # V.sel (not in the diagnostic build)
    free = struct.pack("<2I", 0x3C020000 | ((sel + 0x8000) >> 16), 0x90420000 | (sel & 0xffff))
    hooks = [(HOOK_AT, struct.pack("<I", _jal(base)))] + ([] if KDIAG else [(FREE_AT, free)])
    out = dict(copy=(COPY_AT, cp), hooks=hooks, ram=(base, c + bytes(LIMIT - base - len(c))), size=len(c), base=base)
    if arcbal:
        import arcbalpatch
        out["hooks"] = hooks + arcbalpatch.gate_patches(sym["arcbal"])
        out["bal"] = dict(flag=sym["arcbal"], draw=sym["bal_optdraw"], input=sym["bal_optinput"])
    return out


def apply(exe_read, exe_write, arcbal=False):
    """mktagdisc: checks the hook words and the zero copy area, writes the stub + hooks, chains the header's pc0.
    arcbal: also the ARCADE BALANCE gates (checked by arcbalpatch.check_gates); returns the code() result"""
    assert struct.unpack("<I", exe_read(HOOK_AT, 4))[0] == HOOK_ORIG, "START skip: unexpected word at %08x" % HOOK_AT
    assert hashlib.sha1(exe_read(FREE_AT, 8)).hexdigest() == FREE_SHA1, "START skip: unexpected words at %08x" % FREE_AT
    prev_pc0 = struct.unpack("<I", exe_read(EXE_BASE - EXE_HDR + 0x10, 4))[0]
    c = link(code(arcbal=arcbal), prev_pc0)
    if "bal" in c:
        import arcbalpatch
        arcbalpatch.check_gates(exe_read)
    at, cp = c["copy"]
    assert exe_read(at, len(cp)) == bytes(len(cp)), "START skip: copy area not zero"
    exe_write(at, cp)
    for a, d in c["hooks"]: exe_write(a, d)
    exe_write(EXE_BASE - EXE_HDR + 0x10, struct.pack("<I", COPY_AT))
    print("START skip: code %08x (%d bytes), copy %08x (%d bytes), hooks %08x %08x, pc0 -> %08x (was %08x)" % (
        c["base"], c["size"], at, len(cp), HOOK_AT, FREE_AT, COPY_AT, prev_pc0))
    return c


def apply_ram(emu):
    """harness: the code + the hooks into a running emulator (no copy stub)"""
    c = code()
    emu.poke(*c["ram"])
    for a, d in c["hooks"]: emu.poke(a, d)


if __name__ == "__main__":
    c, sym = build_c()
    print("%d bytes" % len(c), {k: hex(v) for k, v in sym.items() if not k.startswith(".")})


def link(code_result, prev_pc0):
    """the boot copy's last jump -> prev_pc0 (a plain j word; no assembling)"""
    at, cp = code_result["copy"]
    i = cp.index(struct.pack("<I", 0x08000000))                  # j 0 (placeholder), the stub's only one
    cp = cp[:i] + struct.pack("<I", 0x08000000 | ((prev_pc0 >> 2) & 0x03FFFFFF)) + cp[i + 4:]
    return dict(code_result, copy=(at, cp))
