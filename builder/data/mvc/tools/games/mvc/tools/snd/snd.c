/* Full sound banks for every character of an MvC tag battle (SLUS-01059), linked into the tag loader blob
 * (tools/tagload/tagload.c).  Build side: tools/snd/sndbank.py, sndbuild.py; notes: games/mvc/docs/SOUND.md.
 *
 * Stock battle: SPU 0x1010 COMMON (bank 0, loaded once at boot), banks 1-4 at 0x315b0 / 0x490e0 / 0x4cac0 / 0x645f0
 * (P1 main CHRxx 97 KB, P1 partner = section 3 of PLxx_11.A0 14.8 KB, P2 main, P2 partner), kind-6 sets 0x68000..,
 * SP_EFF2 0x75800...  Entry table 0x800887d8: 250 slots, COMMON 130 / 50 / 10 / 50 / 10 (0x800884dc), id -> u8
 * index + 1 (0x80089bb8), bank SPU addresses 0x800884b4[bank], entries per bank 0x80089b80.
 *
 * Here (per tag battle): one level (sndbank.LADDER: effects capped first, then voices) for COMMON and the four
 * characters' full banks so that COMMON + the four banks + the entry lists fit below 0x68000:
 *     0x1010 COMMON (our file; re-uploaded only when another level is loaded: marker in entry 0's spare byte),
 *     the four banks (64-byte steps), then the entry lists: per slot the full list (50 slots) and the assist list (10),
 *     then the owner map (u8 per id: slot whose bank has it).
 * Banks 1-4 of the bank address table point at the slots' banks (slot s -> bank 1 / 3 / 2 / 4), their table regions
 * get the point character's full list (1, 3) and the benched character's assist list (2, 4); swap.c (RAM code)
 * swaps a side's lists when a benched character asks for a sound the table does not have.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#ifndef SND_NL
#define SND_NL 36
#endif
#define NB         28                         /* COMMON, 21 characters, 6 Mega Man variants (sndbank.bank_names) */
#define NSUB       10
#define TABK(k)    ((u8 *)0x800887c4u + 20 * (k))
#define IDT        ((u8 *)0x80089bb8u)
#define SPUTAB     ((u32 *)0x800884b4u)
#define CNT        ((s16 *)0x80089b80u)
#define FTAB       ((u32 *)0x800255e4u)
#define SPARE      0x1ab
#define RD         ((int (*)(int, void *))0x80024800)
#define SPUW       ((int (*)(u32, void *, u32))0x80087534)
#define SPUREAD    ((void (*)(u32, void *, u32, u32))0x80090434)
#ifdef SPSSENT
/* (--spssent, 2026-11-25) the MiSTer PSX core reports an SPU -> RAM DMA done before its last words reach RAM: a
 * sentinel in the last destination word, then wait (bounded) until it changed.  DMA writes in order.  A real PS1 /
 * Beetle has the data there already: no wait. */
static __attribute__((noinline)) void rds(u32 a, void *d, u32 n)
{
    volatile u32 *e = (volatile u32 *)((u8 *)d + n - 4);
    u32 k = 0x10000;
    *e = (u32)e;                                      /* sentinel = its own address */
    SPUREAD(a, d, 0, n);
    while (*e == (u32)e && --k) ;
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
#define UNLOAD     ((int (*)(int))0x80087410)
#define REG0       ((void (*)(void))0x800873ac)   /* registers bank 0's ids */
#define SPU_COMMON 0x1010u
#define SPU_END    0x68000u                   /* kind-6 sets from here (tagload.c SPU0) */
#define SWAP_AT    0x801fe800u
#define FULLB      1280
#define OWNB       0x540
#define SWMAGIC    0x4d444e53u                /* 'SNDM' */

extern void flushcache(void);
u32 snd_spu_end = SPU_END;                   /* end of the bank area; the 8 MB loader (tools/ap8) raises it to 0x75800 */
extern u8 tl_dbg[16];

struct slev { u32 msf; u16 d16; u8 n; u8 pad; };   /* level file: msf, sample bytes / 16, entries (file = 20 (n+1) + d) */
struct sdir {
    u32 magic;
    u32 swsize;                               /* bytes of the swap code image (struct swd + code) */
#ifdef SNDX                                   /* --spustore: the level table is a disc item (blob space), read by */
    u32 bx_msf, bx_size;                      /* snd_table() at tl_main start, the chosen level copied by snd_plan */
#else
    struct slev b[NB][SND_NL];
#endif
    u16 sub[0x17][NSUB];                      /* assist ids per character (stock partner bank), 0 = none */
    u32 sw[256];                              /* swap code image, linked at SWAP_AT (<= 0x801fec00) */
};
struct sdir snd_dir __attribute__((section(".sdir"))) = { 0x43444e53 };   /* 'SNDC'; filled by mktag.py */

struct swd { u32 magic; u32 lbase; u32 own; u32 a[5]; u8 point[2]; u8 lsrc[4]; u8 pad[2]; u8 scratch[64]; };

static int lvl = -1;
static u32 at[4], lbase, own;
static signed char lsl[4];
u8 snd_dbg[8];                               /* [0] level, [1] 1 planned, [2] COMMON re-uploaded, [3] fits */
static const u8 BANK[4] = { 1, 3, 2, 4 };      /* slot -> bank (the stock upload swaps 2 and 3) */
static const u8 K0[5] = { 0, 131, 181, 191, 241 }; /* first index byte of each bank's table region */
static const u32 STOCKA[5] = { 0x1010, 0x315b0, 0x490e0, 0x4cac0, 0x645f0 };

static u32 r64(u32 x) { return (x + 63) & ~63u; }
#ifdef VOLROW
/* (voice 3) --voicevol: voice entries come with volume | 0x8000 (data +6 dB over stock, sndhq.voice_hq); the EX OPTIONS
 * row VOICE VOLUME (byte 0x80011763: 0 NORMAL, 1 +3 DB, 2 +6 DB) scales them by 64 / 90 / 128 and clears the flag. */
#define VROW (*(volatile u8 *)0x80011763u)
static const u8 VK[3] = { 64, 90, 128 };
static void vscale(u8 *e)
{
    u16 v = *(u16 *)(e + 2);
    if (v & 0x8000) { v = (u16)(((v & 0x7f) * VK[VROW < 3 ? VROW : 0] + 64) >> 7); *(u16 *)(e + 2) = v ? v : 1; }
}
#define VROWTAG ((u8)(0x40 | (VROW < 3 ? VROW : 0)))
#endif
static u32 sec(u32 x) { return (x + 2047) & ~2047u; }
static int bix(int c, int s) { return c == 0x10 ? 22 + (s < 2 ? *(u8 *)0x8007b8e3u : 0) : (c < 0x10 ? c : c - 1); }
#ifdef SNDX
static const struct slev *TB;                 /* the table in RAM (planning), 0 after snd_plan: bl[] = chosen level */
static struct slev bl[NB];
#define LV(b, L) (TB ? &TB[(b) * SND_NL + (L)] : &bl[b])
#else
#define LV(bk, L) (&snd_dir.b[bk][L])
#endif
static u32 dsz(int b, int L) { return (u32)LV(b, L)->d16 << 4; }
static u32 fsz(int b, int L) { return 20u * (LV(b, L)->n + 1) + dsz(b, L); }
static u32 mmax(int c, int L)                 /* Mega Man: the variant is picked during the load, plan with the biggest */
{
    int v; u32 m = 0;
    if (c != 0x10) return r64(dsz(bix(c, 2), L));
    for (v = 0; v < 6; v++) if (r64(dsz(22 + v, L)) > m) m = r64(dsz(22 + v, L));
    return m;
}

#ifdef SNDVFY
/* --sndverify (rc4, Onslaught-ending freeze): an SPU upload can end short (fight 3 of coldtest arcade 1,c,6,10 on the
 * rc3 line with the store: COMMON stopped after ~8 KB while the RAM table took the new level -> table and SPU at
 * different levels -> a looping voice froze the post-Onslaught ending).  Every upload is read back (first and last
 * 64 bytes) and repeated (up to 4 times) until both match; snd_dbg[4] counts the repeats. */
#ifdef SPSVERIFY
/* (--spsverify, 2026-11-25) the MiSTer PSX core can return bad SPU -> RAM data: the owner map (read, changed, written
 * back) is read until two consecutive reads have the same word sum (at most 4 reads) */
static void rdv(u32 a, u8 *w, u32 n)
{
    u32 s0 = 0, s, i, k;
    for (k = 0; k < 4; k++) {
        SPURD(a, w, n);
        for (s = 0, i = 0; i + 4 <= n; i += 4) s += *(u32 *)(w + i);
        if (k && s == s0) break;
        s0 = s;
    }
}
#endif
#ifdef SPSDRAIN
/* (--spsdrain, 2026-11-25) the MiSTer PSX core reports an SPU upload done while up to 128 halfwords still sit in its
 * write FIFO (drained ~24 per sample); whatever is queued when the next transfer address is set lands at that NEW
 * address.  ~1 ms of busy wait after every upload lets the FIFO drain (a real SPU is done already: just a delay). */
static void drain(void) { volatile u32 i; for (i = 0; i < 3000; i++) ; }
#else
#define drain() ((void)0)
#endif
static u8 vbuf[64];
static int same64(u32 a, const u8 *src)
{
    int i;
    SPURD(a, vbuf, 64);
    for (i = 0; i < 64 && vbuf[i] == src[i]; i++) ;
    return i == 64;
}
static void spuw(u32 a, void *src, u32 n)
{
    int t;
    for (t = 0; t < 4; t++) {
        SPUW(a, src, n);
        drain();
        if (n < 64 || (same64(a, (const u8 *)src) && same64(a + n - 64, (const u8 *)src + n - 64))) return;
        snd_dbg[4]++;
    }
}
#define SPUWV(a, s, n) spuw((a), (s), (n))
#else
#define SPUWV(a, s, n) do { SPUW((a), (s), (n)); drain(); } while (0)
#endif

static int rdfile(const struct slev *v, u32 size, void *dst)
{
    u32 om = FTAB[SPARE * 2], os = FTAB[SPARE * 2 + 1];
    int n;
    FTAB[SPARE * 2] = v->msf; FTAB[SPARE * 2 + 1] = size;
    n = RD(SPARE, dst);
    FTAB[SPARE * 2] = om; FTAB[SPARE * 2 + 1] = os;
    return n;
}

#ifdef SND8
#include "s8.h"                              /* tools/ap8/s8 (8 MB module): voice streaming, snd8.inc below */
static int s8on;
#endif

#ifdef SNDX
/* tl_main start (region start, nothing placed yet): the level table -> dst */
void snd_table(void *dst)
{
    struct slev v = { snd_dir.bx_msf, (u16)(snd_dir.bx_size >> 4), 0, 0 };
    TB = 0;
    if (snd_dir.magic != 0x43444e53 || !snd_dir.bx_size) return;
    rdfile(&v, snd_dir.bx_size, dst);
    TB = (const struct slev *)dst;
}
#endif

/* every battle load (also when the loader declines): the stock bank addresses */
void snd_reset(void)
{
    int b;
    lvl = -1;
    if (snd_dir.magic != 0x43444e53) return;
    for (b = 1; b < 5; b++) SPUTAB[b] = STOCKA[b];
    *(u32 *)SWAP_AT = 0;                      /* swap code off until this battle's snd_finish */
#ifdef SND8
    s8on = s8d.magic == 0x44384e53u && s8d.on;
#endif
}

static void voices_idle(void)                 /* as the stock upload 0x800870e0 */
{
    int i;
    for (i = 0; i < 8; i++) ((u32 *)0x80089b60u)[i] = 0;
    *(u8 *)0x800887c8u = 10; *(u32 *)0x800887ccu = 0xc00; *(u16 *)0x800887d0u = 0;
    ((void (*)(void))0x8008707c)();
}

#ifdef SND8                                  /* 8 MB module only (tools/ap8/mkap8.py): voice streaming */
#include "snd8.inc"
#endif

/* SPU end the lowest sound level needs for this team (tagload.c plan_spu may lower the kind-6 area start to it);
 * SPU_END when the full banks are off (stock layout) */
u32 snd_need_min(signed char *list)
{
    int s, L = SND_NL - 1;
    u32 a;
    if (snd_dir.magic != 0x43444e53) return SPU_END;
#ifdef SND8
    if (s8on) return s8_need(list);
#endif
    a = SPU_COMMON + r64(dsz(0, L));
    for (s = 0; s < 4; s++) if (list[s] >= 0) a += mmax(list[s], L);
    return a + 4 * FULLB + OWNB;
}

#ifdef SPUSTORE
/* --spustore (tagload.c): end of the sound data at the level snd_plan will pick for snd_spu_end = end (the store
 * uses [that, end)); end itself when no level fits */
u32 snd_end_plan(signed char *list, u32 end)
{
    int s, L;
    u32 a;
    if (snd_dir.magic != 0x43444e53) return end;
#ifdef SND8
    if (s8on) return s8_need(list) <= end ? s8_need(list) : end;
#endif
    for (L = 0; L < SND_NL; L++) {
        a = SPU_COMMON + r64(dsz(0, L));
        for (s = 0; s < 4; s++) if (list[s] >= 0) a += mmax(list[s], L);
        a += 4 * FULLB + OWNB;
        if (a <= end) return a;
    }
    return end;
}
#endif

#ifdef ASSIST
/* --assist (assists lead, rc4.4) */
const int snd_nlv = SND_NL;
/* end of the sound data at ladder level L (tagload.c as_search); 0 for L out of range */
u32 snd_end_lv(signed char *list, int L)
{
    int s;
    u32 a;
    if (snd_dir.magic != 0x43444e53 || L < 0 || L >= SND_NL) return 0;
#ifdef SND8
    if (s8on) return s8_need(list);
#endif
    a = SPU_COMMON + r64(dsz(0, L));
    for (s = 0; s < 4; s++) if (list[s] >= 0) a += mmax(list[s], L);
    return a + 4 * FULLB + OWNB;
}
/* an assist's SPCxx_y.SE (read to T, size bytes): samples to SPU a, its entries into COMMON's free table slots k0..130
 * (bank 0: offsets from SPU_COMMON), ids indexed.  -> entries registered */
int snd_assist(u8 *T, u32 size, u32 a, int k0)
{
    int n = *(u16 *)T, i, k;
    u32 d = 20u * (n + 1);
    voices_idle();
    SPUWV(a, T + d, r64(size - d));
    for (i = 0; i < n && k0 + i <= 130; i++) {
        u8 *e = T + 0x14 + 20 * i, *t = TABK(k0 + i);
        u32 off = *(u16 *)(e + 4) + ((a - SPU_COMMON) >> 3);
        for (k = 0; k < 20; k++) t[k] = e[k];
        *(u16 *)(t + 4) = (u16)off;
        t[0x11] = 0;
        IDT[*(s16 *)e] = (u8)(k0 + i);
    }
    return i;
}
#endif

/* before the first slot: level, SPU layout, COMMON, empty lists / owner map */
void snd_plan(signed char *list)
{
    int s, L, b;
    u32 a, scratch;
    u8 *w;
    if (snd_dir.magic != 0x43444e53) return;
#ifdef SND8
    if (s8on) { s8_plan(list); return; }
#endif
    for (s = 0; s < 4; s++) {
        lsl[s] = list[s] >= 0 ? s : -1;
        if (list[s] < 0) { int k = ~list[s]; lsl[s] = (k >= 0 && k < 4) ? k : -1; }
    }
    for (L = 0; L < SND_NL; L++) {
        a = SPU_COMMON + r64(dsz(0, L));
        for (s = 0; s < 4; s++) if (list[s] >= 0) a += mmax(list[s], L);
        a += 4 * FULLB + OWNB;
        if (a <= snd_spu_end) break;
    }
    snd_dbg[3] = L < SND_NL;
    if (L == SND_NL) L = SND_NL - 1;
    lvl = L;
#ifdef SNDX
    for (b = 0; b < NB; b++) bl[b] = TB[b * SND_NL + L];   /* before the scratch (region start) is overwritten */
    TB = 0;
#endif
    a = SPU_COMMON + r64(dsz(0, L));
    for (s = 0; s < 4; s++) if (list[s] >= 0) { at[s] = a; a += mmax(list[s], L); }
    lbase = a; own = a + 4 * FULLB;
    voices_idle();
    for (b = 1; b < 5; b++) UNLOAD(b);
    /* scratch: the loader's region start (GPU pool end), free until the first read */
    scratch = *(u32 *)(tl_dbg + 8);
    if (scratch < 0x80090000u || scratch > 0x800c4fe4u) scratch = 0x800c4fe4u;
    w = (u8 *)((scratch + 7) & ~7u);
    /* COMMON: same entries (order, ids) as the boot's, our samples */
#ifdef VOLROW
    if (TABK(1)[0x13] != (0x80 | L) || TABK(2)[0x13] != VROWTAG) {   /* (voice 3) the row is part of the marker */
#else
    if (TABK(1)[0x13] != (0x80 | L)) {
#endif
        const struct slev *v = LV(0, L);
        int i, k;
        rdfile(v, fsz(0, L), w);
        SPUWV(SPU_COMMON, w + 20 * (v->n + 1), r64(dsz(0, L)));
        for (i = 0; i < v->n; i++) {
            u8 *d = TABK(1 + i), *e = w + 0x14 + 20 * i;
            for (k = 0; k < 20; k++) if (k != 0x11 && k != 0x12) d[k] = e[k];
            d[0x13] = 0x80 | L;
#ifdef VOLROW
            vscale(d);
#endif
        }
#ifdef VOLROW
        TABK(2)[0x13] = VROWTAG;
#endif
        REG0();
        snd_dbg[2] = 1;
    }
    for (s = 0; s < 4 * FULLB + OWNB; s++) w[s] = s >= 4 * FULLB ? 0xff : 0;    /* empty lists, owner map */
    SPUWV(lbase, w, 4 * FULLB + OWNB);
    snd_dbg[0] = L; snd_dbg[1] = 1;
}

/* the sound part of slot s (char c): level file -> top scratch, samples -> SPU, the table region, the lists, owners */
int snd_load(int s, int c, u32 top)
{
    const struct slev *v;
    u8 *T, *E, *w;
    int b, i, k, n, kreg, cap;
    u32 base;
    if (lvl < 0) return 0;
#ifdef SND8
    if (s8on) {                                                   /* the slot's .SN8 (upper RAM), its residents */
        T = s8_file(s, c);
        n = (int)s8f[s]->nent;
        voices_idle();
        ST->self = 1;
        SPUWV(at[s], T + 20 * (n + 1), s8f[s]->samp);
        ST->self = 0;
        v = 0; (void)top;
    } else
#endif
    {
    b = bix(c, s);
    v = LV(b, lvl);
    T = (u8 *)((top - sec(fsz(b, lvl))) & ~7u);
    rdfile(v, fsz(b, lvl), T);
    voices_idle();
    SPUWV(at[s], T + 20 * (v->n + 1), r64(dsz(b, lvl)));
    n = v->n;
    }
    E = T + 0x14;
    for (i = 0; i < n; i++) {
        E[20 * i + 0x11] = BANK[s];                               /* every entry plays from its character's bank */
#ifdef VOLROW
        vscale(E + 20 * i);
#endif
    }
    w = (u8 *)(((u32)T - FULLB - OWNB - 64) & ~7u);               /* staging below the bank file */
#ifdef SND8
    if (s8on) w = s8stg;                                          /* (the .SN8 sits in upper RAM: S8_STG) */
#endif
    /* full list (50 slots) + assist list (10) of this slot */
    for (i = 0; i < FULLB; i++) w[i] = 0;
    for (i = 0; i < 20 * n && i < 1000; i++) w[i] = E[i];
    for (i = 0, k = 0; i < n && k < NSUB; i++) {
        int id = *(s16 *)(E + 20 * i), j;
        for (j = 0; j < NSUB; j++)
            if (snd_dir.sub[c][j] && snd_dir.sub[c][j] == id) {
                int q;
                for (q = 0; q < 20; q++) w[1024 + 20 * k + q] = E[20 * i + q];
                k++; break;
            }
    }
    SPUWV(lbase + s * FULLB, w, FULLB);
    /* the table region of this slot's bank: point (mains) full list, bench (partners) assist list */
    kreg = K0[BANK[s]]; cap = s < 2 ? 50 : 10;
    for (i = 0; i < 20 * cap; i++) TABK(kreg)[i] = w[(s < 2 ? 0 : 1024) + i];
    CNT[BANK[s]] = cap;
    /* owner map: read, mark this slot's ids (first owner stays), write back */
#ifdef SPSVERIFY
    rdv(own, w, OWNB);
#else
    SPURD(own, w, OWNB);
#endif
    for (i = 0; i < n; i++) {
        int id = *(s16 *)(E + 20 * i);
        if (id > 0 && id < 0x501 && w[id] == 0xff) w[id] = (u8)s;
    }
    SPUWV(own, w, OWNB);
    base = 0; (void)base;
#ifdef SND8
    if (s8on) {
        ST->vox[BANK[s]] = (const struct s8vox *)((const u8 *)s8f[s] + s8f[s]->vox);
        ST->ssum[s] = s8wsum((u32 *)s8f[s], ST->sn[s]);           /* with this slot's bank bytes */
    }
#endif
    return 1;
}

/* after the last slot: bank addresses, swap code */
void snd_finish(void)
{
    struct swd *d = (struct swd *)SWAP_AT;
    u32 i;
    int s;
    if (lvl < 0) return;
    for (s = 0; s < 4; s++) if (lsl[s] == s) SPUTAB[BANK[s]] = at[s];
    for (i = 1; i < snd_dir.swsize / 4; i++) ((u32 *)SWAP_AT)[i] = snd_dir.sw[i];
    d->lbase = lbase; d->own = own;
    for (s = 0; s < 5; s++) d->a[s] = SPUTAB[s];
    d->point[0] = 0; d->point[1] = 1;
    for (s = 0; s < 4; s++) d->lsrc[s] = lsl[s] < 0 ? (u8)s : (u8)lsl[s];
#ifdef SND8
    if (s8on) s8_finish();                           /* region 1, prefetch, hooks (flushed below) */
#endif
    flushcache();
    d->magic = SWMAGIC;
}
