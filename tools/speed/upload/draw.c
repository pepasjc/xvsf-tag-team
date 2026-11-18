/* Per-object sprite draw 0x80059e60, rewritten (same calls with the same arguments in the same order, same memory
 * writes as the original -O0 code; see work/speed/upload/NOTES.md).  Built with -Os; the callees are absolute
 * symbols (--defsym).  S = scratchpad 0x1f800000. */
typedef unsigned char u8; typedef signed char s8; typedef unsigned short u16; typedef short s16; typedef unsigned int u32;

#define S        0x1f800000u
#define B(o)     (*(u8 *)(S + (o)))
#define H(o)     (*(u16 *)(S + (o)))
#define W(o)     (*(u32 *)(S + (o)))
#define M8(a)    (*(u8 *)(a))
#define M16(a)   (*(u16 *)(a))
#define M32(a)   (*(u32 *)(a))
#define N        W(0x90)                       /* VRAM node */
#define TFREE    M32(0x80069dd0)
#define HEAD     M32(0x8006a34c)
#define POOL     M32(0x8006a344)
#define TAIL     M32(0x80069a80)

extern u32 parse0(void), parse1(void), quad(u32 obj), f55ebc(u32 node), f55ef8(void), f55fa4(u32 obj);
extern u32 f5c4f8(u32 obj), f5c258(u32 obj), f5883c(u32 node), f57a70(void), decode(u32 src, u32 dst, u32 n);
extern u32 alloc(void), up_cached(u32 obj), up_partial(u32 obj), up_stream(u32 obj);
extern u32 HINT;

/* one part: sec0 parser, modifier check (0xff = hidden: S[0x58]++, S[0x48]++), sec1 parser.  1 = hidden. */
static int __attribute__((noinline, section(".text.hot2"))) part(void)
{
    u32 a;
    W(0x54) += parse0();
    a = W(0x58);
    if (a && M8(a) == 0xff) { W(0x58) = a + 1; W(0x48) += 1; return 1; }
    W(0x88) = W(0x8c) + H(0xf4) * 4;
    parse1();
    return 0;
}

/* placement of a part without the S[0x4c] write (the quad-only loops) */
static void __attribute__((noinline, section(".text.hot2"))) place0(void)
{
    u32 p = W(0x48); u8 c = M8(p);
    B(5) = (c & 15) << 2; W(0x48) = p + 1; B(6) = c & 0xf0;
}

/* quad-only loop over the parts (0x8005a800 / 0x8005a900 / 0x8005acdc in the original) */
static void __attribute__((noinline, section(".text.hot2"))) quadloop(u32 obj)
{
    do {
        if (part()) continue;
        place0();
        if (M8(N + 0xb) == 1) f55ef8();
        quad(obj);
    } while (!(H(0xf6) & 0x80));
}

/* the arena block's unlink + push onto the free pool (and the allocator hint cleared) */
static void __attribute__((noinline)) blkfree(u32 a0)
{
    u32 v0, v1;
    if (TAIL == a0) TAIL = M32(a0);
    v1 = M32(a0);
    if (v1 == 0) { v0 = M32(a0 + 4); HEAD = v0; if (v0) M32(v0) = 0; }
    else { v0 = M32(a0 + 4); if (v0) M32(v0) = v1; M32(M32(a0) + 4) = M32(a0 + 4); }
    HINT = 0;
    v0 = POOL; M32(a0) = 0; M32(a0 + 4) = 0;
    if (v0 == 0) POOL = a0;
    else { M32(v0) = a0; M32(a0 + 4) = v0; POOL = a0; }
}

/* free the node's pre-decoded chain: every tile's arena block, then the chain onto the tile-node free list */
static void __attribute__((noinline)) chainkill(void)
{
    u32 t, v1, n = N;
    if (M32(n + 0x30)) {
        W(0x98) = M32(n + 0x30);
        for (;;) {
            t = M32(W(0x98) + 8);
            if (t) blkfree(t);
            t = M32(W(0x98) + 4);
            if (!t) break;
            W(0x98) = t;
        }
        v1 = TFREE; M32(v1) = W(0x98); M32(W(0x98) + 4) = v1;
        t = M32(N + 0x30); M32(N + 0x30) = 0; TFREE = t; M32(N + 0x34) = 0;
    }
}

/* node position fields from the object (+0x28 attachment) */
static void __attribute__((noinline)) setpos(u32 obj)
{
    s8 b = (s8)M8(obj + 0x28);
    if (b) {
        u32 t = M32(0x8003ea4c + (u32)((int)b >> 2) * 4);
        W(0x168) = t;
        M16(N + 0x24) = M16(obj + 0xc) - M16(t + 0x14);
        M16(N + 0x26) = M16(obj + 0x10) - M16(W(0x168) + 0x16);
    } else {
        M16(N + 0x24) = M16(obj + 0xc);
        M16(N + 0x26) = M16(obj + 0x10);
    }
}

static void __attribute__((noinline)) setattr(u32 obj)
{
    setpos(obj);
    M16(N + 0x14) = H(0x14);
    M16(N + 0x16) = (s8)M8(obj + 0x51);
    M8(N + 0x12) = M8(obj + 0x50);
    M16(N + 0x18) = (s8)M8(obj + 0x4e);
}

static void __attribute__((noinline)) rectdesc(void)
{
    u32 n = N, t;
    if (M8(n + 0xf) == 0) W(0x94) = n;
    else {
        t = M32(0x8005c65c + M8(n + 0x11) * 4); W(0xa0) = t;
        t += M8(n + 0x10) * 8; W(0xa0) = t;
        W(0x94) = M32(t + 4);
    }
}

/* pre-decode allocation failure: the tile node is unlinked and freed (with the original's tail check), C aborted */
static void __attribute__((noinline)) predfail(void)
{
    u32 a0, t;
                  /* no room: drop the tile node, pre-decode aborted */
    u32 a1n;
    M32(W(0x98) + 8) = 0;
    if (M32(N + 0x34) == W(0x98)) M32(N + 0x34) = M32(W(0x98));
    a0 = W(0x98); a1n = N;
    if (a0) {
        if (TAIL == a0) TAIL = M32(a0);
        if (!M32(a0)) { t = M32(a0 + 4); M32(a1n + 0x30) = t; if (t) M32(t) = 0; }
        else { t = M32(a0 + 4); if (t) M32(t) = M32(a0); M32(M32(a0) + 4) = M32(a0 + 4); }
        t = TFREE; M32(a0) = 0; M32(a0 + 4) = 0;
        if (!t) TFREE = a0;
        else { M32(t) = a0; M32(a0 + 4) = t; TFREE = a0; }
    }
    M8(N + 0xa) = 2;
    }

/* the pre-decode loop: per part a tile node from the free list, linked at the chain's tail, an arena block, decode.
 * n / q cache S[0x90] / S[0x98] between the calls (no callee writes them). */
static void __attribute__((noinline, section(".text.hot"))) predloop(void)
{
    u32 n, q, t, a0;
    for (;;) {
        W(0x54) += parse0();
        W(0x88) = W(0x8c) + H(0xf4) * 4;
        parse1();
        n = N; q = TFREE;
        if (q) { t = M32(q + 4); TFREE = t; M32(t) = 0; M32(q) = 0; M32(q + 4) = 0; }
        W(0x98) = q;
        if (!q) { M8(n + 0xa) = 2; return; }
        a0 = W(0x9c);
        if (!a0) {
            t = M32(n + 0x30);
            if (!t) { M32(n + 0x30) = q; M32(q) = 0; M32(q + 4) = 0; }
            else { M32(t) = q; M32(q + 4) = M32(n + 0x30); M32(n + 0x30) = q; }
        } else {
            M32(q) = a0; t = M32(a0 + 4); M32(q + 4) = t;
            if (t) M32(t) = q;
            M32(a0 + 4) = q;
        }
        W(0x9c) = q;
        if (!M32(q + 4)) M32(n + 0x34) = q;
        t = alloc(); M32(W(0x98) + 8) = t;
        if (t == 0xffffffff) { predfail(); return; }       /* no room: drop the tile node, pre-decode aborted */
        n = N;
        decode(M32(0x8005c830 + M8(n + 0x11) * 4) + W(0xe4), M32(0x80060af0) + *(s16 *)(M32(W(0x98) + 8) + 0xa), B(0xe8) * B(0xe9));
        n = N;
        M16(n + 0x22) += 1;
        if (H(0xf6) & 0x80) { M8(n + 0xa) = 1; return; }
    }
}

#ifdef FC
/* ------------------------------------------------------------------------------------------------------------
 * Frame cache (Saturn VDP1 style): the sprite pool's rects outlive their frame.  When an object's frame changes,
 * its old rect stays allocated in the page list under a resident slot (key: set, sec0 frame, layout A, modifiers B)
 * instead of being freed; a later change to a resident frame takes that rect back: no decode, no upload, quads only.
 * Resident rects are dropped LRU only when the rect allocator 0x8005883c finds no room (fc_drop from its failure
 * path, then it retries), or when the slot table is full.  The slots are list members with the node layout the
 * allocator reads (+0 prev, +4 next, +0xd w, +0xe h, +0x1a x, +0x1c y).  All of it lives at the end of the arena,
 * which the battle/round init 0x800545c4 zeroes together with the page lists: magic word gone = table empty.
 * ------------------------------------------------------------------------------------------------------------ */
#define NR       48
#define RS(i)    (FCDATA + 32 * (i))           /* slot: +8 lru (0 = free), +0xc set, +0xd w, +0xe h, +0xf page,
                                                  +0x10 sec0, +0x12 A, +0x14 B, +0x1a x, +0x1c y */
#define SIDE(i)  (FCDATA + 32 * NR + 8 * (i))  /* per pool node: +0 A, +2 B, +4 ok (rect holds the frame complete) */
#define FCV      (FCDATA + 32 * NR + 8 * 128)  /* +0 magic, +4 hits, +8 misses, +0xc retired, +0x10 dropped, +0x14 bad */
#define FCBAD    M8(FCV + 0x18)                /* set by the upload loops when a part was skipped (no arena room) */
#define LIST(p)  (0x80069a50 + 4 * (p))
#define NOWW     M32(0x800421b8)

static int __attribute__((noinline)) fc_on(void)
{
    if (M8(0x80042348) != 8) return 0;
    if (M32(FCV) != 0x31434646) {              /* zeroed by the battle / round init: no slot is linked */
        u32 i;
        for (i = 0; i < NR; i++) M32(RS(i) + 8) = 0;
        for (i = 0; i < 128; i++) M8(SIDE(i) + 4) = 0;
        M32(FCV) = 0x31434646;
    }
    return 1;
}

static u32 __attribute__((noinline)) nidx(u32 n) { return (n - M32(0x80060af4)) / 0x38; }

/* put b in a's place in page list p (a leaves the list) */
static void __attribute__((noinline)) fc_swap(u32 a, u32 b, u32 p)
{
    u32 pr = M32(a), nx = M32(a + 4);
    M32(b) = pr; M32(b + 4) = nx;
    if (pr) M32(pr + 4) = b; else M32(LIST(p)) = b;
    if (nx) M32(nx) = b;
    M32(a) = 0; M32(a + 4) = 0;
}

static void __attribute__((noinline, section(".text.hot"))) fc_unlink(u32 r)
{
    u32 pr = M32(r), nx = M32(r + 4);
    if (pr) M32(pr + 4) = nx; else M32(LIST(M8(r + 0xf))) = nx;
    if (nx) M32(nx) = pr;
    M32(r) = 0; M32(r + 4) = 0; M32(r + 8) = 0;
}

/* the least recently used linked slot (or a free one first with free = 1) */
static u32 __attribute__((noinline, section(".text.hot"))) fc_lru(int free)
{
    u32 i, best = 0, bl = 0xffffffff;
    for (i = 0; i < NR; i++) {
        u32 r = RS(i), l = M32(r + 8);
        if (!l) { if (free) return r; continue; }
        if (l < bl) { bl = l; best = r; }
    }
    return best;
}

/* the rect allocator found no room: drop the LRU resident rect (1) so it can retry, or 0 = none left */
int fc_drop(void)
{
    u32 r;
    if (M32(FCV) != 0x31434646 || !(r = fc_lru(0))) return 0;
    fc_unlink(r); M32(FCV + 0x10) += 1;
    return 1;
}

/* frame change, before the old rect is unlinked: keep it resident when it holds its frame complete */
static int __attribute__((noinline)) fc_retire(u32 n)
{
    u32 r, k = nidx(n), ok;
    if (k >= 128) return 0;
    ok = M8(SIDE(k) + 4); M8(SIDE(k) + 4) = 0;                 /* (the rect will not hold this frame any more) */
    if (!fc_on() || !ok || M8(n + 0xf) || M8(n + 0x11) == 0x37 || M16(n + 0x20) == 0xffff || M8(n + 9) != 1) return 0;
    if (!(r = fc_lru(1))) return 0;
    if (M32(r + 8)) fc_unlink(r);               /* table full: the LRU rect goes */
    fc_swap(n, r, M8(n + 0xc));
    M32(r + 8) = NOWW + 1; M8(r + 0xc) = M8(n + 0x11); M8(r + 0xd) = M8(n + 0xd); M8(r + 0xe) = M8(n + 0xe);
    M8(r + 0xf) = M8(n + 0xc); M16(r + 0x10) = M16(n + 0x20); M16(r + 0x12) = M16(SIDE(k)); M16(r + 0x14) = M16(SIDE(k) + 2);
    M16(r + 0x1a) = M16(n + 0x1a); M16(r + 0x1c) = M16(n + 0x1c);
    M8(n + 9) = 0; M32(FCV + 0xc) += 1;
    return 1;
}

/* the new frame (node +0x11 / +0x20 / +0xd / +0xe set, dynamic rect): a resident copy -> its rect, 1 */
static int __attribute__((noinline)) fc_hit(u32 n)
{
    u32 i, r;
    if (!fc_on() || M8(n + 0x11) == 0x37) return 0;
    for (i = 0; i < NR; i++) {
        r = RS(i);
        if (M32(r + 8) && M16(r + 0x10) == M16(n + 0x20) && M8(r + 0xc) == M8(n + 0x11) && M16(r + 0x12) == H(0xa)
            && M16(r + 0x14) == H(0x14) && M8(r + 0xd) == M8(n + 0xd) && M8(r + 0xe) == M8(n + 0xe)) {
            fc_swap(r, n, M8(r + 0xf));
            M8(n + 0xc) = M8(r + 0xf); M16(n + 0x1a) = M16(r + 0x1a); M16(n + 0x1c) = M16(r + 0x1c); M8(n + 9) = 1;
            M32(r + 8) = 0; M32(FCV + 4) += 1;
            return 1;
        }
    }
    M32(FCV + 8) += 1;
    return 0;
}

/* is a resident copy of sec0 frame c of the node's set there (the pre-decode of C is then skipped) */
static int __attribute__((noinline, section(".text.hot"))) fc_has(u32 n, u32 c)
{
    u32 i, r;
    if (M32(FCV) != 0x31434646) return 0;
    for (i = 0; i < NR; i++) { r = RS(i); if (M32(r + 8) && M16(r + 0x10) == c && M8(r + 0xc) == M8(n + 0x11)) return 1; }
    return 0;
}

/* after the upload of a new frame: the rect holds it (complete unless a part was skipped) */
static void __attribute__((noinline)) fc_mark(u32 n, u32 ab)
{
    u32 k = nidx(n);
    if (k >= 128) return;
    M32(SIDE(k)) = ab;
    M8(SIDE(k) + 4) = !FCBAD && M8(n + 9) == 1 && !M8(n + 0xf) && B(2) == 0xff && M8(0x80042348) == 8;
    if (FCBAD) M32(FCV + 0x14) += 1;
}
#endif

/* pre-decode of the next frame C (sec3 record word 2) into cached arena blocks, in hold frames */
static void __attribute__((noinline)) predecode(u32 obj)
{
    u32 a0, t, n;
        if ((s8)M8(obj + 0x75) && B(0) == 4) {
            u32 c = H(0x18), q;
            n = N;
            if (c != M16(n + 0x20) && c != 0xffff && B(2) == 0xff && !M8(n + 0xa)
#ifdef FC
                && !fc_has(n, c)
#endif
                ) {
                W(0x74) = W(0x40) + c;
                if (M16(N + 0x1e) != H(0x18)) {
                    chainkill();
                    M16(N + 0x22) = 0; M8(N + 0xa) = 0; M16(N + 0x1e) = H(0x18);
                    W(0x54) = W(0x74); W(0x9c) = M32(N + 0x30);
                    predloop();
                }
            }
        }
}


__attribute__((section(".text.entry"))) void draw(u32 obj)
{
    u32 a0, a3, p, t, n, set;
    u16 a1, a2;
#ifdef FC
    int hit = 0; u16 fa, fb;
#endif

    M32(0x8006a340) = S;
    W(0x70) = S + 0x170;
    if (*(s16 *)0x8004212a < 0) return;
    a0 = M32(obj + 0x40);
    if ((a0 & 0xffff) == 0xffff || !(a0 & 0xffff0000)) return;
    set = M8(obj + 0x6c);
    a3 = M32(0x80069de0 + set * 4); W(0x44) = a3;
    if (!a3) return;
    t = M32(0x8006a358 + M8(obj + 0x6c) * 4); W(0x40) = t;
    if (!t) return;
    t = M32(obj + 0x70); W(0x90) = t;
    if (!t) return;
    W(0x34) = M16(obj + 0x40);
    B(0) = M8(a3);
    p = a3 + (M32(obj + 0x40) >> 16);
    W(0x50) = p;
    a1 = M8(p) | M8(p + 1) << 8; W(0x50) = p + 2; H(0xa) = a1;
    a2 = M8(p + 2) | M8(p + 3) << 8; W(0x50) = p + 4; H(0x14) = a2;
    H(0x18) = M8(p + 4) | M8(p + 5) << 8;
    if (!a1) return;
    p = a3 + a1; W(0x50) = p;
    H(0x16) = M8(p) | M8(p + 1) << 8;
    B(2) = M8(p + 3);
    W(0x60) = a2 ? a3 + a2 : 0;
    B(3) = M8(obj + 0x76);
    set = M8(obj + 0x6c);
    if (obj == 0x80043178 || obj == 0x800434b8 || (set != M8(0x80042dc4) && set != M8(0x80042a7c) && set != 0x26)) {
        if (M32(N + 0x28)) f55ebc(N);
        M8(N + 0xb) = 0;
    } else if (M8(N + 0xb) == 0) M8(N + 0xb) = 1;

    if (H(0x16) == 0xffff) {                                   /* composite sprite */
        W(0x54) = W(0x40) + W(0x34);
        W(0x48) = H(0xa) + W(0x44) + 2;
        W(0x58) = W(0x60);
        t = M32(0x8005ce80 + M8(obj + 0x6c) * 4); W(0x8c) = t;
        if (!t) return;
        for (;;) {
            u8 c, k;
            p = W(0x48);
            a1 = M8(p) | M8(p + 1) << 8;
            t = W(0x44) + a1; H(0x12) = a1; W(0x50) = t + 1;
            c = M8(t); B(4) = c;
            if (c < 3) B(4) = c + 5;
            B(0x5c) = B(4) < 8;
            W(0x54) += parse0();
            W(0x88) = W(0x8c) + H(0xf4) * 4;
            parse1();
            c = M8(W(0x50));
            B(5) = B(0x5c) + ((c & 15) << 2);
            B(6) = B(0x5c) + (c & 0xf0);
            k = B(4);
            H(0x13e) = M16(0x8005c604 + k * 4);
            H(0x140) = M16(0x8005c606 + k * 4);
            B(0x130) = k;
            W(0x94) = S + 0x124;
            quad(obj);
            if (H(0xf6) & 0x80) break;
            W(0x48) += 2;
        }
        f57a70();
        return;
    }
    if ((u8)(B(0) - 3) >= 2) return;
    n = N;
    if (M16(n + 0x20) == M16(obj + 0x40) && M8(n + 0x11) == M8(obj + 0x6c)) {
        /* ------------------------------------------------ same frame as drawn last time: quads only + pre-decode */
        u8 b;
        t = M32(0x8005ce80 + M8(n + 0x11) * 4); W(0x8c) = t;
        if (!t) return;
        n = N; b = M8(n + 0xb);
        if (b == 1) {
            if (!M32(n + 0x28)) M8(n + 0xb) = 2;
            n = N;
            if (M8(n + 0xb) == 1 && (int)(s8)M8(obj + 0x51) == (int)M16(n + 0x16) && M16(n + 0x14) == H(0x14)
                && (s8)M8(obj + 0x50) == (s8)M8(n + 0x12) && (int)(s8)M8(obj + 0x4e) == (int)M16(n + 0x18)) {
                f55fa4(obj);
                setpos(obj);
                goto predecode;
            }
            n = N;
        }
        if ((u8)(M8(n + 0xb) - 1) < 2) setattr(obj);
        W(0x54) = W(0x40) + W(0x34);
        W(0x48) = H(0xa) + W(0x44) + 4;
        W(0x58) = W(0x60);
        rectdesc();
        n = N; b = M8(n + 0xb);
        if (b == 2) {
            M8(n + 0xb) = 1;
            if (M32(N + 0x28)) f55ebc(N);
            W(0x160) = M32(N + 0x28);
            quadloop(obj);
        } else {
            if (b == 1) { W(0x164) = M32(n + 0x28); W(0x160) = M32(N + 0x28); }
            do {
                if (part()) continue;
                place0();
                if (M8(N + 0xb) == 1 && W(0x164) == 0) f55ef8();
                quad(obj);
                if (M8(N + 0xb) == 1) W(0x164) = M32(W(0x164) + 4);
            } while (!(H(0xf6) & 0x80));
        }
predecode:
        predecode(obj);
        f57a70();
        return;
    }
    /* ---------------------------------------------------- the frame changed */
#ifdef FC
    if (fc_retire(n)) n = N;                                   /* the old rect stays resident (the node leaves it) */
    fa = H(0xa); fb = H(0x14);                                 /* the new frame's layout / modifier offsets */
#endif
    if (M8(n + 9) == 1) {                                      /* unlink the old VRAM rect */
        u32 lst = 0x80069a50 + M8(n + 0xc) * 4;
        if (!M32(n)) { t = M32(n + 4); M32(lst) = t; if (t) M32(t) = 0; }
        else { t = M32(n + 4); if (t) M32(t) = M32(n); M32(M32(N) + 4) = M32(N + 4); }
        M32(N) = 0; M32(N + 4) = 0; M8(N + 9) = 0;
    }
    for (;;) {
        if (M8(N + 0xf)) f5c4f8(obj);
        B(7) = M8(N + 0x11); M8(N + 0x11) = M8(obj + 0x6c);
        M16(N + 0x20) = M32(obj + 0x40);
        p = H(0xa) + W(0x44); W(0x48) = p;
        M8(N + 0xd) = ((M8(p + 2) & 15) + 1) << 2;
        M8(N + 0xe) = (M8(W(0x48) + 2) & 0xf0) + 0x10;
        n = N;
        if (M8(n + 0xb)) { M8(n + 0xb) = 1; setattr(obj); }
        if (B(2) != 0xff) {
            if (M8(N + 0xf)) break;
            if ((f5c258(obj) & 0xff) == 1) continue;
        }
        if (M8(N + 0xf)) break;
#ifdef FC
#ifndef FC_NOHIT
        if (B(2) == 0xff && fc_hit(N)) { hit = 1; break; }
#endif
#endif
        if ((f5883c(N) & 0xff) == 1) continue;
        break;
    }
    t = M32(0x8005ce80 + M8(N + 0x11) * 4); W(0x8c) = t;
    if (!t) return;
    n = N;
    if (M16(n + 0x1e) != M16(n + 0x20) || B(7) != M8(obj + 0x6c)) {
        chainkill();
        M16(N + 0x22) = 0; M8(N + 0xa) = 0;
    }
    W(0x54) = W(0x40) + W(0x34);
    W(0x48) = H(0xa) + W(0x44) + 4;
    rectdesc();
    W(0x4c) = 0xff; W(0x58) = W(0x60);
    if (M32(N + 0x28)) f55ebc(N);
    W(0x160) = M32(N + 0x28);
    n = N;
#ifdef FC
    FCBAD = 0;
    if (hit) { chainkill(); quadloop(obj); }               /* resident: the pre-decoded chain is not needed */
    else
#endif
    if ((s8)M8(obj + 0x75)) {
        if (M8(n + 0xa) == 1) up_cached(obj);
        else if (*(s16 *)(n + 0x22) > 0) up_partial(obj);
        else if (M8(n + 0xf) < 2) up_stream(obj);
        else quadloop(obj);
    } else if (M8(n + 0xf) < 2) up_stream(obj);
    else quadloop(obj);
    M8(N + 0xa) = 0; M16(N + 0x22) = 0; M16(N + 0x1e) = 0xffff;
#ifdef FC
    fc_mark(N, fa | fb << 16);
#endif
    f57a70();
}
