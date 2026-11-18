"""Load-delay check for R3000 code: a load's destination must not be read by the next executed instruction
(straight line, branch targets, the instruction after a delay slot).  lwl/lwr pairs on the same register are
allowed (the R3000 merges them).  hazards(code, org) -> list of (addr, text)."""
import capstone

LOADS = {"lb", "lbu", "lh", "lhu", "lw", "lwl", "lwr"}
BR = {"b", "beq", "bne", "beqz", "bnez", "bgez", "bgtz", "blez", "bltz", "bgezal", "bltzal", "j", "jal", "jr", "jalr", "bal"}


def _md():
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    return md


def hazards(code, org):
    md = _md()
    ins = {i.address: i for i in md.disasm(code, org)}
    STORES = {"sb", "sh", "sw", "swl", "swr"}
    ALLREAD = STORES | BR | {"mult", "multu", "div", "divu", "mthi", "mtlo", "mtc0", "mtc2", "ctc2", "teq", "tne"}
    def reads(i):
        s = set()
        for k, o in enumerate(i.operands):
            if o.type == capstone.mips.MIPS_OP_REG:
                if k > 0 or i.mnemonic in ALLREAD or i.mnemonic in ("lwl", "lwr"): s.add(i.reg_name(o.reg))
            elif o.type == capstone.mips.MIPS_OP_MEM:
                s.add(i.reg_name(o.mem.base))
        return s
    def target(i):
        if i.mnemonic in BR and i.mnemonic not in ("jr", "jalr"):
            op = i.operands[-1]
            if op.type == capstone.mips.MIPS_OP_IMM: return op.imm & 0xffffffff
        return None
    out = []
    for a, i in ins.items():
        if i.mnemonic not in LOADS: continue
        dst = i.reg_name(i.operands[0].reg)
        if dst == "zero": continue
        prev = ins.get(a - 4)
        nexts = []
        if prev is not None and prev.mnemonic in BR:       # load in a delay slot: next = target and/or fall-through
            t = target(prev)
            if t is not None: nexts.append(t)
            if prev.mnemonic not in ("b", "j", "jr"): nexts.append(a + 4)
            if prev.mnemonic in ("jal", "jalr", "bal"): nexts = []              # callee: unknown, caller must not rely
        else:
            nexts.append(a + 4)
        for n in nexts:
            j = ins.get(n)
            if j is None: continue
            if j.mnemonic in ("lwl", "lwr") and i.mnemonic in ("lwl", "lwr") and j.reg_name(j.operands[0].reg) == dst: continue
            if dst in reads(j): out.append((a, "%s %s -> %08x %s %s" % (i.mnemonic, i.op_str, n, j.mnemonic, j.op_str)))
    return out
