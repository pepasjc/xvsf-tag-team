/* 8 MB battle loader of the MSHvSF tag hack ("ap8"), linked into the same blob as the 2 MB loader (tools/tagload).
 *
 * The resident glue (tools/tagload/glue.S, unchanged) reads the blob into the sprite decode arena each battle and
 * calls its entry with the stock loader's list; the ap8 build links the entry to ap8_main instead of tl_main:
 *
 *   ap8_main(list):  no 8 MB (probe, once per boot) or not a tag fight  ->  tl_main(list): exactly the 2 MB path.
 *                    8 MB: every listed character FULL from upper RAM, stock RLE sprites, nothing in the 2 MB area.
 *
 * Upper RAM (0x80200000-0x80800000):
 *   UP + 0          cache header (magic, tick, NCS slot records)
 *   WORK + s * WA   per list slot s: header + sec1 (code/data, relocated) + sec2 (kind-6 set) of PLxx_10.A0
 *   CACHE + k * CS  cache slot k: [PLxx_10.A0 + relocation table][SP_PLxx.DSP][HLPxx.SE], pristine disc bytes.
 *                   The sprite file is registered IN PLACE (the game only reads it); sound comes from the slot too.
 * A cache slot is reused when its key (character, disc position + size of the A0 file and of the sprite file)
 * matches and the word sum of each part still matches the sum taken when it was read; else the part is read again.
 * The first call of a boot (tl_dbg[12] == 0: the EXE image was just loaded) wipes the header: upper RAM survives a
 * reset / core reload on some machines (MiSTer) and may hold another build's data.
 *
 * Sound: every character gets its own character bank as in the 2 MB build (tools/snd/snd.c); level files are read
 * into SND_SCRATCH.  The cached helper bank (HLPxx.SE) is only the fallback when the sound module is absent.
 *
 * tl_dbg (glue.S): [0] 1 loaded, [1] [2] 0x99 (stock RLE everywhere), [3] probe 0 not yet / 1 no 8 MB / 2 8 MB,
 *   [4..7] UPEND marker = end of the used cache, [12] boot flag, [13] OPTION "ARCADE FRAMES" (1 = on, set with
 *   [15] = 8 MB present by the probe; ap8menu.S probes at the first main-menu frame).  Cache hits / reads: header.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

/* ---- shared with tagload.c (same layout; mkap8.py passes NT from tagload.c, mktag.py checks the record size) ---- */
struct fent { u32 msf, size; };
#ifndef NT
#error "NT (tagload.c sprite tiers) not given"
#endif
struct chr {
    struct fent a0;
    u32 a0size;
    u32 codefp[2];
    u16 forb_lo, forb_hi;
    struct fent t[NT - 1];
    u16 cost[NT + (NT & 1)];
};
_Static_assert(sizeof(struct chr) == 24 + 8 * (NT - 1) + 2 * (NT + (NT & 1)), "struct chr differs from tagload.c");
struct dir {
    u32 magic;
    u32 strong_size;
    struct chr c[0x17];
};
extern struct dir tl_dir;
extern u8 tl_dbg[16];
extern void flushcache(void);
extern int tl_main(signed char *list);
extern void snd_reset(void);                    /* tools/snd/snd.c: full sound bank for every character */
extern void snd_plan(signed char *list);
extern u32 snd_stash(int s, u32 dflt);
extern int snd_load(int s, int c, u8 *sec3, u8 *scratch);
#define SND_SCRATCH ((u8 *)0x80100000u)         /* level files: the 2 MB character area is unused in 8 MB fights */

#define SLOT0_BASE   0x800bc000u
#define FTAB         ((u32 *)0x800247dcu)
#define SPARE        0x10f
#define INIT_TAB     ((u32 *)0x800650e4u)
#define SPU_STASH    ((u32 *)0x800650d4u)
typedef int  (*rd_t)(int idx, void *dst);
typedef void (*snd_t)(int bank, void *src, int size);
typedef int  (*stash_t)(int set, void *src, int kind, int size, u32 spu);
typedef void (*reg_t)(int slot, void *dsp, int zero);
typedef void (*init_t)(int delta, u32 base0);
#define RD    ((rd_t)0x80024554)
#define SND   ((snd_t)0x8007ae24)
#define STASH ((stash_t)0x8008006c)
#define REG   ((reg_t)0x8007fddc)
#define KANJI ((void (*)(void *))0x8002a244)     /* char 0: KANJI.TEX after its sprites (stock 0x8002a564) */
#define POOLRESET ((void (*)(void))0x80020fbc)
#define POOLINIT  ((void (*)(void *, u32))0x80020fe4)
#define POOL_END  0x800bbfd8u
#define POOL_CAP  16384u

/* ---- upper RAM layout.  The cache slot geometry comes from tl8_dir (mkap8.py sizes it for the files on the disc and
 * checks every file against it); the defaults are the stock-file geometry. ---- */
#define UP        0x80200000u
#define WORK      (UP + 0x1000u)
#define WA        0x1c000u                      /* header + sec1 + sec2 of the biggest A0 is 0x19dc4, + frame-id table */
#define CACHE     (WORK + 4 * WA)
#define C_A0      0u                            /* cap 0x32000: A0 + table (max 202672 B) */
#define NCSMAX    16
#define KANJI_AT  0x800c0000u                   /* char 0's KANJI.TEX: the 2 MB character area is free in this mode */
#define MAGIC     0x4143534du                   /* 'MSCA' */
#define RAM_SIZE  (*(volatile u32 *)0x1f801060)

/* restored content (games/mshvsf/tools/ap/build8.py): per file character a sprite file and an animation patch */
struct a8ent { struct fent dsp, ap8; };
struct dir8 {
    u32 magic;                                  /* 'AP8D' */
    u32 cs, c_dsp, c_hlp, c_ap8, ncs;           /* cache slot size, part offsets in a slot, slot count */
    u32 on;                                     /* restored content used (0: stock files everywhere) */
    struct a8ent c[0x17];
};
struct dir8 tl8_dir __attribute__((section(".dir8"))) = { 0x44385041, 0xb1000, 0x32000, 0xab000, 0xb0000, 8, 0 };
#define CS     (tl8_dir.cs)
#define C_DSP  (tl8_dir.c_dsp)
#define C_HLP  (tl8_dir.c_hlp)
#define C_AP8  (tl8_dir.c_ap8)
#define NCS    ((int)tl8_dir.ncs)
#define UPEND  (CACHE + NCS * CS)

struct cslot {
    u32 c;                                      /* char id + 1 (0 = empty) */
    u32 a0msf, a0n, dspmsf, dspn, hlpmsf, hlpn; /* key: disc positions + sizes (hlpn 0: no sound part) */
    u32 a0sum, dspsum, hlpsum;
    u32 used;                                   /* tick of the last battle that used it */
    u32 ap8msf, ap8n, ap8sum;                   /* animation patch (ap8n 0: none) */
};
struct chdr {
    u32 magic, tick;
    u32 hits, reads;                            /* parts reused / read in the last battle (tests) */
    struct cslot s[NCSMAX];
};
#define H ((struct chdr *)UP)

static int filechar(int c)
{
    if (c == 0x17) return 2;
    if (c == 0x18) return 8;
    if (c == 0x19) return 7;
    return c;
}

static u32 a8(u32 x) { return (x + 7) & ~7u; }

static u32 place(u32 cur, const struct chr *h)
{
    u32 p = a8(cur + 0x1c);
    if (h->forb_lo != h->forb_hi) {
        u32 r = (p - SLOT0_BASE) & 0xffff;
        if (r >= h->forb_lo && r < h->forb_hi) p += a8(h->forb_hi - r);
    }
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

/* ---- 8 MB probe (once per boot).  Real consoles: the CPU write buffer can answer a read from a just-written
 * address before the write reached RAM, so a write-then-read test alone can see "8 MB" on a 2 MB console
 * (XvSF 1.0 froze there).  First a test that writes nothing: on 2 MB hardware the window mirrors the low 2 MB,
 * so game code reads the same 2 MB higher.  Then write / read-back with the low word checked, one uncached
 * dummy read between write and read-back (drains the write buffer), everything restored. ---- */
static volatile u32 pw;

static int probe(void)
{
    const volatile u32 *c = (const volatile u32 *)0x80024554u;     /* game code (CD read), never patched */
    volatile u32 *lo = &pw, *hi;
    u32 l, keep;
    int k, i, ok = 1;
    RAM_SIZE = 0xb88;                   /* what the BIOS writes at boot: 8 MB address window */
    for (i = 0; i < 32 && c[i] == ((const volatile u32 *)((u32)c + 0x200000u))[i]; i++) ;
    if (i == 32) return 0;
    pw = 0x13579bdfu;
    l = *lo;
    for (k = 1; k < 4 && ok; k++) {
        hi = (volatile u32 *)((u32)lo + k * 0x200000u);
        keep = *hi;
        *hi = l ^ 0x5aa5c33cu;
        (void)*(volatile u32 *)0xbfc00000u;         /* BIOS ROM read: waits for the write buffer */
        if (*hi != (l ^ 0x5aa5c33cu) || *lo != l) ok = 0;
        *lo = l;
        *hi = keep;
    }
    return ok;
}

static void spare(u32 msf, u32 size)
{
    FTAB[SPARE * 2] = msf;
    FTAB[SPARE * 2 + 1] = size;
}

static u8 *slotp(int k) { return (u8 *)(CACHE + k * CS); }

/* make the cache slot of char c hold A0 + sprites (+ helper sound when partner); returns the slot */
static int fill(int c, int partner, u32 busy)
{
    const struct chr *h = &tl_dir.c[filechar(c)];
    const struct a8ent *r = &tl8_dir.c[filechar(c)];
    int rest = tl8_dir.on && r->dsp.size && tl_dbg[13];      /* OPTION ARCADE FRAMES (1 = on) */
    u32 dmsf = rest ? r->dsp.msf : FTAB[(c + 4) * 2], dn = rest ? r->dsp.size : FTAB[(c + 4) * 2 + 1];
    u32 hmsf = FTAB[(c + 0x2c) * 2], hn = FTAB[(c + 0x2c) * 2 + 1];
    struct cslot *e = 0;
    int k, best = -1, need = 0;
    u8 *P;
    for (k = 0; k < NCS; k++) {
        e = &H->s[k];
        if (e->c == (u32)c + 1 && e->a0msf == h->a0.msf && e->a0n == h->a0.size && e->dspmsf == dmsf && e->dspn == dn) break;
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
        e->a0msf = h->a0.msf; e->a0n = h->a0.size; e->dspmsf = dmsf; e->dspn = dn;
        e->hlpn = 0; e->ap8n = 0;
        need = 3;
    } else {
        P = slotp(k);
        if (wsum((u32 *)(P + C_A0), e->a0n) != e->a0sum) need |= 1;
        if (wsum((u32 *)(P + C_DSP), e->dspn) != e->dspsum) need |= 2;
        H->hits += 2 - (need & 1) - (need >> 1);
    }
    P = slotp(k);
    if (need & 1) {
        spare(e->a0msf, e->a0n);
        RD(SPARE, P + C_A0);
        e->a0sum = wsum((u32 *)(P + C_A0), e->a0n);
        H->reads++;
    }
    if (need & 2) {
        if (rest) { spare(dmsf, dn); RD(SPARE, P + C_DSP); }
        else RD(c + 4, P + C_DSP);
        e->dspsum = wsum((u32 *)(P + C_DSP), e->dspn);
        H->reads++;
    }
    if (partner && hn) {
        if (e->hlpmsf != hmsf || e->hlpn != hn || wsum((u32 *)(P + C_HLP), hn) != e->hlpsum) {
            e->hlpn = 0;
            RD(c + 0x2c, P + C_HLP);
            e->hlpmsf = hmsf; e->hlpn = hn;
            e->hlpsum = wsum((u32 *)(P + C_HLP), hn);
            H->reads++;
        } else H->hits++;
    }
    if (rest && r->ap8.size) {
        if (e->ap8msf != r->ap8.msf || e->ap8n != r->ap8.size || wsum((u32 *)(P + C_AP8), r->ap8.size) != e->ap8sum) {
            e->ap8n = 0;
            spare(r->ap8.msf, r->ap8.size);
            RD(SPARE, P + C_AP8);
            e->ap8msf = r->ap8.msf; e->ap8n = r->ap8.size;
            e->ap8sum = wsum((u32 *)(P + C_AP8), r->ap8.size);
            H->reads++;
        } else H->hits++;
    } else e->ap8n = 0;
    e->used = H->tick;
    return k;
}

/* PLxx.AP8 (tools/ap/build8.py): the frame-id table, stock entries + new ones, goes to T (behind the character's
 * sec2 in its work area); the blob's table offset (blob + 8, read by the game at run time) points there; patched
 * records get their new frame index (byte 0 + bits 12-14 of the second half-word). */
static void anim_patch(u8 *F, const u32 *a, u32 *T)
{
    u8 *blob = F + a[1];
    u32 *bh = (u32 *)blob, nf0 = a[2], nf = a[3], m = a[4], i;
    const u8 *old = blob + bh[2];                /* the stock table is only 2-byte aligned (the game reads it by bytes) */
    const u32 *nw = a + 5, *rp = a + 5 + (nf - nf0);
    if (a[0] != 0x3138414du || (bh[3] - bh[2]) >> 2 != nf0) return;      /* 'MA81', table of the expected size */
    for (i = 0; i < nf0; i++, old += 4) T[i] = old[0] | old[1] << 8 | old[2] << 16 | old[3] << 24;
    for (; i < nf; i++) T[i] = nw[i - nf0];
    bh[2] = (u32)T - (u32)blob;
    for (i = 0; i < m; i++, rp += 2) {
        u8 *r = F + rp[0];
        u16 w1 = r[2] | r[3] << 8;
        w1 = (w1 & 0x8fffu) | ((rp[1] >> 8) & 7) << 12;
        r[0] = rp[1] & 0xff; r[2] = w1 & 0xff; r[3] = w1 >> 8;
    }
}

static int load8(signed char *list)
{
    int s, k, slot[4];
    u32 busy = 0, poolend;
    if (!tl_dbg[12] || H->magic != MAGIC || NCS > NCSMAX) {     /* first battle of this boot, or no header: empty cache */
        for (k = 0; k < NCS; k++) H->s[k].c = 0;
        H->tick = 0;
        H->magic = MAGIC;
        tl_dbg[12] = 1;
    }
    H->tick++;
    H->hits = H->reads = 0;
    for (s = 0; s < 4; s++) {
        if (list[s] < 0) continue;
        slot[s] = fill(list[s], s & 1, busy);
        busy |= 1u << slot[s];
    }
    for (s = 0; s < 4; s++) {
        const struct chr *h;
        u8 *F, *C;
        u32 *hdr, p;
        int c = list[s];
        if (c < 0) continue;
        h = &tl_dir.c[filechar(c)];
        C = slotp(slot[s]);
        p = place(WORK + s * WA, h);
        F = (u8 *)(p - 0x1c);
        hdr = (u32 *)(C + C_A0);                                /* u32 3, (off, size) x 3 */
        wcopy((u32 *)F, (u32 *)(C + C_A0), hdr[3] + hdr[4]);
        reloc((u32 *)F, (const u16 *)(C + C_A0 + ((h->a0size + 3) & ~3u)), (int)(p - SLOT0_BASE));
        if (H->s[slot[s]].ap8n)
            anim_patch(F, (const u32 *)(C + C_AP8), (u32 *)(((u32)F + hdr[3] + hdr[4] + 7) & ~3u));
        flushcache();
        ((init_t)(INIT_TAB[c] + (p - SLOT0_BASE)))((int)(p - SLOT0_BASE), SLOT0_BASE);
        if (s & 1)
            REG(s + 8, F + hdr[3], 0);
        else
            STASH(s + 8, F + hdr[3], 4, hdr[4], snd_stash(s, SPU_STASH[s]));
        if (!snd_load(s, c, C + C_A0 + hdr[5], SND_SCRATCH)) {      /* the cache copy stays pristine (level files: scratch) */
            if (!(s & 1)) SND(s + 1, C + C_A0 + hdr[5], hdr[6]);
            else if (H->s[slot[s]].hlpn) SND(s + 1, C + C_HLP, H->s[slot[s]].hlpn);
        }
        REG(s, C + C_DSP, 0);
        if (c == 0) KANJI((void *)KANJI_AT);
    }
    /* the GPU primitive pool back to its stock size (heapcap capped it for the 2 MB area, unused in this mode) */
    poolend = *(u32 *)(tl_dbg + 8);
    if (poolend - POOL_CAP >= 0x80094800u && poolend < POOL_END) {
        POOLRESET();
        POOLINIT((void *)(poolend - POOL_CAP), POOL_END - (poolend - POOL_CAP));
        *(u32 *)(tl_dbg + 8) = POOL_END;
    }
    *(u32 *)(tl_dbg + 4) = UPEND;
    tl_dbg[1] = tl_dbg[2] = (NT - 1) * 0x11;                   /* stock RLE everywhere (speed meter: 9) */
    tl_dbg[0] = 1;
    return 1;
}

int ap8_main(signed char *list)
{
    int s;
    if (!tl_dbg[3]) {                           /* normally done at the first main-menu frame (ap8menu.S) */
        tl_dbg[3] = probe() ? 2 : 1;
        tl_dbg[13] = tl_dbg[15] = tl_dbg[3] == 2;
    }
    if (tl_dbg[3] != 2) return tl_main(list);
    /* the same fights as the 2 MB loader: arcade / versus with a human (else tl_main declines: stock) */
    if (tl_dir.magic != 0x4c474154 || *(signed char *)0x800250ac < 0 || *(signed char *)0x800250ac > 2 || !*(u8 *)0x80070a91)
        return tl_main(list);
    for (s = 0; s < 4; s++)
        if (list[s] > 0x19) return tl_main(list);
    tl_dbg[1] = tl_dbg[2] = 0;
    snd_reset();
    snd_plan(list);
    return load8(list);
}
