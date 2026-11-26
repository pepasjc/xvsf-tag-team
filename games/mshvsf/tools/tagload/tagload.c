/* Four-full-character battle loader for Marvel Super Heroes vs. Street Fighter (USA, SLUS-00793).
 *
 * Runs from the sprite decode arena (0x80087e10), which is idle for the whole battle load (measured:
 * games/mshvsf/work/loader/arena_idle.py).  The resident glue (glue.S) reads this blob there each
 * battle, checks it, flushes the I-cache and calls tl_main(list) in place of the slot loop of the
 * stock battle loader (0x8002af50..0x8002afdc).
 *
 * list = the four deduplicated entries of the stock loader (P1 main, P1 partner, P2 main, P2 partner):
 * >= 0 char id to load, < 0 shares the data of slot ~entry (done by the stock code after the loop).
 *
 * Every listed character is loaded FULL, packed upwards from 0x800bbfe4, in slot order:
 *     [A0 file: header + code/data (relocated at load) + kind-6 set] [sprite file]
 * The A0 file on the disc is PLxx_10.A0 followed by its relocation table (tools/reloc.py).  The sprite
 * file is the stock RLE one (fast tier) or the DSM1 one (common/dsp, ~57% of the size).
 * Mains keep the stock kind-6 handling (pixels stashed in SPU, at the address tools/snd/snd.c chose); full
 * partners keep their kind-6 set in RAM like the stock cut-down partner.  Every character, partners included,
 * gets its own character sound bank (tools/snd/snd.c: SPU layout, level, upload).
 *
 * Region: from the end of the GPU primitive pool to 0x801fea00 - 2048.  The pool normally takes all
 * the space between the stage data and 0x800bbfd8 (16-54 KB by stage); heapcap (glue.S, hook in
 * 0x8002a9b4) caps it at 16 KB, the smallest stock pool (stage 8), and leaves its end in tl_dbg+8.
 *
 * Sprite tiers: 0 strong (DSH1), 1 DSM1, 2 stock RLE.  Policy: everybody DSM1; while it does not fit,
 * characters go strong in the order P2 partner, P1 partner, P2 main, P1 main; if it still does not
 * fit, return 0 = stock loop (cut-down partners, stock rules).  Then each DSM1 character in the order
 * P1 main, P2 main, P1 partner, P2 partner goes to the stock RLE file if the total still fits.
 * After the last CD read the strong decoder is copied to STRONG_AT (the sector-spill zone).
 *
 * Arcade / versus / training with a human only (else stock, tl_dbg 0xf9).
 *
 * Returns 1 when it loaded everything (the reduced-partner mask stays 0 -> tagmode.py switches the
 * fight to the arcade tag rules).
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define REGION_START 0x800bbfe4u            /* stock: pool ends 0x800bbfd8 */
#define STRONG_AT    0x801fe200u
#ifndef REGION_SHRINK
#define REGION_SHRINK 0                         /* test builds only (mktag --testshrink=N): pretend N bytes less room */
#endif
#ifndef PSTALL
#define PSTALL 0                                /* (mshvsf 1.1, mshspeed) mktag --pstall: partners' kind-6 sets in SPU in every
                                                   battle (the pst floor as the start): ~16-18 KB more sprite RAM, effect
                                                   sound one or more sample-rate levels lower (tools/snd/sndfit.py) */
#endif
#ifdef L2G
/* (mshvsf 1.1, mshspeed) mktag --l2g: the g2get image + RAM block (games/mshvsf/tools/l2) live at G2AT, right below
 * the strong decoder: the region ends there.  The packed sec1 of the tier files makes the characters smaller. */
#define REGION_END   (G2AT - REGION_SHRINK)
u32 tl_l2img[L2WORDS] = { 1 };              /* the image (filled by mktag.py), copied to G2AT after the last read */
#else
#define REGION_END   (0x801fea00u - 2048u - REGION_SHRINK)      /* CD reads write whole sectors: keep one sector of spill */
#endif
#define SLOT0_BASE   0x800bc000u
#define FTAB         ((u32 *)0x800247dcu)       /* game file table: 8-byte entries (BCD MSF, size) */
#define SPARE        0x10f                      /* unused file-table entry: our reads */
#define INIT_TAB     ((u32 *)0x800650e4u)       /* char init entry (linked for slot 0) */
#define SPU_STASH    ((u32 *)0x800650d4u)       /* kind-6 pixel stash in SPU per slot */

typedef int  (*rd_t)(int idx, void *dst);
typedef void (*snd_t)(int bank, void *src, int size);
typedef int  (*stash_t)(int set, void *src, int kind, int size, u32 spu);
typedef void (*reg_t)(int slot, void *dsp, int zero);
typedef void (*init_t)(int delta, u32 base0);
#define RD    ((rd_t)0x80024554)
#define SND   ((snd_t)0x8007ae24)
#define STASH ((stash_t)0x8008006c)
#define REG   ((reg_t)0x8007fddc)

extern void flushcache(void);
extern u8 tl_dbg[16];
/* full sound banks for every character (tools/snd/snd.c) */
extern void snd_reset(void);
extern void snd_plan(signed char *list);
extern u32 snd_stash(int s, u32 dflt);
extern u8 snd_pst;                          /* partners' kind-6 sets stashed in SPU too (snd_plan reserves them) */
extern int snd_load(int s, int c, u8 *sec3, u8 *scratch);

/* directory, filled by the disc builder (tools/tagload/mkdisc.py).  Indexed by FILE character
 * (variants 0x17-0x19 use the files of 02 / 08 / 07). */
struct fent { u32 msf, size; };
#define NT 11               /* sprite tiers, smallest first: 0 DSH1 with cut tiles (last resort, tools/tagload/cuttier.py),
                               1 DSH1 (strong), 2-5 DSH1 + hottest 4/8/16/32 KB of tiles kept RLE, 6 DSM1, 7-9 DSM1 +
                               hottest 16/32/64 KB kept RLE, 10 the stock RLE file (idx char + 4) */
#define DSMT 6              /* plain DSM1 (present for every character) */
#define DSHT 1              /* plain DSH1 */
struct chr {
    struct fent a0;         /* PLxx_10.A0 + relocation table */
    u32 a0size;             /* bytes of the A0 part (table follows, 4-aligned) */
    u32 codefp[2];          /* DSP offset from the file start, rounded like the stock loader: [0] main
                               (kind-6 pixels stashed in SPU), [1] partner (whole kind-6 set in RAM) */
    u16 forb_lo, forb_hi;   /* forbidden (P - 0x800bc000) & 0xffff residues [lo, hi), lo == hi: none */
    struct fent t[NT - 1];  /* sprite files of tiers 0..NT-2 (size 0: tier missing) */
    u16 cost[NT + (NT & 1)];  /* expected decode cost per tier (+ a pad entry when NT is odd: 4-byte record size) (tools/tagload/tiercost.py: play volume x codec cycles) */
};
_Static_assert(sizeof(struct chr) == 24 + 8 * (NT - 1) + 2 * (NT + (NT & 1)), "struct chr != mktag.py record");
struct dir {
    u32 magic;
    u32 strong_size;        /* bytes of the strong decoder at tl_strong */
    struct chr c[0x17];
};
extern u32 tl_strong[];
struct dir tl_dir __attribute__((section(".dir"))) = { 0x4c474154, 0 };    /* 'TAGL' */

static int filechar(int c)
{
    if (c == 0x17) return 2;
    if (c == 0x18) return 8;
    if (c == 0x19) return 7;
    return c;
}

static u32 stock_size(int idx) { return FTAB[idx * 2 + 1]; }

static u32 a8(u32 x) { return (x + 7) & ~7u; }

#ifdef L2G
/* (mshvsf 1.1, mshspeed) the after-match quote / continue overlay writes GPU primitives at 0x801f5000-0x801f5300
 * while the characters are still drawn (regress gameover2): a packed sec1's head (header, tables, anchors) must not
 * lie there, or every group of that character is lost.  sec1 offset per character and tier: tl_l2o1 (mktag). */
#define L2HL 0x801f4f00u
#define L2HH 0x801f5300u
#define L2PROT 1024u
u32 tl_l2o1[0x17 * NT] = { 1 };
#endif
static u32 place(u32 cur, const struct chr *h)
{
    u32 p = a8(cur + 0x1c);                     /* P = data base (8-aligned), file at P - 0x1c */
    if (h->forb_lo != h->forb_hi) {
        u32 r = (p - SLOT0_BASE) & 0xffff;
        if (r >= h->forb_lo && r < h->forb_hi) p += a8(h->forb_hi - r);
    }
    return p;
}

static void spare(const struct fent *f)
{
    FTAB[SPARE * 2] = f->msf;
    FTAB[SPARE * 2 + 1] = f->size;
}

static void mmove_down(u8 *d, const u8 *s, u32 n)  /* d < s, word-aligned */
{
    u32 *D = (u32 *)d; const u32 *S = (const u32 *)s;
    n = (n + 3) >> 2;
    while (n--) *D++ = *S++;
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


static u32 dspsize(int c, const struct chr *h, int t)
{
    return t == NT - 1 ? stock_size(c + 4) : h->t[t].size;
}

#define KANJI_IDX 0x65                          /* file KANJI.TEX: char 0's texture data, read behind its sprites */
#define KANJI ((void (*)(void *))0x8002a244)  /* the stock reader: RD(0x65, a), *0x80070530 = a */
static u32 kanji_at(u32 dsp_end) { return ((dsp_end >> 3) + 1) << 3; }   /* the stock rounding (+8 when aligned) */
static int pst;     /* 1: the partners' kind-6 sets go to SPU like the mains' (only when nothing else fits) */
#ifdef L2G
static u32 placet(u32 cur, const struct chr *h, int s, int c, int t)
{
    int k;
    u32 p = place(cur, h), o, a;
    for (k = 0; k < 4; k++) {
        o = t < NT - 1 ? tl_l2o1[filechar(c) * NT + t] : 0;
        if (!o) break;
        a = p - 0x1c + h->codefp[(s & 1) && !pst] + o;
        if (a >= L2HH || a + L2PROT <= L2HL) break;
        cur += a8(L2HH - a);                    /* move the character up until its sec1 head is past the overlay */
        p = place(cur, h);
    }
    return p;
}
#else
#define placet(cur, h, s, c, t) place(cur, h)
#endif

static u32 total(signed char *list, int *tier, u32 start)
{
    int s;
    u32 cur = start;
    for (s = 0; s < 4; s++) {
        const struct chr *h;
        int c = list[s];
        if (c < 0) continue;
        h = &tl_dir.c[filechar(c)];
        cur = placet(cur, h, s, c, tier[s]) - 0x1c + h->codefp[(s & 1) && !pst] + dspsize(c, h, tier[s]);
        if (c == 0) cur = kanji_at(cur) + stock_size(KANJI_IDX);   /* Apocalypse: KANJI.TEX behind his sprites */
    }
    return cur;
}

int tl_main(signed char *list)
{
    int s, k, tier[4];
    u32 cur, p, start;

    tl_dbg[0] = 0; tl_dbg[1] = 0; tl_dbg[2] = 0;
#ifdef L2G
    *(volatile u32 *)G2AT = 0;                  /* every battle load: the EXE gate sees no image until it is copied */
#endif
    snd_reset();                                                /* every battle, also when declining: stock tables */
    if (tl_dir.magic != 0x4c474154) { tl_dbg[0] = 0xfd; return 0; }
    /* only where tools/gameplay/tagmode.py switches the tag rules on: BATTLE (arcade, 0), VERSUS (1) and TRAINING
     * (2; the dummy picks a partner too, tools/gameplay/training.py) with a human player.  Elsewhere (hero battle,
     * attract demo) partners are assist-only, and the assist code exists only in the cut-down partner files: stock
     * loading.  (CROSS OVER loads full partners itself.) */
    if (*(signed char *)0x800250ac < 0 || *(signed char *)0x800250ac > 2 || !*(u8 *)0x80070a91) { tl_dbg[0] = 0xf9; return 0; }
    for (s = 0; s < 4; s++) {
        tier[s] = 0;
        if (list[s] < 0) continue;
        if (list[s] > 0x19) { tl_dbg[0] = 0xfc; return 0; }                    /* no such id */
    }
    /* entries < 0 share the data of another slot (the stock dedup: mirror characters and the solo characters'
     * dummy partner, e.g. Cyber-Akuma's team word 0x26 in both slots of a side): nothing to load, tier nibble 15
     * (the meter shows it blank) */
    for (s = 0; s < 4; s++)
        if (list[s] < 0) tl_dbg[1 + (s >> 1)] |= 15 << (4 * (s & 1));
    start = *(u32 *)(tl_dbg + 8);
    if (start < 0x80094800u || start > REGION_START) start = REGION_START;
    /* plan: everybody DSM1, or if that does not fit everybody on the smallest tier (else stock).  Then, while anything fits, the upgrade (any
     * slot, any higher tier) with the largest saving of expected decode cost per extra byte; mains weigh 3,
     * partners 2 (tag battles: both play, team supers draw both). */
    /* floors, each only when the previous one does not fit: everybody DSM1; everybody DSH1; + the partners' kind-6
     * sets in SPU (like the mains'; the sound level drops to make room); everybody on the cut tier (the greedy step
     * below upgrades cut characters back to DSH1 first, so only as many as needed stay cut).  tools/tagload/fitall.py
     * proves the last floor fits every team on every stage. */
    pst = PSTALL;
    for (s = 0; s < 4; s++) tier[s] = DSMT;
    if (total(list, tier, start) > REGION_END)
        for (s = 0; s < 4; s++) tier[s] = DSHT;
    if (total(list, tier, start) > REGION_END) pst = 1;
    if (total(list, tier, start) > REGION_END)
        for (s = 0; s < 4; s++) tier[s] = 0;
    snd_pst = pst;
    if (total(list, tier, start) > REGION_END) { tl_dbg[0] = 0xfe; return 0; }   /* never (fitall.py) */
    for (;;) {
        int bs = -1, bt = 0;
        u32 bg = 0, bd = 1;
        for (s = 0; s < 4; s++) {
            const struct chr *h;
            int t, old = tier[s];
            if (list[s] < 0) continue;
            h = &tl_dir.c[filechar(list[s])];
            for (t = old + 1; t < NT; t++) {
                u32 g, d, a, b;
                if (t < NT - 1 && !h->t[t].size) continue;
                if (h->cost[t] >= h->cost[old]) continue;
                g = (u32)(h->cost[old] - h->cost[t]) * ((s & 1) ? 2 : 3);
                a = dspsize(list[s], h, t); b = dspsize(list[s], h, old);
                d = a > b ? ((a - b) >> 8) + 1 : 1;
                if (g * bd <= bg * d) continue;
                tier[s] = t;
                if (total(list, tier, start) <= REGION_END) { bs = s; bt = t; bg = g; bd = d; }
                tier[s] = old;
            }
        }
        if (bs < 0) break;
        tier[bs] = bt;
    }
    snd_plan(list);
    /* load, in slot order */
    cur = start;
    for (s = 0; s < 4; s++) {
        const struct chr *h;
        u8 *F, *T;
        u32 *hdr, need, dsz;
        int c = list[s];
        if (c < 0) continue;
        h = &tl_dir.c[filechar(c)];
        p = placet(cur, h, s, c, tier[s]);
        F = (u8 *)(p - 0x1c);
        need = a8(h->a0.size) + 2048;
        T = F;
        if ((u32)F + need > REGION_END + 2048)                 /* no room for the whole file here: read it */
            T = (u8 *)((REGION_END + 2048 - need) & ~7u);      /*  higher up, keep sound, move code down   */
        spare(&h->a0);
        RD(SPARE, T);
        hdr = (u32 *)T;                                         /* u32 3, (off, size) x 3 */
        if (T != F)                                             /* header + sec1 + sec2 (sec2 ends the moved part) */
            mmove_down(F, T, hdr[3] + hdr[4]);
        reloc((u32 *)F, (const u16 *)(T + ((h->a0size + 3) & ~3u)), (int)(p - SLOT0_BASE));
        flushcache();
        ((init_t)(INIT_TAB[c] + (p - SLOT0_BASE)))((int)(p - SLOT0_BASE), SLOT0_BASE);
        hdr = (u32 *)F;
        if ((s & 1) && !pst)
            REG(s + 8, F + hdr[3], 0);
        else
            STASH(s + 8, F + hdr[3], 4, hdr[4], snd_stash(s, SPU_STASH[s]));
        /* sec3 = sound bank, still intact at T; a level file (smaller) is read over it */
        if (!snd_load(s, c, T + hdr[5], T + hdr[5]) && !(s & 1))
            SND(s + 1, T + hdr[5], hdr[6]);
        F = (u8 *)(p - 0x1c + h->codefp[(s & 1) && !pst]);
        if (tier[s] == NT - 1) dsz = RD(c + 4, F);
        else { spare(&h->t[tier[s]]); dsz = RD(SPARE, F); }
        REG(s, F, 0);
        cur = (u32)F + dsz;
        if (c == 0) {                                           /* Apocalypse (the stock 0x8002a564 does the same) */
            cur = kanji_at((u32)F + dsz);
            KANJI((void *)cur);
            cur += stock_size(KANJI_IDX);
        }
        tl_dbg[1 + (s >> 1)] |= tier[s] << (4 * (s & 1));        /* [1] tiers P1 main | P1 partner << 4, [2] P2 */
    }
    if (tl_dir.strong_size) {                                    /* after the last read: spill zone is ours */
        u32 *d = (u32 *)STRONG_AT, n = tl_dir.strong_size >> 2;
        for (k = 0; k < (int)n; k++) d[k] = tl_strong[k];
        flushcache();
#ifdef MCFIX
        /* --mcfix (MvC rc1 lesson): the meter part is installed now; kill the arena copy's magic so the battle-init
         * MCOPY (tools/speed/meter.S chunk C) cannot re-copy it from arena bytes the game may have reused meanwhile.
         * Declined (stock-loader) battles keep MCOPY: the glue re-reads the blob into the arena right before. */
        if (n > (0x801fe640u - STRONG_AT) >> 2) tl_strong[(0x801fe640u - STRONG_AT) >> 2] = 0;
#endif
    }
#ifdef L2G
    {                                                            /* after the last read: image, RAM block zeroed, */
        u32 *d = (u32 *)G2AT;                                    /* magic word last (the gate's key) */
        for (k = 1; k < L2WORDS; k++) d[k] = tl_l2img[k];
        for (; k < (int)((0x801fe200u - G2AT) >> 2); k++) d[k] = 0;
        flushcache();
        d[0] = tl_l2img[0];
    }
#endif
    *(u32 *)(tl_dbg + 4) = cur;
    tl_dbg[0] = 1;
    return 1;
}
