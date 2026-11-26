"""Checker tile form, run time (fx worker; mktag --chk; data side: chkform.py).
Hook 0x8008c5cc `jal 0x8008c318` (per-part tile decode of 0x8008c45c; s0 = ctx, s3 = cell; a0 / a1 its arguments,
a1 = the part's offset in the tile arena 0x80092c40).  A kind-8 tile whose offset (ctx+0x30) has bit 21 is a record:
u32 {rle offset | phase << 31} at set + offset; CHK decodes that stream through the normal entry 0x8001bd48 (the source
lies past the coded section -> RLE route) into the arena slot, then ORs the transparent nibbles back per row
(phase 0: even rows 0xF0, odd rows 0x0F).  Everything else -> 0x8008c318 unchanged.
Code: kernel span 0x80009410-0x800094F0 (achbuild SPANS, hardware-proven; unclaimed), copied by tl_main every tag battle."""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "..", "..", "..", "tools", "speed", "frame")]
from gas import gas

AT, END = 0x80009410, 0x800094F0
SITE, STOCK = 0x8008c5cc, 0x0c0230c6           # jal 0x8008c318
SRC = r"""
CHK:    lw    $t0, 0x30($s0)
        lw    $t1, 0x18($s0)
        lui   $t2, 0x20
        and   $t2, $t0, $t2
        beqz  $t2, plain
        addiu $t1, $t1, -4
        beqz  $t1, plain                /* kind-6 set (SPU path) */
        lw    $t3, 0x44($s0)
        addiu $sp, $sp, -32
        sw    $ra, 16($sp)
        lbu   $t3, 0xd($t3)             /* set slot */
        sll   $t0, $t0, 11
        srl   $t0, $t0, 11              /* record offset */
        sll   $t3, $t3, 2
        lui   $t4, 0x8009
        addu  $t4, $t4, $t3
        lw    $t4, 0x2b30($t4)          /* pixel section of the slot */
        lui   $t5, 0x8009
        addu  $t0, $t4, $t0
        lw    $t6, 0($t0)
        addiu $t5, $t5, 0x2c40
        addu  $a1, $a1, $t5             /* dst in the arena */
        srl   $t7, $t6, 31
        sw    $t7, 20($sp)
        sw    $a1, 24($sp)
        lbu   $t8, 0x34($s0)
        lbu   $t9, 0x35($s0)
        sll   $t6, $t6, 1
        srl   $t6, $t6, 1
        addu  $a0, $t4, $t6             /* RLE stream */
        mult  $t8, $t9
        mflo  $a2
        jal   0x8001bd48
        nop
        lw    $a1, 24($sp)
        lw    $t7, 20($sp)
        lbu   $t9, 0x35($s0)            /* rows */
        beqz  $t7, 1f
        li    $t6, 0xf0                 /* (delay slot) phase 0 */
        li    $t6, 0x0f
1:      lbu   $t8, 0x34($s0)            /* row bytes */
2:      lbu   $t3, 0($a1)
        addiu $t8, $t8, -1
        or    $t3, $t3, $t6
        sb    $t3, 0($a1)
        bnez  $t8, 2b
        addiu $a1, $a1, 1
        addiu $t9, $t9, -1
        bnez  $t9, 1b
        xori  $t6, $t6, 0xff
        lw    $ra, 16($sp)
        nop
        jr    $ra
        addiu $sp, $sp, 32
plain:  j     0x8008c318
        nop
"""


def build():
    code, sym = gas(SRC, AT, {})
    assert AT + len(code) <= END, len(code)
    return code, sym


def header():
    code, sym = build()
    words = struct.unpack("<%dI" % (len(code) // 4), code)
    jl = 0x0C000000 | (sym["CHK"] >> 2 & 0x3ffffff)
    return ("#define CHK_AT 0x%08xu\n#define CHK_N %d\n#define CHK_SITE 0x%08xu\n#define CHK_HOOK 0x%08xu\n"
            "static const u32 chk_code[CHK_N] = { %s };\n" % (AT, len(words), SITE, jl, ", ".join("0x%08xu" % w for w in words)))


if __name__ == "__main__":
    c, s = build(); print("chkrt %d B at %08x (limit %d)" % (len(c), AT, END - AT))
