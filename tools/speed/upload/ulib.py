"""Shared helpers of the upload speed work (tools/speed/upload.py):
  gas(path, org, defs)  assemble a GNU-as .S file at a fixed address -> (bytes, {symbol: address})
  exe_image()           2 MB RAM image of the 1.0.1 executable (same bytes as the original disc in 0x80016000-0x8005c000)
  UC                    unicorn MIPS runner over a 2 MB RAM + scratchpad snapshot, with call stubs
  hazards()             R3000 load-delay checker (same rules as tools/speed/decode/dlib.py)"""
import os, sys, struct, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import toolenv


def gas(path, org, defs=None):
    P = toolenv.mips_prefix()
    src = open(path).read()
    with tempfile.TemporaryDirectory() as d:
        s, o, e, b = (os.path.join(d, n) for n in ("a.S", "a.o", "a.elf", "a.bin"))
        hdr = "".join(".set %s, 0x%x\n" % (k, v) for k, v in (defs or {}).items())
        open(s, "w").write(".set noreorder\n.set noat\n.text\n" + hdr + src + "\n")
        subprocess.check_call([P + "as", "-EL", "-march=r3000", "-mabi=32", "-no-mips16", "-o", o, s])
        subprocess.check_call([P + "ld", "-EL", "-Ttext=0x%x" % org, "-e", "0x%x" % org, "-o", e, o])
        subprocess.check_call([P + "objcopy", "-O", "binary", "-j", ".text", e, b])
        syms = {}
        for l in subprocess.check_output([P + "nm", e]).decode().split("\n"):
            p = l.split()
            if len(p) == 3: syms[p[2]] = int(p[0], 16) & 0xffffffff
        return open(b, "rb").read(), syms


def cc(path, org, syms, extra=(), hot=None):
    """compile a C file with -Os at a fixed address; the function in section .text.entry goes first.
    syms: {name: address} for the absolute callees.  -> (bytes, {symbol: address})"""
    P = toolenv.mips_prefix()
    with tempfile.TemporaryDirectory() as d:
        o, e, b, ld = (os.path.join(d, n) for n in ("a.o", "a.elf", "a.bin", "a.ld"))
        subprocess.check_call([P + "gcc", "-Os", "-mips1", "-G0", "-mno-abicalls", "-fno-pic", "-fno-strict-aliasing", "-ffreestanding",
                               "-fno-builtin", "-mno-gpopt", "-fno-toplevel-reorder", *extra, "-c", path, "-o", o])
        hot = hot or {}
        hs = "".join(" .%s 0x%08x : { *(.text.%s) }\n" % (k, a, k) for k, a in hot.items())
        open(ld, "w").write(("SECTIONS { . = 0x%08x; .text : { *(.text.entry) *(.text) *(.text.[!h]*) *(.text.hx*) *(.rodata*) *(.data*) *(.sdata*) }\n" % org) + hs +
                            " /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) } }\n")
        subprocess.check_call([P + "ld", "-EL", "-T", ld, *["--defsym=%s=0x%08x" % kv for kv in syms.items()], "-o", e, o])
        subprocess.check_call([P + "objcopy", "-O", "binary", "-j", ".text", e, b])
        out = {}
        for l in subprocess.check_output([P + "nm", e]).decode().split(chr(10)):
            p = l.split()
            if len(p) == 3: out[p[2]] = int(p[0], 16) & 0xffffffff
        if hot:
            segs = {}
            for k in hot:
                subprocess.check_call([P + "objcopy", "-O", "binary", "-j", "." + k, e, b + "." + k])
                segs[k] = open(b + "." + k, "rb").read()
            return open(b, "rb").read(), out, segs
        return open(b, "rb").read(), out


def exe_image():
    """RAM image (2 MB) with the original executable loaded (the 1.0.1 build has identical bytes in our ranges)"""
    import glob
    exe = open(glob.glob(os.path.join(ROOT, "disc", "files", "SLUS*"))[0], "rb").read()
    m = bytearray(0x200000)
    t = exe[0x800:]
    m[0x10000:0x10000 + len(t)] = t
    return m


REGN = "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split()
RET = 0x80000f00                      # fake return address (a 'break' lives there)


class UC:
    """Run a function from a snapshot.  stubs: {addr: python fn(uc) -> v0 or None}; a stubbed call returns at once."""
    def __init__(self, ram, scr=None):
        import unicorn as U, unicorn.mips_const as M
        self.U, self.M = U, M
        mu = self.mu = U.Uc(U.UC_ARCH_MIPS, U.UC_MODE_MIPS32 | U.UC_MODE_LITTLE_ENDIAN)
        mu.mem_map(0, 0x800000 if len(ram) > 0x200000 else 0x200000)          # 8 MB snapshots (8 MB build)
        mu.mem_write(0, bytes(ram))
        mu.mem_map(0x1f800000, 0x1000)
        if scr is not None: mu.mem_write(0x1f800000, bytes(scr))
        self.R = {n: getattr(M, "UC_MIPS_REG_" + n.upper()) for n in REGN}
        self.R["pc"] = M.UC_MIPS_REG_PC
        self.stubs = {}
        self.writes = []
        self.calls = []

    def reg(self, n, v=None):
        if v is None: return self.mu.reg_read(self.R[n]) & 0xffffffff
        self.mu.reg_write(self.R[n], v & 0xffffffff)

    def u32(self, a): return struct.unpack("<I", self.mu.mem_read(a, 4))[0]

    def run(self, fn, regs, stubs=None, limit=50_000_000, track=False):
        """regs: dict name->value; returns v0.  Every stub address is hooked; the stub's python function gets (self)
        and may return v0.  self.calls gets (addr, a0, a1, a2, a3) per stubbed call."""
        mu, U = self.mu, self.U
        stubs = stubs or {}
        for n, v in regs.items(): self.reg(n, v)
        self.reg("ra", RET)
        hooks = []
        def code(uc, addr, size, ud):
            if addr in stubs:
                a = [self.reg(r) for r in ("a0", "a1", "a2", "a3")]
                self.calls.append((addr, *a))
                v = stubs[addr](self)
                if v is not None: self.reg("v0", v)
                self.reg("pc", self.reg("ra"))
            elif addr == RET:
                uc.emu_stop()
        hooks.append(mu.hook_add(U.UC_HOOK_CODE, code))
        if track:
            def wr(uc, access, addr, size, value, ud): self.writes.append((addr, size, value & ((1 << 8 * size) - 1)))
            hooks.append(mu.hook_add(U.UC_HOOK_MEM_WRITE, wr))
        mu.emu_start(fn, 0, count=limit)
        for h in hooks: mu.hook_del(h)
        assert self.reg("pc") == RET, "did not return: pc %08x" % self.reg("pc")
        return self.reg("v0")

    def mem(self, n=0x200000): return bytes(self.mu.mem_read(0, n))
    def scr(self): return bytes(self.mu.mem_read(0x1f800000, 0x400))


def hazards(code, org):
    """load-delay violations (a load's destination read by the next instruction, also across branches) and
    mult/div issued within two instructions of mflo/mfhi.  Operand parsing (capstone has no MIPS regs_access)."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    ins = {i.address: i for i in md.disasm(code, org)}
    LOADS = {"lb", "lbu", "lh", "lhu", "lw", "lwl", "lwr", "mfc0"}
    BR = {"b", "beq", "bne", "beqz", "bnez", "bgez", "bgtz", "blez", "bltz", "bgezal", "bltzal", "j", "jal", "jr", "jalr", "bal"}
    NODEST = {"sw", "sh", "sb", "swl", "swr", "beq", "bne", "beqz", "bnez", "bgez", "bgtz", "blez", "bltz", "bgezal", "bltzal",
              "jr", "mult", "multu", "div", "divu", "mthi", "mtlo", "b", "bal", "j", "jal", "mtc0", "break", "syscall", "nop"}
    def regs(i):
        out = []
        for op in i.operands:
            if op.type == capstone.mips.MIPS_OP_REG: out.append(i.reg_name(op.reg))
            elif op.type == capstone.mips.MIPS_OP_MEM: out.append(("mem", i.reg_name(op.mem.base)))
        return out
    def rd(i):
        r = regs(i); s = set()
        for k, x in enumerate(r):
            if isinstance(x, tuple): s.add(x[1]); continue
            if k == 0 and i.mnemonic not in NODEST and i.mnemonic != "jalr": continue      # the destination
            s.add(x)
        if i.mnemonic in ("lwl", "lwr"): s.add(r[0])
        if i.mnemonic == "jalr": s.add(r[-1])
        return s
    def dest(i):
        r = regs(i)
        return r[0] if r and not isinstance(r[0], tuple) else None
    def tgt(i):
        for op in i.operands:
            if op.type == capstone.mips.MIPS_OP_IMM: return op.imm
    bad = []
    for a, i in ins.items():
        if i.mnemonic not in LOADS: continue
        d = dest(i)
        if d in (None, "zero"): continue
        nxt = []
        prev = ins.get(a - 4)
        if prev is not None and prev.mnemonic in BR:
            t = tgt(prev) if prev.mnemonic not in ("jr", "jalr") else None
            if t is not None and t in ins: nxt.append(ins[t])
            if prev.mnemonic not in ("b", "j", "jr", "jal", "jalr", "bal") and a + 4 in ins: nxt.append(ins[a + 4])
        elif a + 4 in ins: nxt.append(ins[a + 4])
        for n in nxt:
            if d in rd(n) and not (i.mnemonic in ("lwl", "lwr") and n.mnemonic in ("lwl", "lwr")):
                bad.append("%08x %s %s -> %08x %s %s" % (a, i.mnemonic, i.op_str, n.address, n.mnemonic, n.op_str))
    lst = sorted(ins)
    for k, a in enumerate(lst):
        if ins[a].mnemonic in ("mflo", "mfhi"):
            for b in lst[k + 1:k + 3]:
                if ins[b].mnemonic in ("mult", "multu", "div", "divu"): bad.append("%08x mult/div after mf" % b)
    return bad
