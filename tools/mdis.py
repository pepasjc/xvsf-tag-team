"""MIPS disassembly over a 2MB RAM dump (overlays included).

    python mdis.py at 0x80012345 [n]       disassemble
    python mdis.py fn 0x80012345           whole enclosing function
    python mdis.py const 0x800d1000        lui+lo pairs building a constant
    python mdis.py calls 0x80012345        jal sites (and j) to an address
    python mdis.py word 0x800d1000         data words equal to value (pointer tables)
    python mdis.py str TEXT                ascii search
MDIS_RAM=path picks another dump (default work/ram_fight_maybe.bin).
"""
import os, struct, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RAM = os.environ.get("MDIS_RAM", os.path.join(ROOT, "work", "ram_fight_maybe.bin"))
_d = open(RAM, "rb").read()
LO, HI = 0x10000, 0x200000


def word(a):
    return struct.unpack_from("<I", _d, a & 0x1fffff)[0]


def dis(addr, count=32):
    import capstone
    m = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    m.skipdata = True
    o = addr & 0x1fffff
    for ins in m.disasm(_d[o:o + count * 4], addr):
        yield ins.address, ins.mnemonic, ins.op_str


def show(addr, count=32):
    for a, mn, ops in dis(addr, count):
        print(f"{a:08x}  {word(a):08x}  {mn:<8s} {ops}")


def is_prologue(w):
    return (w >> 16) == 0x27BD and (w & 0xFFFF) >= 0x8000


def func_start(addr, limit=0x1000):
    a = addr & ~3
    for _ in range(limit):
        if is_prologue(word(a)):
            return a
        a -= 4
    return None


def func_end(start, limit=0x2000):
    a = start
    for _ in range(limit):
        a += 4
        if word(a) == 0x03E00008:            # jr ra
            # continue if more code follows before next prologue (multi-exit)
            b = a + 8
            while word(b) == 0: b += 4
            if is_prologue(word(b)) or b - a > 64:
                return a + 8
    return a


def find_const(value, lo=LO, hi=HI):
    h, l = (value >> 16) & 0xFFFF, value & 0xFFFF
    hadj = (h + 1) & 0xFFFF
    MEM = (0x23, 0x2B, 0x21, 0x25, 0x29, 0x28, 0x20, 0x24)
    out = []
    for off in range(lo, hi - 4, 4):
        w = struct.unpack_from("<I", _d, off)[0]
        if (w >> 26) != 0x0F: continue
        imm, reg = w & 0xFFFF, (w >> 16) & 0x1F
        if imm not in (h, hadj): continue
        signed = imm == hadj
        for k in range(1, 9):
            p = off + 4 * k
            w2 = struct.unpack_from("<I", _d, p)[0]
            op2, rs, imm2 = w2 >> 26, (w2 >> 21) & 0x1F, w2 & 0xFFFF
            if rs != reg: continue
            if (op2 == 0x09 or op2 in MEM) and imm2 == l and ((imm2 >= 0x8000) == signed or h == hadj):
                out.append((0x80000000 + off, 0x80000000 + p, reg))
            elif op2 == 0x0D and not signed and imm2 == l:
                out.append((0x80000000 + off, 0x80000000 + p, reg))
            break
    return out


def calls(target, lo=LO, hi=HI):
    t = (target >> 2) & 0x03FFFFFF
    out = []
    for off in range(lo, hi - 4, 4):
        w = struct.unpack_from("<I", _d, off)[0]
        if w == (0x0C000000 | t) or w == (0x08000000 | t):
            out.append(0x80000000 + off)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "at":
        show(int(sys.argv[2], 16), int(sys.argv[3]) if len(sys.argv) > 3 else 32)
    elif cmd == "fn":
        s = func_start(int(sys.argv[2], 16)); e = func_end(s)
        print(f"; function {s:08x}-{e:08x}")
        show(s, (e - s) // 4)
    elif cmd == "const":
        for lui, sec, reg in find_const(int(sys.argv[2], 16)):
            fn = func_start(lui)
            print(f"{lui:08x}+{sec:08x} reg={reg} fn={fn and f'{fn:08x}'}")
    elif cmd == "calls":
        for a in calls(int(sys.argv[2], 16)):
            fn = func_start(a)
            print(f"{a:08x} fn={fn and f'{fn:08x}'}")
    elif cmd == "word":
        v = struct.pack("<I", int(sys.argv[2], 16)); p = _d.find(v)
        while p >= 0:
            if p % 4 == 0: print(f"{0x80000000+p:08x}")
            p = _d.find(v, p + 1)
    elif cmd == "str":
        k = sys.argv[2].encode(); p = _d.find(k)
        while p >= 0:
            s = p
            while s > 0 and 32 <= _d[s - 1] < 127: s -= 1
            e = _d.find(b"\0", p)
            print(f"{0x80000000+s:08x} {_d[s:e].decode('ascii','replace')}")
            p = _d.find(k, e)
