/* MSHvSF 8 MB voice streaming engine, resident in upper RAM at S8_CODE (s8.h).  Linked on its own (s8.ld), copied
 * there by the 8 MB battle loader (snd8.c) from the blob; installed only on 8 MB consoles in tag battles.
 *
 * Voice samples of the battle (arcade samples converted at build time, or the stock ones) sit in upper RAM, one voice
 * store per bank (COMMON + the four characters).  Their entries in the game's sound table carry offset 0x8000 | index
 * instead of an SPU offset.  The play function 0x8007a920 computes the voice's SPU start at 0x8007ad08; there it calls
 * s8_play instead: a stream entry gets its SPU copy in the pool (two regions: the free part of the COMMON area and the
 * free SPU between the character banks and the stashes), on a miss the first CHUNK bytes are copied at once (DMA via the
 * game's own SPU write wrapper, synchronous) and the rest trickles from the main loop (s8_tick at 0x80020c84, the dead
 * ResetRCnt(2) call), most urgent first, up to two chunks per pass.  Pool segments are LRU; a segment a voice still
 * plays (ADSR volume != 0, or keyed in the last 4 frames) is never evicted.
 * Every SpuWrite that is not ours (libspu 0x8001bca8: SELECT.SE, the main menu's COMMON...) and touches a region turns
 * that region off until the next battle sets it up again, so a pool copy is never trusted after someone else wrote
 * over it.  No region / no room: the voice gets the one-shot silent block below region 0 (snd8e.c; libspu's 0x1000
 * block loops, and the VS screen after an arcade continue waits for its voice to end: 1.1 fix).  Only entries marked
 * S8_MARK (byte 0x13, set by snd8e.c's upload) stream: SELECT.SE / OP.SE have stock offsets >= 0x8000. */
#include "s8.h"

#define CD48      ((u32 *)0x8007cd48u)
#define SPUW      ((int (*)(u32, const void *, u32))0x8007b1ec)
#define RESETRCNT ((int (*)(int))0x800147f0)
#define VCOUNT    (*(volatile u32 *)0x8001e364u)      /* libetc VSync counter (what VSync(-1) returns) */
#define XADDR     (*(volatile u16 *)0x8001e8bcu)
#define XSHIFT    (*(volatile u32 *)0x8001e8ccu)
#define ENVX(v)   (*(volatile u16 *)(0x1f801c0cu + 16u * (v)))

__asm__(
    ".section .text.start, \"ax\"\n"
    ".set noreorder\n"
    "  j s8_play\n nop\n"
    "  j s8_tick\n nop\n"
    "  j s8_wrstub\n nop\n"
    "  j s8_fetch\n nop\n"
    "  j s8_flush\n nop\n"
    "  j s8_region\n nop\n"
    "  j s8_begin\n nop\n"
    "  j s8_load\n nop\n"
    "  j s8_end\n nop\n"
    "  j s8_stash\n nop\n"
    /* SpuWrite(src, size) entry: tell s8_wr, then the two overwritten instructions and back */
    "s8_wrstub:\n"
    "  addiu $sp, $sp, -40\n"
    "  sw $ra, 32($sp)\n"
    "  sw $a0, 24($sp)\n"
    "  sw $a1, 28($sp)\n"
    "  jal s8_wr\n"
    "  move $a0, $a1\n"
    "  lw $ra, 32($sp)\n"
    "  lw $a0, 24($sp)\n"
    "  lw $a1, 28($sp)\n"
    "  addiu $sp, $sp, 40\n"
    "  addiu $sp, $sp, -0x18\n"
    "  j 0x8001bcb0\n"
    "  sw $s0, 0x10($sp)\n"
    ".set reorder\n"
    ".text\n");


void *memcpy(void *d, const void *s, unsigned n)          /* struct copies (word aligned) */
{
    u32 *a = d; const u32 *b = s;
    n >>= 2;
    while (n--) *a++ = *b++;
    return d;
}

static int busy(const struct s8seg *s, u32 now)
{
    int v;
    if (!s->key) return 0;
    for (v = 0; v < NVOICE; v++)
        if (ST->vspu[v] == s->spu && (now - ST->vt[v] < 4 || ENVX(v))) return 1;
    return 0;
}

static void upload(struct s8seg *s, u32 n)
{
    if (n > s->tot - s->up) n = s->tot - s->up;
    ST->self = 1;
    SPUW(s->spu + s->up, s->src + s->up, n);
    ST->self = 0;
    s->up += n;
    ST->chunks++;
    s->pend = s->up < s->tot;
}

/* a free SPU range of `need` bytes: the window of consecutive idle segments (one region) whose newest use is the
 * oldest; merged into one segment (+ a free rest).  free_only: only windows without a cached voice (prefetch) */
static int alloc(u32 need, u32 now, int free_only)
{
    struct s8seg *g = ST->seg;
    int n = ST->nseg, i, j, best = -1, bend = 0, add, k;
    u32 bcost = ~0u, bspan = 0;
    for (i = 0; i < n; i++) {
        u32 span = 0, cost = 0;
        if (!ST->reg[g[i].reg].on || busy(&g[i], now)) continue;
        for (j = i; j < n && g[j].reg == g[i].reg; j++) {
            u32 c;
            if (busy(&g[j], now)) break;
            c = g[j].key ? g[j].last + 1 : 0;
            if (c > cost) cost = c;
            span += g[j].size;
            if (span >= need) break;
        }
        if (span < need || (free_only && cost)) continue;
        if (cost < bcost || (cost == bcost && span < bspan)) { best = i; bend = j; bcost = cost; bspan = span; }
        if (!bcost && bspan == need) break;
    }
    if (best < 0) return -1;
    add = bspan > need ? 2 : 1;
    if (n - (bend - best + 1) + add > NSEG) { add = 1; need = bspan; }
    {
        struct s8seg a = g[best];
        u32 spu = a.spu;
        int d = add - (bend - best + 1);
        if (d > 0) for (k = n - 1; k > bend; k--) g[k + d] = g[k];
        else if (d < 0) for (k = bend + 1; k < n; k++) g[k + d] = g[k];
        ST->nseg = n + d;
        g[best].key = 0; g[best].spu = spu; g[best].size = need; g[best].pend = 0; g[best].reg = a.reg;
        if (add == 2) {
            g[best + 1].key = 0; g[best + 1].spu = spu + need; g[best + 1].size = bspan - need;
            g[best + 1].pend = 0; g[best + 1].reg = a.reg;
        }
    }
    return best;
}

static u32 get(const struct s8vox *x, int i, u32 now, int play)
{
    const struct s8item *it = &x->it[i];
    u32 key = (u32)it;
    int k;
    struct s8seg *s;
    for (k = 0; k < (int)ST->nseg; k++) {
        s = &ST->seg[k];
        if (s->key == key) {
            s->last = now;
            if (!s->pend) s->t0 = now;
            ST->hits++;
            return s->spu;
        }
    }
    k = alloc(it->size, now, !play);
    if (k < 0) { if (play) ST->fails++; return 0; }
    s = &ST->seg[k];
    s->key = key; s->src = (const u8 *)x + it->off; s->tot = it->size; s->up = 0; s->bpf = it->bpf;
    s->t0 = s->last = now;
    upload(s, play ? CHUNK : it->size);
    if (play) ST->miss++; else ST->prefetch++;
    return s->spu;
}

u32 s8_play(u8 *e, u32 mask)
{
    u16 off = *(u16 *)(e + 4);
    int b = e[0x11], v;
    u32 a, now = VCOUNT;
    if (!(off & 0x8000) || e[0x13] != S8_MARK) {      /* stock offsets >= 0x8000 exist (SELECT.SE, OP.SE) */
        a = CD48[b] + ((u32)off << 3);
        for (v = 0; v < NVOICE; v++) if (mask >> v & 1) ST->vspu[v] = ~0u;
        return a;
    }
    a = 0;
    if (b <= 4 && ST->vox[b] && (off & 0x7fff) < ST->vox[b]->n) a = get(ST->vox[b], off & 0x7fff, now, 1);
    if (!a) a = ST->silent ? ST->silent : SILENT;   /* a one-shot block: a voice the game waits for still ends */
    ST->keys++;
    for (v = 0; v < NVOICE; v++) if (mask >> v & 1) { ST->vspu[v] = a; ST->vt[v] = now; }
    return a;
}

void s8_tick(int a0)
{
    int r, k;
    u32 now;
    RESETRCNT(a0);
    if (ST->magic != S8_MAGIC) return;
    if (ST->dbgplay) { u32 i = ST->dbgplay & 0xffff; ST->dbgplay = 0; ((void (*)(int, int, int, int))0x8007a920)(i, 0x1000, 0, 0); }
    now = VCOUNT;
    for (r = 0; r < 2; r++) {
        struct s8seg *s, *b = 0;
        int lead = 0;
        for (k = 0; k < (int)ST->nseg; k++) {
            s = &ST->seg[k];
            if (!s->pend) continue;
            if (!s->key || !ST->reg[s->reg].on) { s->pend = 0; continue; }
            {
                int l = (int)s->up - (int)(((now - s->t0) * s->bpf) >> 4);
                if (!b || l < lead) { b = s; lead = l; }
            }
        }
        if (!b || (r && lead >= 1536)) break;
        if (lead < 0) ST->starve++;
        upload(b, CHUNK);
    }
}

int s8_fetch(const struct s8vox *x, int i)
{
    return get(x, i, VCOUNT, 0) != 0;
}

void s8_flush(void)
{
    int k;
    for (k = 0; k < (int)ST->nseg; k++) {
        struct s8seg *s = &ST->seg[k];
        if (s->pend && s->key && ST->reg[s->reg].on) upload(s, s->tot);
        s->pend = 0;
    }
}

static void off(int r)
{
    int k;
    ST->reg[r].on = 0;
    for (k = 0; k < (int)ST->nseg; k++)
        if (ST->seg[k].reg == r) { ST->seg[k].key = 0; ST->seg[k].pend = 0; }
}

/* region r = [lo, hi) (64-byte steps), emptied and on (hi <= lo: off); the segment list stays sorted by address
 * (region 0 lies below region 1) */
void s8_region(int r, u32 lo, u32 hi)
{
    struct s8seg *g = ST->seg;
    int n = 0, k, at;
    for (k = 0; k < (int)ST->nseg; k++) if (g[k].reg != r) g[n++] = g[k];
    ST->reg[r].lo = lo; ST->reg[r].hi = hi; ST->reg[r].on = hi > lo;
    if (hi > lo) {
        at = r == 0 ? 0 : n;
        for (k = n; k > at; k--) g[k] = g[k - 1];
        g[at].key = 0; g[at].spu = lo; g[at].size = hi - lo; g[at].pend = 0; g[at].reg = r;
        n++;
    }
    ST->nseg = n;
}

void s8_wr(u32 size)
{
    u32 a, r;
    if (ST->self || ST->magic != S8_MAGIC) return;
    a = (u32)XADDR << XSHIFT;
    for (r = 0; r < NREG; r++)
        if (ST->reg[r].on && a < ST->reg[r].hi && a + size > ST->reg[r].lo) { ST->foreign++; off(r); }
}
