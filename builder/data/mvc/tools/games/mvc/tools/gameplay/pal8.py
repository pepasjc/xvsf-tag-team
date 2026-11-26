"""Stage 8 palette rows in VRAM (`mktag.py --pal8`, needs --kocache; speed worker 2026-11-19).

Stage 8 (BG08.ARC) keeps 24 KB of fade palette rows in its init data (0x800a0480..0x800a6280): 752 CLUT rows of 16
colours in 4 banks (EXE bank-base table 0x8006e2f4[bank / 4] -> per-stage array -> [8]), LoadImage'd from RAM at every
step of the sunset / night fades (stage-8 path of the frame apply 0x8003c464: entries {u16 dst bank, dst line, src
bank, src row}, last entry dst bank | 0x80; 0x8003c584 `jal 0x8003b5c8` -> 0x80021d68 LoadImage).  Here:
  * build: every referenced row gets a compact index; the fade entries are rewritten to (src bank 0, row = compact
    index); the 24 KB block is cut from entry 0 (stagelite.rebuild relocates the stage's own pointers; the EXE words
    of the type-0xd8 descriptor table 0x80078190 for subs 5-7 / 20-24 are relocated here); the rows go to the disc as
    3 items of <= 8 KB.
  * runtime (code in the kocache sector after the KO code, 0x8000F4D0-, loaded by tl_main): P8UP reads the 3 items
    into a buffer and LoadImage's them into free VRAM (memory worker's map, phase-8 free areas): rows 0-511 at
    x 128-383 y 480-511 (16 rows per line), rows 512- at x 960-1023 y 432- (4 per line, <= 40 lines: y 472-511 of that
    column stays for --vcache).  tl_main calls P8UP for stage 8 and writes two hooks: 0x8003c584 `jal P8MV` (fade
    step: MoveImage VRAM row -> CLUT row) and the battle-load site 0x8002b528 `jal P8HC` (every later stage load,
    rematch included: P8UP when the stage is 8, then heapcap); fade lists packed (P8AP at 0x8003c51c).  Bank-12 base of stage 8 -> 0x80000000 (all entries use bank 12), so the fade
    path hands P8MV a0 = 0x80000000 + 32 * compact index.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "speed", "frame")]
import stagelite as SL
from gas import gas

ST = 8
CUT = (0x800a0480, 0x800a6280)
BANKTAB, DESCTAB = 0x8006e2f4, 0x80078190
SUBS = (5, 6, 7, 20, 21, 22, 23, 24)
VBASE = 0x80000000
VBANK = 12                                          # bank 0's per-stage array = EXE_PAL (initial CLUTs): not usable
LOADIMAGE, MOVEIMAGE, DRAWSYNC = 0x80011b10, 0x80011bd0, 0x80011864
FADESITE, FADEW = 0x8003c584, 0x0c00ed72          # jal 0x8003b5c8
HSITE = 0x8002b528
RDF, SPARE = 0x80024800, 0x1ab
FTAB_SPARE = 0x800255e4 + 8 * SPARE
STAGEB = 0x8007bdd9
BUFHC = 0x80092c40                                  # tile arena (free during a battle load; --vcache code from 0x80094f40)
A_X, A_Y, B_X, B_Y = 128, 480, 960, 432


def _w(b, a): return struct.unpack_from("<I", b, a - SL.BASE)[0]
def _h(b, a): return struct.unpack_from("<H", b, a - SL.BASE)[0]


def analyse(b, exe_word):
    """b = stock BG08.ARC -> (entries [(file addr of the src fields)], {(bank, row): compact}, rows bytes)"""
    base = {k: exe_word(exe_word(BANKTAB + k) + 4 * ST) for k in (0, 4, 8, 12)}
    frames = set()
    for s in SUBS:
        p = exe_word(DESCTAB + 4 * s)
        while True:
            frames.add(_w(b, p)); w1 = _w(b, p + 4)
            if w1 & 0x8000: break
            p += 8
    ents = []; m = {}
    for f in sorted(frames):
        p = f
        while True:
            db, sb, si = _h(b, p), _h(b, p + 4) & 0xfffc, _h(b, p + 6)
            key = (sb, si)
            if key not in m: m[key] = len(m)
            ents.append((p + 4, key))
            p += 8
            if db & 0x80: break
    rows = b""
    for (sb, si), k in sorted(m.items(), key=lambda kv: kv[1]):
        a = base[sb] + 32 * si
        rows += b[a - SL.BASE:a - SL.BASE + 32]
    assert len(m) <= 512 + 160, len(m)
    return ents, m, rows, base


FR = (0x800a6280, 0x800a79c0)                     # the 49 fade frame lists (8-B entries), packed by stage_file
APSITE, APW = 0x~~~~~~~~, (0x~~~~~~~~, 0x~~~~~~~~)  # stage-8 branch of the frame apply: lw s1,0x3c(s2); lui v0,0x8007
APRET = 0x8003c5a8                                  # its epilogue


def frames_of(b, exe_word):
    """-> {frame addr: [(dst palette index, (src bank, src row))]}, [(record addr of a frame pointer, frame addr)]"""
    fr = {}; recs = []
    for s in SUBS:
        p = exe_word(DESCTAB + 4 * s)
        while True:
            f = _w(b, p); recs.append((p, f)); w1 = _w(b, p + 4)
            if f not in fr:
                q = f; ents = []
                while True:
                    db, dl, sb, si = _h(b, q), _h(b, q + 2), _h(b, q + 4) & 0xfffc, _h(b, q + 6)
                    a1 = (db & 0x7f) >> 2
                    pal = (a1 + 1 if a1 > 0 else 0) * 32 + dl          # as 0x8003c544..0x8003c588
                    assert pal < 256
                    ents.append((pal, (sb, si))); q += 8
                    if db & 0x80: break
                fr[f] = ents
            if w1 & 0x8000: break
            p += 8
    return fr, recs


def pack(fr, m, at):
    """packed frames at address `at` (original coordinates): destination lists (u8 palette indices, shared), then per
    frame {u8 count, u8 0, s16 offset to its list (from the frame), u16 compact row x count}  -> (bytes, {old: new})"""
    lists = {}; blob = b""
    for f in sorted(fr):
        d = bytes(p for p, k in fr[f])
        if d not in lists: lists[d] = len(blob); blob += d
    blob += bytes(-len(blob) % 4)
    addr = {}
    for f in sorted(fr):
        ents = fr[f]; d = bytes(p for p, k in ents)
        here = len(blob)
        blob += struct.pack("<BBh", len(ents), 0, lists[d] - here) + b"".join(struct.pack("<H", m[k]) for p, k in ents)
        blob += bytes(-len(blob) % 4)
        addr[f] = at + here
    return blob, addr


def stage_file(read, exe_word):
    """-> (new BG08.ARC, [(EXE addr, bytes)], rows, report)"""
    b = bytearray(read("BG08.ARC"))
    ents, m, rows, base = analyse(bytes(b), exe_word)
    fr, recs = frames_of(bytes(b), exe_word)
    span = sorted((f, f + 8 * len(e)) for f, e in fr.items())
    assert span[0][0] == FR[0] and span[-1][1] == FR[1] and all(a[1] == c[0] for a, c in zip(span, span[1:])), "frame lists not contiguous"
    blob, addr = pack(fr, m, FR[0])
    assert len(blob) < FR[1] - FR[0]
    b[FR[0] - SL.BASE:FR[0] - SL.BASE + len(blob)] = blob
    for rec, f in recs:                                  # descriptor records -> the packed frames
        struct.pack_into("<I", b, rec - SL.BASE, addr[f])
    cut2 = (FR[0] + len(blob), FR[1])
    new, rep = SL.rebuild(bytes(b), [CUT, cut2], stage=ST)
    assert not rep["bad"], rep["bad"][:4]
    f_ = SL.mapper([CUT, cut2])
    exe = [(a, struct.pack("<I", n)) for a, o, n in rep["exe"]]
    for s_ in SUBS:                                      # descriptor table words of the stage-8 subs
        a = DESCTAB + 4 * s_; o = exe_word(a)
        assert FR[1] <= o < 0x800c0000, hex(o)
        exe.append((a, struct.pack("<I", f_(o))))
    exe.append((exe_word(BANKTAB + VBANK) + 4 * ST, struct.pack("<I", VBASE)))   # virtual bank base (P8MV's test)
    assert exe_word(BANKTAB) != exe_word(BANKTAB + VBANK)
    rep["packed"] = len(blob)
    return new, exe, rows, rep


SRC = r"""
P8:     .word   P8MAGIC
/* P8UP(a0 = buffer >= 8 KB): the 3 row items -> buffer -> LoadImage into VRAM, DrawSync after each */
P8UP:   addiu   $sp, $sp, -48
        sw      $ra, 40($sp)
        sw      $s0, 36($sp)
        sw      $s1, 32($sp)
        sw      $s2, 28($sp)
        move    $s2, $a0
        lui     $t8, %hi(FTAB_SPARE)
        lw      $t0, %lo(FTAB_SPARE)($t8)
        lw      $t1, %lo(FTAB_SPARE + 4)($t8)
        sw      $t0, 16($sp)
        sw      $t1, 20($sp)
        lui     $s0, %hi(P8TAB)
        addiu   $s0, $s0, %lo(P8TAB)
        li      $s1, 3
1:      lw      $t0, 0($s0)                     /* msf */
        lw      $t1, 4($s0)                     /* size */
        lui     $t8, %hi(FTAB_SPARE)
        beqz    $t1, 2f
        sw      $t0, %lo(FTAB_SPARE)($t8)
        sw      $t1, %lo(FTAB_SPARE + 4)($t8)
        move    $a1, $s2
        jal     RDF
        li      $a0, SPARE
        addiu   $a0, $s0, 8                     /* RECT x, y, w, h */
        jal     LOADIMAGE
        move    $a1, $s2
        jal     DRAWSYNC
        move    $a0, $zero
2:      addiu   $s1, $s1, -1
        bnez    $s1, 1b
        addiu   $s0, $s0, 16
        lw      $t0, 16($sp)
        lw      $t1, 20($sp)
        lui     $t8, %hi(FTAB_SPARE)
        sw      $t0, %lo(FTAB_SPARE)($t8)
        sw      $t1, %lo(FTAB_SPARE + 4)($t8)
        lw      $ra, 40($sp)
        lw      $s0, 36($sp)
        lw      $s1, 32($sp)
        lw      $s2, 28($sp)
        jr      $ra
        addiu   $sp, $sp, 48

/* battle-load hook (0x8002b528, was jal heapcap): stage 8 -> rows to VRAM again, then heapcap(a0, a1) */
P8HC:   lui     $t0, %hi(STAGEB)
        lbu     $t0, %lo(STAGEB)($t0)
        li      $t1, 8
        bne     $t0, $t1, 3f
        nop
        addiu   $sp, $sp, -32
        sw      $ra, 16($sp)
        sw      $a0, 20($sp)
        sw      $a1, 24($sp)
        lui     $a0, %hi(BUFHC)
        jal     P8UP
        addiu   $a0, $a0, %lo(BUFHC)
        lw      $ra, 16($sp)
        lw      $a0, 20($sp)
        lw      $a1, 24($sp)
        addiu   $sp, $sp, 32
3:      j       HEAPCAP
        nop

/* fade step (0x8003c584, was jal 0x8003b5c8(src, palette index, rows = 1)): a0 = VBASE + 32 * row -> MoveImage */
P8MV:   srl     $t0, $a0, 16
        lui     $t1, 0x8000 >> 0
        srl     $t1, $t1, 16
        bne     $t0, $t1, 9f
        andi    $t0, $a0, 0xffff
        srl     $t0, $t0, 5                     /* row */
        addiu   $sp, $sp, -32
        sw      $ra, 24($sp)
        sltiu   $t1, $t0, 512
        beqz    $t1, 4f
        andi    $t2, $t0, 15
        sll     $t2, $t2, 4
        addiu   $t2, $t2, A_X                   /* x */
        srl     $t3, $t0, 4
        b       5f
        addiu   $t3, $t3, A_Y                   /* y */
4:      addiu   $t0, $t0, -512
        andi    $t2, $t0, 3
        sll     $t2, $t2, 4
        addiu   $t2, $t2, B_X
        srl     $t3, $t0, 2
        addiu   $t3, $t3, B_Y
5:      sh      $t2, 16($sp)
        sh      $t3, 18($sp)
        li      $t4, 16
        sh      $t4, 20($sp)
        li      $t4, 1
        sh      $t4, 22($sp)
        srl     $a2, $a1, 5                     /* destination CLUT row (as 0x80021d68) */
        andi    $t5, $a1, 31
        sll     $a1, $a2, 4
        addiu   $a2, $t5, 480
        jal     MOVEIMAGE
        addiu   $a0, $sp, 16
        lw      $ra, 24($sp)
        nop
        jr      $ra
        addiu   $sp, $sp, 32
9:      j       ORIGPAL
        nop

/* stage-8 frame apply (0x8003c51c `j P8AP`, inside 0x8003c464: s2 = object, s0-s3 / ra saved by it): packed frame
   {u8 count, u8 0, s16 list offset, u16 rows} -> P8MV(VBASE + 32 * row, palette index) per entry, then its epilogue */
P8AP:   lw      $s1, 0x3c($s2)
        nop
        lbu     $s3, 0($s1)
        lh      $t0, 2($s1)
        addiu   $s0, $s1, 4
        addu    $s1, $s1, $t0
6:      lhu     $a0, 0($s0)
        lbu     $a1, 0($s1)
        sll     $a0, $a0, 5
        lui     $t0, 0x8000
        jal     P8MV
        or      $a0, $a0, $t0
        addiu   $s3, $s3, -1
        addiu   $s0, $s0, 2
        bnez    $s3, 6b
        addiu   $s1, $s1, 1
        j       APRET
        nop

        .align  2
/* 3 items {msf, size, RECT (x, y, w, h)} - filled by mktag */
P8TAB:  .word   0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0
P8END:
"""


def code(at, heapcap):
    syms = dict(P8MAGIC=0x38414c50, FTAB_SPARE=FTAB_SPARE, RDF=RDF, SPARE=SPARE, LOADIMAGE=LOADIMAGE, MOVEIMAGE=MOVEIMAGE,
                DRAWSYNC=DRAWSYNC, STAGEB=STAGEB, BUFHC=BUFHC, HEAPCAP=heapcap, ORIGPAL=0x8003b5c8, A_X=A_X, A_Y=A_Y,
                B_X=B_X, B_Y=B_Y, APRET=APRET)
    c, s = gas(SRC, at, syms)
    assert len(c) == s["P8END"] - at
    return c, s


def table(fents, nrows):
    """fents = [(msf, size)] of the 3 items -> P8TAB bytes"""
    rects = [(A_X, A_Y, 256, min(16, (min(nrows, 256) + 15) // 16)), (A_X, A_Y + 16, 256, max(0, (min(nrows, 512) - 256 + 15) // 16)),
             (B_X, B_Y, 64, max(0, (nrows - 512 + 3) // 4))]
    out = b""
    for (m, sz), (x, y, w, h) in zip(fents, rects):
        out += struct.pack("<2I4H", m, sz, x, y, w, h)
    return out


def items(rows):
    """rows bytes -> the 3 disc items (VRAM image order: area A 16 rows per line, area B 4 rows per line)"""
    n = len(rows) // 32
    a = rows[:256 * 32]; b = rows[256 * 32:512 * 32]; c = rows[512 * 32:]
    c += bytes(-len(c) % (4 * 32))
    return [a, b, c], n
