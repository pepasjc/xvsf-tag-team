/* Four-full-character battle loader for X-Men vs. Street Fighter (SLUS-00627).
 *
 * Two entries from the battle loader 0x8002ac38 (both get &list = caller sp+0x38 from the glue:
 * the four deduped character numbers P1 main, P1 partner, P2 main, P2 partner; -1 = shares data):
 *
 *   effglue  (jal at 0x8002b154, was jal 0x80054054 = load sprite set 0x26 = SP_EFF1, the last file
 *            below the heap top).  Reads the directory sector, then loads the STOCK (RLE) effects
 *            file instead of the in-place XVM1 one when the default team still fits with it.
 *   glue     (jal at 0x8002b1ac, was jal 0x80054fe4 = battle pool init).  Fixed pool, then every
 *            listed character is loaded FULL, packed:  [code, relocated at load][sprite file] 8-aligned,
 *            its list entry set to -1 so the stock slot loop that follows does nothing.
 *
 * Boss team (any id == 0x10): both hooks fall through to the stock behaviour.
 *
 * Sprite tiers per character, smallest to largest:
 *      strong (1, XVH1)  <  base (0, XVM1, the in-place A/A0 file)  <  mid (3)  <  fat (2)
 * (a character without a separate mid file has its in-place entry in the mid table: cost 0).
 *
 * Policy (model: tools/tagpolicy.py):
 *   1. base characters + XVM1 effects must fit; else characters go STRONG in the order P2 partner,
 *      P1 partner, P2 main, P1 main; else the last partner is dropped.  No upgrades in that case.
 *   2. slack, greedy, skipping what does not fit, always in the order P1 main, P2 main, P1 partner,
 *      P2 partner:  MID for everybody -> effects file = stock RLE (decided in effglue, with the same
 *      MID choice) -> FAT.
 *
 * All file locations/sizes of the variants live in one directory sector on the disc, read to DIR
 * (the 2 KB CD-spill zone above LIMIT) once per battle by effhook.  The same sector carries the
 * policy code (section .ram: need, choose, guard, fatten), linked to run right there; it is only
 * called before the first character is loaded (a later CD spill may overwrite it).
 * Code file = P0 overlay + relocation table.
 *
 * Robustness (tag16/17):
 *   - BIOS FlushCache is only called inside a critical section (glue.S).  Called with interrupts
 *     enabled it hangs when an interrupt (here: the CD drive finishing the code-file read) is taken
 *     while the cache is isolated - the cause of the "NOW LOADING" freeze of tag14.
 *   - the directory sector carries a magic and a checksum; it is re-read up to 3 times, and if it
 *     never validates this battle takes the STOCK loading path (reduced partners), like a boss team.
 *     tl_dbg.dropped = 0xFD marks that fallback.
 *
 * Boss fight at stock speed (tag20): a boss team keeps the stock loading path, but the files that
 * path reads through the game file table are the re-encoded ones.  effhook reads a second
 * directory sector (bossdirent: stock RLE sprite files in the var[T_MID-1] table, stock effects
 * file in eff, and bossprep() as code), loads the stock effects file, and bossprep() exchanges the
 * file-table entries of the two main characters with their stock RLE entries for the stock slot
 * loop.  bossfin() (the stock "extra boss file" read at 0x8002b2d0, which exactly the teams that
 * bossprep() accepts reach) exchanges them back.  tl_dbg.dropped = 0xFB: boss path with stock
 * files; 0xFA: boss path, the boss directory did not validate (in-place files, as tag19).
 *
 * Boss fight on the new loader (tag22): when the boss is P2's main, the player's side has no boss,
 * and the fixed layout fits below BOSSLIMIT (the ending renderer draws into 0x801e5000/0x801e6000),
 * bossprep() selects the new loader instead of the stock slots (tl_dbg.dropped = 0xF9): the
 * player's characters FULL at the FAT tier, Apocalypse relocated like any character with his
 * stock RLE sprite file, stock effects, mask 0.  No policy is needed (it always fits), so the boss
 * directory sector carries the tables (code files, fat files, RLE files) and bplan(), which sits
 * at the address of plan() - hook() calls whichever directory is in RAM.  The extra boss file
 * (KANJI.TEX at stock slot + 0x42000) is not loaded on this path.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

/* game addresses: US values; another region passes -DA_xxx=... (tools/mktagdisc.py + tools/regionmap.py) */
#ifndef A_FTABLE
#define A_FTABLE    0x8003d91c
#define A_D130      0x8003d130
#define A_POOLSIZE  0x8004382c
#define A_IDS       0x800423b2
#define A_INITTAB   0x8003d83c
#define A_LOADFILE  0x8002de3c
#define A_SPRLOAD   0x80053f78
#define A_SETLOAD   0x80054054
#define A_POOLINIT  0x80054fe4
#endif
#define FTABLE      A_FTABLE
#define FT(i)       ((struct xent *)(FTABLE + 8 * (i)))
#define FT_SIZE(i)  (FT(i)->size)
#define D130        (*(u32 *)A_D130)
#define POOLSIZE    (*(u32 *)A_POOLSIZE)
#define IDS         ((s16 *)A_IDS)
#define INITTAB     ((u32 *)A_INITTAB)
#define LOADFILE    ((int (*)(int, u8 *))A_LOADFILE)
#define SPRLOAD     ((u32 (*)(int, u32))A_SPRLOAD)
#define SETLOAD     ((u32 (*)(int, u32))A_SETLOAD)
#define POOLINIT    ((void (*)(int, int, int, u8 *, u32))A_POOLINIT)
#define LINKBASE    0x800d1000u
#define HEAPBASE    0x80098000u
#ifndef POOL
#define POOL        19296u          /* 402 entries of 48 bytes = the original game smallest pool (stage 0) */
#endif
#define LIMIT       0x801fe000u     /* end of data; + <=2047 bytes CD sector spill stays below 0x801fe800 */
#define DIR         ((struct dir *)0x801fe004)      /* == FTABLE mod 8: reachable as a fake file index */
#define FAKE(p)     ((int)((u32)(p) - FTABLE) >> 3)

struct xent { u32 msf; u32 size; };
#ifdef HOT
struct dir { struct xent code[19], var[3][19], eff, hdir; };   /* + the hot directory sector (1.1) */
#else
struct dir { struct xent code[19], var[3][19], eff; };   /* var[tier - 1]: 1 strong, 2 fat, 3 mid */
#endif
#define T_STRONG 1
#define T_FAT    2
#define T_MID    3
extern const struct xent dirent;    /* the directory sector itself; filled by the disc builder */
extern const struct xent bossdirent;                /* directory sector of the stock RLE files (boss path) */
extern struct { u32 w[4]; signed char c[2]; } bk;   /* entries exchanged with the file table for main k (c[k] = -1: none) */
void bossprep(int stage, s16 *list, int unused, u8 *heap);
#define BOSSRLE     0xFB
#define BOSSPLAIN   0xFA
#define BOSSNEW     0xF9
#define BOSSLIMIT   0x801e5000u
/* debug block: loaded = loaded-slot mask (low nibble) | MID mask << 4; fat = FAT mask | 0x80 when the
 * stock effects file was loaded; strong = STRONG mask; dropped = 0 / 3 / 1|3 */
extern struct { u8 dropped; u8 loaded; u8 strong; u8 fat; u32 start, end; } tl_dbg;
void flushcache(void);                              /* EnterCriticalSection + BIOS FlushCache + Exit */
#define DIR_MAGIC   0x31445658u                     /* "XVD1" at word 510 of the sector, word 511 = sum of words 0..509 */
#define FALLBACK    0xFD

#define SEC(s) __attribute__((section(s), noinline))

SEC(".chunke") u32 need(int c, int v)               /* v: tier */
{
    u32 spr = FT_SIZE(0x5a + c);
    if (v) spr = DIR->var[v - 1][c].size;
    return ((((FT_SIZE(3 + c) >> 3) + 1) << 3) + spr + 7) & ~7u;
}

static const signed char order[4] = { 3, 1, 2, 0 };

/* strong mask that makes the team fit in cap; 0 = all default fits; -1 = not even all strong */
SEC(".ram") int choose(s16 *list, u32 cap)
{
    u32 t = 0, save[4];
    int i, k, m = 0;
    for (i = 0; i < 4; i++) {
        save[i] = 0;
        if (list[i] >= 0) {
            u32 f = need(list[i], 0);
            t += f;
            save[i] = f - need(list[i], 1);
        }
    }
    if (t <= cap) return 0;
    for (k = 0; k < 4; k++) {
        i = order[k];
        if (save[i] && t - save[i] <= cap) return 1 << i;
    }
    for (k = 0; k < 4; k++) {
        i = order[k];
        if (save[i]) {
            t -= save[i];
            m |= 1 << i;
            if (t <= cap) return m;
        }
    }
    return -1;
}

SEC(".ram") int guard(s16 *list, u32 cap)
{
    s16 *ids = IDS;
    int i, j, m;
    tl_dbg.dropped = 0;
    for (i = 3; ; i -= 2) {
        m = choose(list, cap);
        if (m >= 0) break;
        if (list[i] >= 0) {                         /* overflow guard: last partner first */
            s16 v = ids[i];
            list[i] = -1;
            tl_dbg.dropped |= i;
            for (j = 1; j < 4; j += 2)              /* everybody who used that data becomes his own main */
                if (ids[j] == v) ids[j] = ids[j - 1];
        }
    }
    tl_dbg.strong = m;
    return m;
}

SEC(".ram") u32 total(s16 *list, u8 *tier)
{
    u32 t = 0;
    int i;
    for (i = 0; i < 4; i++)
        if (list[i] >= 0) t += need(list[i], tier[i]);
    return t;
}

/* spend slack on tier `to`: P1 main, P2 main, P1 partner, P2 partner; greedy, skip what does not fit */
SEC(".ram") u32 upgrade(s16 *list, u8 *tier, u32 slack, int to)
{
    int i, k;
    for (k = 3; k >= 0; k--) {
        i = order[k];                               /* reversed order[] = 0, 2, 1, 3 */
        if (list[i] >= 0) {
            u32 d = need(list[i], to) - need(list[i], tier[i]);
            if (d <= slack) {
                slack -= d;
                tier[i] = to;
            }
        }
    }
    return slack;
}

/* effects file decision (before SP_EFF1 is loaded at heap offset off): 0 = keep the in-place XVM1
 * file, else the stock file entry */
SEC(".ram") const struct xent *effplan(s16 *list, u32 off)
{
    u32 topx = HEAPBASE + ((((off + ((FT_SIZE(0x5a + 0x26) + 3) & ~3u)) >> 3) + 1) << 3);
    u32 tops = HEAPBASE + ((((off + ((DIR->eff.size + 3) & ~3u)) >> 3) + 1) << 3);
    u32 cap = LIMIT - POOL - topx;
    u8 tier[4];
    tl_dbg.fat = 0;
    *(u32 *)tier = 0;
    if (choose(list, cap) != 0) return 0;
    if (upgrade(list, tier, cap - total(list, tier), T_MID) < tops - topx) return 0;
    tl_dbg.fat = 0x80;
    return &DIR->eff;
}

/* tier per slot for the real heap top (after the effects file) */
#ifdef HOT
void hotplan(s16 *list, u32 slack, u8 *tier);
SEC(".ram0") void plan(s16 *list, u32 cap, u8 *tier)
{
    int i, m = guard(list, cap);
    for (i = 0; i < 4; i++) tier[i] = (m >> i) & 1;
    tl_dbg.loaded = 0;
    hotplan(list, cap - total(list, tier), tier);       /* base characters only; also next to strong ones */
}
#else
SEC(".ram0") void plan(s16 *list, u32 cap, u8 *tier)
{
    int i, m = guard(list, cap);
    u32 mid = 0, fat = 0;
    for (i = 0; i < 4; i++) tier[i] = (m >> i) & 1;
    if (m == 0) upgrade(list, tier, upgrade(list, tier, cap - total(list, tier), T_MID), T_FAT);
    for (i = 0; i < 4; i++) {
        if (tier[i] == T_MID) mid |= 16 << i;
        if (tier[i] == T_FAT) fat |= 1 << i;
    }
    tl_dbg.loaded = mid;
    tl_dbg.fat |= fat;
}
#endif

SEC(".chunkb") int isboss(void)
{
    s16 *ids = IDS;
    return ids[0] == 0x10 || ids[2] == 0x10 || ids[1] == 0x10 || ids[3] == 0x10;
}

/* read + validate a directory sector; 0 = it never validated */
SEC(".chunkc") int dirload(const struct xent *ent)
{
    int n, i;
    for (n = 0; n < 3; n++) {
        u32 *p = (u32 *)DIR, sum = 0;
        LOADFILE(FAKE(ent), (u8 *)DIR);
        for (i = 0; i < 510; i++) sum += p[i];
        if (p[510] == DIR_MAGIC && p[511] == sum) {
#ifndef NOFLUSH
            flushcache();                           /* policy code was just loaded */
#endif
            return 1;
        }
    }
    return 0;
}

/* this battle uses the stock loading path: boss team, or the directory could not be read */
SEC(".chunkf") int stockpath(int stage, s16 *list, int unused, u8 *heap)
{
    if (tl_dbg.dropped == BOSSRLE) bossprep(stage, list, unused, heap);    /* may turn it into BOSSNEW */
    return tl_dbg.dropped >= BOSSPLAIN;             /* 0xFA boss/in-place, 0xFB boss/stock files, 0xFD directory unreadable */
}

/* ---- boss on the new loader: plan() of the boss directory (same address as plan()) ---- */
SEC(".ramb0") void bplan(s16 *list, u32 cap, u8 *tier)
{
    int i;
    u32 fat = 0x80, mid = 0;                        /* stock effects were loaded by effhook */
    for (i = 0; i < 4; i++) {
        tier[i] = T_FAT;                            /* player characters: fat files (var[T_FAT-1]) */
        if (list[i] == 8) {
            tier[i] = T_MID;                        /* boss: var[T_MID-1] = stock RLE */
            mid |= 16 << i;
        } else if (list[i] >= 0) fat |= 1 << i;
    }
    tl_dbg.strong = 0;
    tl_dbg.loaded = mid;
    tl_dbg.fat = fat;
}

/* ---- boss path: stock RLE files ---- */
/* exchange the file-table entries of the characters in bk.c with bk.w (self-inverse) */
SEC(".ramb") void bossswap(void)
{
    int k;
    for (k = 0; k < 2; k++) {
        int c = bk.c[k];
        if (c >= 0) {
            u32 *a = (u32 *)FT(0x5a + c), *b = &bk.w[2 * k], t;
            t = a[0]; a[0] = b[0]; b[0] = t;
            t = a[1]; a[1] = b[1]; b[1] = t;
        }
    }
}

/* stock slot loop over: entries back, nothing pending */
SEC(".ramb") void bossdone(void)
{
    bossswap();
    bk.c[0] = bk.c[1] = -1;
}

/* replaces LOADFILE(0x10c, slot base + 0x42000) at 0x8002b2d0: the stock slot loop is over */
SEC(".chunkg") int bossfin(int idx, u8 *dest)
{
    if (tl_dbg.dropped == BOSSNEW) return 0;        /* new loader: no stock slots, the extra file is not loaded */
    if (tl_dbg.dropped == BOSSRLE) bossdone();      /* the boss directory (with its code) is still in RAM */
    return LOADFILE(idx, dest);
}

/* in the boss directory sector: main characters -> stock RLE files, until bossfin() */
SEC(".ramb") void bossprep(int stage, s16 *list, int unused, u8 *heap)
{
    s16 *ids = IDS;
    int k;
    /* new loader: boss = P2 main only (its "partner" is the boss id again = no list entry), a normal
     * player side, and the fixed layout must end below the ending renderer's buffers */
    if (ids[2] == 0x10 && ids[0] != 0x10 && ids[1] != 0x10 && list[0] >= 0 && list[2] == 8 && list[3] < 0) {
        u32 t = (u32)heap + POOL + need(8, T_MID);
        for (k = 0; k < 2; k++)
            if (list[k] >= 0) t += need(list[k], T_FAT);
        if (t <= BOSSLIMIT) {
            tl_dbg.dropped = BOSSNEW;
            return;
        }
    }
    if (ids[0] != 0x10 && ids[2] != 0x10) return;   /* the stock test for the extra boss file: bossfin() will run */
    for (k = 0; k < 2; k++) {
        int c = list[2 * k];
        bk.c[k] = c;
        if (c >= 0) {
            bk.w[2 * k] = DIR->var[T_MID - 1][c].msf;
            bk.w[2 * k + 1] = DIR->var[T_MID - 1][c].size;
        }
    }
    bossswap();
}

/* load a sprite file through the game loader fn(set, off) with the file table entry 0x5a+set
 * temporarily replaced by *var (var == 0: as is).  The entry is restored from the stack, so the
 * directory may be overwritten by the CD spill of this very read. */
SEC(".chunka") u32 varload(u32 (*fn)(int, u32), int set, u32 off, const struct xent *var)
{
    struct xent *fe = FT(0x5a + set), keep = *fe;
    u32 n;
    if (var) *fe = *var;
    n = fn(set, off);
    *fe = keep;
    return n;
}

/* replaces SETLOAD(0x26, off): the resident effects file */
SEC(".chunka") u32 effhook(int set, u32 off, s16 *list)
{
    const struct xent *var = 0;
    if (!isboss()) {
        tl_dbg.dropped = FALLBACK;
        if (dirload(&dirent)) {
            tl_dbg.dropped = 0;
            var = effplan(list, off);
        }
    } else {
        tl_dbg.dropped = BOSSPLAIN;
        if (dirload(&bossdirent)) {
            tl_dbg.dropped = BOSSRLE;
            var = &DIR->eff;
        }
    }
    return varload(SETLOAD, set, off, var);
}

#ifdef HOT
u32 hotspr(int set, u32 off);
#endif
SEC(".chunkb") u32 load_one(int c, u8 *base, const struct xent *var)
{
    u32 code = FT_SIZE(3 + c), delta = (u32)base - LINKBASE, off, n, t;
    u16 *p;
    int k;
    LOADFILE(FAKE(&DIR->code[c]), base);
    p = (u16 *)(base + ((code + 3) & ~3u));
    for (k = 0; k < 3; k++) {
        while ((t = *p++) != 0xffff) {
            u32 *w = (u32 *)(base + t * 4), v = *w;
            if (k == 0) v += delta;                                 /* pointer word */
            else if (k == 1) v = (v & 0xfc000000) | ((v + (delta >> 2)) & 0x03ffffff);   /* j / jal */
            else {                                                  /* lui + lo16 pair */
                u32 *l = (u32 *)(base + *p++ * 4), lv = *l;
                u32 a = (v << 16) + (s16)lv + delta;
                *l = (lv & 0xffff0000) | (a & 0xffff);
                v = (v & 0xffff0000) | ((a + 0x8000) >> 16);
            }
            *w = v;
        }
    }
#ifndef NOFLUSH
    flushcache();
#endif
    ((void (*)(void))(INITTAB[c] + delta))();
    off = ((code >> 3) + 1) << 3;
    D130 = (u32)base;
#ifdef HOT
    n = varload(hotspr, c, off, var);
#else
    n = varload(SPRLOAD, c, off, var);
#endif
    D130 = LINKBASE;
    return (off + n + 7) & ~7u;
}

SEC(".chunkd") void hook(int stage, s16 *list, int unused, u8 *heap)
{
    u8 *cur;
    u8 tier[4];
    int i;
    if (stockpath(stage, list, unused, heap)) {
        POOLINIT(stage, list[0], list[2], heap, LINKBASE - (u32)heap);      /* original path */
        return;
    }
    plan(list, LIMIT - POOL - (u32)heap, tier);
    POOLSIZE = POOL;
    POOLINIT(stage, list[0], list[2], heap, POOL);
    cur = heap + POOL;
    tl_dbg.start = (u32)cur;
#ifdef SLOTORDER                                    /* tag14 disc layout: slot order */
    for (i = 0; i < 4; i++) {
        int c = list[i];
        if (c < 0) continue;
        list[i] = -1;
        cur += load_one(c, cur, tier[i] ? &DIR->var[tier[i] - 1][c] : 0);
        tl_dbg.loaded |= 1 << i;
    }
#else
    for (;;) {                                      /* ascending character number = disc order */
        int c, j = -1;
        for (i = 0; i < 4; i++)
            if (list[i] >= 0 && (j < 0 || list[i] < list[j])) j = i;
        if (j < 0) break;
        c = list[j];
        list[j] = -1;
        cur += load_one(c, cur, tier[j] ? &DIR->var[tier[j] - 1][c] : 0);
        tl_dbg.loaded |= 1 << j;
    }
#endif
    tl_dbg.end = (u32)cur;
}

#ifdef HOT
/* ---- 1.1 continuous hot-tile tier (format: tools/speed/decode/hotfile.py) ----
 * The hot directory sector (DIR->hdir) is read to HDIR right below LIMIT when the policy runs (nothing is loaded
 * there yet); hplan() in it picks a step per base character from the slack; the chosen region entry and suffix
 * size of each character are copied to hslot[] (resident) because later reads overwrite HDIR.
 * hotspr() replaces the game's sprite-file load for every character: base file minus S bytes, then the region
 * prefix (R bytes) right behind it, truncated sec2 size into the XVM1 header, sec1 of the items -> RLE copies. */
#define HDIR        0x801fd804u                     /* == FTABLE mod 8; ends at DIR */
#define HDIR_MAGIC  0x44485658u                     /* "XVHD" at word 510, word 511 = sum of words 0..509 */
#define SEC0TAB     ((u32 *)0x8006a358)
#define SEC1TAB     ((u32 *)0x8005ce80)
#define SEC2TAB     ((u32 *)0x8005c830)
struct hslot { struct xent reg; s16 c; s16 fake; u32 s; };   /* reg first: must sit at FTABLE mod 8; fake = its file index */
extern struct hslot hslot[4];
typedef void (*hplan_fn)(s16 *list, u32 slack, u8 *tier, struct hslot *out);

/* hotplan(list, slack, tier): tagload/hot/hotspr.S */
/* hotspr(): tagload/hot/hotspr.S */

/* ---- in the hot directory sector (linked at HDIR + table size; called through word 0) ---- */
struct hstep { u16 s, net, g; };
struct hchar { u32 msf; u8 n; u8 pad; struct hstep st[9]; };       /* 60 bytes; msf = the region file */
#define HC(c)   ((struct hchar *)(HDIR + 4 + 60 * (c)))   /* word 0 = &hplan; code from HDIR + 1144 */
/* extra RAM of step k of character c over the base file (as hotspr() and load_one() consume it) */
SEC(".hram") static u32 hcost(int c, int k)
{
    u32 f, s, r;
    if (k == 0) return 0;
    f = FT_SIZE(0x5a + c);
    s = HC(c)->st[k - 1].s;
    r = s + HC(c)->st[k - 1].net;
    return ((f - s + 3) & ~3u) + r - ((f + 3) & ~3u) + 8;
}

SEC(".hram") void hplan(s16 *list, u32 slack, u8 *tier, struct hslot *out)
{
    int step[4], live[4], i;
    for (i = 0; i < 4; i++) {
        step[i] = 0;
        live[i] = list[i] >= 0 && tier[i] == 0 && HC(list[i])->n > 0;
    }
    for (;;) {
        int b = -1;
        u32 bg = 0, bd = 1;
        for (i = 0; i < 4; i++) {
            u32 g, d;
            int c = list[i], k;
            if (!live[i]) continue;
            k = step[i];
            d = hcost(c, k + 1) - hcost(c, k);
            g = HC(c)->st[k].g;
            if (b < 0 || g * bd > bg * d) { b = i; bg = g; bd = d; }
        }
        if (b < 0) break;
        if (bd <= slack) {
            slack -= bd;
            if (++step[b] == HC(list[b])->n) live[b] = 0;
        } else live[b] = 0;
    }
    for (i = 0; i < 4; i++) {
        int c = list[i], k = step[i];
        if (k) {
            out[i].c = c;
            out[i].reg.msf = HC(c)->msf;
            out[i].reg.size = HC(c)->st[k - 1].s + HC(c)->st[k - 1].net;
            out[i].s = HC(c)->st[k - 1].s;
            out[i].fake = FAKE(&out[i].reg);
            tl_dbg.loaded |= 16 << i;
        }
    }
}
#endif
