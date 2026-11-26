/* SUPERSEDED 2026-11-24 by the 1.0-line 8 MB module (mkap8.py, entry8.S, ap8m.c, s8/): kept for reference, not built. */
/* 8 MB battle loader of the MvC tag hack ("ap8"), linked into the same blob as the 2 MB loader (tools/tagload).
 *
 * The resident glue (tools/tagload/glue.S, unchanged) reads the blob into the tile decode arena each battle and calls
 * its entry with the stock loader's list; the ap8 build links the entry (entry8.S) to ap8_main instead of tl_main:
 *
 *   ap8_main(list) (ap8stub.c, in the blob): no 8 MB (probe, once per boot) -> tl_main(list): exactly the 2 MB path.
 *                    8 MB: this module (read to UP + 0x1000 once per boot / when its sum is off) -> ap8_mod(list);
 *                    a battle tl_main would decline -> tl_main(list).
 *                    8 MB: every listed character FULL from upper RAM with the STOCK sprite file (full-resolution
 *                    effects, stock RLE: no half-res / cut / DSH / DSA tiers), its kind-6 set kept in RAM (SPU
 *                    0x68000-0x75800 goes to the sound banks: tools/snd snd_spu_end), nothing in the 2 MB area.
 *
 * Upper RAM (0x80200000-0x80800000):
 *   UP + 0          cache header (magic, tick, NCS slot records)
 *   UP + 0x1000     this module (code + data, MODSZ)
 *   WORK + s * WA   per list slot s: part A (header + code (+ Onslaught block)), relocated, then the kind-6 set
 *   VC + s * VCSZ   mains: SPVC portrait (read every battle)
 *   CACHE + k * CS  cache slot k: [part A][part B: set + relocation table][stock PLxx_10.A0], pristine disc bytes.
 *                   The stock A0's sprite section is registered IN PLACE (the game only reads it).
 *   SCRTOP          sound level files are read below it (scratch); 0x807f0000: the game keeps sp in the 0x807xxxxx
 *                   mirror, so on 8 MB machines its stack is real RAM at 0x807ff800-0x80800000.
 * A cache slot is reused when its key (character, disc position + size of the three parts) matches and the word sum
 * of each part still matches the sum taken when it was read; else the part is read again.  The first battle of a boot
 * (byte BOOT == 0: the EXE image was just loaded) wipes the header: upper RAM survives a reset / core reload on some
 * machines (MiSTer) and may hold another build's data.
 *
 * State bytes (dead EXE word 0x800858ac, zeroed in the image by mktag.py): +2 PROBE 0 not yet / 1 no 8 MB / 2 8 MB
 * (tools/ap8/ap8menu.S probes at the first main-menu frame), +3 BOOT (module read / cache valid this boot).
 * Why a module: the blob is read into the tile decode arena with whole sectors; the 2 MB blob already ends ~1 KB below
 * game data that is set before the battle and never rewritten (0x8009b805.., work/cold/arena_cold.json): a bigger
 * blob corrupted it (freeze at a KO hand-over).  The stub adds ~0.3 KB and stays in the 2 MB blob's last sector.
 * tl_dbg: [0] 1 loaded, [1] [2] 0x99 (stock RLE everywhere, meter digit 9), [4..7] end of the used upper RAM.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#include "tl_struct.h"                          /* struct fent / chr / dir, NT, NF, NFR: copied from tagload.c by mkap8.py */

extern struct dir tl_dir;
extern u32 tl_strong[];
extern u8 tl_dbg[16];
extern u32 dshptr, dsaptr;
extern void flushcache(void);
extern int tl_main(signed char *list);
extern void snd_reset(void);
extern void snd_plan(signed char *list);
extern int snd_load(int s, int c, u32 top);
extern void snd_finish(void);
extern u32 snd_spu_end;                         /* tools/snd/snd.c: SPU end of the sound banks (2 MB: 0x68000) */

#define SLOT0        0x800c5000u
#define TOP0         0x801fe000u
#define TOP_ONSL     0x801f7200u
#define FTAB         ((u32 *)0x800255e4u)
#define SPARE        0x1ab
#define INITM        ((u32 *)0x8006a70cu)
#define SPU1         0x75800u                   /* SP_EFF2 (set 0xc) from here */
#define LOADER_FULL  (*(u8 *)0x800858acu)
#define PROBE        (*(volatile u8 *)0x800858aeu)
#define BOOT         (*(u8 *)0x800858afu)
#define ASSIST_BITS  (*(u8 *)0x8007b744u)
#define MODE         (*(signed char *)0x8007b740u)
#define HUMANS       (*(u8 *)0x8007bdc9u)
#define MMVAR        (*(u8 *)0x8007b8e3u)
#define TEAM         ((s16 *)0x8007b8aau)
#define RAM_SIZE     (*(volatile u32 *)0x1f801060)

typedef int  (*rd_t)(int idx, void *dst);
typedef void (*snd_t)(int bank, void *src, int size, int chr);
typedef void (*reg_t)(int set, void *dsp, int mode);
typedef void (*init_t)(u32 *ent, u32 base0);
typedef int  (*rand_t)(void);
typedef void (*d04_t)(int set, int mode, void *pix, void *s1, void *s2, void *s3, int kind);
#define RD    ((rd_t)0x80024800)
#define SND   ((snd_t)0x800870e0)
#define REG   ((reg_t)0x80091e74)
#define RAND  ((rand_t)0x8003bc88)
#define D04   ((d04_t)0x80091d04)

/* ---- upper RAM layout; the cache slot geometry comes from tl8_dir (mkap8.py sizes it for the files on the disc) ---- */
#define UP        0x80200000u
#define MODSZ     0x3000u                       /* this module (ap8stub.c reads it to UP + 0x1000) */
#define WORK      (UP + 0x1000u + MODSZ)
#define NCSMAX    16
#define MAGIC     0x4143564du                   /* 'MVCA' */
struct geo8 {
    u32 magic;                                  /* 'AP8G' */
    u32 wa, vcsz;                               /* work area per slot, SPVC area per main */
    u32 cs, c_b, c_s, ncs;                      /* cache slot size, part offsets in a slot, slot count */
    u32 scrtop;                                 /* sound scratch top */
};
struct geo8 tl8_dir __attribute__((section(".geo8"))) = { 0x47385041, 0x24000, 0x4000, 0xb8000, 0x24000, 0x30000, 7, 0x807f0000 };
#define WA     (tl8_dir.wa)
#define VC     (WORK + 4 * WA)
#define CACHE  (VC + 2 * tl8_dir.vcsz)
#define CS     (tl8_dir.cs)
#define NCS    ((int)tl8_dir.ncs)
#define UPEND  (CACHE + NCS * CS)

struct cslot {
    u32 c;                                      /* char id + 1 (0 = empty) */
    u32 amsf, an, bmsf, bn, smsf, sn;           /* key: disc positions + sizes of part A, part B, stock A0 */
    u32 asum, bsum, ssum;
    u32 used;                                   /* tick of the last battle that used it */
};
struct chdr {
    u32 magic, tick;
    u32 hits, reads;                            /* parts reused / read in the last battle (tests) */
    struct cslot s[NCSMAX];
};
#define H ((struct chdr *)UP)

static u32 a8(u32 x) { return (x + 7) & ~7u; }

/* stock file indices (as tagload.c) */
static int main_se(int c, int s)
{
    int k = 3 * (c - 1) + 66 * s + 10;
    if (c <= 0x10) { if (s) k += 5; }
    else k += 5 * (s + 1);
    return k;
}
static int main_vc(int c, int s) { return main_se(c, s) + (c == 0x10 ? 7 : 2); }
static int stock_a0(int c) { return main_vc(c, 0) - 1; }                 /* PLxx_10.A0 */
static int part_chr(int c, int s)
{
    if (c == 9) {
        signed char st = *(signed char *)(0x8007b8e4u + s);
        if (st == 2) return 0x17;
        if (st == 4) return 0x18;
    }
    return c;
}
static int part_a0(int c, int s) { return (part_chr(c, s) - 1) * 2 + (s - 2) * 48 + 0x98; }

static u32 place(u32 cur, const struct chr *h)
{
    u32 p = a8(cur + h->hdr);
    int k, moved;
    do {
        moved = 0;
        for (k = 0; k < NF; k++) {
            u32 lo = h->forb[2 * k], hi = h->forb[2 * k + 1];
            u32 r = (p - SLOT0) & 0xffff;
            if (lo != hi && r >= lo && r < hi) { p += a8(hi - r); moved = 1; }
        }
    } while (moved);
    return p;
}

static void reloc(u32 *W, const u16 *T, int d)
{
    u32 i;
    while ((i = *T++) != 0xffff) W[i] += d;
    while ((i = *T++) != 0xffff) W[i] = (W[i] & 0xfc000000u) | ((W[i] + (d >> 2)) & 0x03ffffffu);
    while ((i = *T++) != 0xffff) W[i] = (W[i] & 0xffff0000u) | ((W[i] + d) & 0xffff);
    while ((i = *T++) != 0xffff) {
        s16 lo = (s16)*T++;
        u32 t = (W[i] << 16) + lo + d;
        W[i] = (W[i] & 0xffff0000u) | (((t + 0x8000u) >> 16) & 0xffff);
    }
}

static u32 wsum(const u32 *p, u32 n)
{
    u32 s = 0x5a17u;
    n = (n + 3) >> 2;
    while (n--) s += *p++;
    return s;
}

static void wcopy(u32 *d, const u32 *s, u32 n)
{
    n = (n + 3) >> 2;
    while (n--) *d++ = *s++;
}

static int rd_ent(u32 msf, u32 size, void *dst)
{
    FTAB[SPARE * 2] = msf;
    FTAB[SPARE * 2 + 1] = size;
    return RD(SPARE, dst);
}

static u8 *slotp(int k) { return (u8 *)(CACHE + k * CS); }

/* make cache slot of char c hold part A, part B and the stock A0; returns the slot */
static int fill(int c, u32 busy)
{
    const struct chr *h = &tl_dir.c[c];
    int si = stock_a0(c);
    u32 smsf = FTAB[si * 2], sn = FTAB[si * 2 + 1];
    struct cslot *e = 0;
    int k, best = -1, need = 0;
    u8 *P;
    for (k = 0; k < NCS; k++) {
        e = &H->s[k];
        if (e->c == (u32)c + 1 && e->amsf == h->a0.msf && e->an == h->a0.size && e->bmsf == h->st.msf &&
            e->bn == h->st.size && e->smsf == smsf && e->sn == sn) break;
    }
    if (k == NCS) {                     /* not cached: an empty slot, else the least recently used one not in this battle */
        for (k = 0; k < NCS; k++) {
            if (busy & (1u << k)) continue;
            if (!H->s[k].c) { best = k; break; }
            if (best < 0 || H->s[k].used < H->s[best].used) best = k;
        }
        k = best;
        e = &H->s[k];
        e->c = c + 1;
        e->amsf = h->a0.msf; e->an = h->a0.size; e->bmsf = h->st.msf; e->bn = h->st.size; e->smsf = smsf; e->sn = sn;
        need = 7;
    } else {
        P = slotp(k);
        if (wsum((u32 *)P, e->an) != e->asum) need |= 1;
        if (wsum((u32 *)(P + tl8_dir.c_b), e->bn) != e->bsum) need |= 2;
        if (wsum((u32 *)(P + tl8_dir.c_s), e->sn) != e->ssum) need |= 4;
        H->hits += 3 - (need & 1) - ((need >> 1) & 1) - (need >> 2);
    }
    P = slotp(k);
    if (need & 1) { rd_ent(e->amsf, e->an, P); e->asum = wsum((u32 *)P, e->an); H->reads++; }
    if (need & 2) { rd_ent(e->bmsf, e->bn, P + tl8_dir.c_b); e->bsum = wsum((u32 *)(P + tl8_dir.c_b), e->bn); H->reads++; }
    if (need & 4) { RD(si, P + tl8_dir.c_s); e->ssum = wsum((u32 *)(P + tl8_dir.c_s), e->sn); H->reads++; }
    e->used = H->tick;
    return k;
}

static void mmvariant(int s)
{
    static const u16 team_of[4] = { 2, 6, 0, 4 };
    int v;
    do v = RAND() & 7; while (v >= 6);
    if (v == 5 && *(s16 *)(0x8007b8aau + team_of[s]) == 0x10) v = 0;
    MMVAR = (u8)v;
}

static int load8(signed char *list)
{
    int s, k, slot[4];
    u32 busy = 0, top, strong;
    u32 old_msf = FTAB[SPARE * 2], old_size = FTAB[SPARE * 2 + 1];
    if (!BOOT || H->magic != MAGIC || NCS > NCSMAX) {   /* first battle of this boot, or no header: empty cache */
        for (k = 0; k < NCSMAX; k++) H->s[k].c = 0;
        H->tick = 0;
        H->magic = MAGIC;
        BOOT = 1;
    }
    H->tick++;
    H->hits = H->reads = 0;
    /* ARCADE: a CPU partner equal to its main (stock) gets a distinct partner (tools/gameplay/selscreen.py vsinit
     * normally did that before the VS screen) */
    if (MODE == 0 && list[3] < 0 && list[1] != 0x11 && TEAM[3] == TEAM[2]) {
        int c, n = 0;
        do { c = (RAND() & 15) + 1; n++; }
        while (n < 64 && (c == list[0] || c == TEAM[2] / 2 || c == list[2] || !tl_dir.c[c].a0.size));
        if (n < 64) { list[3] = (signed char)c; TEAM[3] = (s16)(c * 2); }
    }
    for (s = 0; s < 4; s++) {
        if (list[s] < 0) continue;
        slot[s] = fill(list[s], busy);
        busy |= 1u << slot[s];
    }
    snd_spu_end = SPU1;                                 /* kind-6 sets stay in RAM: their SPU area goes to the banks */
    snd_plan(list);
    for (s = 0; s < 4; s++) {
        const struct chr *h;
        u8 *F, *C, *A, *dsp;
        u32 p, *ah;
        int c = list[s], n;
        if (c < 0) continue;
        h = &tl_dir.c[c];
        C = slotp(slot[s]);
        /* sound (tools/snd: the full bank of every character), else the stock bank */
        if (s < 2 && c == 0x10) mmvariant(s);
        if (!snd_load(s, c, tl8_dir.scrtop)) {
            u8 *T = (u8 *)(tl8_dir.scrtop - 0x40000u);
            if (s < 2) {
                int idx = main_se(c, s);
                if (c == 0x10) idx += MMVAR;
                n = RD(idx, T);
                SND(s + 1, T, n, c);
            } else {
                RD(part_a0(c, s), T);
                ah = (u32 *)T;
                SND(s + 1, T + ah[5], ah[6], part_chr(c, s));
            }
        }
        /* code: part A to the work area, relocated, init */
        p = place(WORK + s * WA, h);
        F = (u8 *)(p - h->hdr);
        wcopy((u32 *)F, (u32 *)C, h->a0.size);
        reloc((u32 *)F, (const u16 *)(C + tl8_dir.c_b + h->a0size), (int)(p - SLOT0));
        flushcache();
        ((init_t)(INITM[c] + (p - SLOT0)))(&INITM[c], SLOT0);
        if (h->xoff) *(u32 *)0x80078a4cu = (u32)F + h->xoff;     /* Onslaught: giant-form block */
        /* kind-6 set: stays in RAM behind the code (no SPU stash) */
        wcopy((u32 *)(F + h->setoff), (u32 *)(C + tl8_dir.c_b), h->setsize);
        REG(s + 4, F + h->setoff, 0);
        /* SPVC portrait (mains) */
        if (s < 2 && (tl_dir.flags & 1)) {
            u8 *V = (u8 *)(VC + s * tl8_dir.vcsz);
            RD(main_vc(c, s), V);
            REG(0xe + s, V, 0);
        }
        /* sprites: the stock file, in place in the cache (section 1 of PLxx_10.A0) */
        A = C + tl8_dir.c_s;
        ah = (u32 *)A;
        dsp = A + ah[3];
        {
            u32 *dh = (u32 *)dsp;
            D04(s, 0, dsp + 0x14, dsp + dh[2], dsp + dh[3], dsp + dh[4], 8);
        }
    }
    FTAB[SPARE * 2] = old_msf; FTAB[SPARE * 2 + 1] = old_size;
    /* the payload after the last read (as tl_main: meter; the decoders are never used with stock RLE files) */
    top = list[1] == 0x11 ? TOP_ONSL : TOP0;
    strong = top == TOP0 ? tl_dir.strong_at : TOP_ONSL - ((tl_dir.dec_size + 7) & ~7u);
    if (tl_dir.strong_size) {
        u32 *d = (u32 *)strong, n = (top == TOP0 ? tl_dir.strong_size : tl_dir.dec_size) >> 2;
        for (k = 0; k < (int)n; k++) d[k] = tl_strong[k];
        dshptr = strong;
        dsaptr = tl_dir.dsa_off ? strong + tl_dir.dsa_off : 0;
        if (top != TOP0) tl_strong[(0x801fdc00u - 0x801fd400u) >> 2] = 0;
        flushcache();
    }
    ASSIST_BITS &= ~3;
    snd_finish();
    LOADER_FULL = 3;
    *(u32 *)(tl_dbg + 4) = UPEND;
    tl_dbg[1] = tl_dbg[2] = 0x99;
    for (s = 0; s < 4; s++) if (list[s] < 0) tl_dbg[1 + (s & 1)] = (u8)((tl_dbg[1 + (s & 1)] & ~(0xf << (4 * (s >> 1)))) | 10 << (4 * (s >> 1)));
    tl_dbg[0] = 1;
    return 1;
}

/* module entry (ap8stub.c, 8 MB machines only): the same battles as the 2 MB loader, else tl_main declines them */
int ap8_mod(signed char *list)
{
    int s;
    if (tl_dir.magic != 0x4c474154 || MODE < 0 || MODE == 2 || MODE > 3 || !HUMANS || (tl_dir.flags & 6))
        return tl_main(list);
    for (s = 0; s < 4; s++) {
        int c = list[s];
        if (c < 0) continue;
        if (c < 1 || c > 0x16 || (c == 0x11 && s != 1) || !tl_dir.c[c].a0.size) return tl_main(list);
    }
    tl_dbg[0] = tl_dbg[1] = tl_dbg[2] = tl_dbg[3] = 0;
    *(u32 *)(tl_dbg + 12) = 0;
    snd_reset();
    LOADER_FULL = 0;
    return load8(list);
}
