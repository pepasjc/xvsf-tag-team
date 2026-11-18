"""Find load/store instructions with a given struct offset. python offref.py 0x230 [s|l|all] [lo hi]"""
import sys, struct, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdis
off = int(sys.argv[1], 16); mode = sys.argv[2] if len(sys.argv) > 2 else "all"
lo = int(sys.argv[3], 16) & 0x1fffff if len(sys.argv) > 3 else 0x10000
hi = int(sys.argv[4], 16) & 0x1fffff if len(sys.argv) > 4 else 0x200000
ST = {0x28: 'sb', 0x29: 'sh', 0x2B: 'sw'}; LD = {0x20: 'lb', 0x24: 'lbu', 0x21: 'lh', 0x25: 'lhu', 0x23: 'lw'}
d = mdis._d
for o in range(lo, hi, 4):
    w = struct.unpack_from("<I", d, o)[0]
    op = w >> 26
    if (w & 0xFFFF) != off: continue
    rs = (w >> 21) & 31
    if rs in (0, 28, 29, 1): continue
    if op in ST and mode in ("s", "all") or op in LD and mode in ("l", "all"):
        fn = mdis.func_start(0x80000000 + o)
        print(f"{0x80000000+o:08x} {(ST.get(op) or LD.get(op)):4s} r{(w>>16)&31},0x{off:x}(r{rs}) fn={fn and f'{fn:08x}'}")
