"""rc4 L1b (memory worker): sec3 dedupe with a run-time offset remap (SEC3.md section 4).

Packed sec3 section (replaces the stock section 3 of a character DSP; the DSP header is unchanged):
    u32 'S3RM'  u16 n  u16 0  n x {u16 old, u16 new}  (sorted by old)  then the packed records
  entries = the MAXIMAL read intervals [old, end) of all references (main frame table + inline streams, s3refs.py),
  new = offset of that interval's bytes inside this section.  Sorted by old, maximal intervals have increasing ends, so
  for any reference contained in some maximal interval the LAST entry with old <= off contains it too:
      remap(off) = new_i + (off - old_i),  i = last entry with old_i <= off
  (unknown references inside a known read string map correctly as well).
Run time: REMAP (position independent, 0x8000-based) is called from the two readers' load-delay `nop`
(0x8008dc38, 0x8008ffc8 -> `jal REMAP`; the following `addu v0, v0, v1` runs in the delay slot): in v0 = base + off,
v1 = off; out v0 = base + remap(off) when the section starts with 'S3RM', else unchanged.  Uses t0-t9 only.

    python l1b.py            -> per character: sizes, verification (every reference read through the simulated remap
                                equals the stock bytes), REMAP size"""
import os, sys, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__)); GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "common", "dsp"), os.path.join(GAME, "tools", "cuts"), os.path.join(GAME, "tools"), HERE,
                os.path.join(ROOT, "tools", "speed", "frame")]
import s3fmt as F

MAGIC = 0x4d523353                  # 'S3RM'
SITES = (0x8008dc38, 0x8008ffc8)    # load-delay nops before `addu v0, v0, v1` in the two readers
SITE_ADDU = 0x00431021              # addu v0, v0, v1 (checked after each site)
SRC = r"""
remap:  subu  $t0, $v0, $v1             /* section base */
        lw    $t1, 0($t0)
        lui   $t2, %hi(MAGIC)
        ori   $t2, $t2, %lo(MAGIC)
        bne   $t1, $t2, 9f
        lhu   $t6, 4($t0)               /* n (delay slot; harmless when not packed) */
        nop                             /* R3000 load delay (Unicorn does not model it; Beetle / hardware do) */
        addiu $t6, $t6, -1              /* hi */
        move  $t5, $zero                /* lo */
        addiu $t4, $t0, 8               /* entries */
1:      slt   $t7, $t6, $t5
        bnez  $t7, 2f
        addu  $t7, $t5, $t6
        srl   $t7, $t7, 1               /* mid */
        sll   $t8, $t7, 2
        addu  $t8, $t4, $t8
        lhu   $t9, 0($t8)               /* old[mid] */
        nop
        sltu  $t9, $v1, $t9             /* off < old[mid] ? */
        beqz  $t9, 3f
        nop
        b     1b
        addiu $t6, $t7, -1              /* hi = mid - 1 */
3:      b     1b
        addiu $t5, $t7, 1               /* lo = mid + 1 */
2:      bltz  $t6, 9f                   /* off below every entry: unchanged */
        sll   $t8, $t6, 2
        addu  $t8, $t4, $t8
        lhu   $t9, 0($t8)               /* old */
        lhu   $t7, 2($t8)               /* new */
        subu  $t9, $v1, $t9
        addu  $t7, $t7, $t9
        addu  $v0, $t0, $t7
9:      jr    $ra
        nop
"""


def build(org=0x80000000):
    from gas import gas
    code, sym = gas(SRC, org, {"MAGIC": MAGIC})
    return code, sym


def remap_sim(sec, off):
    if struct.unpack_from("<I", sec, 0)[0] != MAGIC: return off
    n = struct.unpack_from("<H", sec, 4)[0]
    lo, hi = 0, n - 1
    while lo <= hi:
        mid = (lo + hi) >> 1
        if off < struct.unpack_from("<H", sec, 8 + 4 * mid)[0]: hi = mid - 1
        else: lo = mid + 1
    if hi < 0: return off
    old, new = struct.unpack_from("<HH", sec, 8 + 4 * hi)
    return new + off - old


def refs(c, partA=None):
    """{old offset: read end} of every reference: main frame table (from partA when given: --redcut / --wmhover change
    the groups and thereby the part counts) + every inline-stream candidate (s3refs.scan)"""
    import s3refs, animtab
    a, s3, g, main, other = s3refs.scan(c)
    b = partA if partA is not None else a.b
    rd = {}
    for i in range(a.B + a.h[2], a.B + a.h[3], 4):
        so, o = struct.unpack_from("<HH", b, i)
        if o == 0xffff: continue
        e, re, it, st = F.walk_engine(s3, o, g[so]); assert st == "ok", (c, hex(i), so, o)
        rd[o] = max(rd.get(o, o), re)
    for q, so, o, n, re in other: rd[o] = max(rd.get(o, o), re)
    return s3, rd


def pack(s3, rd):
    iv = sorted(rd.items())
    mx = []                                          # maximal intervals (not contained in another)
    for o, e in sorted(iv, key=lambda x: (x[0], -x[1])):
        if mx and e <= mx[-1][1]: continue
        mx.append((o, e))
    ends = [e for o, e in mx]; assert ends == sorted(ends) and len(set(o for o, e in mx)) == len(mx)
    strs = sorted({s3[o:e] for o, e in mx}, key=lambda s: (-len(s), s))
    keep = []
    for s in strs:
        if not any(s in k for k in keep): keep.append(s)
    while True:                                      # greedy suffix / prefix overlap
        best = (0, None, None)
        for i, x in enumerate(keep):
            for j, y in enumerate(keep):
                if i == j: continue
                for k in range(min(len(x), len(y)) - 1, best[0], -1):
                    if x.endswith(y[:k]): best = (k, i, j); break
        k, i, j = best
        if not k: break
        x, y = keep[i], keep[j]; keep = [s for n_, s in enumerate(keep) if n_ not in (i, j)] + [x + y[k:]]
    body = b"".join(keep)
    H = 8 + 4 * len(mx)
    ent = []
    for o, e in mx:
        p = body.find(s3[o:e]); assert p >= 0
        assert H + p < 0x10000
        ent.append(struct.pack("<HH", o, H + p))
    sec = struct.pack("<IHH", MAGIC, len(mx), 0) + b"".join(ent) + body
    for o, e in rd.items():                          # verify: every reference through the simulated remap
        r = remap_sim(sec, o); assert sec[r:r + (e - o)] == s3[o:e], (o, e)
    return sec, len(mx)


_CACHE = {}


def packed(c, partA=None):
    """-> (stock sec3, packed section) per character (memoized per code item); (None, None) = not packed (no standard
    animation blob, e.g. Onslaught 0x11: its sets keep the stock section, REMAP passes them through)"""
    import hashlib
    key = (c, hashlib.md5(partA).hexdigest() if partA is not None else None)
    if key not in _CACHE:
        try: s3, rd = refs(c, partA)
        except ValueError: _CACHE[key] = (None, None); return _CACHE[key]
        _CACHE[key] = (s3, pack(s3, rd)[0] if s3 else s3)
    return _CACHE[key]


def replace_sec3(x, c, partA=None):
    """DSP bytes x (any tier; sec3 = stock, last section) -> same DSP with the packed sec3"""
    k, o0, o1, o2, o3 = struct.unpack_from("<5I", x)
    s3, sec = packed(c, partA)
    if s3 is None or not s3: return x
    assert x[o3:] == s3, (c, "sec3 not stock")
    return x[:o3] + sec


def main():
    import dsp as D
    code, sym = build()
    print("REMAP %d B" % len(code))
    T = collections.Counter()
    for c in D.char_ids("mvc"):
        try: s3, rd = refs(c)
        except Exception as ex: continue
        if not s3: continue
        sec, n = pack(s3, rd)
        T["s3"] += len(s3); T["new"] += len(sec)
        print("%02x sec3 %6d -> %6d (map %4d entries = %4d B)  gain %6d" % (c, len(s3), len(sec), n, 8 + 4 * n, len(s3) - len(sec)))
    print("ALL", dict(T), "gain", T["s3"] - T["new"])


if __name__ == "__main__":
    main()
