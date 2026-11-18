"""Whole-frame profiler for the XvSF tag hack (SwanStation, 8 MB core: the 2 MB game runs bit-identically with the
8 MB option on - checked with rate8 - and the profiler keeps its code and buffers above 2 MB, so the game's
RAM is untouched apart from a few hook words).

Two instruments, used in separate runs (both need root counter 2, which the game never touches):
  sampler  root counter 2 IRQ every SAMPLE cycles; the handler (slot 6 of the libapi dispatcher table 0x80021010)
           reads the interrupted EPC and RA from the kernel TCB and counts them in histograms at 0x80400000 /
           0x80600000 (index = addr & 0x1ffffc), and samples GPU state (GPUSTAT bit 26 cmd-ready, DMA2 busy).
  wrappers stopwatch wrappers (counter 2 free running at sysclk/8, counter 1 = hblanks for wrap correction) with a
           software stack above 2 MB (stack arguments of the wrapped function stay valid), inclusive AND exclusive
           (time minus wrapped children) cycles per function.

Library use:
    import fprof as F
    e = F.emu(team=(11,3,9,1), stage=10)           # cached state in work/speed/frame/st_*.st
    F.sampler_install(e); r = F.run_phase(e, "super", F.PH["super"]); F.sampler_read(e)
"""
import os, sys, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
os.environ["XV8_RAM"] = "8"
sys.path.insert(0, os.path.join(ROOT, "work", "ap8")); sys.path.insert(0, HERE)
import lib8 as L
from gas import gas
import cfg
WORK = os.path.join(ROOT, "work", "speed", "frame")
CUE = os.path.join(ROOT, "work", "speed", "base", "b101.cue")
P1, P2 = 0x80042a10, 0x80042d58
LOOPC = 0x800421b8
VB = 33868800 / 59.94
HOOK = 0x80300000          # profiler code
SBASE = 0x80300800         # sampler counters
HIST_PC, HIST_RA = 0x80400000, 0x80600000
WCODE, WACC, WSTK = 0x80310000, 0x80380000, 0x80390000
WSTATE = 0x8038f000        # +0 sp, +4 child accumulator

NAMES = {
    0x800285d4: "game logic (mode dispatch)", 0x80028b58: "draw + present", 0x80028994: "layers from index (sprites..)",
    0x80028908: "layers before sprites (BG, next frame)", 0x80028a1c: "DrawSync + one-shot", 0x80028868: "layer dispatch",
    0x8002e6bc: "sprite list", 0x8002e924: "sprite list entry", 0x80059e60: "per-object sprite draw", 0x8001b5b0: "tile decode",
    0x80056340: "quad build", 0x80058d04: "arena alloc", 0x80016718: "LoadImage", 0x80016454: "DrawSync", 0x80016a54: "DrawOTag",
    0x80011960: "VSync", 0x80016ac8: "PutDrawEnv", 0x80016d20: "PutDispEnv", 0x80015a68: "TermPrim", 0x80057be4: "sec0 part parser",
    0x80057f48: "sec1 tile parser", 0x8001b094: "BG layer 1", 0x8001b124: "BG layer 2", 0x8001b1b4: "BG layer 3", 0x8001b244: "BG layer 4",
    0x8004e94c: "sound/XA per frame", 0x80011db8: "IRQ dispatcher (libapi)", 0x8001bce4: "vblank IRQ cb", 0x800145b4: "CD IRQ cb",
    0x800123cc: "DMA IRQ cb", 0x800590c4: "arena flush (DrawSync)", 0x8002d100: "DrawOTag OT A", 0x8002d134: "DrawOTag OT B",
    0x80057ad8: "sprite OT flush", 0x80057a00: "sprite arena swap", 0x8006dfd4: "post-layer work", 0x8002c960: "8002c960",
    0x8002c1a8: "palette/CLUT upload", 0x8002a840: "palette anim (cond.)", 0x80058f84: "80058f84",
    0x80011aa8: "v_wait (VSync wait loop)", 0x80000000: "BIOS ROM/kernel (bcopy, bzero, memcpy)", 0x80018db4: "libgpu DrawSync timeout check",
    0x800187f0: "libgpu _exeque", 0x80018c38: "libgpu DrawSync loop", 0x80018510: "libgpu _addque",
    0x80011cc0: "SetIntrMask (samples deferred from IRQ-masked code)", 0x800158dc: "XVM1 decoder (nspdec)", 0x80015d9c: "nspdec part", 0x80015bac: "nspdec part",
    0x80098e40: "stage-10 BG layer 2 tile loop (STAGEA.BIN)", 0x800993d8: "stage-10 BG layer 3 (STAGEA.BIN)", 0x800996a0: "stage-10 anim object (bcopy)",
    0x800999b8: "stage-10 anim object 2 (bcopy)", 0x8002c554: "CLUT copy (bcopy)", 0x8002eae8: "bzero wrapper", 0x8007693c: "player update",
    0x80033ba0: "object list update", 0x8001b2d4: "stage object hook", 0x80075a48: "battle logic", 0x80028dc8: "logic mode dispatch",
    0x8007d100: "input pattern check", 0x80029a00: "battle frame",
}


def name(a): return NAMES.get(a, "")


# ---------------------------------------------------------------- emulator + scenarios
def emu(team=(11, 3, 9, 1), stage=10, cue=None, tag=None):
    cue = cue or os.environ.get("CUE") or CUE
    key = tag or "st_%s_s%d_%s" % ("_".join(map(str, team)), stage, os.path.splitext(os.path.basename(cue))[0])
    p = os.path.join(WORK, key + ".st")
    if os.path.exists(p):
        e = L.XV(cue); e.step(2); e.restore(open(p, "rb").read()); e.f = 0
        return e
    e = L.boot(cue, list(team), stage)
    e.step(120, '', '')
    open(p, "wb").write(e.state())
    return e


def _qcf(btn, period, fw):
    def g(f):
        k = f % period
        return "down" if k < 3 else "down+" + fw if k < 6 else fw + "+" + btn if k < 10 else ""
    return g
def _hc(btn, period, a, b):
    def g(f):
        k = f % period
        return a if k < 3 else "down+" + a if k < 6 else "down" if k < 9 else "down+" + b if k < 12 else b + "+" + btn if k < 16 else ""
    return g
_seqb = ["square", "", "triangle", "", "r", "", "cross", "", "circle", "", "r2", "", "down+square", "", "down+r", ""]
_mash = lambda f: _seqb[(f // 6) % len(_seqb)]
_none = lambda f: ''
def _dash(fw):
    def g(f):
        k = f % 36
        return fw if k < 3 or 5 <= k < 11 else ""
    return g
# the phase sequence of work/ap8/rate8.py (p1 mode, tag disc): (p1 input, p2 input, meter for P1, pre-moves [(n, p1, p2)])
PH = collections.OrderedDict([
    ("idle", (_none, _none, False, [])),
    ("walking", (lambda f: "right" if (f // 40) % 2 == 0 else "left", _none, False, [])),
    ("normals", (_mash, _none, False, [])),
    ("specials", (_qcf("square", 60, "right"), _none, False, [])),
    ("super", (_qcf("l", 150, "right"), _none, True, [])),
    ("tag", (lambda f: "r+r2" if f % 150 < 4 else "", _none, False, [])),
    ("both_specials", (_qcf("square", 60, "right"), _qcf("square", 60, "left"), False, [])),
    ("both_normals", (_mash, _mash, False, [])),
    ("dashes", (_dash("right"), _dash("left"), False, [])),
    ("hcf_lp_close", (_hc("square", 75, "left", "right"), _none, False, [(70, "right", "")])),
    ("hcb_lk_close", (_hc("cross", 75, "right", "left"), _none, False, [])),
    ("super_far", (_qcf("l", 150, "left"), _none, True, [(120, "left", "")])),
])
ORDER = list(PH)


def run_phase(e, ph, n=300, per_frame=None, after_pre=None):
    """drive one phase for n vblanks; returns dict(loops=[per-60 counts], frames=n)"""
    a, b, meter, pre = PH[ph] if isinstance(ph, str) else ph
    for k, x, y in pre: e.step(k, x, y)
    if after_pre: after_pre(e)
    per, c0, lp = [], e.u32(LOOPC), []
    for f in range(n):
        if meter: e.poke(P1 + 0x228, struct.pack("<H", 3))
        e.poke(P1 + 0x224, struct.pack("<H", 0x90)); e.poke(P2 + 0x224, struct.pack("<H", 0x90))
        l0 = e.u32(LOOPC)
        e.step(1, a(f), b(f))
        lp.append((e.u32(LOOPC) - l0) & 0xffffffff)
        if per_frame: per_frame(e, f)
        if f % 60 == 59:
            c = e.u32(LOOPC); per.append((c - c0) & 0xffffffff); c0 = c
    return dict(loops=per, perframe=lp, frames=n)


def jword(t): return struct.pack("<I", 0x08000000 | (t >> 2 & 0x3ffffff))


# ---------------------------------------------------------------- sampler
SAMPLE = 2477 * 8          # cycles between samples (counter 2 at sysclk/8, target 2477)

SAMPLER_SRC = r"""
handler:
    lui   $t0, 0x8000
    lw    $t0, 0x108($t0)
    lui   $t9, 0x8030
    lw    $t0, 0($t0)
    lw    $t8, 0x7e0($t9)
    lw    $t1, 0x88($t0)
    lw    $t2, 0x84($t0)
    lui   $t5, 0x1f80
    lw    $t6, 0x1814($t5)
    lw    $t7, 0x10a8($t5)
    lui   $t5, 0x0100
    and   $t7, $t7, $t5
    lw    $t5, 0x7d0($t9)
    lui   $t3, 0x3f
    or    $t7, $t7, $t5
    ori   $t3, $t3, 0xfff0
    and   $t4, $t8, $t3
    lui   $t5, 0x8040
    addu  $t4, $t4, $t5
    sw    $t1, 0($t4)
    sw    $t2, 4($t4)
    sw    $t6, 8($t4)
    sw    $t7, 12($t4)
    addiu $t8, $t8, 16
    jr    $ra
    sw    $t8, 0x7e0($t9)
init:
    lui   $t9, 0x8030
    lw    $t8, 0x7f0($t9)
    nop
    bne   $t8, $zero, 1f
    nop
    lui   $t7, 0x1f80
    ori   $t8, $zero, TARGET
    sh    $t8, 0x1128($t7)
    ori   $t8, $zero, 0x258
    sh    $t8, 0x1124($t7)
    lw    $t8, 0x1074($t7)
    nop
    ori   $t8, $t8, 0x40
    sw    $t8, 0x1074($t7)
    ori   $t8, $zero, 1
    sw    $t8, 0x7f0($t9)
    sw    $ra, 0x7f4($t9)
    sw    $a0, 0x7f8($t9)
    ori   $a0, $zero, 2
    move  $a1, $zero
    ori   $t2, $zero, 0xc0
    jalr  $t2
    ori   $t1, $zero, 0xa
    lui   $t9, 0x8030
    lw    $ra, 0x7f4($t9)
    lw    $a0, 0x7f8($t9)
1:  lui   $v0, 0x8002
    lw    $v0, 0xfa4($v0)
    j     0x80011968
    nop
"""


def sampler_install(e, period=SAMPLE):
    code, sy = gas(SAMPLER_SRC, HOOK, dict(TARGET=period // 8))
    assert e.u32(0x80011960) == 0x3c028002, "VSync prologue changed"
    e.poke(HOOK, code); e.poke(HOOK + 0x7e0, bytes(0x60))
    e.poke(0x80021010 + 4 * 6, struct.pack("<I", sy["handler"]))
    m = e.u16(0x8002103c); e.poke(0x8002103c, struct.pack("<H", m | 0x40))
    e.poke(0x80011960, jword(sy["init"]) + bytes(4))
    sampler_clear(e)


# main-loop markers: the sampler stores the last marker passed (low bits of word 3)
MARKS = [(0x80028d88, 0x800285d4, 1, "logic"), (0x80028b94, 0x80028994, 3, "sprites+front layers"), (0x80028b9c, 0x8006dfd4, 4, "8006dfd4/c960"),
         (0x80028bc8, 0x80028a1c, 5, "DrawSync#1 (GPU tail)"), (0x80028bd0, 0x80016454, 6, "DrawSync#2"), (0x80028bd8, 0x80011960, 7, "VSync(0) wait"),
         (0x80028be8, 0x80016d20, 8, "flip (Put*Env)"), (0x80028c00, 0x80057a00, 9, "arena swap"), (0x80028c94, 0x8002c1a8, 10, "CLUT upload"),
         (0x80028d2c, 0x8002a840, 11, "8002a840"), (0x80028d3c, 0x80028908, 12, "BG layers (next frame)"), (0x80028d44, 0x8004e94c, 13, "sound")]
MARKNAME = {m[2]: m[3] for m in MARKS}; MARKNAME[0] = "-"


def markers_install(e):
    src = ""
    for site, tgt, k, nm in MARKS:
        w = e.u32(site)
        if w >> 26 != 3: continue                              # (frame.py rewrote 0x80028b58: no marker there)
        tgt = 0x80000000 | (w & 0x3ffffff) << 2               # the current target (speed patches move some)
        src +="m%d:\n lui $t9, 0x8030\n ori $t8, $zero, %d\n j 0x%08x\n sw $t8, 0x7d0($t9)\n" % (k, k, tgt)
    code, sy = gas(src, HOOK + 0x400)
    e.poke(HOOK + 0x400, code)
    for site, tgt, k, nm in MARKS:
        if "m%d" % k in sy: e.poke(site, struct.pack("<I", 0x0c000000 | (sy["m%d" % k] >> 2 & 0x3ffffff)))


def sampler_clear(e):
    e.poke(HOOK + 0x7e0, bytes(4))


def sampler_read(e):
    """-> numpy array [n, 4] of (epc, ra, gpustat, dma2 chcr) per sample"""
    import numpy as np
    n = e.u32(HOOK + 0x7e0) // 16
    assert n < 0x40000, "sample ring wrapped"
    a = np.frombuffer(e.ram(HIST_PC, 16 * n), dtype="<u4").reshape(n, 4).copy()
    sampler_clear(e)
    return a


# ---------------------------------------------------------------- wrappers
WRAP_SRC = r"""
w_{k}:
    lui   $t9, 0x8039
    lw    $t8, -0x1000($t9)
    lui   $t7, 0x1f80
    addiu $t8, $t8, 16
    sw    $t8, -0x1000($t9)
    lhu   $t6, 0x1120($t7)
    lhu   $t5, 0x1110($t7)
    sw    $ra, -16($t8)
    sw    $t6, -12($t8)
    sw    $t5, -8($t8)
    lw    $t6, -0xffc($t9)
    sw    $zero, -0xffc($t9)
    jal   t_{k}
    sw    $t6, -4($t8)
    lui   $t9, 0x8039
    lw    $t8, -0x1000($t9)
    lui   $t7, 0x1f80
    lhu   $t6, 0x1120($t7)
    lhu   $t5, 0x1110($t7)
    lw    $t4, -12($t8)
    lw    $t3, -8($t8)
    subu  $t6, $t6, $t4
    andi  $t6, $t6, 0xffff
    subu  $t5, $t5, $t3
    andi  $t5, $t5, 0xffff
    sll   $t4, $t5, 8
    sll   $t3, $t5, 3
    addu  $t4, $t4, $t3
    sll   $t3, $t5, 2
    addu  $t4, $t4, $t3
    srl   $t3, $t5, 1
    addu  $t4, $t4, $t3
    subu  $t4, $t4, $t6
    addiu $t4, $t4, 0x7fff
    addiu $t4, $t4, 1
    bltz  $t4, 1f
    sra   $t4, $t4, 16
    sll   $t4, $t4, 16
    addu  $t6, $t6, $t4
1:  lw    $t3, -0xffc($t9)
    lw    $t4, -4($t8)
    subu  $t3, $t6, $t3
    addu  $t4, $t4, $t6
    sw    $t4, -0xffc($t9)
    lui   $t9, {ahi}
    lw    $t4, {alo}($t9)
    lw    $t5, {alo}+4($t9)
    lw    $t7, {alo}+8($t9)
    addiu $t4, $t4, 1
    addu  $t5, $t5, $t6
    addu  $t7, $t7, $t3
    sw    $t4, {alo}($t9)
    sw    $t5, {alo}+4($t9)
    sw    $t7, {alo}+8($t9)
{log}    lw    $ra, -16($t8)
    addiu $t8, $t8, -16
    lui   $t9, 0x8039
    jr    $ra
    sw    $t8, -0x1000($t9)
t_{k}:
    .word {w0}
    j     {cont}
    .word {w1}
"""
WLOG_SRC = r"""
    lui   $t9, 0x8039
    lw    $t4, -0xff4($t9)
    lui   $t5, 0x8050
    addu  $t5, $t5, $t4
    ori   $t7, $zero, {k}
    sw    $t7, 0($t5)
    sw    $t6, 4($t5)
    sw    $t3, 8($t5)
    lui   $t7, 0x8002
    lw    $t7, 0x20c8($t7)
    addiu $t4, $t4, 16
    sw    $t7, 12($t5)
    lui   $t7, 0xf
    ori   $t7, $t7, 0xfff0
    and   $t4, $t4, $t7
    sw    $t4, -0xff4($t9)
"""
WLOG = 0x80500000
WINIT_SRC = r"""
init:
    lui   $t9, 0x8039
    lw    $t8, -0xff8($t9)
    nop
    bne   $t8, $zero, 1f
    nop
    lui   $t7, 0x1f80
    ori   $t8, $zero, 0x200
    sh    $t8, 0x1124($t7)
    ori   $t8, $zero, 1
    sw    $t8, -0xff8($t9)
1:  lui   $v0, 0x8002
    lw    $v0, 0xfa4($v0)
    j     0x80011968
    nop
"""


def movable(w):
    op = w >> 26
    if op in (1, 2, 3, 4, 5, 6, 7) or (op == 0x10 and (w >> 21) & 31 == 8): return False
    if op == 0 and (w & 0x3f) in (8, 9): return False
    return True


def wrappable(ram, fn):
    w0, w1 = cfg.u32(ram, fn), cfg.u32(ram, fn + 4)
    if not (movable(w0) and movable(w1)): return False
    q = fn                                             # code before must not fall through into fn
    while cfg.u32(ram, q - 4) == 0 and fn - q < 64: q -= 4
    prev = cfg.u32(ram, q - 8)
    if not (prev == 0x03e00008 or prev >> 26 == 2 or prev >> 16 == 0x1000 or (q != fn and cfg.u32(ram, q - 4) == 0x03e00008)): return False
    # no branch inside the function to its first two instructions
    c, seen, t = cfg.walk(ram, fn)
    for a in seen:
        w = cfg.u32(ram, a); op = w >> 26
        if op in (1, 4, 5, 6, 7):
            off = w & 0xffff
            if off & 0x8000: off -= 0x10000
            if a + 4 + off * 4 in (fn, fn + 4): return False
        if op == 2 and (0x80000000 | (w & 0x3ffffff) << 2) in (fn + 4,): return False
    return True


def wrap_install(e, addrs, log=()):
    ram = e.ram(0x80000000, 0x200000)
    assert e.u32(0x80011960) == 0x3c028002, "VSync prologue changed"
    used = [a for a in addrs if wrappable(ram, a) and a != 0x80011960]
    src = WINIT_SRC
    defs = {}
    for k, fn in enumerate(used):
        A = WACC + 16 * k
        src += WRAP_SRC.format(k=k, ahi="0x%x" % ((A + 0x8000) >> 16 & 0xffff), alo="%d" % ((A & 0xffff) - (0x10000 if A & 0x8000 else 0)), w0="0x%08x" % cfg.u32(ram, fn), log=WLOG_SRC.format(k=k) if fn in log else "", w1="0x%08x" % cfg.u32(ram, fn + 4), cont="0x%08x" % (fn + 8))
    code, sy = gas(src, WCODE)
    assert WCODE + len(code) < WACC
    e.poke(WCODE, code); e.poke(WACC, bytes(16 * len(used)))
    e.poke(WSTATE, struct.pack("<4I", WSTK, 0, 0, 0))
    e.poke(0x80011960, jword(sy["init"]) + bytes(4))
    for k, fn in enumerate(used): e.poke(fn, jword(sy["w_%d" % k]) + bytes(4))
    skipped = [a for a in addrs if a not in used]
    return used, skipped


def wrap_log(e, used):
    """-> list of (function, incl cycles, excl cycles, Vcount) for the logged functions since the last call (ring 64K entries)"""
    n = e.u32(WSTATE + 12) // 16
    raw = e.ram(WLOG, 16 * n); e.poke(WSTATE + 12, bytes(4))
    return [(used[k], 8 * a, 8 * ((b + 0x80000000) % 0x100000000 - 0x80000000), v) for k, a, b, v in struct.iter_unpack("<4I", raw)]


def wrap_read(e, used, clear=True):
    raw = e.ram(WACC, 16 * len(used))
    if clear: e.poke(WACC, bytes(16 * len(used)))
    out = {}
    for k, fn in enumerate(used):
        c, inc, exc, _ = struct.unpack_from("<4I", raw, 16 * k)
        out[fn] = (c, 8.0 * inc, 8.0 * ((exc + 0x80000000) % 0x100000000 - 0x80000000))
    return out


def tree(ram, roots, depth, skip=()):
    """functions reachable from roots within depth calls (static)"""
    out, lvl = list(roots), list(roots)
    for d in range(depth):
        nxt = []
        for f in lvl:
            if f in skip: continue
            c, s, t = cfg.walk(ram, f)
            for x in c:
                if x not in out and 0x80010000 <= x < 0x80200000: out.append(x); nxt.append(x)
        lvl = nxt
    return out
