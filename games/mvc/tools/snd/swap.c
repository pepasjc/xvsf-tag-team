/* MvC tag battles: entry swap on demand (RAM code, copied to SWAP_AT = 0x801fe800 by snd_finish() every tag battle;
 * entered from the EXE stub at the play function 0x80086ae8 only while the tag rules run: versus flag 0x8007b75d == 0,
 * LOADER_FULL 0x800858ac == 3, magic here).
 *
 * The SPU holds the full bank of all four characters, but the 250-slot entry table (u8 index per id at 0x80089bb8)
 * cannot: COMMON uses 126 of its 130 slots, the four character regions have 50 / 10 / 50 / 10 slots (banks 1-4 =
 * P1 point, P1 bench, P2 point, P2 bench).  The point region holds the point character's full entry list, the bench
 * region the benched character's assist ids (the stock partner bank's ids, <= 9).  Every list is kept in SPU RAM
 * (snd.c); when a request finds no entry and the owner map (SPU, u8 per id) names a character on a bench, its side is
 * swapped: point list <- that character's full list, bench list <- the other one's assist list (two SPU reads into
 * the table), ids re-registered.  Each entry carries its character's own bank number, so the bank address table is
 * never changed by a swap.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define TABK(k)  ((u8 *)0x800887c4u + 20 * (k))           /* entry of index byte k (1-based) */
#define IDT      ((u8 *)0x80089bb8u)
#define SPUTAB   ((u32 *)0x800884b4u)
#define SPUREAD  ((void (*)(u32, void *, u32, u32))0x80090434)
#define FULLB    1280                                    /* per slot in the list area: full list (50 x 20, 1024) + assist list (10 x 20, 256) */

struct swd { u32 magic; u32 lbase; u32 own; u32 a[5]; u8 point[2]; u8 lsrc[4]; u8 pad[2]; u8 scratch[64]; };
struct swd sw __attribute__((section(".swd"))) = { 0 };

#ifdef SPSSENT
/* (--spssent, 2026-11-25) the MiSTer PSX core reports an SPU -> RAM DMA done before its last words reach RAM: a
 * sentinel in the last destination word, then wait (bounded) until it changed.  DMA writes in order.  A real PS1 /
 * Beetle has the data there already: no wait. */
static __attribute__((noinline)) void rds(u32 a, void *d, u32 n)
{
    volatile u32 *e = (volatile u32 *)((u8 *)d + n - 4);
    *e = (u32)e;                                      /* sentinel = its own address */
    SPUREAD(a, d, 0, n);
    while (*e == (u32)e) ;                            /* unbounded here (1024 B image): owner-map / entry-list words
                                                         (bytes <= 0xff, ids < 0x501) never equal their 0x80.. address */
}
#define SPURD(a, d, n) rds(a, d, n)
#else
#define SPURD(a, d, n) SPUREAD(a, d, 0, n)
#endif
#ifdef SPSRDDLY
#ifndef SPSN
#define SPSN "256"
#endif
/* (--spsrddly, 2026-11-25) MiSTer PSX core (dma.vhd): DMA4 SPU -> RAM clears CHCR bit 24 when its RAM-side out FIFO is
 * NEAR empty (distance 2): the last words reach RAM a little later.  A short wait after every SpuRead before the data
 * is used (a real PS1 / Beetle: just a delay).  NOT a sentinel: a CPU store into the DMA destination can land in SDRAM
 * after the DMA's words on the core (--spssent froze 3/3 on .23). */
static __attribute__((noinline)) void rdd(u32 a, void *d, u32 n)
{
    SPUREAD(a, d, 0, n);
    __asm__ volatile(".set noreorder\n li $t0, " SPSN "\n1: addiu $t0, $t0, -1\n bnez $t0, 1b\n nop\n .set reorder" ::: "t0");
}
#undef SPURD
#define SPURD(a, d, n) rdd(a, d, n)
#endif

static void get(u8 *dst, u32 spu, u32 n)
{
    u32 f = n & ~63u, i;
    if (f) SPURD(spu, dst, f);
    if (n > f) {
        SPURD(spu + f, sw.scratch, 64);
        for (i = 0; i < n - f; i++) dst[f + i] = sw.scratch[i];
    }
}

static void unreg(int k0, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        int id = *(s16 *)TABK(k0 + i);
        if (id > 0 && id < 0x501 && IDT[id] == k0 + i) IDT[id] = 0;
    }
}

static void reg(int k0, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        int id = *(s16 *)TABK(k0 + i);
        if (id > 0 && id < 0x501) IDT[id] = (u8)(k0 + i);
    }
}

void snd_swapchk(int id)
{
    int o, x, b, kp, kb;
    if (SPUTAB[2] != sw.a[2]) { for (o = 1; o < 5; o++) SPUTAB[o] = sw.a[o]; }   /* undone by the EXE stub's restore */
    id &= 0xffff;
    if (id <= 0 || id >= 0x501 || IDT[id]) return;
    SPURD(sw.own + (id & ~63), sw.scratch, 64);
    o = sw.scratch[id & 63];
    if (o > 3) return;
    x = o & 1;
    if (sw.point[x] == o) return;
    b = o ^ 2;
    kp = x ? 191 : 131;                                   /* index bytes: bank base + 1 (COMMON 130, 50, 10, 50, 10) */
    kb = x ? 241 : 181;
    unreg(kp, 50); unreg(kb, 10);
    get(TABK(kp), sw.lbase + sw.lsrc[o] * FULLB, 1000);
    get(TABK(kb), sw.lbase + sw.lsrc[b] * FULLB + 1024, 200);
    reg(kb, 10); reg(kp, 50);
    sw.point[x] = (u8)o;
}
