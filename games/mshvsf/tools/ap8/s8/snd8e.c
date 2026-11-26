/* 8 MB battle sound with voice streaming (MSHvSF tag hack 8 MB build; files: tools/snd/sn8build.py).  Part of the
 * resident engine binary (s8/s8.c, linked at S8_CODE, read from the disc into upper RAM by tools/ap8/ap8.c): nothing of
 * it is in the loader blob, which must stay small (a bigger blob stalled the fight at READY).  The 2 MB loader and
 * tools/snd/snd.c are unchanged.
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
#include "s8.h"

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

struct sn8 { u32 magic, nent, bank, banklen, samp, vox, voxlen, npf, pf; };
#define snd8_dbg (ST->ldbg)                /* [0] used this battle, [1] fits, [2] COMMON uploaded, [3] prefetched, [4] overflow, [5] exit */
#define SN(s) ((const struct sn8 *)ST->sn[s])

static u32 r64(u32 x) { return (x + 63) & ~63u; }

static u32 wsum(const u32 *p, u32 n)
{
    u32 s = 0x5a17u;
    n = (n + 3) >> 2;
    while (n--) s += *p++;
    return s;
}

u32 s8_stash(int s) { return ST->stash[s]; }

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
        d[0x11] = b; d[0x12] |= 1 << b; d[0x13] = SN8_MARK;     /* ours (s8_play streams marked entries only) */
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

static void fresh_state(int first)
{
    u32 i;
    if (first || ST->magic != S8_MAGIC) {     /* first battle of this boot: fresh state */
        u8 *p = (u8 *)ST;
        for (i = 0; i < sizeof(struct s8st); i++) p[i] = 0;
        for (i = 0; i < NVOICE; i++) ST->vspu[i] = ~0u;
        ST->magic = S8_MAGIC;
    }
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
    ST->installed++;                          /* the caller (ap8.c) flushes the I-cache */
}

/* after the cache fill: p[s] = the slot's .SN8 in its cache record (0: none); d = ap8.c's directory (comat, COMMON's
 * disc entry); stash[s] = kind-6 stash bytes of the mains.  0: streaming not used (snd.c plan) */
int s8_begin(signed char *list, u8 *const *p, const struct s8dir *d, const u32 *stash, int first)
{
    const struct sn8 *com = (const struct sn8 *)d->comat;
    u32 top, a, lo0;
    int s, t, fresh;
    fresh_state(first);
    ST->used = 0;
    snd8_dbg[0] = snd8_dbg[1] = snd8_dbg[2] = snd8_dbg[3] = snd8_dbg[4] = snd8_dbg[5] = 0;
    ST->comat = d->comat;
    s8_flush();
    /* COMMON.SN8 in upper RAM (read once per boot; checked by its word sum) */
    if (ST->commsf != d->com.msf || ST->comn != d->com.size || wsum((u32 *)com, d->com.size) != ST->comsum) {
        FTAB[SPARE * 2] = d->com.msf; FTAB[SPARE * 2 + 1] = d->com.size;
        RD(SPARE, (void *)com);
        ST->commsf = d->com.msf; ST->comn = d->com.size;
        ST->comsum = wsum((u32 *)com, d->com.size);
        TAB[0x13] = 0;                          /* upload it again */
    }
    if (com->magic != 0x31384e53) { snd8_dbg[5] = 1; return 0; }
    for (s = 0; s < 4; s++) {
        ST->sn[s] = list[s] < 0 ? 0 : (const void *)p[s];
        if (SN(s) && SN(s)->magic != 0x31384e53) { snd8_dbg[5] = 2; return 0; }
    }
    /* SPU layout */
    top = SPU_TOP;
    for (s = 0; s < 4; s += 2)
        if (list[s] >= 0) { top -= r64(stash[s]); ST->stash[s] = top; }
    a = SPU_CHARS;
    for (s = 0; s < 4; s++) if (SN(s)) { ST->at[s] = a; a += r64(SN(s)->samp); }
    lo0 = r64(SPU_COMMON + com->samp) + 64;     /* 64 B below region 0: the one-shot silent block (ST->silent) */
    if (a > top || lo0 > SPU_CHARS) { snd8_dbg[5] = 3; return 0; }
    snd8_dbg[1] = 1;
    /* table partition (slots of banks 1-4, mains first; the rest goes to OVF) */
    {
        int n[5], rem = SLOTS14, b;
        static const u8 order[4] = { 1, 3, 2, 4 };
        for (s = 0; s < 4; s++) n[s + 1] = SN(s) ? (int)SN(s)->nent : 0;
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
    if (fresh || !ST->reg[0].on || ST->reg[0].lo != lo0) {
        static const u8 blk[64] = { 0, 1 };     /* block 0: end flag, no repeat; then zeros */
        s8_region(0, lo0, SPU_CHARS);
        ST->self = 1;
        SPUW(lo0 - 64, (void *)blk, 64);
        ST->self = 0;
        ST->silent = lo0 - 64;
    }
    else {
        u32 k, vlo = (u32)ST->vox[0], vhi = vlo + com->voxlen;
        for (k = 0; k < ST->nseg; k++)
            if (ST->seg[k].reg == 0 && ST->seg[k].key && (ST->seg[k].key < vlo || ST->seg[k].key >= vhi)) ST->seg[k].key = 0;
    }
    s8_region(1, r64(a), top);
    ST->used = 1;
    snd8_dbg[0] = 1;
    return 1;
}

/* the bank of list slot s (after snd8_begin) */
void s8_load(int s)
{
    if (!ST->used || !SN(s)) return;
    upload(s + 1, SN(s), ST->at[s]);
    ST->vox[s + 1] = (const struct s8vox *)((const u8 *)SN(s) + SN(s)->vox);
}

/* after every bank: prefetch (mains, partners, COMMON in turns, shortest voices first), then the EXE hooks */
void s8_end(void)
{
    static const u8 ord[5] = { 1, 3, 2, 4, 0 };
    u32 i, k, got = 0;
    if (!ST->used) return;
    for (i = 0; i < 64; i++) {
        int more = 0;
        for (k = 0; k < 5; k++) {
            int b = ord[k];
            const struct s8vox *x = ST->vox[b];
            const struct sn8 *f = b ? SN(b - 1) : (const struct sn8 *)ST->comat;
            const u16 *pf;
            if (!x || !f || i >= f->npf) continue;
            more = 1;
            pf = (const u16 *)((const u8 *)f + f->pf);
            got += s8_fetch(x, pf[i]);
        }
        if (!more) break;
    }
    snd8_dbg[3] = got > 255 ? 255 : got;
    hooks();
}
