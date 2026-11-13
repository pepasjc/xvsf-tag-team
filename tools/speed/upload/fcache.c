/* Frame cache in the sprite pool (Saturn VDP1 style), hooked into the STOCK per-object draw 0x80059e60 (draw.c is not
 * used: the stock function's leftover v0 reaches game logic through 0x8003611c / 0x8003648c).
 *
 * The sprite pool's rects outlive their frame: when an object's frame changes, its old rect stays allocated in its page
 * list under a resident slot (key: set, sec0 frame, layout A, modifiers B) instead of being freed; a later change to a
 * resident frame takes that rect back - no decode, no upload, only the quads.  Resident rects are dropped LRU when the
 * rect allocator 0x8005883c finds no room (fc_drop from its failure path, then it retries) or the slot table is full.
 * Slots are page-list members with the node fields the allocator reads (+0 prev, +4 next, +0xd w, +0xe h, +0x1a x,
 * +0x1c y).  Everything lives at the end of the arena, which the battle / round init 0x800545c4 zeroes together with
 * the page lists: magic word gone = no slot linked.  Only during a fight (match phase 8).
 *
 * Hooks (tools/speed/upload.py):
 *   0x8005a2a0  fc_rt(node)     frame change, before the stock unlink of the old rect: 0 = skip the unlink
 *   0x8005a510  fc_alloc(node)  in place of jal 0x8005883c (dynamic rect): a resident copy -> 0 (allocated), hit armed
 *   upload loops (helpers.S): entry -> fc_quads when the hit is for this node; exit -> fc_done (the rect holds the frame)
 *   0x80058ba4  fc_evict (fcstub.S) -> fc_drop, on the rect allocator's failure path */
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32;
#define M8(a)    (*(volatile u8 *)(a))
#define M16(a)   (*(volatile u16 *)(a))
#define M32(a)   (*(volatile u32 *)(a))
#define S        0x1f800000u
#define B(o)     M8(S + (o))
#define H(o)     M16(S + (o))
#define W(o)     M32(S + (o))

#define NR       48
#define RS(i)    (FCDATA + 32 * (i))           /* slot: +8 lru (0 = free), +0xc set, +0xd w, +0xe h, +0xf page,
                                                  +0x10 A | B << 16, +0x14 sec0, +0x1a x, +0x1c y */
#define SIDE(i)  (FCDATA + 32 * NR + 8 * (i))  /* per pool node: +0 A, +2 B, +4 ok (its rect holds that frame complete) */
#define FCV      (FCDATA + 32 * NR + 8 * 128)  /* +0 magic, +4 hits, +8 misses, +0xc retired, +0x10 dropped, +0x14 bad */
#define FCBAD    M8(FCV + 0x18)                /* set by the upload loops when a part was skipped (no arena room) */
#define FCHIT    M32(FCV + 0x1c)               /* node whose frame change hit (its upload loop only builds quads) */
#define FCARM    M32(FCV + 0x20)               /* node whose frame change went through fc_alloc */
#define FCAB     M32(FCV + 0x24)               /* its A | B << 16 */
#define LIST(p)  (0x80069a50 + 4 * (p))
#define NOWW     M32(0x800421b8)
#define MAGIC    0x31434646

extern u32 alloc_rect(u32 node);               /* 0x8005883c */

static void fc_unlink(u32 r);

/* Active only in a fight: match phase 8 AND the battle sprite pool (0x800545c4 called by 0x80054fe4 with 100 / 120
 * nodes; the title / intro / menu screens use 70 nodes from 0x80054c80).  The phase byte is NOT reset when a fight is
 * left (it stays 8 through the attract title / menus after a demo fight or a START abort), so the phase alone let the
 * cache run on non-battle screens.  Leaving the fight (phase != 8 or another pool) unlinks every resident while the
 * battle pool's lists are still the live ones: no slot stays linked outside a fight. */
static void __attribute__((noinline)) fc_off(void)
{
    u32 i;
    if (M32(FCV) != MAGIC) return;
    for (i = 0; i < NR; i++) if (M32(RS(i) + 8)) fc_unlink(RS(i));
    FCHIT = FCARM = 0;
    M32(FCV) = 0;
}

static int __attribute__((noinline)) fc_on(void)
{
    if (M8(0x80042348) != 8 || M16(0x8005d9b4) < 100) { fc_off(); return 0; }
    if (M32(FCV) != MAGIC) {                   /* zeroed by the battle / round init: no slot is linked */
        u32 i;
        for (i = 0; i < NR; i++) M32(RS(i) + 8) = 0;
        for (i = 0; i < 128; i++) M8(SIDE(i) + 4) = 0;
        FCHIT = FCARM = 0;
        M32(FCV) = MAGIC;
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

static void __attribute__((noinline)) fc_unlink(u32 r)
{
    u32 pr = M32(r), nx = M32(r + 4);
    if (pr) M32(pr + 4) = nx; else M32(LIST(M8(r + 0xf))) = nx;
    if (nx) M32(nx) = pr;
    M32(r) = 0; M32(r + 4) = 0; M32(r + 8) = 0;
}

/* the least recently used linked slot (a free one first with free = 1) */
static u32 __attribute__((noinline)) fc_lru(int free)
{
    u32 i, best = 0, bl = 0xffffffff;
    for (i = 0; i < NR; i++) {
        u32 r = RS(i), l = M32(r + 8);
        if (!l) { if (free) return r; continue; }
        if (l < bl) { bl = l; best = r; }
    }
    return best;
}

#define ISRES(m) ((m) - FCDATA < 32 * NR)

/* the rect allocator 0x8005883c is a shelf packer per page (x0 = 0x8005c604[p], y0 = +2; shelves = runs of list members
 * with the same y, sorted; a request (w, h) fits a gap when w < gap and h < the shelf's height).  Geometry-aware drop for
 * a failed request: per page and shelf, the windows between LIVE rects (members that are not resident slots); a window
 * wider than w on a shelf taller than h (or a shelf of residents only, at the page bottom, for a taller request) is made
 * free by dropping the residents inside it.  The window whose residents were used least recently goes.  1 = dropped
 * something (the allocator runs again), 0 = nothing resident left. */
int fc_drop(u32 node)
{
    u32 p, m, best = 0, bestl = 0xffffffff, bp = 0, bx0 = 0, bx1 = 0, by = 0, w = M8(node + 0xd), h = M8(node + 0xe);
    if (M32(FCV) != MAGIC) return 0;
    if (!fc_on()) return 1;                                      /* left the fight: residents unlinked, retry */
    for (p = M32(0x8005c920); p <= M32(0x80069a78) && p < 10; p++) {
        u32 x0 = M16(0x8005c604 + 4 * p) + 1;
        for (m = M32(LIST(p)); m; ) {
            u32 y = M16(m + 0x1c), sh = 0, n, last, start = x0, mx = 0, nres = 0, live = 0;
            for (n = m; n && M16(n + 0x1c) == y; n = M32(n + 4)) if (M8(n + 0xe) > sh) sh = M8(n + 0xe);
            last = !n;                                           /* the page's last shelf */
            for (n = m; ; n = M32(n + 4)) {                      /* windows between live members (and the shelf ends) */
                int end = !n || M16(n + 0x1c) != y;
                if (end || !ISRES(n)) {
                    u32 stop = end ? x0 + 0x3f : M16(n + 0x1a);
                    if (nres && stop - start > w && h < sh) {
                        if (mx < bestl) { bestl = mx; bp = p; bx0 = start; bx1 = stop; by = y; best = 1; }
                    }
                    if (end) break;
                    start = M16(n + 0x1a) + M8(n + 0xd); mx = 0; nres = 0; live = 1;
                } else { nres++; if (M32(n + 8) > mx) mx = M32(n + 8); }
            }
            if (last && !live && nres && h >= sh && mx < bestl) { bestl = mx; bp = p; bx0 = x0; bx1 = x0 + 0x3f; by = y; best = 1; }
            m = n;
        }
    }
    m = fc_lru(0);
    if (best && m && M32(m + 8) + 60 < bestl) best = 0;          /* a much older resident elsewhere goes first */
    if (best) {
        u32 i, r, k = 0;
        for (i = 0; i < NR; i++) {
            r = RS(i);
            if (M32(r + 8) && M8(r + 0xf) == bp && M16(r + 0x1c) == by && M16(r + 0x1a) >= bx0 && M16(r + 0x1a) < bx1) { fc_unlink(r); k++; }
        }
        if (k) { M32(FCV + 0x10) += k; return 1; }
    }
    if (!m) return 0;                                            /* no window: the least recently used one */
    fc_unlink(m); M32(FCV + 0x10) += 1;
    return 1;
}

/* frame change, before the old rect is unlinked: keep it resident when it holds its frame complete.
 * -> the node when the stock unlink should run, 0 = skip it (no rect, or the rect stays as a resident) */
u32 fc_rt(u32 n)
{
    u32 r, k = nidx(n), ok = 0;
    if (k < 128) { ok = M8(SIDE(k) + 4); M8(SIDE(k) + 4) = 0; }   /* the rect will not hold this frame any more */
    if (M8(n + 9) != 1) return 0;
    if (!fc_on() || !ok || M8(n + 0xf) || M8(n + 0x11) == 0x37 || M16(n + 0x20) == 0xffff || !(r = fc_lru(1))) return n;
    if (M32(r + 8)) fc_unlink(r);               /* table full: the LRU rect goes */
    fc_swap(n, r, M8(n + 0xc));
    M32(r + 8) = NOWW + 1; M8(r + 0xc) = M8(n + 0x11); M8(r + 0xd) = M8(n + 0xd); M8(r + 0xe) = M8(n + 0xe);
    M8(r + 0xf) = M8(n + 0xc); M16(r + 0x14) = M16(n + 0x20); M32(r + 0x10) = M32(SIDE(k));
    M16(r + 0x1a) = M16(n + 0x1a); M16(r + 0x1c) = M16(n + 0x1c);
    M8(n + 9) = 0; M32(FCV + 0xc) += 1;
    return 0;
}

/* in place of the stock jal 0x8005883c (dynamic rect; node +0x11 / +0x20 / +0xd / +0xe set; S: A at 0xa, B at 0x14) */
u32 fc_alloc(u32 n)
{
    u32 i, r, ab = H(0xa) | H(0x14) << 16;
    FCARM = 0; FCHIT = 0;
    if (fc_on() && M8(n + 0x11) != 0x37 && nidx(n) < 128) {
        FCARM = n; FCAB = ab;
        for (i = 0; i < NR; i++) {
            r = RS(i);
            if (M32(r + 8) && M16(r + 0x14) == M16(n + 0x20) && M8(r + 0xc) == M8(n + 0x11) && M32(r + 0x10) == ab
                && M8(r + 0xd) == M8(n + 0xd) && M8(r + 0xe) == M8(n + 0xe)) {
                fc_swap(r, n, M8(r + 0xf));
                M8(n + 0xc) = M8(r + 0xf); M16(n + 0x1a) = M16(r + 0x1a); M16(n + 0x1c) = M16(r + 0x1c); M8(n + 9) = 1;
                M32(r + 8) = 0; M32(FCV + 4) += 1; FCHIT = n;
                return 0;
            }
        }
        M32(FCV + 8) += 1;
    }
    return alloc_rect(n);
}

/* end of an upload loop (or of the quads after a hit): the node's rect holds its new frame (complete unless a part
 * was skipped) */
void fc_done(void)
{
    u32 n = W(0x90), k;
    if (FCARM == n && n) {
        k = nidx(n);
        M32(SIDE(k)) = FCAB;
        M8(SIDE(k) + 4) = !FCBAD && M8(n + 9) == 1 && !M8(n + 0xf) && B(2) == 0xff && M8(0x80042348) == 8;
        if (FCBAD) M32(FCV + 0x14) += 1;
    }
    FCARM = 0; FCHIT = 0; FCBAD = 0;
}
