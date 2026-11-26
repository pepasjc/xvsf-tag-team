"""rc3 cut-in hang fix, variant "A-chunked" (memory worker; SPEED_TEAM.md, orchestrator decision (A)).

Stock (0x80045180): codec(src = *(0x80092be8) + 0x400, dst = arena 0x80092c40, 28,800 B), then at 0x800451ac
LoadImage({642, 258, 60, 240}, arena).  The 28,800 B reach 0x80099d40 and wipe the --postvc SPVC portraits
(0x80095c40..0x8009a8a4) -> a later portrait draw reads garbage -> hang.
Fix: CUTIN replaces the jal at 0x80045180: the image is decoded in bands of BAND rows (120 B per row) into the arena
HEAD only (BAND * 120 + 16 < 0x3000 = the bytes below the SPVC area) and uploaded band by band:
    loop: codec(src, buf + carry, n - carry)            stock codec entry 0x8001bd48; its RLE route returns
                                                         a0 = next source byte + 1 (pipelined control fetch),
                                                         a1 = output end (a run may overrun n)
          LoadImage({642, 258 + row, 60, rows}, buf); DrawSync(0)
          carry = a1 - (buf + n): move those <= 15 overrun bytes to buf (the next band's first bytes)
0x800451ac `jal LoadImage` -> nop (its delay slot `sh v0, 0x2e(sp)` stays, harmless).
Result: the same VRAM image, the SPVC area never written.  Position independent (calls by absolute jal).
    python cutinfix.py       -> size + Python model check (bands vs one-shot decode) on the cut-in streams found in
                                the RAM dumps given as arguments (optional)"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "..", "..", "..", "tools", "speed", "frame"), os.path.join(HERE, "..", "..", "..", "..", "common", "dsp")]
SITE_DEC, SITE_LI = 0x80045180, 0x800451ac
W_DEC, W_LI = 0x0c0116a0, 0x0c0046c4            # jal 0x80045a80, jal 0x80011b10
CODEC, LOADIMAGE, DRAWSYNC, ARENA = 0x8001bd48, 0x80011b10, 0x80011864, 0x80092c40
BAND, ROWB, ROWS, X, Y, WH = 100, 120, 240, 642, 258, 60
assert BAND * ROWB + 16 <= 0x3000
SRC = r"""
cutin:  addiu $sp, $sp, -48
        sw    $ra, 16($sp)
        sw    $s0, 20($sp)
        sw    $s1, 24($sp)
        sw    $s2, 28($sp)
        sw    $s3, 32($sp)
        move  $s0, $a1                  /* source */
        move  $s1, $zero                /* row */
        move  $s2, $zero                /* carry bytes already at the buffer start */
1:      li    $s3, ROWS
        subu  $s3, $s3, $s1
        slti  $t0, $s3, BAND + 1
        bnez  $t0, 2f
        nop
        li    $s3, BAND                 /* rows of this band */
2:      li    $t0, ROWB
        mult  $s3, $t0
        mflo  $t1                       /* n */
        sw    $t1, 36($sp)
        move  $a0, $s0
        lui   $a1, %hi(ARENA)
        addiu $a1, $a1, %lo(ARENA)
        addu  $a1, $a1, $s2
        jal   CODEC
        subu  $a2, $t1, $s2
        addiu $s0, $a0, -1              /* next source byte: the codec loop is pipelined, it has already
                                           fetched the next op's control byte (a0 = next + 1) */
        lw    $t1, 36($sp)
        lui   $t2, %hi(ARENA)
        addiu $t2, $t2, %lo(ARENA)
        addu  $t3, $t2, $t1             /* buf + n */
        subu  $s2, $a1, $t3             /* overrun = next carry */
        bgez  $s2, 3f
        nop
        move  $s2, $zero
3:      li    $t0, X
        sh    $t0, 40($sp)
        li    $t0, Y
        addu  $t0, $t0, $s1
        sh    $t0, 42($sp)
        li    $t0, WH
        sh    $t0, 44($sp)
        sh    $s3, 46($sp)
        addiu $a0, $sp, 40
        jal   LOADIMAGE
        move  $a1, $t2
        jal   DRAWSYNC
        move  $a0, $zero
        beqz  $s2, 5f                   /* carry: buf[n .. n + carry) -> buf[0 ..) */
        lw    $t1, 36($sp)
        lui   $t2, %hi(ARENA)
        addiu $t2, $t2, %lo(ARENA)
        addu  $t3, $t2, $t1
        move  $t4, $s2
4:      lbu   $t5, 0($t3)
        addiu $t3, $t3, 1
        addiu $t4, $t4, -1
        sb    $t5, 0($t2)
        bnez  $t4, 4b
        addiu $t2, $t2, 1
5:      addu  $s1, $s1, $s3
        slti  $t0, $s1, ROWS
        bnez  $t0, 1b
        nop
        lw    $ra, 16($sp)
        lw    $s0, 20($sp)
        lw    $s1, 24($sp)
        lw    $s2, 28($sp)
        lw    $s3, 32($sp)
        jr    $ra
        addiu $sp, $sp, 48
"""


def build(org):
    from gas import gas
    return gas(SRC, org, dict(CODEC=CODEC, LOADIMAGE=LOADIMAGE, DRAWSYNC=DRAWSYNC, ARENA=ARENA, BAND=BAND, ROWB=ROWB, ROWS=ROWS, X=X, Y=Y, WH=WH))


def patches(org):
    """[(addr, bytes)] of the EXE hook words for an image at org"""
    j = struct.pack("<I", 0x0c000000 | (org >> 2 & 0x3ffffff))
    return [(SITE_DEC, j), (SITE_LI, bytes(4))]


def model(src, pos):
    """bands exactly as the MIPS: -> (image bytes, source bytes used)"""
    import dsp as D
    out = b""; carry = b""; p = pos; row = 0
    while row < ROWS:
        rows = min(BAND, ROWS - row); n = rows * ROWB
        need = n - len(carry)
        raw, used, over = D.rle_decode(src, p, need)
        # the decoder's real output includes the overrun (rle_decode trims it): recompute the over bytes
        full, used2, over2 = D.rle_decode(src, p, need + over) if over else (raw, used, 0)
        band = carry + full
        out += band[:n]; carry = band[n:n + over]; p += used; row += rows
    return out, p - pos


if __name__ == "__main__":
    code, sym = build(0x80000000)
    print("CUTIN %d B" % len(code))
    import dsp as D
    for f in sys.argv[1:]:
        m = open(f, "rb").read(); u = lambda a: struct.unpack_from("<I", m, a & 0x1fffff)[0]
        src = u(0x80092be8) + 0x400
        full, used, over = D.rle_decode(m, src & 0x1fffff, 28800)
        img, used2 = model(m, src & 0x1fffff)
        print(f, "src %08x one-shot %d B used %d, bands equal: %s" % (src, len(full), used, img == full))
