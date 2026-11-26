/* DSA1 tile decoder (format: common/dsp/dsa.py), MIPS R3000, gcc -O2.
 * dsa_dec(src, dst, nbytes, model): src = width byte + range-coder bytes, model = pixel-section start ('DSA1').
 * Same ABI as the game's tile decoder when entered from the dispatch (common/dsp/dsmdec.S -DDSA: a0-a2 unchanged,
 * a3 = the section): built with every callee-saved register fixed (dsatest.build checks: no $sp, no $s0-$s8, no $gp,
 * no calls), so it uses only caller-saved registers and no stack.  Writes exactly nbytes.
 * Neighbours packed in V = L | U<<4 | UL<<8 | UR<<12 | LL<<16 | UU<<20 | ULL<<24 | URR<<28.
 * Scratchpad 0x1f800300..0x1f800300 + W + 1 (W <= 248 px) and the word at 0x1f8003fc (end of the output): ONE byte per column, low nibble = row y-1 (U),
 * high nibble = row y-2 (UU); rb[x] is rewritten as the row is decoded (new pixel | U << 4), so UL / ULL come from
 * a register window (WD = L | UL<<8 | LL<<16 | ULL<<24) and UR / URR from rb[x+1], rb[x+2] (still the old row).
 * rb[W], rb[W+1] stay 0xff (UR / URR outside the tile = 15). */
typedef unsigned int u32; typedef unsigned char u8;

#define RB ((u8 *)0x1f800300)
#define SPEND (*(u8 * volatile *)0x1f8003fc)       /* end of the output (kept in the scratchpad: no spill to a stack) */

void dsa_dec(const u8 *src, u8 *dst, int n, const u8 *model)
{
    const u32 *nodes = (const u32 *)(model + 12);
    const u8 *lp = model + 12 + 4 * (model[8] | (model[9] << 8));
    u32 W = src[0] * 2;
    const u8 *p = src + 5;
    u32 code = (src[1] << 24) | (src[2] << 16) | (src[3] << 8) | src[4];
    u32 rng = 0xFFFFFFFFu;
    u8 *q, *qe = RB + W;
    SPEND = dst + n;
    for (q = RB; q <= qe + 1; q++) *q = 0xff;
    while (dst != SPEND) {
        u32 wd = 0x0f0f0f0f;                       /* L, UL, LL, ULL = 15 at the row start */
        q = RB;
        do {
            u32 b = q[0], V, k = 0, nd, idx, bound, v;
            const u8 *pb;
            V = wd | ((b & 15) << 4) | ((b >> 4) << 20) | ((q[1] & 15) << 12) | ((u32)(q[2] & 15) << 28);
            for (;;) {
                u32 r, a;
                nd = nodes[k];
                if (nd & 0x8000) break;
                a = V >> (nd & 31);
                if ((nd & 0xc00) == 0) r = a & 1;
                else if ((nd & 0xc00) == 0x400) r = (a & 15) == 15;
                else r = ((a ^ (V >> ((nd >> 5) & 31))) & 15) == 0;
                k = r ? nd >> 16 : k + 1;
            }
            pb = lp + 16 * (nd & 0x7FFF);
            bound = (rng >> 8) * pb[0];
            if (code < bound) { rng = bound; idx = 1; }
            else { code -= bound; rng -= bound; idx = 0; }
            while (rng < (1u << 24)) { rng <<= 8; code = (code << 8) | *p++; }
            if (idx == 0) v = b & 15;
            else {
                do {
                    bound = (rng >> 8) * pb[idx];
                    if (code < bound) { rng = bound; idx = idx * 2; }
                    else { code -= bound; rng -= bound; idx = idx * 2 + 1; }
                    while (rng < (1u << 24)) { rng <<= 8; code = (code << 8) | *p++; }
                } while (idx < 16);
                v = idx - 16;
            }
            q[0] = v | ((b & 15) << 4);
            if ((u32)q & 1) *dst++ = (wd & 15) | (v << 4);
            wd = v | ((b & 15) << 8) | ((wd & 0x0f0f) << 16);
            q++;
        } while (q != qe);
    }
}
