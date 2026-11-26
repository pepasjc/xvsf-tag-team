/* 8 MB battle sound with voice streaming (MSHvSF tag hack 8 MB build; engine: s8/s8.c, files: tools/snd/sn8build.py).
 * Linked into the ap8 blob only (the 2 MB loader and tools/snd/snd.c are unchanged).
 *
 * SPU in a streaming battle:
 *   0x01010            COMMON residents (effects, looping samples) of COMMON.SN8, then region 0 of the pool .. 0x315d0
 *   0x315d0            the four characters' residents (64-byte steps), then region 1 of the pool .. the stashes
 *   stashes            the mains' kind-6 sets packed right below 0x70800 (P1 on top), as tools/snd/snd.c does
 *   0x70800-          stage SP_EFF2 / AKEBONO / bank 5 (stock)
 * Region 0 survives select screens (SELECT.SE starts at 0x315d0), so COMMON voices keep working there; the engine
 * turns a region off as soon as a write that is not ours lands in it.
 *
 * Entry table: as snd.c (slots of banks 1-4 re-partitioned per battle, the rest to OVF, its unload hook installed by
 * snd_reset).  COMMON = ours while entry 0's spare byte is SN8_MARK (the main menu reloads the stock COMMON). */
#include "s8/s8.h"

#define TAB        ((u8 *)0x8007d330u)
#define IDTAB      ((u8 **)0x8007e220u)
#define FB18       ((s16 *)0x8007fb18u)
#define CD48       ((u32 *)0x8007cd48u)
#define CD60       ((u32 *)0x8007cd60u)
#define CD8C       ((u8 *)0x8007cd8cu)
#define UNLOAD     ((void (*)(int))0x8007b06c)
#define WAITIDLE   ((void (*)(void))0x8007adc0)
#define SPUW       ((int (*)(u32, void *, u32))0x8007b1ec)
#define RD         ((int (*)(int, void *))0x80024554)
#define FTAB       ((u32 *)0x800247dcu)
#define SPARE      0x10f
#define SPU_COMMON 0x1010u
#define SPU_CHARS  0x315d0u
#define SPU_TOP    0x70800u
#define SLOTS14    114
#define OVFN       (*(u32 *)0x801ff07cu)
#define OVF        ((u8 *)0x801ff080u)
#define OVFMAX     70
#define SN8_MARK   0xc1
#define NCH        0x17

extern void flushcache(void);
extern u8 tl_dbg[16];
struct schr_ { u8 lv[12 * 36]; u16 stash; u16 pad; };          /* tools/snd/snd.c struct schr (SND_NL = 36) */
extern struct { u32 magic; u32 hook[30]; struct schr_ c[NCH + 1]; } snd_dir;

struct fent8 { u32 msf, size; };
struct sdir8 {
    u32 magic;                                  /* 'SN8D' */
    u32 on;                                     /* .SN8 files on this disc */
    u32 c_sn8;                                  /* part offset in a cache slot (ap8.c) */
    u32 comat;                                  /* COMMON.SN8 in upper RAM */
    struct fent8 com;
    struct fent8 c[NCH];
};
struct sdir8 tl8_snd __attribute__((section(".dir8"))) = { 0x44384e53 };
struct sn8 { u32 magic, nent, bank, banklen, samp, vox, voxlen, npf, pf; };

extern const u8 s8_bin[], s8_bin_end[];
#define snd8_dbg (ST->ldbg)                /* [0] used this battle, [1] fits, [2] COMMON uploaded, [3] prefetched, [4] overflow */

u8 snd8_first;                   /* set by ap8.c: first battle of this boot (fresh engine state) */
static u32 stash[4], at[4];
static const struct sn8 *sn[4];
static int used;

static int fchar(int c) { return c == 0x17 ? 2 : c == 0x18 ? 8 : c == 0x19 ? 7 : c; }
static u32 r64(u32 x) { return (x + 63) & ~63u; }

static u32 wsum(const u32 *p, u32 n)
{
    u32 s = 0x5a17u;
    n = (n + 3) >> 2;
    while (n--) s += *p++;
    return s;
}

int snd8_on(void) { return tl8_snd.magic == 0x44384e53 && tl8_snd.on; }
u32 snd8_top(void) { return tl8_snd.comat; }
const struct fent8 *snd8_file(int c) { return &tl8_snd.c[fchar(c)]; }
u32 snd8_stash(int s) { return stash[s]; }

static void upload(int b, const struct sn8 *f, u32 spu)
{
    const u8 *bank = (const u8 *)f + f->bank;
    int i, cap, base, n = f->nent;
    WAITIDLE();
    for (i = 0; i < 8; i++) ((u32 *)0x8007faf0u)[i] = 0;
    *(u8 *)0x8007fb10u = 6;
    base = 0;
    for (i = 0; i < b; i++) base += CD8C[i];
    cap = CD8C[b];
    for (i = 0; i < n; i++) {
        const u8 *e = bank + 0x14 + 20 * i;
        u8 *d;
        int id, k;
        if (i < cap) d = TAB + 20 * (base + i);
        else {
            if (OVFN >= OVFMAX) break;
            d = OVF + 20 * OVFN++; snd8_dbg[4]++;
        }
        for (k = 0; k < 20; k++) d[k] = e[k];
        d[0x11] = b; d[0x12] |= 1 << b;
        id = *(s16 *)d;
        if (id == 0x139 && b) continue;
        if (b == 3 && *(s16 *)0x80070f5eu == 0x26 && IDTAB[id]) continue;
        IDTAB[id] = d;
    }
    FB18[b] = n < cap ? n : cap;
    CD48[b] = spu; CD60[b] = f->samp;
    if (f->samp) {
        ST->self = 1;
        SPUW(spu, (u8 *)bank + (u32)(n + 1) * 20, f->samp);
        ST->self = 0;
    }
}

static void install(void)
{
    const u32 *src = (const u32 *)s8_bin;
    u32 *dst = (u32 *)S8_CODE, i, n = (u32)(s8_bin_end - s8_bin) >> 2;
    for (i = 0; i < n; i++) dst[i] = src[i];
    if (snd8_first || ST->magic != S8_MAGIC) {     /* first battle of this boot: fresh state */
        u8 *p = (u8 *)ST;
        for (i = 0; i < sizeof(struct s8st); i++) p[i] = 0;
        for (i = 0; i < NVOICE; i++) ST->vspu[i] = ~0u;
        ST->magic = S8_MAGIC;
    }
    flushcache();
}

static void hooks(void)
{
    u32 *w = (u32 *)0x8007ad08u;
    /* play: move a0,s1 / jal s8_play / move a1,s2 / sw v0,0x34(sp) / nop x5 (stock: CD48[bank] + off * 8) */
    if (w[0] == 0x92230011u && w[8] == 0xafa30034u) {
        w[0] = 0x02202021u;
        w[1] = 0x0c000000u | ((S8_PLAY >> 2) & 0x03ffffffu);
        w[2] = 0x02402821u;
        w[3] = 0xafa20034u;
        w[4] = w[5] = w[6] = w[7] = w[8] = 0;
    }
    w = (u32 *)0x8001bca8u;                     /* SpuWrite: j s8_wrstub / nop */
    if (w[0] == 0x27bdffe8u && w[1] == 0xafb00010u) {
        w[0] = 0x08000000u | ((S8_WRHOOK >> 2) & 0x03ffffffu);
        w[1] = 0;
    }
    w = (u32 *)0x80020c84u;                     /* main loop ResetRCnt(2) -> s8_tick(2) */
    if (w[0] == 0x0c0051fcu) w[0] = 0x0c000000u | ((S8_TICK >> 2) & 0x03ffffffu);
    flushcache();
    ST->installed++;
}

/* after the cache fill: p[s] = the slot's .SN8 in its cache slot (0: none).  0: streaming not used (snd.c plan) */
int snd8_begin(signed char *list, u8 *const p[4])
{
    const struct sn8 *com = (const struct sn8 *)tl8_snd.comat;
    u32 top, a, lo0;
    int s, t, fresh;
    used = 0;
    if (!snd8_on()) return 0;
    install();
    snd8_dbg[0] = snd8_dbg[1] = snd8_dbg[2] = snd8_dbg[3] = snd8_dbg[4] = snd8_dbg[5] = 0;
    ((void (*)(void))S8_FLUSH)();
    /* COMMON.SN8 in upper RAM (read once per boot; checked by its word sum) */
    if (ST->commsf != tl8_snd.com.msf || ST->comn != tl8_snd.com.size || wsum((u32 *)com, tl8_snd.com.size) != ST->comsum) {
        FTAB[SPARE * 2] = tl8_snd.com.msf; FTAB[SPARE * 2 + 1] = tl8_snd.com.size;
        RD(SPARE, (void *)com);
        ST->commsf = tl8_snd.com.msf; ST->comn = tl8_snd.com.size;
        ST->comsum = wsum((u32 *)com, tl8_snd.com.size);
        TAB[0x13] = 0;                          /* upload it again */
    }
    if (com->magic != 0x31384e53) { snd8_dbg[5] = 1; return 0; }
    for (s = 0; s < 4; s++) {
        sn[s] = list[s] < 0 ? 0 : (const struct sn8 *)p[s];
        if (sn[s] && sn[s]->magic != 0x31384e53) { snd8_dbg[5] = 2; return 0; }
    }
    /* SPU layout */
    top = SPU_TOP;
    for (s = 0; s < 4; s += 2)
        if (list[s] >= 0) { top -= r64((u32)snd_dir.c[fchar(list[s])].stash << 4); stash[s] = top; }
    a = SPU_CHARS;
    for (s = 0; s < 4; s++) if (sn[s]) { at[s] = a; a += r64(sn[s]->samp); }
    lo0 = r64(SPU_COMMON + com->samp);
    if (a > top || lo0 > SPU_CHARS) { snd8_dbg[5] = 3; return 0; }
    snd8_dbg[1] = 1;
    /* table partition (slots of banks 1-4, mains first; the rest goes to OVF) */
    {
        int n[5], rem = SLOTS14, b;
        static const u8 order[4] = { 1, 3, 2, 4 };
        for (s = 0; s < 4; s++) n[s + 1] = sn[s] ? (int)sn[s]->nent : 0;
        for (t = 0; t < 4; t++) {
            b = order[t];
            CD8C[b] = n[b] < rem ? n[b] : rem;
            rem -= CD8C[b];
        }
        CD8C[4] += rem;
    }
    /* COMMON (bank 0): ours, unless the table holds it already */
    fresh = !(TAB[0x13] == SN8_MARK && FB18[0] == (s16)com->nent && CD48[0] == SPU_COMMON);
    if (fresh) {
        UNLOAD(0);
        upload(0, com, SPU_COMMON);
        for (s = 0; s < (int)com->nent && s < CD8C[0]; s++) TAB[20 * s + 0x13] = SN8_MARK;
        snd8_dbg[2] = 1;
    }
    ST->vox[0] = (const struct s8vox *)((const u8 *)com + com->vox);
    for (s = 0; s < 4; s++) ST->vox[s + 1] = 0;
    /* pool regions: 0 kept when COMMON stayed (its cached voices too; character voices of the last battle dropped) */
    if (fresh || !ST->reg[0].on || ST->reg[0].lo != lo0) ((void (*)(int, u32, u32))S8_RESET)(0, lo0, SPU_CHARS);
    else {
        u32 k, vlo = (u32)ST->vox[0], vhi = vlo + com->voxlen;
        for (k = 0; k < ST->nseg; k++)
            if (ST->seg[k].reg == 0 && ST->seg[k].key && (ST->seg[k].key < vlo || ST->seg[k].key >= vhi)) ST->seg[k].key = 0;
    }
    ((void (*)(int, u32, u32))S8_RESET)(1, r64(a), top);
    used = 1;
    snd8_dbg[0] = 1;
    return 1;
}

/* the bank of list slot s (after snd8_begin) */
void snd8_load(int s)
{
    if (!used || !sn[s]) return;
    upload(s + 1, sn[s], at[s]);
    ST->vox[s + 1] = (const struct s8vox *)((const u8 *)sn[s] + sn[s]->vox);
}

/* after every bank: prefetch (mains, partners, COMMON in turns, shortest voices first), then the EXE hooks */
void snd8_end(void)
{
    static const u8 ord[5] = { 1, 3, 2, 4, 0 };
    u32 i, k, got = 0;
    if (!used) return;
    for (i = 0; i < 64; i++) {
        int more = 0;
        for (k = 0; k < 5; k++) {
            int b = ord[k];
            const struct s8vox *x = ST->vox[b];
            const struct sn8 *f = b ? sn[b - 1] : (const struct sn8 *)tl8_snd.comat;
            const u16 *pf;
            if (!x || !f || i >= f->npf) continue;
            more = 1;
            pf = (const u16 *)((const u8 *)f + f->pf);
            got += ((int (*)(const struct s8vox *, int))S8_FETCH)(x, pf[i]);
        }
        if (!more) break;
    }
    snd8_dbg[3] = got > 255 ? 255 : got;
    hooks();
}
