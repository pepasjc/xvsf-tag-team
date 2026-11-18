"""Static call graph over a RAM dump (control-flow walk from a function entry).
    callees(ram, fn) -> (sorted jal targets, set of instruction addresses, has_jr_table)
    func_starts(ram) -> sorted list of jal targets in the dump (function entries)"""
import struct, bisect


def u32(ram, a): return struct.unpack_from("<I", ram, a & 0x1fffff)[0]


_starts_cache = {}
def func_starts(ram, lo=0x80010000, hi=0x80200000):
    """function entries: jal targets, plus the first instruction after a `jr ra` + delay slot (+ nops)
    that precedes a stack-frame prologue (addiu sp,sp,-N) within 6 instructions"""
    k = id(ram)
    if k in _starts_cache: return _starts_cache[k]
    s = set()
    W = struct.unpack_from("<%dI" % ((hi - lo) // 4), ram, lo - 0x80000000)
    for i, w in enumerate(W):
        if w >> 26 == 3:
            t = 0x80000000 | (w & 0x3ffffff) << 2
            if lo <= t < hi: s.add(t)
        if w >> 16 == 0x27bd and w & 0x8000:
            for j in range(i, max(i - 7, 1), -1):
                if W[j - 2] == 0x03e00008:
                    q = j
                    while q < i and W[q] == 0: q += 1
                    s.add(lo + 4 * q); break
    r = sorted(s); _starts_cache[k] = r; return r


def walk(ram, fn, limit=0x8000):
    starts = func_starts(ram)
    i = bisect.bisect_right(starts, fn)
    nxt = starts[i] if i < len(starts) else fn + limit
    seen, calls, todo, table = set(), set(), [fn], False
    while todo:
        a = todo.pop()
        while a not in seen and fn <= a < fn + limit:
            seen.add(a)
            w = u32(ram, a); op = w >> 26
            if op == 3:
                calls.add(0x80000000 | (w & 0x3ffffff) << 2); a += 4; continue
            if op == 2:
                t = 0x80000000 | (w & 0x3ffffff) << 2
                seen.add(a + 4)
                if fn <= t < nxt: todo.append(t)
                else: calls.add(t)                     # tail call
                break
            if op == 0 and (w & 0x3f) == 8:            # jr
                seen.add(a + 4)
                rs = (w >> 21) & 31
                if rs != 31:
                    table = True
                    for t in jump_table(ram, a, rs, fn, fn + limit): todo.append(t)
                break
            if op == 0 and (w & 0x3f) == 9:            # jalr
                a += 4; continue
            if op in (4, 5, 6, 7) or op == 1:
                off = w & 0xffff
                if off & 0x8000: off -= 0x10000
                t = a + 4 + off * 4
                todo.append(t)
                if op == 4 and (w >> 16) & 0x3ff == 0:   # beq zero,zero = b
                    seen.add(a + 4); break
            a += 4
    return sorted(calls), seen, table


def jump_table(ram, a, rs, lo, hi):
    """targets of `jr rs` at a when rs was loaded by `lw rs, L(at)` after `lui at, H` (gcc switch tables)"""
    base = None
    for k in range(1, 10):
        w = u32(ram, a - 4 * k)
        if w >> 26 == 0x23 and (w >> 16) & 31 == rs and base is None:
            br, off = (w >> 21) & 31, w & 0xffff
            if off & 0x8000: off -= 0x10000
            for j in range(k + 1, k + 8):
                w2 = u32(ram, a - 4 * j)
                if w2 >> 26 == 0x0f and (w2 >> 16) & 31 == br:
                    base = ((w2 & 0xffff) << 16) + off; break
            if base is None: return []
    if base is None or not (0x80010000 <= base < 0x80200000): return []
    out = []
    for i in range(256):
        t = u32(ram, base + 4 * i)
        if not (lo <= t < hi) or t & 3: break
        out.append(t)
    return out


def callees(ram, fn):
    c, s, t = walk(ram, fn)
    return c, s, t


def owner(ram, pc):
    """function entry containing pc (nearest jal target at or below)"""
    st = func_starts(ram)
    i = bisect.bisect_right(st, pc) - 1
    return st[i] if i >= 0 else 0
