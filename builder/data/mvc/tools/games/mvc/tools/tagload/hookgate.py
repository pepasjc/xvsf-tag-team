"""Hook-lifecycle gate (freeze worker, rc4 audit 2026-11-20; `mktag.py --hookgate`, opt-in until gated).

Problem (SPEED_TEAM.md "hook-lifecycle audit"): tl_main writes `jal <image>` into EXE call sites whose image lives in
tag-only REGION RAM (L2 g2get 0x8008f694, L1b REMAP 0x8008dc38 / 0x8008ffc8, vcache 0x8008c5cc).  The words stay until
the NEXT tl_main, so every later scene that draws sprites (win, continue, ending, the post-Onslaught scene 28, the
loading-screen thread) calls into RAM that the next loads overwrite - the same bug class as the dxahead freeze.
Fix: the sites call a gate entry in KERNEL RAM instead (HG_AT 0x80009A10, inside the real-PS1 proven span).
  * nop sites (L2, L1b x2; the stock word was a nop): the image runs only when LOADER_FULL 0x800858ac != 0 and three
    code words of the image (first / middle / last) are intact, else return (= the stock nop).  NO scene test: the win
    and continue screens draw the packed data (v2 with a scene test hung the win screen).  LOADER_FULL rather than
    tl_dbg[0]: the loader-less ARCADE continue rematch still draws the packed data (hcguard keeps LOADER_FULL).
    The gate saves t0 / t1 / ra (16 B of stack); the images keep their own contracts (g2get v0 / v1, REMAP t0-t9).
  * call sites (vcache 0x8008c5cc, replaced a normal `jal`): tail jump without a stack frame (v1's stack frame hung the
    first fight: the vcache route does not return through the gate), t0 / t1 only; on = vcache stub when scene
    0x8007bdcc == 8 and LOADER_FULL != 0, else off = CHK (kernel; always correct).
Table T[k] = {on, off, a0, w0, a1, w1, a2, w2} (32 B each, written by tl_main hg_set()).  428 B for the 4 sites.

    code, sym = build(at)        python hookgate.py   (prints size + load-delay hazards)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "tools", "speed", "frame"), os.path.join(ROOT, "tools", "speed", "decode")]
from gas import gas

SITES = ["L2", "L1B0", "L1B1", "VC"]          # gate slot index = position here
CALLSITE = {"VC"}       # sites that replaced a normal `jal`: tail-jump gate, no stack frame (v2: the vcache route returns
                        # past its caller's frame - the stack gate of v1 left sp unbalanced -> hang at the first fight)
HG_AT = int(os.environ.get("HOOKGATE_AT", "0x80009A10"), 16)   # dx side-1 pool 0x80009A00-9D00 (dx worker OK), inside the real-PS1 proven span 0x80009A10-0x80009CF0 (achbuild.py)
SCENE, LFULL = 0x8007bdcc, 0x800858ac


def ent(k):
    if SITES[k] in CALLSITE:                     # call site: t0 / t1 are caller-saved there; ra / sp untouched; tail jump
        return """E%d:     lui   $t0, %%hi(SCENE)
        lbu   $t0, %%lo(SCENE)($t0)
        lui   $t1, %%hi(LFULL)
        xori  $t0, $t0, 8
        bnez  $t0, C%dOFF
        lbu   $t1, %%lo(LFULL)($t1)
        nop
        beqz  $t1, C%dOFF
        lui   $t0, %%hi(T + %d)
        lw    $t1, %%lo(T + %d)($t0)
        nop
        jr    $t1
        nop
C%dOFF:  lui   $t0, %%hi(T + %d)
        lw    $t1, %%lo(T + %d)($t0)
        nop
        jr    $t1
        nop""" % (k, k, k, 32 * k, 32 * k, k, 32 * k + 4, 32 * k + 4)
    return """E%d:     addiu $sp, $sp, -16
        sw    $t0, 4($sp)
        b     G
        li    $t0, %d""" % (k, k)


def src(ns):
    ents = "\n".join(ent(k) for k in range(ns))
    return ents + """
G:      sw    $ra, 0($sp)
        sw    $t1, 8($sp)
        sll   $t0, $t0, 5                       /* T + 32 k */
        lui   $t1, %hi(T)
        addiu $t1, $t1, %lo(T)
        addu  $t0, $t0, $t1                     /* t0 = &T[k] */
        lui   $t1, %hi(LFULL)                   /* v3: no scene test here - win / continue screens draw the packed data */
        lbu   $t1, %lo(LFULL)($t1)
        nop
        beqz  $t1, Goff
        nop
        lw    $t1, 8($t0)                       /* first code word of the image */
        nop
        lw    $t1, 0($t1)
        lw    $ra, 12($t0)
        nop
        bne   $t1, $ra, Goff
        nop
        lw    $t1, 16($t0)                      /* last code word */
        nop
        lw    $t1, 0($t1)
        lw    $ra, 20($t0)
        nop
        bne   $t1, $ra, Goff
        nop
        lw    $t1, 24($t0)                      /* middle code word */
        nop
        lw    $t1, 0($t1)
        lw    $ra, 28($t0)
        nop
        bne   $t1, $ra, Goff
        nop
        b     Gcall
        lw    $t1, 0($t0)                       /* on: the image entry */
Goff:   lw    $t1, 4($t0)                       /* off: stock routine or 0 (nop site) */
Gcall:  nop
        beqz  $t1, Gret
        lw    $t0, 4($sp)                       /* the caller's t0 back before the call */
        jalr  $t1
        nop
Gret:   lw    $ra, 0($sp)
        lw    $t0, 4($sp)
        lw    $t1, 8($sp)
        jr    $ra
        addiu $sp, $sp, 16
        .align 2
T:      .space TSIZE
END:
""".replace("TSIZE", str(32 * ns))


def build(at=HG_AT, ns=len(SITES)):
    code, sym = gas(src(ns), at, {"SCENE": SCENE, "LFULL": LFULL})
    assert sym["END"] - at == len(code)
    return code, sym


def header(at=HG_AT):
    code, sym = build(at)
    words = [int.from_bytes(code[i:i + 4], "little") for i in range(0, sym["T"] - at, 4)]
    d = ["#define HG_AT 0x%08xu" % at, "#define HG_T 0x%08xu" % sym["T"], "#define HG_NW %d" % len(words)]
    for k, n in enumerate(SITES): d.append("#define HG_E_%s 0x%08xu" % (n, sym["E%d" % k]))
    d.append("static const unsigned int hg_img[%d] = { %s };" % (len(words), ", ".join("0x%08xu" % w for w in words)))
    return "\n".join(d) + "\n"


if __name__ == "__main__":
    import dlib
    c, s = build()
    print("hookgate %d B at %08x (code %d B, table %d B); entries %s" % (len(c), HG_AT, s["T"] - HG_AT, s["END"] - s["T"],
          {n: hex(s["E%d" % k]) for k, n in enumerate(SITES)}))
    print("load-delay hazards:", dlib.hazards(c[:s["T"] - HG_AT], HG_AT) or "none")
