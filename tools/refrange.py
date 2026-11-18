"""Find lui+lo pairs whose value lands in [lo,hi). python refrange.py 0x8003d900 0x8003e190"""
import sys, struct, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdis
lo, hi = int(sys.argv[1], 16), int(sys.argv[2], 16)
d = mdis._d
MEM = {0x23: 'lw', 0x2B: 'sw', 0x21: 'lh', 0x25: 'lhu', 0x29: 'sh', 0x28: 'sb', 0x20: 'lb', 0x24: 'lbu', 0x09: 'addiu', 0x0D: 'ori'}
for off in range(0x10000, 0x200000 - 4, 4):
    w = struct.unpack_from("<I", d, off)[0]
    if (w >> 26) != 0x0F: continue
    imm, reg = w & 0xFFFF, (w >> 16) & 0x1F
    if not ((lo >> 16) - 1 <= imm <= (hi >> 16) + 1): continue
    for k in range(1, 12):
        w2 = struct.unpack_from("<I", d, off + 4 * k)[0]
        op2, rs, rt, imm2 = w2 >> 26, (w2 >> 21) & 0x1F, (w2 >> 16) & 0x1F, w2 & 0xFFFF
        if op2 in MEM and rs == reg:
            v = (imm << 16) + (imm2 if op2 == 0x0D else (imm2 - 0x10000 if imm2 & 0x8000 else imm2))
            if lo <= v < hi:
                fn = mdis.func_start(0x80000000 + off)
                print(f"{0x80000000+off:08x}+{k} {MEM[op2]:5s} -> {v:08x}  fn={fn and f'{fn:08x}'}")
            if op2 in (0x09, 0x0D, 0x23, 0x21, 0x25, 0x20, 0x24) and rt == reg: break
        # stop if reg overwritten by lui
        if (w2 >> 26) == 0x0F and rt == reg: break
