/* MvC 8 MB voice streaming engine (port of games/mshvsf/tools/ap8/s8/s8.c; same .SE engine).  Linked into the 8 MB
 * module (tools/ap8/mkap8.py); its state is at ST.  Hooks (installed by snd.c's SND8 part, snd8.inc): play 0x80086fc8
 * (SPU start of a voice = s8_play(entry, mask) instead of SPUTAB[bank] + off * 8; stream entries: byte 0x13 = S8_MARK
 * and offset 0x8000 | item), libspu SpuWrite 0x8001bc88 (a write that is not ours into a pool region turns the region
 * off until the next battle), main loop 0x80022f54 (ResetRCnt(2) -> s8_tick: trickle uploads).  A miss uploads the
 * first 1 KB at key-on through the game's SPU write 0x80087534 (synchronous), the rest 1 KB per main-loop pass, most
 * urgent first.  Pool segments LRU; a segment whose voice still sounds (ADSR volume, or keyed in the last 4 vblanks) is
 * never evicted; no room / region off: the one-shot silent block below region 0 (ST->silent). */
#include "s8.h"

#define SPUTAB    ((u32 *)0x800884b4u)
#define SPUW      ((int (*)(u32, const void *, u32))0x80087534)
#define RESETRCNT ((int (*)(int))0x80017260)
#define VCOUNT    (*(volatile u32 *)0x8001e214u)      /* libetc VSync counter */
#define XADDR     (*(volatile u16 *)0x8001e90cu)      /* libspu transfer start address (>> XSHIFT) */
#define XSHIFT    (*(volatile u32 *)0x8001e91cu)
#define ENVX(v)   (*(volatile u16 *)(0x1f801c0cu + 16u * (v)))
#define PLAYFN    0x80086ae8u

struct s8dir s8d __attribute__((section(".dir8m"))) = { 0x44384e53 };

__asm__(
    ".text\n"
    ".set noreorder\n"
    ".globl s8_wrstub\n"
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
    "  j 0x8001bc90\n"
    "  sw $s0, 0x10($sp)\n"
    ".set reorder\n");

static void wcp(void *d, const void *s, unsigned n)
{
    u32 *a = d; const u32 *b = s;
    n >>= 2;
    while (n--) *a++ = *b++;
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
        struct s8seg a;
        u32 spu;
        int d = add - (bend - best + 1);
        wcp(&a, &g[best], sizeof a);
        spu = a.spu;
        if (d > 0) for (k = n - 1; k > bend; k--) wcp(&g[k + d], &g[k], sizeof a);
        else if (d < 0) for (k = bend + 1; k < n; k++) wcp(&g[k + d], &g[k], sizeof a);
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
    if (!(off & 0x8000) || e[0x13] != S8_MARK || ST->magic != S8_MAGIC) {
        a = SPUTAB[b] + ((u32)off << 3);
        if (ST->magic == S8_MAGIC) for (v = 0; v < NVOICE; v++) if (mask >> v & 1) ST->vspu[v] = ~0u;
        return a;
    }
    a = 0;
    if (b <= 4 && ST->vox[b] && (off & 0x7fff) < ST->vox[b]->n) a = get(ST->vox[b], off & 0x7fff, now, 1);
    if (!a) a = ST->silent ? ST->silent : SILENT;
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
    if (ST->dbgplay) { u32 i = ST->dbgplay & 0xffff; ST->dbgplay = 0; ((void (*)(int, int, int, int))PLAYFN)(i, 0x1000, 0, 0); }
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

void s8_region(int r, u32 lo, u32 hi)
{
    struct s8seg *g = ST->seg;
    int n = 0, k, at;
    for (k = 0; k < (int)ST->nseg; k++) if (g[k].reg != r) { if (n != k) wcp(&g[n], &g[k], sizeof g[0]); n++; }
    ST->reg[r].lo = lo; ST->reg[r].hi = hi; ST->reg[r].on = hi > lo;
    if (hi > lo) {
        at = r == 0 ? 0 : n;
        for (k = n; k > at; k--) wcp(&g[k], &g[k - 1], sizeof g[0]);
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
