/* XvSF speed 1.1 - "quad" part: per-sprite-part primitive building, rewritten in place.
 *
 *   quad_part   replaces 0x80056340  (builds the POLY_FT4 / sprite packet of one sprite part, links it)
 *   sec0_parse  replaces 0x80057be4  (sec0 part header parser, returns header length 5/6/7)
 *   sec1_parse  replaces 0x80057f48  (sec1 tile header parser)
 *   0x80055c34 (sprite-packet variant, only caller 0x80056340) is folded into quad_part as quad_sprt();
 *   the original stays in RAM untouched and unused.
 *
 * Same calling interface, same return values, same memory writes (final values) as the originals,
 * including the scratch fields of the work frame (ctx->0x70) and of the context struct.
 * The context struct lives in the scratchpad (*(u32*)0x8006a340 = 0x1f800000).
 */
typedef unsigned char u8;
typedef signed char s8;
typedef unsigned short u16;
typedef short s16;
typedef unsigned int u32;
typedef int s32;

#define B(p, o)  (*(u8 *)((u8 *)(p) + (o)))
#define SB(p, o) (*(s8 *)((u8 *)(p) + (o)))
#define H(p, o)  (*(u16 *)((u8 *)(p) + (o)))
#define SH(p, o) (*(s16 *)((u8 *)(p) + (o)))
#define W(p, o)  (*(u32 *)((u8 *)(p) + (o)))
#define SW(p, o) (*(s32 *)((u8 *)(p) + (o)))
#define G8(a)    (*(u8 *)(a))
#define G16(a)   (*(u16 *)(a))
#define GS16(a)  (*(s16 *)(a))
#define G32(a)   (*(u32 *)(a))
#define CTX      (*(u8 **)0x8006a340)

extern int DrawSync(int);               /* 0x80016454 */
extern void f15a68(u32);                /* 0x80015a68 */
extern void f16a54(u32);                /* 0x80016a54 */

/* link packet pk after the previous one (prev pointer at *prevp, head at *headp) */
static inline __attribute__((always_inline)) void link(u8 *ctx, u32 pk)
{
    u32 *prevp, *headp;
    if (B(ctx, 3) == 1) { prevp = (u32 *)0x8006a348; headp = (u32 *)0x80069dd8; }
    else { prevp = (u32 *)0x8005cf70; headp = (u32 *)0x8005c758; }
    u32 *a = (u32 *)*prevp;
    if (a) *a = (*a & 0xff000000) | (pk & 0x00ffffff);
    else *headp = pk;
    *prevp = pk;
}

/* former 0x80055c34: sprite packet (32-byte slots) for unflipped parts of codes 0x2c..0x36 */
static __attribute__((noinline)) u32 quad_sprt(u8 *w)
{
    s16 n = GS16(0x8005c5fe);
    u8 *s;
    if (n < (s32)G16(0x8006a350) - 1) {
        GS16(0x8005c5fe) = n + 1;
        s = (u8 *)(G32(0x80069ed8) + (n << 5));
    } else {
        while (DrawSync(1)) ;
        GS16(0x8005c5fe) = 1;
        s = (u8 *)G32(0x80069ed8);
    }
    W(w, 0x38) = (u32)s;
    u8 *ctx = CTX;
    u32 t = B(W(ctx, 0x94), 0xc) << 2;
    u32 x68 = H(w, 0x68), x6a = H(w, 0x6a);
    W(s, 0x14) = H(w, 0x5c) | (H(w, 0x5e) << 16);
    B(s, 0x18) = (x68 - G8(0x8005c604 + t)) << 2;
    B(s, 0x19) = x6a - G8(0x8005c606 + t);
    W(s, 0x1c) = B(ctx, 0xe8) | (B(ctx, 0xe9) << 16);
    W(s, 4) = (x68 >> 6) + (x6a < 0x100 ? 0xe1000000 : 0xe1000010);
    H(s, 0x1a) = G16(0x8005d4a0 + H(w, 0x6e) * 2);
    link(ctx, (u32)s);
    u32 v = W(ctx, 0x70) - 0xb4;
    W(ctx, 0x70) = v;
    return v;
}

u32 quad_part(u8 *o)
{
    u8 *ctx = CTX;
    u8 *w = (u8 *)W(ctx, 0x70);
    W(ctx, 0x70) = (u32)w + 0xb4;
    u32 typ = B(W(ctx, 0x90), 0xb);
    if (typ == 1) W(w, 0x34) = W(ctx, 0x164) + 8;
    u32 f6 = H(ctx, 0xf6);
    u32 e8 = (u8)(B(ctx, 0xe8) << 1), e9 = B(ctx, 0xe9);
    B(ctx, 0xe8) = e8;
    u32 fx = (f6 >> 5) & 1, fy = (f6 >> 6) & 1;
    u32 o51 = B(o, 0x51);
    u32 mx = o51 & 1, my = o51 & 2;
    H(w, 0x4c) = mx; H(w, 0x4e) = my;
    u32 X, Y;
    if (!mx) X = H(o, 0xc) + H(ctx, 0xf0) - 0x40;
    else { fx ^= 1; X = H(o, 0xc) - (e8 + SH(ctx, 0xf0)) - 0x40; }
    if (!my) Y = H(o, 0x10) + H(ctx, 0xf2) - 8;
    else {
        fy ^= 1;
        s32 y44 = SH(o, 0x10), y40 = SH(o, 0x96);
        if (y40 < 0) { y40 &= 0xfff; y44 -= y40; }
        W(w, 0x40) = y40; W(w, 0x44) = y44;
        Y = y44 - (e9 + SH(ctx, 0xf2)) - 8;
    }
    B(w, 0x6c) = fx; B(w, 0x6d) = fy;
    u32 o28 = B(o, 0x28);
    if (o28) {
        u8 *p = *(u8 **)(0x8003ea4c + ((s32)(s8)o28 >> 2) * 4);
        W(w, 0x58) = (u32)p;
        X -= H(p, 0x14); Y -= H(p, 0x16);
    }
    X &= 0xffff; Y &= 0xffff;
    H(w, 0x5c) = X; H(w, 0x5e) = Y;
    u32 pal = f6 & 0x1f;
    s32 o4e = SB(o, 0x4e);
    if (SB(o, 0x50) < 0) pal += o4e;
    else if (o4e < 0) pal = o4e & 0x7f;
    pal &= 0xffff;
    H(w, 0x6e) = pal;
    u8 *c94 = (u8 *)W(ctx, 0x94);
    u32 x68 = (u16)(H(c94, 0x1a) + B(ctx, 5));
    u32 x6a = (u16)(H(c94, 0x1c) + B(ctx, 6));
    H(w, 0x68) = x68; H(w, 0x6a) = x6a;
    W(w, 0x78) = 0;                                 /* 0x78, 0x7a */
    if ((u8)(B(o, 0x6c) - 0x2c) < 0xb && !(SB(o, 0x51) | fx | fy))
        return quad_sprt(w);

    u32 t = B(c94, 0xc) << 2;
    s32 u0 = (x68 - G16(0x8005c604 + t)) << 2;
    s32 v0 = x6a - G16(0x8005c606 + t);
    s32 dx0 = 0, dy0 = 0, dx1 = 0, dy1 = 0, dx2 = 0, dy2 = 0, dx3 = 0, dy3 = 0;
    u32 m78 = 0, m7a = 0, offs = 0;
    u8 *sp = (u8 *)W(ctx, 0x58);
    if (sp) {
        u32 fl = *sp++;
        B(ctx, 0x114) = fl;
        if (fl) {
            offs = 1;
            if (fl & 0x10) {
                s32 a = (s8)sp[0], b = (s8)sp[1];
                X = (u16)(mx ? X - a : X + a); Y = (u16)(my ? Y - b : Y + b);
                H(w, 0x5c) = X; H(w, 0x5e) = Y;
                sp += 2;
            }
            u8 d[8];
            for (int i = 0; i < 4; i++) {
                u32 a = 0, b = 0;
                if (fl & (1 << i)) {
                    a = sp[0]; b = sp[1];
                    if (mx) a = -a;
                    if (my) b = -b;
                    sp += 2;
                }
                d[2 * i] = a; d[2 * i + 1] = b;
            }
            W(w, 0x70) = d[0] | d[1] << 8 | d[2] << 16 | d[3] << 24;
            W(w, 0x74) = d[4] | d[5] << 8 | d[6] << 16 | d[7] << 24;
            H(w, 0x4a) = 4;
            dx0 = (s8)d[0]; dy0 = (s8)d[1]; dx1 = (s8)d[2]; dy1 = (s8)d[3];
            dx2 = (s8)d[4]; dy2 = (s8)d[5]; dx3 = (s8)d[6]; dy3 = (s8)d[7];
            m78 = (d[0] | d[2] | d[4] | d[6]) != 0;
            m7a = (d[1] | d[3] | d[5] | d[7]) != 0;
            W(w, 0x78) = m78 | m7a << 16;
        }
        W(ctx, 0x58) = (u32)sp;
        W(ctx, 0x118) = (u32)sp;
    }
    B(w, 0x8e) = offs;

    u32 pk;
    if (typ == 0 || typ == 2) {
        if (!(GS16(0x8005c5fc) < (s32)G16(0x80069a7c) - 1)) {
            u8 c = G8(0x8005d958) + 1;
            G8(0x8005d958) = c;
            if (c >= 2) {
                while (DrawSync(1)) ;
                G8(0x8005d958) = 0;
            }
            u32 a = G32(0x8005cf70);
            if (a) { f15a68(a); f16a54(G32(0x8005c758)); }
            else if ((a = G32(0x8005c758))) f16a54(a);
            u32 k = G8(0x80060a98) == 0;
            u32 base = G32(0x8005c928 + k * 4);
            G32(0x8005c758) = 0; G32(0x8005cf70) = 0; GS16(0x8005c5fc) = 0;
            G8(0x80060a98) = k; G32(0x8005d9b0) = base;
            ctx = CTX;
            e8 = B(ctx, 0xe8); e9 = B(ctx, 0xe9);
        }
        s32 n = GS16(0x8005c5fc);
        GS16(0x8005c5fc) = n + 1;
        pk = G32(0x8005d9b0) + n * 40;
        W(w, 0x34) = pk;
    } else pk = W(w, 0x34);
    W(w, 0x30) = pk;
    u8 *P = (u8 *)pk;

    if (fx && !m78 && --u0 < 0) { u0 = 0; e8 = (u8)(e8 - 1); B(ctx, 0xe8) = e8; }
    if (fy && !m7a && --v0 < 0) { v0 = 0; e9 = (u8)(e9 - 1); B(ctx, 0xe9) = e9; }
    W(w, 0) = u0; W(w, 4) = v0;
    W(w, 0x50) = pk + 32;
    if (!offs) { W(w, 0x94) = pk + 0x2c; W(w, 0xa8) = pk + 0x2c; }

    u32 xl = X - m78, xr = X + e8, yt = Y - m7a, yb = Y + e9;
    u32 xa = fx ? xr : xl, xb = fx ? xl : xr, ya = fy ? yb : yt, yc = fy ? yt : yb;
    W(P, 8) = (u16)(xa + dx0) | (ya + dy0) << 16;
    W(P, 16) = (u16)(xb + dx1) | (ya + dy1) << 16;
    W(P, 24) = (u16)(xa + dx2) | (yc + dy2) << 16;
    W(P, 32) = (u16)(xb + dx3) | (yc + dy3) << 16;

    u32 ua = (u8)u0, ub = (u8)(e8 + u0 - m78), va = (u8)v0 << 8, vb = (u8)(e9 + v0 - m7a) << 8;
    u32 clut = G16(0x8005d4a0 + pal * 2);
    u32 tpage = (u16)((x68 >> 6) + ((x6a & 0x100) >> 4));
    W(P, 0xc) = ua | va | clut << 16;
    W(P, 0x14) = ub | va | tpage << 16;
    H(P, 0x1c) = ua | vb;
    H(P, 0x24) = ub | vb;

    link(ctx, pk);
    u32 v = W(ctx, 0x70) - 0xb4;
    W(ctx, 0x70) = v;
    return v;
}

/* former 0x80057be4: copy the part header (8 bytes aligned / 7 bytes unaligned) into the work frame and decode it */
u32 sec0_parse(void)
{
    u8 *ctx = CTX;
    u8 *s = (u8 *)W(ctx, 0x54);
    u8 *a = (u8 *)W(ctx, 0x70);
    u32 b4, b5, b6;
    u32 b1, b2, b3;
    if (!((u32)s & 3)) {
        u32 x = W(s, 0), y = W(s, 4);
        W(a, 0x14) = x; W(a, 0x18) = y;
        W(a, 0x20) = (u32)a + 0x18; W(a, 0x24) = (u32)s + 4;
        b1 = (x >> 8) & 0xff; b2 = (x >> 16) & 0xff; b3 = x >> 24;
        b4 = y & 0xff; b5 = (y >> 8) & 0xff; b6 = (y >> 16) & 0xff;
        H(ctx, 0xf6) = x & 0xff;
    } else {
        b1 = s[1]; b2 = s[2]; b3 = s[3]; b4 = s[4]; b5 = s[5]; b6 = s[6];
        u32 b0 = s[0];
        W(a, 0x14) = b0 | b1 << 8 | b2 << 16 | b3 << 24;
        H(a, 0x18) = b4 | b5 << 8;
        B(a, 0x1a) = b6;
        W(a, 0x2c) = (u32)a + 0x1b; W(a, 0x34) = (u32)a + 0x1b; W(a, 0x30) = (u32)s + 7;
        H(ctx, 0xf6) = b0;
    }
    u8 *a3 = a + 0x14;
    W(a, 0) = (u32)a3;
    H(ctx, 0xf4) = (b1 | b2 << 8) & 0xfff;
    u32 m1 = (b2 >> 4) & 3, m2 = b2 >> 6;
    W(a, 0x1c) = m1 | m2 << 16;
    if (m1 == 3) {
        H(ctx, 0xf0) = b3 | b4 << 8;
        if (m2 == 3) { W(a, 0x10) = (u32)a3; H(ctx, 0xf2) = b5 | b6 << 8; return 7; }
        W(a, 8) = (u32)a3;
        if (m2 == 2) b5 = -b5;
        else if (m2 == 0) b5 = (s8)b5;
        H(ctx, 0xf2) = b5;
        return 6;
    }
    if (m2 == 3) {
        W(a, 0xc) = (u32)a3;
        H(ctx, 0xf0) = m1 == 2 ? -b3 : b3;
        H(ctx, 0xf2) = b4 | b5 << 8;
        return 6;
    }
    W(a, 4) = (u32)a3;
    if (m1 == 2) b3 = -b3;
    else if (m1 == 0) b3 = (s8)b3;
    H(ctx, 0xf0) = b3;
    if (m2 == 2) b4 = -b4;
    else if (m2 == 0) b4 = (s8)b4;
    H(ctx, 0xf2) = b4;
    return 5;
}

/* former 0x80057f48: tile header */
u32 sec1_parse(void)
{
    u8 *ctx = CTX;
    u8 *w = (u8 *)W(ctx, 0x70);
    u32 *src = (u32 *)W(ctx, 0x88);
    u32 x = *src;
    W(w, 0) = (u32)w + 8; W(w, 4) = (u32)src; W(w, 8) = x;
    W(ctx, 0xe4) = x & 0x3fffff;
    u32 r = (x >> 8) & 0x8000;
    W(ctx, 0xe8) = (((x >> 24) & 0xf) + 1) * 8 | (u8)(((x >> 24) & 0xf0) + 0x10) << 8 | r << 16;
    return r;
}
