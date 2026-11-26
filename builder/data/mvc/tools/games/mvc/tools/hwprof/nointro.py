"""Ground intro for War Machine (01) and Gold War Machine (14) (mktag.py --nointro[=C1|C2|C3]; user 2026-11-19: "the
iron man intro still plagues the game ... let him start from the ground like other characters do").

Engine: battle state 0 / sub 0 (0x8004fd40) calls the character's own intro routine every logic frame through the
per-character table 0x80079c80[char] (filled at load from the A0 code item; `jalr` at 0x8004fd74) until it sets +6;
then the engine sets the stand animation and waits for the fight phase.  War Machine's routine (A0 sec1 0x2140, Gold
WM 0x1ec4) is a substate machine on +8: hidden until phase 4, thruster sound 0x162, x = start - 0xe0, flight
animations cat 19 / idx 0..3, then x += 4 per frame, landing (cat 19 / 9 area), hover; +6 after ~288 frames.

The replacement is written over the routine's own entry (the table pointer stays valid; the rest of the old routine
is unreachable).  The words the loader relocates (reloc.py: hi / lo / j26 / ptr) keep their stock values: the new
code hops over them.  It only calls EXE functions (set_anim 0x8002db54(obj, cat*2, idx*2), anim step 0x8003bd54) and
uses relative branches, so it is position independent like the slot loader needs.  Behaviour: visible at the normal
start position from the first intro frame, animation A until SWITCH frames, animation B until the battle phase reaches 6, then +6
(exactly when the stock routine finishes; FIGHT is driven by the phase timer and does not move).  No sound, no effect objects.

    nointro.patch(c, partA, H) -> partA with the routine replaced (called from mktag.py's A0 item builder)
    python nointro.py show        print the generated code per character / candidate
"""
import os, sys, struct, importlib.util, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
spec = importlib.util.spec_from_file_location("mvc_reloc_ni", os.path.join(GAME, "tools", "reloc.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "frame"))
from gas import gas

# char -> (sec1 offset of the intro routine, prologue words kept verbatim (ends after `lhu v1,8(s0)` + its lo word),
#          epilogue (stack frame, saved regs as (reg, offset)))
FN = {0x01: dict(off=0x2140, pro=7, frame=0x20, saves=[("ra", 0x1c), ("s0", 0x18)]),
      0x14: dict(off=0x1ec4, pro=8, frame=0x28, saves=[("ra", 0x20), ("s1", 0x1c), ("s0", 0x18)]),
      # Jin (2026-11-20, rc4.1): stock intro = rides in on the Blodia mech (+8 = 2 ride, 4 hold, 6 jump out, 8 land);
      # routine found with introfind.py (table 0x80079c80[0xc] -> sec1 0x2534; same +8 jump-table shape as WM)
      0x0c: dict(off=0x2534, pro=7, frame=0x18, saves=[("ra", 0x14), ("s0", 0x10)])}
# candidates: (anim A (cat, idx), SWITCH, anim B, TOTAL).  (0, 0) = stance; (20, 1) = fist raise (55 frames);
# (20, 2) = kneel and rise (60 frames).  Same indices in both characters (checked in animtab).
TOTAL = int(os.environ.get("NOINTRO_TOTAL", "288"))
CAND = {"C1": ((0, 0), 44, (20, 1)),                 # stance, fist raise at the end of phase 4 (~110 logic frames)
        "C2": ((20, 1), 64, (0, 0)),                  # fist raise first, then stance
        "C3": ((20, 2), 66, (0, 0))}                  # kneel and rise, then stance
# per-character candidate sets (characters not listed use CAND).  Jin's frames (work/intro/anims_c_19_20_21.png):
# (20, 0) bandana whip 40 f, (20, 1) cape fling 42 f, (19, 3) flex 160 f; phase 6 starts ~190 logic frames in.
CANDS = {0x0c: {"J1": ((0, 0), 120, (20, 0)),          # stance, bandana whip just before FIGHT
                "J2": ((20, 1), 60, (0, 0)),           # cape fling first, then stance
                "J3": ((19, 3), 170, (0, 0))}}         # long flex, then stance
DEFPOSE = {0x01: "C1", 0x14: "C1", 0x0c: "J1"}         # pose per character (rc4 WM / GWM = C1); env NOINTRO_POSE_<CC> overrides
# (2026-11-24, env NOINTRO_0E=1, candidate fix for the hardware 2 MB-mode freeze in Strider's stock intro): Strider
# (0e) intro routine A0 sec1 0x94f0 (introfn.py: table 0x80079c80[0xe], unique hit; prologue as Jin's), stance pose
if os.environ.get("NOINTRO_0E") == "1":
    # Strider dispatches on +4 (prologue `lhu v1, 4(s0)`), and his dispatcher's lw delay slot loads a1 = obj + 0x50
    FN[0x0e] = dict(off=0x94f0, pro=7, frame=0x18, saves=[("ra", 0x14), ("s0", 0x10)], state=4, slot=0x8e050050)
    CANDS[0x0e] = {"S1": ((0, 0), 44, (0, 0))}
    DEFPOSE[0x0e] = "S1"


def cands(c): return CANDS.get(c, CAND)


def pose(c, cand=None):
    """pose of character c: --nointro=<name> if it is one of c's candidates, else env NOINTRO_POSE_<CC> / DEFPOSE"""
    if cand in cands(c): return cand
    v = os.environ.get("NOINTRO_POSE_%02X" % c) or (os.environ.get("NOINTRO_POSE") if c not in CANDS else None)
    return v or DEFPOSE.get(c, "C1")
SET_ANIM, ANIM_STEP = 0x8002db54, 0x8003bd54


def stock(c):
    a = open(R.path(c, 10), "rb").read(); S = R.sections(a); r = R.get(c)
    rel = set(r.ptr) | set(r.j26) | set(r.lo) | set(r.hi)
    base = S[0][0]
    return a, base, rel


def body(c, cand):
    (ca, ia), sw, (cb, ib) = cands(c)[pose(c, cand)]
    f = FN[c]
    stream = [  # atoms: lists of instruction strings; a branch and its delay slot form one atom
        ["bnez $v1, run_"], ["nop"],
        ["ori $v0, $zero, 2"], ["sh $v0, %d($s0)" % f.get("state", 8)], ["sh $zero, 0xa($s0)"], ["ori $v0, $zero, 1"],
        ["sb $v0, 1($s0)"], ["move $a0, $s0"], ["ori $a1, $zero, %d" % (ca * 2)],
        ["jal 0x%x" % SET_ANIM, "ori $a2, $zero, %d" % (ia * 2)],
        ["b end_", "nop"],
        ["LABEL run_"],
        ["jal 0x%x" % ANIM_STEP, "move $a0, $s0"],
        ["lhu $t0, 0xa($s0)"], ["nop"], ["addiu $t0, $t0, 1"], ["sh $t0, 0xa($s0)"],
        ["xori $t1, $t0, %d" % sw],
        ["bnez $t1, sk_", "move $a0, $s0"],
        ["ori $a1, $zero, %d" % (cb * 2)],
        ["jal 0x%x" % SET_ANIM, "ori $a2, $zero, %d" % (ib * 2)],
        ["lhu $t0, 0xa($s0)"], ["nop"],
        ["LABEL sk_"],
        ["lui $t1, 0x8008"], ["lb $t1, -0x47d8($t1)"], ["nop"],      # battle phase 0x8007b828: done at 6 (as stock)
        ["slti $t1, $t1, 6"],
        ["bnez $t1, end_", "ori $v0, $zero, 1"],
        ["sh $v0, 6($s0)"],
        ["LABEL end_"]]
    for reg, o in f["saves"]: stream.append(["lw $%s, 0x%x($sp)" % (reg, o)])
    stream.append(["nop"])
    stream.append(["jr $ra", "addiu $sp, $sp, 0x%x" % f["frame"]])
    # the first atom (bnez) needs v1 from the prologue's lhu: the prologue ends with the relocated lo word -> 1 slot
    return stream


def layout(c, cand):
    a, base, rel = stock(c)
    f = FN[c]
    w0 = (base + f["off"]) // 4                           # file word index of the routine entry
    word = lambda i: struct.unpack_from("<I", a, 4 * (w0 + i))[0]
    reserved = {i for i in range(0, 400) if (w0 + i) in rel}
    lines = [".set noreorder", ".set noat"]
    for i in range(f["pro"]): lines.append(".word 0x%08x" % word(i))
    pos = f["pro"]; hop = 0
    for atom in body(c, cand):
        if atom[0].startswith("LABEL"):
            lines.append(atom[0].split()[1] + ":"); continue
        s = len(atom)
        R_ = min(i for i in reserved if i >= pos) if any(i >= pos for i in reserved) else 10 ** 6
        if pos + s + 2 > R_:
            assert pos + 2 <= R_, (c, pos, R_)
            lines += ["b hop%d" % hop, "nop"]; pos += 2
            while pos < R_: lines.append("nop"); pos += 1
            while pos in reserved: lines.append(".word 0x%08x" % word(pos)); pos += 1
            lines.append("hop%d:" % hop); hop += 1
        lines += atom; pos += s
    return lines, pos, w0, reserved, word


def code(c, cand):
    lines, n, w0, reserved, word = layout(c, cand)
    blob, sym = gas("\n".join(lines) + "\n", 0x800c0000)
    assert len(blob) == 4 * n, (len(blob), n)
    for i in reserved:
        if i < n: assert struct.unpack_from("<I", blob, 4 * i)[0] == word(i), ("relocated word changed", c, i)
    return blob


# ---- v2 (2026-11-19 night): OPTION "INTRO STOCK / SIMPLE".  The stock routine stays; its +8 dispatcher (11 words
# after the prologue: sll, sra, srl, addu, sra, sll, addu, lw, nop, jr, nop) becomes: read the INTRO byte (| FORCE),
# non-zero -> branch to the ground routine APPENDED to the code item, else the same jump-table dispatch (v1 = +8 is
# even and >= 0, so (s16)v1 / 2 * 4 == v1 * 2).  Table-driven: FN (routine offset, prologue, frame) + POSE per char.
def intro_byte():
    """the INTRO value byte: the fx worker's OPTION rows (tools/gameplay/optrows.py, --fs05 --introopt) own it;
    without --introopt (test discs, pokes) 0x800858cb = the rc3 slot (dead EXE span after ASSIST_GATE, zeroed by mktag)"""
    if "--introopt" in sys.argv:
        sys.path.insert(0, os.path.join(GAME, "tools", "gameplay")); import optrows
        return optrows.byte("INTRO", sys.argv)
    return int(os.environ.get("NOINTRO_BYTE", "0x800858cb"), 16)
DISPATCH = [0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~,
            0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~]           # stock words, asserted


def mode():
    a = next((x for x in sys.argv if x.startswith("--nointro")), None)
    if a is None: return None
    v = a.split("=", 1)[1] if "=" in a else "menu"
    if v in CAND or any(v in d for d in CANDS.values()):
        return dict(force=1, cand=v)                      # --nointro=C1..C3 / J1..J3: test disc, always SIMPLE, that pose
    if v == "on": return dict(force=1, cand=None)
    return dict(force=0, cand=None)                       # pose per character: pose(c)


def simple_default():
    """--introsimple (rc4.1): power-on value of the INTRO byte = 1 (SIMPLE), written by mktag.opt_init (byte map of the
    fx worker's EX OPTIONS: 0 STOCK / 1 SIMPLE, reader semantics unchanged)"""
    return "--introsimple" in sys.argv


def appendix(c, cand):
    """the ground routine, entered from the dispatcher with the stock prologue done (s0 = obj, v1 = +8)"""
    lines = [".set noreorder", ".set noat"]
    for atom in body(c, cand):
        if atom[0].startswith("LABEL"): lines.append(atom[0].split()[1] + ":")
        else: lines += atom
    blob, sym = gas("\n".join(lines) + "\n", 0x800c0000)
    return blob


def dispatcher(c, app_off, force):
    f = FN[c]; at = f["off"] + 4 * f["pro"]                # sec1 offset of the first dispatcher word
    src = """.set noreorder
        lui   $t0, %%hi(B)
        lbu   $t0, %%lo(B)($t0)
        nop
        %s
        .word BNEZ
        sll   $v0, $v1, 1
        addu  $v0, $v0, $a0
        lw    $v0, 0($v0)
        .word SLOT
        jr    $v0
        nop
""" % ("ori   $t0, $t0, %d" % force)
    off = (app_off - (at + 4 * 4 + 4)) // 4                # bnez is the 5th word
    assert -0x8000 <= off < 0x8000
    blob, sym = gas(src, 0x800c0000 + at, {"B": intro_byte(), "BNEZ": 0x15000000 | 8 << 21 | (off & 0xffff), "SLOT": f.get("slot", 0)})
    assert len(blob) == 44
    return at, blob


def stock_dispatch_ok(c, code):
    f = FN[c]; at = f["off"] + 4 * f["pro"]
    want = DISPATCH[:8] + [f.get("slot", 0)] + DISPATCH[9:]
    return [struct.unpack_from("<I", code, at + 4 * i)[0] for i in range(11)] == want


def patch(c, partA, H):
    """(v1 overwrite variant, kept for the pose-strip discs --nointro=C1..C3 only when NOINTRO_V1=1)"""
    cand = next((x.split("=", 1)[1] for x in sys.argv if x.startswith("--nointro=")), "C1")
    f = FN[c]; blob = code(c, cand)
    k = H + f["off"]
    a, base, rel = stock(c)
    assert partA[k:k + 32] == a[base + f["off"]:base + f["off"] + 32], ("intro routine not stock", c)
    return partA[:k] + blob + partA[k + len(blob):]


if __name__ == "__main__":
    for c in FN:
        for cand in CAND:
            lines, n, w0, reserved, word = layout(c, cand)
            b = code(c, cand)
            print("char %02x %s: %d words (%d B), relocated kept: %s" % (c, cand, n, len(b), sorted(i for i in reserved if i < n)))
    if "show" in sys.argv: print("\n".join(layout(1, "C1")[0]))
