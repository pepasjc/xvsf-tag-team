/* 8 MB "arcade frames" (mkap8.py --frames8; included by ap8m.c with -DAP8FR, never in a 2 MB path).
 *
 * Per character one disc file PLxx.R8 (tools/ap/build8.py, built from the user's arcade ROM at disc build time):
 * [header][record patches][frame-id table: stock + new ids][sprite file: the stock DSP + appended tiles / frames].
 * It replaces the stock PLxx_10.A0 cache of the 1.0 module: one arena of variable-size records in the upper RAM the
 * voice stores leave free ([0x80220000, 0x80600000) and [0x80740000, 0x807d0000)), each record exactly its file
 * (2 KB steps), LRU over the records the current battle does not use; the same character twice (mirror) shares one
 * record (the game only reads the sprite file and the table).
 *
 *   ap8_modmain -> r8_prefetch(list): every character of the battle resident before anything is placed (a full arena
 *                  is emptied and refilled in slot order: the four largest records fit together, mkap8.py checks it)
 *   ap8_uncut(c, F) -> r8_patch: the code item's animation blob (F + word 7) gets the record's table (blob + 8 = table
 *                  - blob, read by the game at run time) and the patched records their new frame index (byte 0 + bits
 *                  12-14 of the second half-word).  Every patched record and the stock table are checked first: any
 *                  difference -> nothing patched (stock frames; the restored sprite file starts with the stock one)
 *   ap8_a0(idx) -> the record: word 3 = the sprite file's offset, as the A0 header word the loader reads (D = A + ah[3])
 */
#define R8H      0x807df000u                     /* arena header (the 1.0 A0 cache header page; unused with --frames8) */
#define R8HMAGIC 0x48523852u                     /* 'R8RH' */
#define R8FMAGIC 0x31463852u                     /* 'R8F1' */
#define NR8      12
#define R8AS     0x20                            /* record key: character c (01-16) or R8AS + assist id (DAxx.R8) */
#define AS_BITS  (*(volatile u8 *)0x8007b744u)    /* assists chosen (bit per side), ids * 4 at 0x8007b8d8 (tagload.c) */
#define AS_ID(q) (((volatile short *)0x8007b8d8u)[q] >> 2)
#define R8OFF    0x807dff40u                     /* ARCADE FRAMES byte (mkap8 R8BYTE): 0 = ON (boot stub), else OFF */
#define SPARE8   0x1ab                           /* file table entry used for reads (entry8.S uses it the same way) */

struct r8f { u32 msf, size; };
struct r8dir { u32 magic, on; struct r8f f[0x17]; struct r8f a[0x16]; };   /* f: characters 01-16, a: assists 00-15 */
struct r8dir r8d __attribute__((section(".dir8m"))) = { 0x52443852u };        /* 'R8DR', filled by mkap8.py */

struct r8e { u32 c, msf, size, base, sum, used; };
struct r8h { u32 magic, tick, hits, reads, fails, patched, nrec; struct r8e e[NR8]; };

static const u32 r8lo[2] = { 0x80220000u, 0x80740000u }, r8hi[2] = { 0x80600000u, 0x807d0000u };
static u32 r8busy, r8chk;                        /* records of this battle / sum-checked (module .bss: fresh every battle) */

static const struct r8f *r8f_of(int c)            /* directory entry of record key c, 0: none */
{
    const struct r8f *f = c >= R8AS && c < R8AS + 0x16 ? &r8d.a[c - R8AS] : c >= 1 && c <= 0x16 ? &r8d.f[c] : 0;
    return f && r8d.on && f->size ? f : 0;
}

static u32 r8sum(const u32 *p, u32 n) { u32 s = 0x5a17u; n >>= 2; while (n--) s += *p++; return s; }
static u32 r8r2k(u32 x) { return (x + 2047) & ~2047u; }

static void r8read(u32 msf, u32 size, void *P)
{
    u32 a = FTAB[SPARE8 * 2], b = FTAB[SPARE8 * 2 + 1];
    FTAB[SPARE8 * 2] = msf; FTAB[SPARE8 * 2 + 1] = size;
    RD(SPARE8, P);
    FTAB[SPARE8 * 2] = a; FTAB[SPARE8 * 2 + 1] = b;
}

static struct r8h *r8hdr(void)
{
    struct r8h *H = (struct r8h *)R8H;
    if (H->magic != R8HMAGIC) {
        u32 *w = (u32 *)H; int k;
        for (k = 0; k < (int)(sizeof *H / 4); k++) w[k] = 0;
        H->magic = R8HMAGIC;
    }
    return H;
}

static int r8fits(struct r8h *H, u32 a, u32 size, int self)
{
    int j, ok = 0;
    for (j = 0; j < 2; j++) if (a >= r8lo[j] && a + size <= r8hi[j]) ok = 1;
    if (!ok) return 0;
    for (j = 0; j < NR8; j++) {
        const struct r8e *o = &H->e[j];
        if (j != self && o->c && a < o->base + r8r2k(o->size) && a + size > o->base) return 0;
    }
    return 1;
}

static u32 r8gap(struct r8h *H, u32 size, int self)
{
    int j, r;
    for (r = 0; r < 2; r++) if (r8fits(H, r8lo[r], size, self)) return r8lo[r];
    for (j = 0; j < NR8; j++) {
        const struct r8e *o = &H->e[j];
        if (j != self && o->c && r8fits(H, o->base + r8r2k(o->size), size, self)) return o->base + r8r2k(o->size);
    }
    return 0;
}

/* record of character c resident (read when missing / changed); -1: no room without evicting this battle's records */
static int r8fill(struct r8h *H, int c)
{
    const struct r8f *f;
    struct r8e *e;
    int k, best = -1;
    u32 a, sz;
    if (!(f = r8f_of(c))) return -1;
    sz = r8r2k(f->size);
    for (k = 0; k < NR8; k++) {
        e = &H->e[k];
        if (e->c == (u32)c + 1 && e->msf == f->msf && e->size == f->size) {
            if (r8chk >> k & 1) ;                    /* checked this battle (mirror) */
            else if (r8sum((u32 *)e->base, e->size) != e->sum) {     /* changed (game used the RAM?): read again */
                r8read(f->msf, f->size, (void *)e->base); H->reads++;
                e->sum = r8sum((u32 *)e->base, e->size);
            } else H->hits++;
            r8chk |= 1u << k;
            e->used = H->tick; r8busy |= 1u << k;
            return k;
        }
    }
    for (k = 0; k < NR8; k++) {
        if (r8busy >> k & 1) continue;
        if (!H->e[k].c) { best = k; break; }
        if (best < 0 || H->e[k].used < H->e[best].used) best = k;
    }
    if (best < 0) return -1;
    e = &H->e[best];
    e->c = 0;
    while (!(a = r8gap(H, sz, best))) {          /* evict the least recently used record not in this battle */
        int j, v = -1;
        for (j = 0; j < NR8; j++)
            if (j != best && H->e[j].c && !(r8busy >> j & 1) && (v < 0 || H->e[j].used < H->e[v].used)) v = j;
        if (v < 0) return -1;
        H->e[v].c = 0;
    }
    e->base = a; e->msf = f->msf; e->size = f->size;
    r8read(f->msf, f->size, (void *)a); H->reads++;
    e->sum = r8sum((u32 *)a, f->size);
    e->c = c + 1; e->used = H->tick;
    r8busy |= 1u << best; r8chk |= 1u << best;
    return best;
}

#ifdef AP8FR_LAZY
static signed char *r8list;                      /* (bisect) the battle's list: prefetch at the first record use (in tl_main) */
static void r8_prefetch(signed char *list0);
#endif
static int r8find(int c)
{
    struct r8h *H = r8hdr();
    int k;
#ifdef AP8FR_LAZY
    if (r8list) { signed char *l = r8list; r8list = 0; r8_prefetch(l); }
#endif
    for (k = 0; k < NR8; k++) if ((r8busy >> k & 1) && H->e[k].c == (u32)c + 1) return k;
    return r8fill(H, c);
}

static void r8_prefetch(signed char *list0)
{
    struct r8h *H = r8hdr();
    int s, k, list[6];
    for (s = 0; s < 4; s++) list[s] = list0[s];
    for (s = 0; s < 2; s++) list[4 + s] = (AS_BITS >> s & 1) && AS_ID(s) >= 0 && AS_ID(s) < 0x16 ? R8AS + AS_ID(s) : -1;
    H->tick++;
    H->hits = H->reads = H->fails = H->patched = 0;
    for (s = 0; s < 6; s++) {                       /* pass 1: records already resident are this battle's (no eviction) */
        int c = list[s];
        const struct r8f *f = r8f_of(c);
        if (!f) continue;
        for (k = 0; k < NR8; k++)
            if (H->e[k].c == (u32)c + 1 && H->e[k].msf == f->msf && H->e[k].size == f->size) r8busy |= 1u << k;
    }
    for (s = 0; s < 6; s++) {                       /* pass 2: fill (resident: sum check / hit) */
        if (!r8f_of(list[s])) continue;
        if (r8fill(H, list[s]) < 0) {               /* no room: empty the arena, fill in slot order */
            for (k = 0; k < NR8; k++) H->e[k].c = 0;
            r8busy = r8chk = 0;
            for (s = 0; s < 6; s++) if (r8f_of(list[s])) r8fill(H, list[s]);
            break;
        }
    }
    for (k = 0, H->nrec = 0; k < NR8; k++) H->nrec += !!H->e[k].c;
}

static const u32 *r8_apply(int c, u8 *F, int tabchk);
static void r8_patch(int c, u8 *F) { r8_apply(c, F, 1); }

/* assist a's code item P (tagload.c, AP8FR, before relocation / init): the record's stock frame table (also undoes the
 * 2 MB --ascut words: no table compare) + restored records; -> the record (sprite file at word 3) or 0 (tier data) */
#ifdef AP8FR_NOAS
u8 *ap8_aspatch(int a, u8 *P) { (void)a; (void)P; return 0; }      /* (bisect build) assists: stock 2 MB tier */
#else
u8 *ap8_aspatch(int a, u8 *P) { return (u8 *)r8_apply(R8AS + a, P, 0); }
#endif

static const u32 *r8_apply(int c, u8 *F, int tabchk)
{
    struct r8h *H = r8hdr();
    int k = r8find(c);
    const u32 *R;
    u8 *blob;
    u32 *bh, *T, i, nf0, m;
    const u8 *old;
    const u8 *p;
    if (k < 0) { H->fails++; return 0; }
    R = (const u32 *)H->e[k].base;
    if (R[0] != R8FMAGIC || R[1] != (c >= R8AS ? 0x100u + c - R8AS : (u32)c)) { H->fails++; return 0; }
#ifdef AP8FR_NOPATCH
    return c >= R8AS ? 0 : R;                    /* (bisect build) no table / record patches */
#endif
    if (*(volatile u8 *)R8OFF) return c >= R8AS ? 0 : R;     /* EX OPTIONS ARCADE FRAMES OFF: stock frames (mvc_8_1_2) */
    blob = F + R[7]; bh = (u32 *)blob; nf0 = R[6]; m = R[8];
    T = (u32 *)((u8 *)R + R[4]);
    if (bh[0] != 0x10 || (bh[3] - bh[2]) >> 2 != nf0) { H->fails++; return 0; }
    old = blob + bh[2];                          /* stock table: compare by bytes (only 2-byte aligned) */
    for (i = 0; tabchk && i < nf0; i++, old += 4)
        if ((old[0] | old[1] << 8 | old[2] << 16 | (u32)old[3] << 24) != T[i]) { H->fails++; return 0; }
    for (i = 0, p = (const u8 *)R + R[9]; i < m; i++, p += 8) {
        const u8 *r = F + (p[0] | p[1] << 8 | p[2] << 16);
        u32 cur = r[0] | ((r[3] >> 4) & 7) << 8;
        if (cur != (u32)(p[6] | p[7] << 8)) { H->fails++; return 0; }
    }
    bh[2] = (u32)T - (u32)blob;
    for (i = 0, p = (const u8 *)R + R[9]; i < m; i++, p += 8) {
        u8 *r = F + (p[0] | p[1] << 8 | p[2] << 16);
        u32 nw = p[4] | p[5] << 8;
        r[0] = nw & 0xff;
        r[3] = (r[3] & 0x8f) | ((nw >> 8) & 7) << 4;
    }
    H->patched++;
    return R;
}

/* stock_a0(c) of tagload.c inverted: PLxx_10.A0 file index -> character */
static int r8char(int idx)
{
    int c;
    for (c = 1; c <= 0x16; c++) {
        int k = 3 * (c - 1) + 10 + (c > 0x10 ? 5 : 0);
        if (k + (c == 0x10 ? 7 : 2) - 1 == idx) return c;
    }
    return -1;
}

u8 *ap8_a0(int idx)
{
    int k = r8find(r8char(idx));
    if (k < 0) {                                 /* cannot happen (mkap8.py checks the sizes): a stopped game is */
        for (;;) ;                               /* better than a sprite set from another character */
    }
    return (u8 *)((struct r8h *)R8H)->e[k].base;
}
