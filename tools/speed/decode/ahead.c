/* Decode-ahead predictor (work/speed/AHEAD_API.md; reference model: tools/speed/decode/ahead_ref.py).
 * Pure: reads game state only.  ahead_begin() starts a window; ahead_next() yields one tile descriptor per call,
 * bounded by `budget` work units; ahead_cost() estimates a tile's decode time in hblank lines.
 * Order: tick 1 (incl. the engine's own pre-decode targets: sec3 record word C of the current frame), then 2, 3;
 * inside a tick the frames by decode bytes (largest first, stable), inside a frame the parts in sec0 order; a key
 * is yielded once per window.  Character sets only (0..0x12): the other sets (effects 0x26, stage 0x2b ...) are
 * mostly not decoded at their frame changes (measured), and set 0x37 is CD-streamed. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

struct ahead_tile { u32 src; u16 tile; u8 set, ticks, e8, e9, fmt, prio; u32 key; };
struct ahead_cur { u32 w[8]; };

#define U8(a)   (*(const u8 *)(a))
#define U16(a)  (*(const u16 *)(a))
#define U32(a)  (*(const u32 *)(a))
#define SEC0    0x8006a358u
#define SEC1    0x8005ce80u
#define SEC2    0x8005c830u
#define SEC3    0x80069de0u
#define OK(p)   ((u32)(p) - 0x80010000u < 0x1f0000u)
#define OK4(p)  (OK(p) && !((u32)(p) & 3))      /* every pointer read with lw must be aligned (no fault on stale data) */
#define OK2(p)  (OK(p) && !((u32)(p) & 1))
#define U32H(a) (U16(a) | U16((a) + 2) << 16)       /* script data is only 2-byte aligned: read words as halves */
#define U16B(a) (U8(a) | U8((a) + 1) << 8)          /* sec3 records are byte-addressed (0x80059e60 reads them with lbu) */
#define MAXOBJ  32
#define MAXCAND 32
#define MAXREC  64
#define MAXPART 64
#define NSEEN   32

/* work area (static: one window at a time) */
static u32 cand_fid[MAXCAND];
static u32 cand_size[MAXCAND];
static u8  cand_set[MAXCAND];
static u32 objs[MAXOBJ];
static u32 seen[NSEEN];
static int nobj, ncand, nseen;

/* cursor fields */
#define C_STATE  w[0]   /* 0 objects, 1 collect tick, 2 yield, 3 done */
#define C_TICK   w[1]   /* 1..horizon */
#define C_HOR    w[2]
#define C_I      w[3]   /* object / candidate index */
#define C_PART   w[4]   /* part pointer inside the current candidate frame (0 = start) */
#define C_NP     w[5]   /* parts yielded of the current frame (MAXPART at most, as frame_bytes) */

static const u32 lists[6][3] = {   /* count address, entry 0 address, stride (negative) */
    { 0x8004c2ac, 0x80043c80, 8 }, { 0x800420cc, 0x8004c564, 4 },
    { 0x80041de4, 0x800426bc, 4 }, { 0x80041de6, 0x8004272c, 4 },
    { 0x80041de8, 0x8004276c, 4 }, { 0x80041e10, 0x800427d4, 4 } };

void ahead_begin(struct ahead_cur *c, int horizon)
{
    c->C_STATE = 0; c->C_TICK = 1; c->C_HOR = horizon < 1 ? 1 : horizon > 3 ? 3 : horizon; c->C_I = 0; c->C_PART = 0;
}

static void collect_objects(void)
{
    int l, k, j;
    nobj = 0; nseen = 0;
    for (l = 0; l < 6; l++) {
        int n = (s16)U16(lists[l][0]);
        if (n > 64) n = 64;
        for (k = 0; k < n; k++) {
            u32 o = U32(lists[l][1] - lists[l][2] * k);
            if (!OK4(o)) continue;
            for (j = 0; j < nobj; j++) if (objs[j] == o) break;
            if (j == nobj && nobj < MAXOBJ) objs[nobj++] = o;
        }
    }
}

/* frame after `ticks` ticks of the object's script; 0xffffffff = unknown */
static u32 script(u32 obj, int ticks)
{
    u32 nxt = U32(obj + 0x38), base = U32(obj + 0x44), fid = U32(obj + 0x40);
    int t = U16(obj + 0x48), k, r;
    for (k = 0; k < ticks; k++) {
        if (--t > 0) continue;
        if (!OK2(nxt) || !OK2(base)) return 0xffffffffu;
        for (r = 0; r < MAXREC; r++) {
            u32 r0 = U16(nxt), r2 = U16(nxt + 2), s, fa = base + U32H(base + 8) + 4 * (r2 & 0xfff), f;
            if (!OK2(fa)) return 0xffffffffu;
            f = U32H(fa);
            s = (r2 & 0x8000) | (r0 >> 9);
            nxt += 4;
            if (s == 0) continue;
            if (s & 0x8000) {
                nxt = base + U32H(base + 4) + U32H(nxt);
                if (!OK2(nxt)) return 0xffffffffu;
            }
            if (s & 0x7fff) { fid = f; t = s & 0x7fff; break; }
        }
        if (r == MAXREC) return 0xffffffffu;
    }
    return fid;
}

static int part_size(u32 b2)
{
    u32 xm = (b2 >> 4) & 3, ym = b2 >> 6;
    return (xm == 3 && ym == 3) ? 7 : (xm == 3 || ym == 3) ? 6 : 5;
}

static u32 frame_bytes(u32 set, u32 fid)
{
    u32 s0 = U32(SEC0 + 4 * set), s1 = U32(SEC1 + 4 * set), p, n = 0;
    int k;
    if (!OK(s0) || !OK4(s1) || (fid & 0xffff) == 0xffff || (fid >> 16) == 0xffff) return 0;
    p = s0 + (fid & 0xffff);
    for (k = 0; k < MAXPART; k++) {
        u32 fl = U8(p), tile = (U8(p + 1) | U8(p + 2) << 8) & 0xfff, w = U32(s1 + 4 * tile);
        n += ((w >> 24 & 15) + 1) * 8 * ((w >> 28) + 1) * 16;
        p += part_size(U8(p + 2));
        if (fl & 0x80) break;
    }
    return n;
}

static int uploads(u32 s3, u32 fid)
{
    u32 a = U16B(s3 + (fid >> 16));
    return a != 0 && U16B(s3 + a) != 0xffff;
}

static void add_cand(u32 set, u32 fid)
{
    u32 n = frame_bytes(set, fid);
    int i;
    if (!n || ncand >= MAXCAND) return;
    for (i = ncand; i > 0 && cand_size[i - 1] < n; i--) {       /* stable: equal sizes keep insertion order */
        cand_size[i] = cand_size[i - 1]; cand_fid[i] = cand_fid[i - 1]; cand_set[i] = cand_set[i - 1];
    }
    cand_size[i] = n; cand_fid[i] = fid; cand_set[i] = set; ncand++;
}

/* candidates of one object for tick k (1-based) */
static void object_tick(u32 obj, int k)
{
    u32 set = U8(obj + 0x6c), node = U32(obj + 0x70), s3, cur, pre, drawn, f, prev;
    if (set > 0x12 || !OK4(node) || U8(node + 0xf) >= 2) return;
    s3 = U32(SEC3 + 4 * set);
    if (!OK(s3)) return;
    cur = U32(obj + 0x40);
    pre = U8(node + 0xa) == 1 ? U16(node + 0x1e) : 0x10000;
    drawn = U16(node + 0x20);
    if (k == 1 && (cur & 0xffff) != 0xffff && (cur >> 16) != 0xffff && U16B(s3 + (cur >> 16)) != 0) {
        u32 cc = U16B(s3 + (cur >> 16) + 4);
        if (cc != 0xffff && cc != (cur & 0xffff) && cc != pre && cc != drawn) add_cand(set, (cur & 0xffff0000) | cc);
    }
    prev = k == 1 ? cur : script(obj, k - 1);
    if (prev == 0xffffffffu) return;
    f = script(obj, k);
    if (f == 0xffffffffu) return;
    if (f != prev && (f & 0xffff) != pre && (f & 0xffff) != drawn && uploads(s3, f)) add_cand(set, f);
}

int ahead_next(struct ahead_cur *c, struct ahead_tile *out, int budget)
{
    while (budget > 0) {
        switch (c->C_STATE) {
        case 0:
            collect_objects();
            c->C_STATE = 1; c->C_I = 0; ncand = 0; budget -= 4;
            break;
        case 1:                                     /* collect: one object per unit */
            if ((int)c->C_I < nobj) { object_tick(objs[c->C_I++], c->C_TICK); budget--; break; }
            c->C_STATE = 2; c->C_I = 0; c->C_PART = 0;
            break;
        case 2: {                                   /* yield: one part per unit */
            u32 set, fid, s0, s1, s2, s3, p, fl, tile, w, key;
            int i;
            if ((int)c->C_I >= ncand) {
                if (++c->C_TICK > c->C_HOR) { c->C_STATE = 3; return 0; }
                c->C_STATE = 1; c->C_I = 0; ncand = 0;
                break;
            }
            set = cand_set[c->C_I]; fid = cand_fid[c->C_I];
            s0 = U32(SEC0 + 4 * set); s1 = U32(SEC1 + 4 * set); s2 = U32(SEC2 + 4 * set); s3 = U32(SEC3 + 4 * set);
            /* every predicted tile: index inside the set's sec1 table, stream inside its sec2 (sec2 < sec3, contiguous) */
            if (!c->C_PART) { p = s0 + (fid & 0xffff); c->C_NP = 0; } else p = c->C_PART;
            fl = U8(p); tile = (U8(p + 1) | U8(p + 2) << 8) & 0xfff;
            c->C_PART = ((fl & 0x80) || ++c->C_NP == MAXPART) ? 0 : p + part_size(U8(p + 2));
            if (!c->C_PART) c->C_I++;
            budget--;
            w = s1 + 4 * tile < s2 ? U32(s1 + 4 * tile) : 0xffffffff;        /* tile index inside the sec1 table */
            if (s2 + (w & 0x3fffff) >= s3) break;                    /* stream inside sec2 (e9 wrap: vc_prefetch) */
            key = (set << 24) | (w & 0x3fffff);
            for (i = 0; i < nseen; i++) if (seen[i] == key) break;
            if (i < nseen || !OK(s2)) break;
            if (nseen < NSEEN) seen[nseen++] = key;
            out->src = s2 + (w & 0x3fffff); out->tile = tile; out->set = set; out->ticks = c->C_TICK;
            out->e8 = ((w >> 24 & 15) + 1) * 8; out->e9 = ((w >> 28) + 1) * 16; out->fmt = 0; out->prio = 0; out->key = key;
            return 1;
        }
        default:
            return 0;
        }
    }
    return -1;
}

/* decode time in hblank lines (2152 cycles; /2048 here: a slight over-estimate) at the measured cycles per byte:
 * XVH1 (strong tier) 82, otherwise 26 (XVM1; stock RLE tiles cost less: 8) */
int ahead_cost(const struct ahead_tile *t)
{
    u32 s2 = U32(SEC2 + 4 * t->set), c = 26;
    if (U32(s2) == 0x31485658u) c = 82;
    return ((t->e8 * t->e9 * c) >> 11) + 1;
}

#ifdef SECTOR
/* ---- the per-battle predictor area (tools/speed/decode/ahead_sector.py): read with the directory sector to
 * 0x801fe804 (header in ahead_head.S).  ahook(deadline, late) is called through the resident check stub (decoder
 * chunk R) from the frame worker's idle hook EBV+12: a0 = root counter 1 (hblank) deadline, a1 = vblanks passed. */
#define RCNT1   (*(volatile u16 *)0x1f801110)
extern u32 ah_vc[2];                /* vc_lookup, vc_prefetch (0 = none: predictions are discarded) */
extern u32 ah_sum, ah_state;        /* expected checksum of the area, 0 unchecked / 1 good / 2 bad */
extern u32 ah_start[], ah_end[];
typedef int (*vc_lookup_fn)(u32 key);
typedef int (*vc_prefetch_fn)(const struct ahead_tile *t);

void ahook(u32 deadline, int late)
{
    static struct ahead_cur cur;
    static struct ahead_tile t;
    int r;
    if (ah_state != 1) {
        u32 *p, s = 0;
        if (ah_state) return;
        for (p = ah_start; p < ah_end; p++) if (p != &ah_sum && p != &ah_state) s += *p;
        ah_state = s == ah_sum ? 1 : 2;
        return;                                     /* (the check takes this frame's slack) */
    }
    if (late) return;
    ahead_begin(&cur, 3);
    for (;;) {
        if ((s16)(deadline - RCNT1) < 3) return;
        r = ahead_next(&cur, &t, 8);
        if (r == 0) return;
        if (r < 0 || !ah_vc[0] || !ah_vc[1]) continue;
        if (((vc_lookup_fn)ah_vc[0])(t.key)) continue;
        if ((s16)(deadline - RCNT1) < ahead_cost(&t) + 3) return;
        ((vc_prefetch_fn)ah_vc[1])(&t);
    }
}
#endif
