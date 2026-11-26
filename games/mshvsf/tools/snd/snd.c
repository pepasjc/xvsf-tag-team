/* Full character sound banks for every character of a tag battle (MSHvSF tag hack v10), linked into the loader blob
 * (tools/tagload/tagload.c, tools/ap8/ap8.c).  Build side: tools/snd/sndbank.py; notes: games/mshvsf/docs/SOUND.md.
 *
 * Stock battle: SPU 0x1010 COMMON (bank 0, loaded by the main menu), 0x315d0 P1 main bank (1), 0x48030 P1 helper
 * bank HLPxx.SE (2, 0x4ab0 bytes), 0x4cae0 P2 main (3), 0x63540 P2 helper (4), kind-6 pixel stashes of the mains at
 * 0x6d000 / 0x69800, stage SP_EFF2 stash 0x70800, AKEBONO stash + bank 5 0x7a6a0-0x7fff0.  The rest (0x67ff0-0x69800,
 * 0x6ba00-0x6d000, 0x6f200-0x70800) holds stale select-screen data and is never read in a battle.
 *
 * Here: the four character banks packed from 0x315d0 (64-byte steps: libspu's SpuWrite DMA writes whole 64-byte
 * blocks, so a shorter piece overwrites the start of the next one), the two main stashes right below 0x70800 (P1 on top), one
 * level for the whole battle (the best whose banks fit, sndbank.CAPS: lossless, then a sample-rate cap one semitone
 * lower per level).  A main uploads its whole bank, a partner the prefix without the win-quote voices (ids >= 0x600;
 * the stock helper banks never had them).  Bank tables 0x8007cd48 (SPU address) / 0x8007cd60 (size) are set per bank.
 *
 * Entries: the stock entry table 0x8007d330 has 190 slots of 20 bytes (COMMON 75, banks 1-4 114 = 45/12/45/12,
 * bank 5 1) with base(b) = sum of 0x8007cd8c[0..b).  Four banks need up to ~151.  The 114 slots of banks 1-4 are
 * re-partitioned (the sum stays 114, so bank 5's and every menu bank's base is unchanged), mains first; what does not
 * fit goes to OVF (0x801ff080.., RAM below the deepest stack the game ever uses, 0x801ffaa8 in every state checked).
 * The stock unload 0x8007b06c(bank) clears only the slot entries, so its first two instructions jump to UNLHOOK
 * (written next to OVF the first time) which also drops the bank's overflow entries.  snd_reset() (every battle
 * load, also when the loader declines) unloads banks 1-4 and puts the stock tables back, so a stock battle or a
 * menu sees the stock layout.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define NCH        0x17
#ifndef SND_NL
#define SND_NL     36                        /* sndbank.NL */
#endif
#define TAB        ((u8 *)0x8007d330u)       /* entry table, 20-byte slots */
#define IDTAB      ((u8 **)0x8007e220u)      /* id -> entry */
#define FB18       ((s16 *)0x8007fb18u)      /* entries per bank in the table */
#define CD48       ((u32 *)0x8007cd48u)      /* SPU address per bank */
#define CD60       ((u32 *)0x8007cd60u)      /* size per bank */
#define CD8C       ((u8 *)0x8007cd8cu)       /* table slots per bank */
#define UNLOAD     ((void (*)(int))0x8007b06c)
#define WAITIDLE   ((void (*)(void))0x8007adc0)
#define SPUW       ((int (*)(u32, void *, u32))0x8007b1ec)
#define SPUREAD    ((void (*)(u32, void *, u32, u32))0x80085040)   /* stock kind-6 fetch: SPU (a + off) -> dst, n; waits */
#define RD         ((int (*)(int, void *))0x80024554)
#define FTAB       ((u32 *)0x800247dcu)
#define SPARE      0x10f
#define SPU_COMMON 0x1010u                   /* bank 0 (COMMON) */
#define REGION_START 0x800bbfe4u            /* tools/tagload/tagload.c: COMMON's level file is read at the pool end */
#define SPU_TOP    0x70800u                  /* SP_EFF2 stash of the stage (constant at 0x8002ab1c) */
#define SLOTS14    114                       /* table slots of banks 1-4 */
#define HOOKAT     0x801ff000u
#define OVFN       (*(u32 *)0x801ff07cu)
#define OVF        ((u8 *)0x801ff080u)
#define OVFMAX     70                        /* .. 0x801ff658 */

extern void flushcache(void);
extern u8 tl_dbg[16];

struct slev { u32 msf; u16 dall, dpart; u8 nall, npart, pad[2]; };   /* sample bytes / 16; msf 0: section 3 as is */
struct schr { struct slev lv[SND_NL]; u16 stash; u16 pad; };          /* stash bytes / 16 */
struct sdir { u32 magic; u32 hook[30]; struct schr c[NCH + 1]; };   /* c[NCH] = COMMON */
struct sdir snd_dir __attribute__((section(".sdir"))) = { 0x31444e53 };  /* 'SND1'; filled by mktag.py */

static const u32 stock48[5] = { 0x1010, 0x315d0, 0x48030, 0x4cae0, 0x63540 };
static const u32 stock60[5] = { 0x305c0, 0x16a60, 0x4ab0, 0x16a60, 0x4ab0 };
static const u8 stock8c[5] = { 75, 45, 12, 45, 12 };

static int lvl;                              /* level of this battle, -1: not planned (stock) */
static u8 full[4];                           /* slot uploads the whole bank (main, or shared by a main) */
static u32 at[4], stash[4], base14;
u8 snd_pst;                                  /* set by the loader before snd_plan: partners' kind-6 sets go to SPU */
u8 snd_dbg[8];                               /* [0] level, [1] overflow entries, [2] 1 planned, [3] fits, [4] partner stashes */

static int fchar(int c) { return c == 0x17 ? 2 : c == 0x18 ? 8 : c == 0x19 ? 7 : c; }
static u32 r64(u32 x) { return (x + 63) & ~63u; }   /* libspu writes whole 64-byte blocks */

static void install(void)
{
    u32 j = 0x08000000u | ((HOOKAT >> 2) & 0x03ffffffu);
    int k;
    if (*(u32 *)0x8007b06cu == j) return;
    for (k = 0; k < 30; k++) ((u32 *)HOOKAT)[k] = snd_dir.hook[k];
    OVFN = 0;
    *(u32 *)0x8007b06cu = j;
    *(u32 *)0x8007b070u = 0;
    flushcache();
}

void snd_reset(void)
{
    int b;
    lvl = -1;
    if (snd_dir.magic != 0x31444e53) return;
    install();
    for (b = 1; b <= 4; b++) UNLOAD(b);       /* with the partition they were loaded with; the hook drops OVF */
    for (b = 0; b < 5; b++) { CD48[b] = stock48[b]; CD60[b] = stock60[b]; CD8C[b] = stock8c[b]; }
    OVFN = 0;
    lvl = -1;
    snd_pst = 0;                              /* the tag loader sets it (after this) for the battle it plans */
    snd_dbg[2] = 0;
}

static u32 dsize(int s, int c, int L)
{
    const struct slev *v = &snd_dir.c[c == NCH ? NCH : fchar(c)].lv[L];
    return r64((u32)(s >= 0 && full[s] ? v->dall : v->dpart) << 4);
}

#ifdef SNDVFY
/* --sndverify (MvC rc4 lesson, games/mvc/tools/snd/snd.c): an SPU upload can end short while the RAM entry table takes
 * the new level -> table and SPU at different levels -> a voice that loops in sustain can freeze the game.  Every
 * upload is read back (first and last 64 bytes) and repeated (up to 4 times) until both match; snd_dbg[6] counts
 * the repeats. */
static u8 vbuf[64];
static int same64(u32 a, const u8 *src)
{
    int i;
    SPUREAD(a, vbuf, 0, 64);
    for (i = 0; i < 64 && vbuf[i] == src[i]; i++) ;
    return i == 64;
}
static void spuw(u32 a, void *src, u32 n)
{
    int t;
    for (t = 0; t < 4; t++) {
        SPUW(a, src, n);
        if (n < 64 || (same64(a, (const u8 *)src) && same64(a + n - 64, (const u8 *)src + n - 64))) return;
        snd_dbg[6]++;
    }
}
#define SPUWV(a, s, n) spuw((a), (s), (n))
#else
#define SPUWV(a, s, n) SPUW((a), (s), (n))
#endif

/* entries of `bank` (an .SE image in RAM) into the table / OVF, then the samples to SPU (as 0x8007ae24 does) */
static void upload(int b, const u8 *bank, int n, int nall, u32 spu, u32 sz)
{
    int i, cap, base, ovf = 0;
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
            d = OVF + 20 * OVFN++; ovf++;
        }
        for (k = 0; k < 20; k++) d[k] = e[k];
        d[0x11] = b; d[0x12] |= 1 << b;
        id = *(s16 *)d;
        if (id == 0x139 && b) continue;                                     /* stock rule */
        if (b == 3 && *(s16 *)0x80070f5eu == 0x26 && IDTAB[id]) continue;    /* stock rule (Cyber-Akuma as P2) */
        IDTAB[id] = d;
    }
    FB18[b] = n < cap ? n : cap;
    CD48[b] = spu; CD60[b] = sz;
    SPUWV(spu, (u8 *)bank + (u32)(nall + 1) * 20, sz);
    snd_dbg[1] += ovf;
}

/* COMMON (bank 0) at level L: our file (no win quotes, reordered, effects capped at the level) replaces the stock bank
 * loaded by the main menu.  Skipped when the table already holds it (entry 0's spare byte +0x13 = 0x80 | L); the main
 * menu's reload puts the stock bank (byte 0) back, the select screen does not touch bank 0. */
static void common(int L, u8 *scratch)
{
    const struct slev *v = &snd_dir.c[NCH].lv[L];
    int i;
    if (TAB[0x13] == (0x80 | L) && FB18[0] == v->npart) return;
    FTAB[SPARE * 2] = v->msf;
    FTAB[SPARE * 2 + 1] = (u32)(v->nall + 1) * 20 + ((u32)v->dall << 4);
    RD(SPARE, scratch);
    UNLOAD(0);
    upload(0, scratch, v->npart, v->nall, SPU_COMMON, dsize(-1, NCH, L));
    for (i = 0; i < v->npart; i++) TAB[20 * i + 0x13] = 0x80 | L;
    snd_dbg[5] = 1;
}

/* after snd_reset, before the first bank: choose the level and the SPU layout */
void snd_plan(signed char *list)
{
    int s, t, L;
    u32 top, a, scratch;
    if (snd_dir.magic != 0x31444e53) return;
    for (s = 0; s < 4; s++) {
        full[s] = 0;              /* v10snd: every bank without the win quotes (never requested; see sndbank.QUOTE) */
    }
    top = SPU_TOP;
    for (s = 0; s < 4; s += snd_pst ? 1 : 2)      /* mains; partners too when the loader stashes theirs (snd_pst) */
        if (list[s] >= 0) { top -= r64((u32)snd_dir.c[fchar(list[s])].stash << 4); stash[s] = top; }
    snd_dbg[4] = snd_pst;
    for (L = 0; L < SND_NL; L++) {
        a = SPU_COMMON + dsize(-1, NCH, L);
        for (s = 0; s < 4; s++)
            if (list[s] >= 0) a += dsize(s, list[s], L);
        if (a <= top) break;
    }
    snd_dbg[3] = L < SND_NL;
    if (L == SND_NL) L = SND_NL - 1;
    lvl = L;
    a = base14 = SPU_COMMON + dsize(-1, NCH, L);
    for (s = 0; s < 4; s++)
        if (list[s] >= 0) { at[s] = a; a += dsize(s, list[s], L); }
    scratch = *(u32 *)(tl_dbg + 8);                   /* the loader's region start (GPU pool end): free until the first read */
    if (scratch < 0x80094800u || scratch > REGION_START) scratch = REGION_START;
    snd_dbg[1] = 0;
    common(L, (u8 *)((scratch + 7) & ~7u));
    /* table partition: mains first */
    {
        int n[5], rem = SLOTS14, b;
        static const u8 order[4] = { 1, 3, 2, 4 };
        for (s = 0; s < 4; s++) {
            const struct slev *v = &snd_dir.c[fchar(list[s] < 0 ? 0 : list[s])].lv[L];
            n[s + 1] = list[s] < 0 ? 0 : (full[s] ? v->nall : v->npart);
        }
        for (t = 0; t < 4; t++) {
            b = order[t];
            CD8C[b] = n[b] < rem ? n[b] : rem;
            rem -= CD8C[b];
        }
        CD8C[4] += rem;
    }
    snd_dbg[0] = L; snd_dbg[2] = 1;
}

u32 snd_stash(int s, u32 dflt) { return lvl < 0 ? dflt : stash[s]; }

/* upload the bank of slot s (char c).  sec3 = the character's section 3 in RAM (our reordered level-0 bank, used as
 * it is at level 0); scratch = where a level file is read (2 MB: sec3 itself, it is at least as big) */
int snd_load(int s, int c, u8 *sec3, u8 *scratch)
{
    const struct slev *v;
    u8 *bank = sec3;
    int b = s + 1, n;
    u32 sz;
    if (lvl < 0) return 0;
    v = &snd_dir.c[fchar(c)].lv[lvl];
    if (v->msf) {
        FTAB[SPARE * 2] = v->msf;
        FTAB[SPARE * 2 + 1] = (u32)(v->nall + 1) * 20 + ((u32)v->dall << 4);
        RD(SPARE, scratch);
        bank = scratch;
    }
    n = full[s] ? v->nall : v->npart;
    sz = dsize(s, c, lvl);
    upload(b, bank, n, v->nall, at[s], sz);
    return 1;
}
