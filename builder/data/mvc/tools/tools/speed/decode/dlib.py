"""Shared harness for the decode speed work (tools/speed/decode.py):
  assemble()   gcc/ld/objcopy a .S at a fixed address
  image()      2 MB RAM image = 1.0.1 executable (work/speed/decode/b101_exe.bin) + patches
  test sets    every sprite file the tile decoder 0x8001b5b0 sees (stock RLE, XVM1/XVH1 tiers, effects)
  UC           unicorn runner: call the decoder on one tile, read the output back
  bench()      Beetle micro-benchmark: run a decoder over a tile list with interrupts off, root-counter cycles
  hazards()    R3000 load-delay checker for assembled code
"""
import os, sys, struct, subprocess, glob
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOLS = os.path.join(ROOT, "tools")
WORK = os.path.join(ROOT, "work", "speed", "decode")
sys.path.insert(0, TOOLS)
import toolenv
GCC = toolenv.mips_prefix()
EXE_BASE = 0x80010000
EXE_B101 = os.path.join(WORK, "b101_exe.bin")
SECTAB = 0x8005c830
FILEBASE, DST, SLACK = 0x80100000, 0x80180000, 64
STACK = 0x801ff000


def assemble(src, org, outdir=None, defs=()):
    """-> (bytes, {symbol: address})"""
    outdir = outdir or os.path.join(WORK, "obj")
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + "_%08x_%d" % (org, os.getpid()))
    ld = base + ".ld"
    open(ld, "w").write("SECTIONS {\n  . = 0x%08x;\n  .text : { *(.text*) *(.rodata*) *(.data*) }\n"
                        "  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }\n}\n" % org)
    subprocess.check_call([GCC + "gcc", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", *["-D" + d for d in defs], "-c", src, "-o", base + ".o"])
    subprocess.check_call([GCC + "ld", "-T", ld, base + ".o", "-o", base + ".elf"])
    subprocess.check_call([GCC + "objcopy", "-O", "binary", base + ".elf", base + ".bin"])
    sym = {}
    for l in subprocess.check_output([GCC + "nm", base + ".elf"]).decode().splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    return open(base + ".bin", "rb").read(), sym


def exe_b101():
    if not os.path.exists(EXE_B101):
        from iso import Disc
        d = Disc(os.path.join(ROOT, "work", "speed", "base", "b101.bin"))
        for full, lba, sz, fl in d.walk():
            if full.startswith("SLUS"):
                open(EXE_B101, "wb").write(d.read(lba, sz))
    return open(EXE_B101, "rb").read()


def image(patches=(), exe=None):
    exe = exe or exe_b101()
    m = bytearray(0x200000)
    t = exe[0x800:]
    m[EXE_BASE & 0x1fffff:(EXE_BASE & 0x1fffff) + len(t)] = t
    for a, d in patches:
        m[a & 0x1fffff:(a & 0x1fffff) + len(d)] = d
    return m


def old_patches():
    """the shipped 1.0.1 decoder patches (tools/nsppatch.py as built)"""
    import nsppatch
    return nsppatch.patches()


# ------------------------------------------------------------------------------------------- test sets
A0 = os.path.join(ROOT, "disc", "files", "A", "A0")
A2 = os.path.join(ROOT, "disc", "files", "A", "A2")
B = os.path.join(ROOT, "build")


def test_files(which=None):
    """-> [(set name, path, section-table slot)]"""
    out = []
    for c in range(19): out.append(("stock", os.path.join(A0, "SP_PL%02X.NSP" % c), c))
    for f in sorted(glob.glob(os.path.join(A2, "*.NSP"))): out.append(("stockA2", f, 0x26))
    for d in ("nspm", "nspm4", "nspfat2", "nsp"):
        for c in range(19): out.append((d, os.path.join(B, d, "SP_PL%02X.NSP" % c), c))
    out.append(("nspm_eff", os.path.join(B, "nspm_eff", "SP_EFF1.NSP"), 0x26))
    for c in range(19):                                    # strong tier with hot tiles as RLE (work/speed/decode/strongrle.py)
        p = os.path.join(WORK, "nsph4", "SP_PL%02X.NSP" % c)
        if os.path.exists(p): out.append(("nsph4", p, c))
    return [x for x in out if which is None or x[0] in which]


def tiles(data):
    """-> (sec2 offset in file, [(offset in sec2, nbytes)])  every sec1 entry whose bytes and offset are inside the file"""
    o = struct.unpack_from("<4I", data, 0)
    s1 = data[o[1]:o[2]]; s2len = o[3] - o[2]
    out = []
    for i in range(len(s1) // 4):
        w = struct.unpack_from("<I", s1, i * 4)[0]
        off = w & 0x3FFFFF; n = ((w >> 24 & 15) + 1) * 8 * ((w >> 28) + 1) * 16
        if off < s2len: out.append((off, n))
    return o[2], out


def magic(data):
    o = struct.unpack_from("<4I", data, 0)
    return data[o[2]:o[2] + 4]


# ------------------------------------------------------------------------------------------- unicorn
class UC:
    def __init__(self, mem):
        import unicorn as U, unicorn.mips_const as M
        self.U, self.M = U, M
        mu = self.mu = U.Uc(U.UC_ARCH_MIPS, U.UC_MODE_MIPS32 | U.UC_MODE_LITTLE_ENDIAN)
        mu.mem_map(0, 0x200000)
        mu.mem_write(0, bytes(mem))
        self.R = {n: getattr(M, "UC_MIPS_REG_" + n.upper()) for n in
                  "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split()}

    def load(self, data, slot):
        """file at FILEBASE, section table: only `slot` -> its sec2"""
        self.mu.mem_write(FILEBASE & 0x1fffff, data + bytes(64))
        self.mu.mem_write(SECTAB & 0x1fffff, bytes(0x28 * 4))
        o2 = struct.unpack_from("<I", data, 8)[0]
        self.mu.mem_write((SECTAB + 4 * slot) & 0x1fffff, struct.pack("<I", FILEBASE + o2))
        return FILEBASE + o2

    def call(self, fn, a0, a1, a2, a3=0, fill=0xCC, n_read=None, count=False):
        mu, R = self.mu, self.R
        n_read = n_read if n_read is not None else max(a2, 0) + SLACK
        mu.mem_write(a1 & 0x1fffff, bytes([fill]) * n_read)
        for i, r in enumerate(("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "fp", "gp")):
            mu.reg_write(R[r], 0x5A5A0000 + i)
        mu.reg_write(R["sp"], STACK); mu.reg_write(R["ra"], 0x80001000)
        for r, v in (("a0", a0), ("a1", a1), ("a2", a2 & 0xFFFFFFFF), ("a3", a3)): mu.reg_write(R[r], v)
        cnt = [0]
        if count:
            h = mu.hook_add(self.U.UC_HOOK_BLOCK, lambda uc, addr, size, ud: cnt.__setitem__(0, cnt[0] + size // 4))
        mu.emu_start(fn, 0x80001000, count=200_000_000)
        if count: mu.hook_del(h)
        assert mu.reg_read(R["pc"] if "pc" in R else self.M.UC_MIPS_REG_PC) == 0x80001000, "decoder did not return"
        for i, r in enumerate(("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "fp", "gp")):
            assert mu.reg_read(R[r]) == 0x5A5A0000 + i, "callee-saved %s clobbered" % r
        assert mu.reg_read(R["sp"]) == STACK
        out = bytes(mu.mem_read(a1 & 0x1fffff, n_read))
        return (out, cnt[0]) if count else out

    def mem(self):
        return bytes(self.mu.mem_read(0, 0x200000))


# ------------------------------------------------------------------------------------------- R3000 hazards
def hazards(code, org, ranges=None):
    """load-delay violations: an instruction that reads the register loaded by the instruction before it
    (also across a branch: the delay-slot load vs the target's first instruction).  -> list of strings"""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    ins = {}
    for i in md.disasm(code, org):
        ins[i.address] = i
    LOADS = {"lb", "lbu", "lh", "lhu", "lw", "lwl", "lwr", "mfc0"}
    BR = {"b", "beq", "bne", "beqz", "bnez", "bgez", "bgtz", "blez", "bltz", "bgezal", "bltzal", "j", "jal", "jr", "jalr", "bal"}
    ALLREAD = {"sb", "sh", "sw", "swl", "swr", "mult", "multu", "div", "divu", "mthi", "mtlo", "jr", "jalr", "mtc0",
               "beq", "bne", "beqz", "bnez", "bgez", "bgtz", "blez", "bltz", "bgezal", "bltzal", "teq"}
    def regs_read(i):
        names = set()
        for k, op in enumerate(i.operands):
            if op.type == capstone.mips.MIPS_OP_REG and (k > 0 or i.mnemonic in ALLREAD):
                names.add(i.reg_name(op.reg))
            elif op.type == capstone.mips.MIPS_OP_MEM:
                names.add(i.reg_name(op.mem.base))
        if i.mnemonic in ("lwl", "lwr"): names.add(i.reg_name(i.operands[0].reg))
        if i.mnemonic == "mtc0": names = {i.reg_name(i.operands[0].reg)}
        return names
    def dest(i):
        return i.reg_name(i.operands[0].reg)
    def target(i):
        for op in i.operands:
            if op.type == capstone.mips.MIPS_OP_IMM: return op.imm
        return None
    bad = []
    for a, i in ins.items():
        if ranges and not any(lo <= a < hi for lo, hi in ranges): continue
        if i.mnemonic not in LOADS: continue
        d = dest(i)
        if d == "zero": continue
        nxt = []
        prev = ins.get(a - 4)
        if prev is not None and prev.mnemonic in BR:          # load in a delay slot
            t = target(prev) if prev.mnemonic not in ("jr", "jalr") else None
            if t is not None and t in ins: nxt.append(ins[t])
            if prev.mnemonic not in ("b", "j", "jr", "jal", "jalr", "bal") and a + 4 in ins: nxt.append(ins[a + 4])
        elif a + 4 in ins:
            nxt.append(ins[a + 4])
        for n in nxt:
            if d in regs_read(n) and not (i.mnemonic in ("lwl", "lwr") and n.mnemonic in ("lwl", "lwr")):
                bad.append("%08x %s %s -> %08x %s %s" % (a, i.mnemonic, i.op_str, n.address, n.mnemonic, n.op_str))
    return bad


# ------------------------------------------------------------------------------------------- Beetle bench
HB_CYC = 33868800 / 59.94 / 263
LIST, RES, DRV = 0x801a0000, 0x801b0000, 0x801c0000
MAXT = (RES - LIST - 4) // 8


def bench(patches, data, slot, tl, func, model=0, state="kiko_prof", sym=None):
    """Run func(FILEBASE+sec2+off, DST, n, model) for every (off, n) in tl inside Beetle.
    -> list of cycles per call (the empty-call overhead is NOT subtracted; see bench_overhead())"""
    sys.path.insert(0, os.path.join(ROOT, "work", "kiko"))
    from xvemu import XV
    code, s = assemble(os.path.join(HERE, "bench.S"), DRV)
    res = []
    for k in range(0, len(tl), MAXT):
        chunk = tl[k:k + MAXT]
        e = XV(); e.step(5); e.loadst(state)
        for a, d in patches: e.poke(a, d)
        o2 = struct.unpack_from("<I", data, 8)[0]
        e.poke(FILEBASE, data + bytes(64))
        e.poke(SECTAB, bytes(0x28 * 4)); e.poke(SECTAB + 4 * slot, struct.pack("<I", FILEBASE + o2))
        lst = struct.pack("<I", len(chunk)) + b"".join(struct.pack("<2I", FILEBASE + o2 + off, n) for off, n in chunk)
        e.poke(LIST, lst)
        e.poke(DRV, code)
        e.poke(s["CFG"], struct.pack("<6I", LIST, RES, func, model, DST, 0))
        e.poke(0x80011960, struct.pack("<2I", 0x08000000 | ((s["bench"] >> 2) & 0x3FFFFFF), 0))
        for f in range(100000):
            e.step(5)
            if e.u32(s["CFG"] + 20) == 1: break
        r = e.ram(RES, 4 * len(chunk))
        for i in range(len(chunk)):
            fine, coarse = struct.unpack_from("<2H", r, 4 * i)
            fine *= 8
            wraps = max(0, round((coarse * HB_CYC - fine) / 524288.0))
            res.append(fine + 524288 * wraps)
        del e
    return res
