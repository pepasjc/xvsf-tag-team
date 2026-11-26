/* VRAM tile cache.  Decoded tiles are kept in otherwise unused VRAM (per stage: free 16-row band runs, proven on the
 * hack image: tools/speed/upload/vcmap.txt); a tile is split into 16-row chunks placed one after the other in a ring
 * over the runs, FIFO eviction.  Entry points:
 *   vc_decode(src, dst, n)   the stock 0x80059e60's pre-decode (dst is uploaded in a later frame, so it must hold the
 *                            pixels): hit = the chunks are read back into dst (StoreImage); miss = decode, then the
 *                            chunks are uploaded into the cache (LoadImage).
 *   vc_decode_lazy(src, dst, n), vc_load(rect, data)   the upload loops' decode + LoadImage of one part (dectile ->
 *                            rect -> LoadImage): a hit leaves dst alone and vc_load copies the chunks VRAM -> VRAM
 *                            from the cache into the part's rect; a miss decodes, vc_load uploads (fastload) and then
 *                            copies the part's rect VRAM -> VRAM into the cache.  The copies are GPU linked-list
 *                            packets (GP0 0x01 clear cache + 0x80 copy) queued through libgpu's _addque2 behind
 *                            everything queued before (the order of the LoadImage they stand for).
 *   vc_lookup / vc_prefetch  the decode-ahead API (work/speed/AHEAD_API.md).
 * libgpu runs a LoadImage / StoreImage / packet at once when its queue is empty and the GPU idle, else queues it, so
 * every cache transfer is ordered with the game's own GPU work.  VRAM outside the cache area and the pictures are
 * identical to the stock code (the game never sets the mask bits: GP0 E6 is only ever sent as 0 by libgpu).  dst
 * after a lazy hit does not hold the tile: it is a temporary block (flag 0 after the upload, nothing reads it).
 * Active only during a fight (match phase 0x80042348 == 8) on a known stage without Apocalypse; reset on any other
 * phase, at battle / round init (the block pool 0x80069ee0 is zeroed there: marker at 0x80069eee) and on a stage change. */
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32; typedef short s16;
#define M8(a)  (*(volatile u8 *)(a))
#define M16(a) (*(volatile u16 *)(a))
#define M32(a) (*(volatile u32 *)(a))
#define S8(o)  (*(u8 *)(0x1f800000 + (o)))
#define MARK   M16(0x80069eee)                 /* block 0 +0xe: never written by the game, zeroed at battle/round init */
#define NOWW   M32(0x800421b8)                 /* main loop counter (one DrawSync(0) per iteration in battle) */
#define NE 256
#define NB 64
#define NPK 25                                  /* packet slots (6 words: one chunk copy) */
#ifndef VC_DATA
#define VC_DATA 0x80068e50
#endif

extern u32 decode(u32 src, u32 dst, u32 n);
extern u32 LoadImage(u16 *rect, u32 src);
extern u32 fastload(u16 *rect, u32 src);
#define vc_runs ((const u8 *)(VC_RUNS + 4))   /* after the magic word "VCMP": per stage the address of its table - 0x80050000
                                                 (12 x u16); a stage table: n, n x (band, x0 in 4-halfword units, len) */

struct ent { u32 key; u16 pos; u8 wk, next; };          /* wk = (w - 1) | (k - 1) << 4, w in 4-halfword units */
#define E      ((struct ent *)VC_DATA)                    /* NE entries */
#define bucket ((u8 *)(VC_DATA + 8 * NE))                 /* NB heads */
#define STAMP  ((u8 *)(VC_DATA + 8 * NE + NB))            /* NE: low byte of the loop counter when last used */
struct st { u16 head, cnt, cur, L; const u8 *runs; u8 stage, nrun, pnext, pad; u16 rect[4]; u32 stats[8];
            u32 pframe; u8 pad2, pn, w, k; u32 e9, *pk, pfok; };
#define V      (*(struct st *)(VC_DATA + 8 * NE + NB + NE))
/* pending tiles: decoded (miss) or not (hit: dst left as it was) into dst, uploaded later by vc_load(rect, dst) */
struct pend { u32 dst, key, fp; u8 wk, e9, hit, i; };
#define NPEND 32
#define PEND   ((struct pend *)(VC_DATA + 8 * NE + NB + NE + 76))
#define PK     ((u32 *)(VC_DATA + 8 * NE + NB + NE + 76 + 16 * NPEND))   /* NPK x 6 words */
#define NOW    M8(0x800421b8)
enum { ST_HIT, ST_MISS, ST_INS, ST_COPYOUT, ST_COPYIN, ST_QLOAD, ST_NOPK, ST_PREF };
#ifdef VC_STATS
#define STAT(x, d) ((x) == ST_INS || (x) == ST_NOPK || (x) == ST_QLOAD || (x) == ST_PREF ? (void)0 : (void)(V.stats[x] += (d)))
#else
#define STAT(x, d) ((void)0)
#endif

/* the current tile's geometry: V.w (4-halfword units, bytes per row = 8 * V.w), V.k chunks, V.e9 rows */
static u32 __attribute__((noinline)) wkey(void) { return (V.w - 1) | (V.k - 1) << 4; }

static void __attribute__((noinline)) reset(void)
{
    int i;
    for (i = 0; i < NB; i++) bucket[i] = 0xff;
    V.head = V.cnt = V.cur = 0;
    for (i = 0; i < NPEND; i++) PEND[i].dst = 0;
}

static int __attribute__((noinline, section(".text.hcold"))) active(void)
{
#ifdef VC_OFF
    return 0;
#endif
    u32 s; int i;
    if (M8(0x80042348) != 8) { V.stage = 0xff; return 0; }
    for (i = 0; i < 4; i++) if (M16(0x800423b2 + 2 * i) == 16) return 0;   /* Apocalypse */
    s = M8(0x80042781);
    if (MARK != 0x5643 || s != V.stage) {
        u32 o, l = 0;
        if (s > 11 || M32(0x80060af0) != 0x800620e0 || M32(VC_RUNS) != 0x504d4356
            || M32(0x80069a78) != 4 || M32(0x8005c920) != 0) return 0;          /* sprite pages as measured: 0..4 */
        o = 0x80050000 + (vc_runs[2 * s] | vc_runs[2 * s + 1] << 8);
        V.runs = (const u8 *)o + 1; V.nrun = *(const u8 *)o;
        for (i = 0; i < V.nrun; i++) l += V.runs[3 * i + 2];
        V.L = l; reset(); V.stage = s; MARK = 0x5643;
    }
    return V.L != 0;
}

/* linear ring position p -> VRAM y << 16 | x (halfwords); 0x80000000 | next run start if a chunk of the current
 * width does not fit at p; 0xffffffff past the ring */
static u32 __attribute__((noinline)) where(u32 p)
{
    int i; u32 a = 0, w = V.w; const u8 *r = V.runs;
    for (i = 0; i < V.nrun; i++, r += 3) {
        u32 n = r[2];
        if (p < a + n) {
            if (p + w > a + n) return 0x80000000 | (a + n);
            return r[0] << 20 | (r[1] + p - a) << 2;
        }
        a += n;
    }
    return 0xffffffff;
}

/* walk the k chunks of the current tile from ring position p (no chunk across a run end).  op: 0 = only find the
 * end, 2 = read back into dst (StoreImage), 4 = upload from dst (LoadImage), 5 = packets copying cache -> rect,
 * 6 = packets copying rect -> cache (dst = rect y << 16 | x; packets at V.pk).  -> end, 0 = past the ring. */
static u32 __attribute__((noinline)) walk(u32 op, u32 p, u32 dst)
{
    u32 b, c, h, k = V.k, *pk = V.pk;
    for (b = 0; b < k; b++) {
        while ((c = where(p)) >> 31) { if (c == 0xffffffff) return 0; p = c & 0xffff; }
        h = b + 1 < k ? 16 : V.e9 - 16 * b;
        if (op == 4) {
            V.rect[0] = c & 0xffff; V.rect[1] = c >> 16; V.rect[2] = V.w * 4; V.rect[3] = h;
            LoadImage(V.rect, dst);
            dst += 128 * V.w;
        } else if (op) {
            u32 q = dst + (16 * b << 16);
            pk[0] = 5 << 24 | (b + 1 < k ? ((u32)(pk + 6) & 0xffffff) : 0xffffff);
            pk[1] = 0x01000000; pk[2] = 0x80000000;
            pk[3] = op == 5 ? c : q; pk[4] = op == 5 ? q : c; pk[5] = h << 16 | V.w * 4;
            pk += 6;
        }
        p += V.w;
    }
    return p;
}

/* libgpu command queue (64 entries, write index 0x80022628, read index 0x8002262c): room for n more without making
 * _addque2 wait (a full queue blocks the CPU until the GPU drains it) */
static int __attribute__((noinline)) qroom(u32 n)
{
    return ((M32(0x80022628) - M32(0x8002262c)) & 63) + n <= 40;
}

/* packet slots for the current tile's k chunk copies (-> V.pk), 0 = none.  The slots of an earlier main-loop
 * iteration are free again: that iteration's DrawSync(0) ran the queue to its end. */
static int __attribute__((noinline)) pk_alloc(void)
{
    if (!qroom(1)) return 0;
    if (NOWW != V.pframe) { V.pframe = NOWW; V.pn = 0; }
    if (V.pn + V.k > NPK) { STAT(ST_NOPK, 1); return 0; }
    V.pk = PK + 6 * V.pn; V.pn += V.k;
    return 1;
}

typedef int (*addque_fn)(u32 fn, u32 param, u32 size, u32 extra);
static void __attribute__((noinline)) copy(u32 op, u32 p, u32 rect)
{
    u32 vt = M32(0x8002251c);
    walk(op, p, rect);
    ((addque_fn)M32(vt + 8))(M32(vt + 0x18), (u32)V.pk, 0, 0);     /* as MoveImage / DrawOTag: linked-list DMA */
#ifdef VC_STATS
    V.stats[op - 2]++;
#endif
}

static inline u32 hash(u32 key) { return (key >> 3 ^ key >> 10) & (NB - 1); }

static void __attribute__((noinline)) unlink(u32 i)
{
    u8 *pp = &bucket[hash(E[i].key)];
    while (*pp != 0xff) {
        if (*pp == i) { *pp = E[i].next; return; }
        pp = &E[*pp].next;
    }
}

/* make room for the current tile at the ring cursor (FIFO eviction) and enter it under key; keep: refuse if that
 * would evict a tile used in this or the previous logic frame.  -> ring position of its first chunk, or -1 */
static int __attribute__((noinline)) place(u32 key, int keep)
{
    u32 c0, end, st, i, h, c, lo = 0xffff;
    if (V.w * V.k * 2 > V.L) return -1;
    c0 = V.cur;
    if (!(end = walk(0, c0, 0))) { lo = c0; if (!(end = walk(0, c0 = 0, 0))) return -1; }
    for (st = c0; (i = where(st)) >> 31; st = i & 0xffff) ;
    /* the oldest entries are the ones just ahead of the cursor: drop those that start inside [c0, end); after a wrap
     * to 0 first those between the old cursor and the ring end (lo: older than everything at 0..) */
    for (h = V.head, c = V.cnt; c && (c == NE || E[h].pos >= lo || (E[h].pos >= c0 && E[h].pos < end)); h = (h + 1) & (NE - 1), c--) {
        if (keep && (u8)(NOW - STAMP[h]) < 2) return -1;
        if (!keep) { unlink(h); V.head = (h + 1) & (NE - 1); V.cnt = c - 1; }
    }
    if (keep) return place(key, 0);
    i = (V.head + V.cnt) & (NE - 1);
    E[i].key = key; E[i].pos = st; E[i].wk = wkey(); STAMP[i] = NOW;
    h = hash(key); E[i].next = bucket[h]; bucket[h] = i;
    V.cnt++; V.cur = end; STAT(ST_INS, 1);
    return st;
}

/* insert the current tile from dst (RAM) by LoadImages (dst must stay unchanged until this main-loop iteration's
 * DrawSync: a pre-decoded block (flag 1) or a temporary block of the idle hook) */
static int __attribute__((noinline)) insert(u32 src, u32 dst, int keep)
{
    int st;
    if (!qroom(V.k) || (st = place(src, keep)) < 0) return 0;
    walk(4, st, dst); STAT(ST_QLOAD, 1);
    return 1;
}

/* fingerprint of a pending block (anything else writing it -> no longer ours) */
static u32 __attribute__((noinline)) fp(u32 dst, u32 n) { return M32(dst) ^ M32(dst + (n >> 1 & ~3)) ^ M32(dst + n - 4); }

/* the tile decoder of the upload loops and of the stock 0x80059e60's pre-decode: the block at dst is uploaded later
 * by vc_load (at once in the upload loops, a later frame for a pre-decode).  hit: nothing is decoded; miss: decode */
u32 vc_decode(u32 src, u32 dst, u32 n)
{
    u32 e8 = S8(0xe8), e9 = S8(0xe9), i, wk, r = 0;
    struct pend *p = PEND;
    if (!active()) return decode(src, dst, n);                     /* (PEND is cleared when the cache comes on) */
    for (i = 0; i < NPEND; i++, p++)                                /* pending blocks this decode writes over */
        if (p->dst < dst + n + 64 && dst < p->dst + 8 * ((p->wk & 15) + 1) * p->e9) p->dst = 0;
    V.w = e8 >> 3; V.k = (e9 + 15) >> 4; V.e9 = e9;
    if (n != e8 * e9 || V.k > 8 || !V.w || V.w > 16 || M8(M32(0x1f800090) + 0x11) == 0x37) return decode(src, dst, n);
    wk = wkey();
    for (i = bucket[hash(src)]; i != 0xff; i = E[i].next) if (E[i].key == src && E[i].wk == wk) break;
    if (i == 0xff) { r = decode(src, dst, n); STAT(ST_MISS, 1); }
    else { STAT(ST_HIT, 1); STAMP[i] = NOW; }
    p = PEND + V.pnext; V.pnext = (V.pnext + 1) & (NPEND - 1);
    p->dst = dst; p->key = src; p->wk = wk; p->e9 = e9; p->hit = i != 0xff; p->i = i; p->fp = fp(dst, n);
    return r;
}

/* LoadImage(rect, data) of the upload loops */
u32 vc_load(u16 *rect, u32 data)
{
    u32 r, i, xy = rect[1] << 16 | rect[0], n;
    struct pend *p = PEND;
    int st;
    if (V.stage == 0xff || !V.L || MARK != 0x5643) return fastload(rect, data);   /* cache off: nothing pending */
    for (i = 0; i < NPEND; i++, p++) if (p->dst == data && data) break;
    if (i == NPEND) return fastload(rect, data);
    p->dst = 0;
    V.w = (p->wk & 15) + 1; V.k = (p->wk >> 4) + 1; V.e9 = p->e9; n = 8 * V.w * V.e9;
    if (fp(data, n) != p->fp || rect[2] != V.w * 4 || rect[3] != V.e9 || rect[0] + V.w * 4 > 1024 || rect[1] + V.e9 > 512) {
        return fastload(rect, data);
    }
    if (p->hit) {                                                   /* hit: cache -> rect */
        if (E[p->i].key == p->key && E[p->i].wk == p->wk && ((p->i - V.head) & (NE - 1)) < V.cnt && pk_alloc()) {
            copy(5, E[p->i].pos, xy); return 0;
        }
        decode(p->key, data, n);                                    /* evicted / no packet room: decode after all */
        return fastload(rect, data);
    }
    r = fastload(rect, data);                                       /* miss: upload, then rect -> cache */
    if (pk_alloc() && (st = place(p->key, 0)) >= 0) copy(6, st, xy);
    return r;
}


#ifndef VC_NOAPI   /* 1.4 speed table (opt-in, UP_VC_DEFS=VC_NOAPI): no decode-ahead API (its home 0x80055c34 is sndpatch's now) */
/* the sprite layer's sweep freed the blocks of its LoadImages before the GPU ran them: the arena may be used outside
 * the sprite layer only when none of those is still pending (checked once per main-loop iteration; later blocks of
 * the idle hook are allocated live) */
static int __attribute__((noinline)) arena_ok(void)
{
#if defined(VC_STATS) && !defined(VC_PREF)
    return 0;
#endif
    u32 r = M32(0x8002262c), lf = M32(M32(0x8002251c) + 0x20);
    if (V.pfok == NOWW) return 1;
    if ((M32(0x1f8010a8) & 0x01000000) && M32(0x80022618) == lf) return 0;
    for (; r != M32(0x80022628); r = (r + 1) & 63) if (M32(0x80025f88 + 96 * r) == lf) return 0;
    V.pfok = NOWW;
    return 1;
}

/* ---------------------------------------------------------------- decode-ahead API (work/speed/AHEAD_API.md) */
struct ahead_tile { u32 src; u16 tile; u8 set, ticks, e8, e9, fmt, prio; u32 key; };

static u32 __attribute__((noinline, section(".text.hapi"))) find(u32 src)
{
    u32 i;
    for (i = bucket[hash(src)]; i != 0xff; i = E[i].next) if (E[i].key == src) return i;
    return 0xff;
}

__attribute__((section(".text.hapi"))) int vc_lookup(u32 key)
{
    u32 s2 = M32(0x8005c830 + 4 * (key >> 24));
    if (!active() || !s2) return 0;
    return find(s2 + (key & 0x3fffff)) != 0xff;
}

extern u32 alloc(void);

/* decode one predicted tile into the cache (idle time, main loop, never from an interrupt).  1 = cached now,
 * 0 = refused (stale / not cacheable / would evict a tile of this or the last frame / no room) */
__attribute__((section(".text.hapi"))) int vc_prefetch(const struct ahead_tile *t)
{
    u32 s2 = M32(0x8005c830 + 4 * t->set), src = s2 + (t->key & 0x3fffff), e8 = t->e8, e9 = t->e9, b, d, r;
    u8 o8, o9, *sp;
    if (!s2 || src != t->src || t->fmt || t->set == 0x37 || e9 > 128 || e9 < 16 || e8 < 8 || e8 > 128 || !active()) return 0;
    if (find(src) != 0xff) return 1;
#if defined(PF_A) || (defined(VC_STATS) && !defined(VC_PREF))     /* (measurement builds: no room for both) */
    return 0;
#endif
    if (!arena_ok()) return 0;
    sp = (u8 *)M32(0x8006a340);                                     /* the allocator's S (not always the scratchpad) */
    o8 = sp[0xe8]; o9 = sp[0xe9]; sp[0xe8] = e8; sp[0xe9] = e9;
    b = alloc();                                                    /* a temporary arena block (no waiting) */
    sp[0xe8] = o8; sp[0xe9] = o9;
    if (b == 0xffffffff) return 0;
    V.w = e8 >> 3; V.k = (e9 + 15) >> 4; V.e9 = e9;
    d = M32(0x80060af0) + *(s16 *)(b + 0xa);
    decode(src, d, e8 * e9);
#ifdef PF_B
    M8(b + 8) = 0; return 0;
#endif
    r = insert(src, d, 1);
    M8(b + 8) = 0;                                                  /* uploaded (or queued before this iteration's
                                                                       DrawSync(0)): the next sweep frees it */
    STAT(ST_PREF, r);
    return r;
}
#endif /* VC_NOAPI */
