"""MvC CPU game-logic speedups (ex-Strider worker, 2026-11-19), `mktag.py --cpufast` (opt-in; default build unchanged).

Measured with tools/cpuprof (fwrap.py exact per-function cycles, sprof/sprof2 samplers), verified with mtest.py
(unicorn differential on calls captured by mcap.py) + the usual gates.

Parts (name: what, where):
  cmd   command-input matcher 0x800566d0 (21-24 calls per logic frame, ~350 cycles each, mostly I-cache misses):
        entry `j CMDFP`; the fast path returns at once for the dominant case "human, step 0, first input not
        matched" of a 2..7-input command (jump tables 0x800724a8[2..7][0] = 0x8005679c, static EXE data), doing
        exactly what the original does there (state+2 = 0, step = 0, v0 = 0); every other case runs the original
        (its two moved prologue words, then 0x800566d8).
        Code in the dead span 0x8009154c-0x800915c4 (unreferenced ClearImage helper; fnscan.py: no reference
        in the EXE or any disc file).

patches(which) -> [(ram_addr, bytes)]; SPANS = every range written; check() = load-delay hazard check.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CMD_FN, CMD_FP, CMD_END = 0x800566d0, 0x8009154c, 0x800915c4
CMD_W0, CMD_W1 = 0x~~~~~~~~, 0x~~~~~~~~          # addiu sp,sp,-0x30 ; sw s1,0x1c(sp)
CMD_SRC = r"""
cmdfp:
    lb    $t0, 3($a0)
    lbu   $t1, 0($a2)
    beqz  $t0, 9f
    lh    $t2, 0($a1)
    bnez  $t1, 9f
    addiu $t2, $t2, -2
    sltiu $t2, $t2, 6
    beqz  $t2, 9f
    lhu   $t4, 0xec($a0)
    lh    $t5, 2($a1)
    lh    $t6, 8($a1)
    andi  $t4, $t4, 0xf
    andi  $t5, $t5, 1
    beqz  $t5, 1f
    sh    $zero, 2($a2)
    and   $t4, $t4, $t6
    b     2f
    sltu  $t4, $zero, $t4
1:  xor   $t4, $t4, $t6
    sltiu $t4, $t4, 1
2:  bnez  $t4, 9f
    nop
    sb    $zero, 0($a2)
    jr    $ra
    move  $v0, $zero
9:  addiu $sp, $sp, -0x30
    j     0x800566d8
    sw    $s1, 0x1c($sp)
"""
# bios: the EXE's BIOS A0 stubs memcpy (0x2a) and bzero (0x28) -> RAM copies of the BIOS routines (same code in
# scph1001 / scph5501: byte loops, NULL dst -> 0, len <= 0 -> dst (memcpy) / 0 (bzero)).  The BIOS runs them from
# uncached ROM: PutDrawEnv's memcpy(0x5c) alone cost ~5.7k cycles per frame (Beetle).
MEMCPY_STUB, BZERO_STUB = 0x800145b8, 0x800170c8
MEMCPY_AT, MEMCPY_END = 0x8001722c, 0x80017260
BZERO_AT, BZERO_END = 0x800174bc, 0x800174e8
MEMCPY_SRC = r"""
memcpy:
    beqz  $a0, 3f
    move  $v1, $a0
    blez  $a2, 3f
    nop
2:  lbu   $t6, 0($a1)
    addiu $a2, $a2, -1
    addiu $a1, $a1, 1
    addiu $a0, $a0, 1
    bgtz  $a2, 2b
    sb    $t6, -1($a0)
3:  jr    $ra
    move  $v0, $v1
"""
BZERO_SRC = r"""
bzero:
    blez  $a1, 3f
    move  $v1, $zero
    beqz  $a0, 3f
    move  $v1, $a0
2:  addiu $a1, $a1, -1
    sb    $zero, 0($a0)
    bgtz  $a1, 2b
    addiu $a0, $a0, 1
3:  jr    $ra
    move  $v0, $v1
"""
PARTS = ("cmd", "bios")
SPANS = [(CMD_FN, CMD_FN + 8), (CMD_FP, CMD_END), (MEMCPY_STUB, MEMCPY_STUB + 8), (BZERO_STUB, BZERO_STUB + 8),
         (MEMCPY_AT, MEMCPY_END), (BZERO_AT, BZERO_END)]


def _gas():
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "tools", "speed", "frame"))
    from gas import gas
    return gas


def build(which=None):
    which = PARTS if which in (None, "all") else tuple(which.split(","))
    out = []
    if "cmd" in which:
        code, sy = _gas()(CMD_SRC, CMD_FP)
        assert CMD_FP + len(code) <= CMD_END, "cmd fast path too big: %d" % len(code)
        out.append((CMD_FP, code))
        out.append((CMD_FN, struct.pack("<2I", 0x08000000 | (CMD_FP >> 2 & 0x3ffffff), 0)))
    if "bios" in which or "bios_m" in which or "bios_z" in which:     # bios_m / bios_z: memcpy / bzero alone (bisecting)
        sel = [] + ([(MEMCPY_SRC, MEMCPY_AT, MEMCPY_END, MEMCPY_STUB)] if "bios" in which or "bios_m" in which else [])             + ([(BZERO_SRC, BZERO_AT, BZERO_END, BZERO_STUB)] if "bios" in which or "bios_z" in which else [])
        for src, at, end, stub in sel:
            code, sy = _gas()(src, at)
            assert at + len(code) <= end, "bios part too big at %08x" % at
            out.append((at, code))
            out.append((stub, struct.pack("<2I", 0x08000000 | (at >> 2 & 0x3ffffff), 0)))
    return out


_cache = {}
def patches(which=None):
    if which not in _cache: _cache[which] = build(which)
    return _cache[which]


def stock_words():
    """(addr, bytes) the stock EXE must have where we write (asserted by mktag)"""
    return [(CMD_FN, struct.pack("<2I", CMD_W0, CMD_W1)), (CMD_FP, struct.pack("<2I", 0x~~~~~~~~, 0x~~~~~~~~)),
            (MEMCPY_STUB, struct.pack("<3I", 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~)), (BZERO_STUB, struct.pack("<3I", 0x~~~~~~~~, 0x~~~~~~~~, 0x~~~~~~~~)),
            (MEMCPY_AT, struct.pack("<2I", 0x~~~~~~~~, 0x~~~~~~~~)), (BZERO_AT, struct.pack("<3I", 0, 0, 0))]


def check():
    """load-delay hazards: an instruction must not read the register loaded by the instruction just before it"""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN); md.detail = True
    bad = []
    for a, b in patches():
        prev = None
        for ins in md.disasm(b, a):
            if prev is not None:
                rd = [r for r in ins.regs_read] + [op.reg for op in ins.operands if op.type == 1] + [op.mem.base for op in ins.operands if op.type == 3]
                if prev in rd and not (ins.mnemonic in ("sw", "sh", "sb") and ins.operands[0].type == 1 and ins.operands[0].reg == prev and False):
                    bad.append("%08x %s %s (reads %s loaded just before)" % (ins.address, ins.mnemonic, ins.op_str, md.reg_name(prev)))
            prev = ins.operands[0].reg if ins.mnemonic in ("lb", "lbu", "lh", "lhu", "lw", "lwl", "lwr") else None
    return bad


def mutate(rec, ram, scr, rnd):
    """fuzz the matcher's inputs: state bytes, pad word, human flag"""
    if rec["fn"] in (MEMCPY_STUB, BZERO_STUB):
        a = list(rec["a"]); k = rnd.randrange(6)
        n = 2 if rec["fn"] == MEMCPY_STUB else 1
        if k == 0: a[n] = rnd.choice([0, -1 & 0xffffffff, 1, 2, 3, 0x80000000])
        elif k == 1: a[0] = 0
        elif k == 2: a[0] += rnd.randrange(1, 4)
        elif k == 3 and n == 2: a[1] = (a[0] + rnd.choice([-3, -1, 1, 2, 5])) & 0xffffffff     # overlap (forward byte order)
        elif k == 4: a[n] = rnd.randrange(1, 200)
        else: a[n] = rnd.randrange(1, 40); a[0] = 0x80000000 | rnd.randrange(0x100000, 0x1f0000)
        return (dict(rec, a=a), ram, scr)
    if rec["fn"] != CMD_FN: return None
    a0, a1, a2, a3 = rec["a"]
    m = bytearray(ram)
    k = rnd.randrange(6)
    if k == 0: m[a2 & 0x1fffff] = rnd.choice([0, 0, 2, 4, 6, 1, 0x80])
    elif k == 1: struct.pack_into("<H", m, (a0 + 0xec) & 0x1fffff, rnd.getrandbits(16))
    elif k == 2: m[(a0 + 3) & 0x1fffff] = rnd.choice([0, 1, 2])
    elif k == 3: struct.pack_into("<H", m, (a0 + 0xee) & 0x1fffff, rnd.getrandbits(16))
    elif k == 4: m[(a2 + 1) & 0x1fffff] = rnd.getrandbits(8)
    else: m[(a0 + 0x30f) & 0x1fffff] = rnd.choice([0, 1])
    return (rec, bytes(m), scr)


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        b = check(); print("\n".join(b) or "no load-delay hazards"); sys.exit(1 if b else 0)
    for a, b in patches(): print("%08x %d bytes" % (a, len(b)))
