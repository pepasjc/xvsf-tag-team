/* 8 MB battle loader module for the X-Men vs. Street Fighter tag hack (SLUS-00627), "ap8" build.
 *
 * Read by the boot stub (ap8boot.c, in the EXE) to MOD = 0x80200000 once per battle load, only after
 * the stub has PROVEN that there is distinct RAM above 2 MB.  On a 2 MB machine none of this is ever
 * read or run: the stub jumps to the normal loader of the 2 MB hack (same disc).
 *
 * Memory above 2 MB:
 *      0x80200000  this module (7 sectors: vectors, file tables, code; magic + checksum at the end)
 *      0x80203800  struct state: resident-block records + debug info (survives between battles)
 *      0x80203c00  undo list of the restored effects (SPEC 17.5)
 *      0x80205000  effects file, shared-slot tables, then the arena up to ARENA_END: one block per loaded character
 *                      [code file = P0 overlay + relocation table][sprite file][PLxx.AP8][PLxx.AD8]
 *                  each part starts on a 2048-byte step (a CD read spills up to the end of its last sector)
 * Below 2 MB, as in the 2 MB hack but only the code:  heap | pool (POOL) | relocated overlay copies, 8-aligned.
 *
 * Per battle (hook): the pool, then for every listed character (ascending id = disc order)
 *      - a block from the previous battles is reused when it is the same character with the same files
 *        (disc positions and sizes) and its checksum (32-bit sum of all words of the block) still holds;
 *        otherwise the three files are read.  First fit; when a needed block does not fit between the kept
 *        ones, everything is dropped and read again (four blocks always fit an empty arena).
 *      - the code is copied below 2 MB, relocated (same table format as tools/tagload), the AP8 animation
 *        patch is applied to that copy (work/ap/SPEC.md section 3; the frame-id table is used in place, in the
 *        block), FlushCache, the character's init routine, then the four sprite section pointers are stored.
 * All sprite files are stock RLE (restored or original); the effects file is the stock RLE one.
 *
 * Boss: only the configuration the 2 MB hack runs on its new loader (boss = P2 main, normal player side) is
 * taken; tl_dbg.dropped = 0xF9 then (bossfin() skips the extra file).  Any other boss team: eff() declines and
 * the normal 2 MB code runs (it only uses memory below 2 MB, so it also works here).
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define FTABLE      0x8003d91cu
#define FT_SIZE(i)  (((struct xent *)(FTABLE + 8 * (i)))->size)
#define POOLSIZE    (*(u32 *)0x8004382c)
#define IDS         ((s16 *)0x800423b2)
#define INITTAB     ((u32 *)0x8003d83c)
#define LOADFILE    ((int (*)(int, u8 *))0x8002de3c)
#define SETLOAD     ((u32 (*)(int, u32))0x80054054)
#define POOLINIT    ((void (*)(int, int, int, u8 *, u32))0x80054fe4)
#define SEC0        ((u32 *)0x8006a358)
#define SEC1        ((u32 *)0x8005ce80)
#define SEC2        ((u32 *)0x8005c830)
#define SEC3        ((u32 *)0x80069de0)
#define LINKBASE    0x800d1000u
#define POOL        19296u
#define FAKE(p)     ((int)((u32)(p) - FTABLE) >> 3)
#define STATE       ((struct state *)0x80203800)
#define SLOTPTR     ((u32 *)0x8005c65c)         /* per sprite set: its shared-slot table, 8 bytes per slot, ends with 0xffff */
/* fixed areas above 2 MB (addresses from the disc builder, -D):
 *   EFFAREA   .. SLOTAREA   the effects sprite file (set 0x26, SP_EFF1), resident like a character block
 *   SLOTAREA  .. ARENA      extended shared-VRAM-slot tables (see slots()), rebuilt at every battle load
 *   ARENA     .. ARENA_END  character blocks
 *   SCRATCH = ARENA_END     battle load: the packed stream being decoded.  SELECT SCREEN: its sprite file (set 0x27,
 *                           SP_SEL0) lives here, up to the top of RAM - the two uses never overlap in time, and no
 *                           resident block is touched
 *   LT_ADDR, DT_ADDR        decode tables (inside the top of the scratch/select area, battle load only) */
#define EFFAREA     0x80205000u
#define SELAREA     SCRATCH
#define SPRLOAD     ((u32 (*)(int, u32))0x80053f78)
#define D130        (*(u32 *)0x8003d130)        /* base the game's sprite loaders add to their offset argument */
/* ARENA, ARENA_END, SLOTAREA depend on the content (sizes of the effects file and of the largest packed block): the
 * disc builder writes them into the module table, so one compiled module serves any content.
 * LT_ADDR / DT_ADDR: the two decode tables (64 KB each) at the top of RAM. */
#define ARENA       (T.arena)
#define ARENA_END   (T.arena_end)
#define SLOTAREA    (T.slotarea)
#define LT_ADDR     0x807e0000u
#define DT_ADDR     0x807f0000u
#define SCRATCH     ARENA_END
#define CDCONTROL   ((int (*)(int, u8 *, u8 *))0x800128f0)
#define CDSYNC      ((int (*)(int, u8 *))0x80012880)
#define CDREAD      ((int (*)(int, u8 *, int))0x800156a0)
#define CDREADSYNC  ((int (*)(int, u8 *))0x800157a4)           /* (1, result): sectors still to come, 0 done, -1 error/timeout */
#define XASTOP      ((void (*)(void))0x8004f1c8)
#define MKLOC       ((void (*)(u8 *, int))0x8002dcec)          /* file-table entry -> CdlLOC + size */
#define ST_MAGIC    0x38504158u         /* "XAP8" */
#define R(n)        (((n) + 2047) & ~2047u)

struct xent { u32 msf; u32 size; };
struct tab { struct xent code[19], spr[19], ap8[19], ad8[19], eff, sel0, selap, sel2, selap2, effr, effae, pack[19]; u32 psum[19]; u32 slotstock[39]; u16 slots[20]; u32 arena, arena_end, slotarea; u32 sel2sum, selap2sum, effrsum, effaesum;
             u32 pad0; struct xent auxp; u32 auxpsum, auxarea; };   /* auxp at 4 mod 8 like every file entry */
/* effr + effae: restored effects file (set 0x26) and EFF1.AE8 (work/ap/SPEC.md section 17), with their word sums */
/* sel0 + selap: restored select-screen sprite file and SELECT.AP8 (work/ap/SPEC.md section 10); size 0 = none
 * sel2 + selap2: second select-screen sprite file (set 0x39) and SELECT2.AP8 (section 15), with their word sums */
/* slotstock: the game's own table pointer of every sprite set 0..38; slots: entries of an extended table per character
 * (and [19]: effects set 0x26), 0 = keep the game's; arena, arena_end, slotarea: the memory map above 2 MB (see below) */   /* sel0.size 0 = the game's own SP_SEL0 */
#define T_SEL0 (&T.sel0)   /* pack: the whole block, raw deflate; psum: sum of its words */
extern const struct tab T;              /* filled by the disc builder; at 4 mod 8 = reachable as fake file indices */
struct blk { int c; u32 addr, size, sum, id, used; };   /* id: file identity (disc positions, sizes, sum); used: battle number of the last use */
#define NBLK 8                          /* four in use + blocks kept from earlier battles while there is room */
struct state {
    u32 magic;
    struct blk b[NBLK];
    /* debug, per battle */
    u32 battles;                        /* battle loads done by this module */
    u8 slot[4];                         /* per list slot: 0 not loaded, 1 read from disc, 2 reused; | 0x10 AP8 applied, | 0x20 AP8 present but refused,
                                           | 0x40 packed stream failed (error code in perr): the plain files were read instead,
                                           | 0x80 AD8 applied, | 0x08 AD8 present but refused */
    u8 why[NBLK];                       /* per block record: 0 in use / empty, 1 not needed now but kept, 2 file identity, 3 checksum, 4 evicted for space */
    u32 addr[4];                        /* block address per list slot */
    u32 low[4];                         /* overlay copy address per list slot */
    u32 sumtime;                        /* words summed for validation this battle */
    u32 perr;                           /* last packed-stream failure: 1..14 decoder, 0x100 read, 0x200 size, 0x300 checksum */
    u32 waits, polls;                   /* decoder waits for data / CdReadSync polls this battle: >0 = the decoder keeps up with the drive */
    u32 effid, effsum;                  /* effects file in EFFAREA: identity (0 = none) and word sum */
    u32 effhow, sels;                   /* effects this battle: 1 stock read, 2 stock reused, 3 RESTORED read, 4 RESTORED reused; select-screen loads */
    u32 slotcur;                        /* next free byte of the slot-table area */
    u32 selhow;                         /* last select screen: 1 stock file above 2 MB, 2 restored file + SELECT.AP8 applied, 3 SELECT.AP8 refused,
                                           4 = 2 + the second set (SP_SEL2 + SELECT2.AP8 + stub) installed */
    u32 efferr;                         /* why the restored effects were not used: 1 undo met a foreign word, 2 file sums, 3 AE8 header,
                                           4 a record (address / stock id), 5 sprite file header, 6 slot table missing; 0 = used or not on the disc */
    u32 sel2err;                        /* why the second set was refused: 1 patch file sum, 2 header, 3 a patch offset, 4 a call site is not
                                           `jal 0x80030dd4`, 5 table entries of set 0x39 not zero, 6 sprite file sum; 0 = installed or not on the disc */
    struct aux { u32 msf, size, addr, sum; } aux[7];    /* raw file copies (see mod_loadfile), one per auxpri() position; size 0 = empty */
    u32 auxhits, auxmiss, auxstored;    /* debug: cache hits, whitelisted reads from the disc, copies kept */
    u32 corehits, coreloads, selres;    /* compressed core: files served, pack reads; selres 1 = select sprites in the scratch area */
    u32 sellow;                         /* where the game would have put its own SP_SEL0 (select screen memory, unused on this path) */
};
#define AUXN 7

/* from the EXE part of the loader (tools/tagload, addresses passed by the linker) */
extern struct { u8 dropped; u8 loaded; u8 strong; u8 fat; u32 start, end; u8 ap8; u8 title; u8 effp; } tl_dbg;
#define UNDOLIST    ((u32 *)0x80203c00)         /* count + { address, stock id, new id }: what effundo() in the EXE restores */
#define EFF_LO      0x80091afcu
#define EFF_LEN     0xd48u
u32 varload(u32 (*fn)(int, u32), int set, u32 off, const struct xent *var);
u32 effhook(int set, u32 off, s16 *list);
void flushcache(void);
#define BOSSNEW 0xF9
/* restored frames switched off in OPTION MODE (tl_dbg.title 3): every hook takes the stock content.  The restored
 * sprite files are the stock files plus appended data (SPEC 1), so an unpatched overlay draws the stock frames from them. */
#define FRAMES_OFF  (tl_dbg.title == 3)
#ifndef VERSION
#define VERSION "TAG HACK 1.0.1"
#endif
#define PRINT       ((void (*)(const char *, int, int, int, int, int))0x8002d79c)   /* (text, x, y, x step, colour, 1) */
#include "inflate.h"

struct rd { struct inf s; const u8 *base; int total; u8 res[8]; u32 *sp; u32 acc; };     /* sp, acc: word sum of the output so far */

/* the decoder ran out of input: wait for the drive */
static int more(struct inf *s)
{
    struct rd *r = (struct rd *)s;
    STATE->waits++;
    {                                   /* use the wait: sum the output that is already final */
        u32 *p = r->sp, *e = (u32 *)((u32)s->cur & ~15u), a = r->acc;
        while (p < e) { a += p[0]; a += p[1]; a += p[2]; a += p[3]; p += 4; }
        r->sp = p; r->acc = a;
    }
    for (;;) {
        int left = CDREADSYNC(1, r->res);
        const u8 *arrived;
        STATE->polls++;
        if (left < 0) return 0;
        if (left == 0) { s->lim = r->base + r->total * 2048 + 0x10000; return 1; }
        arrived = r->base + (r->total - left) * 2048;
        if (arrived - INF_MARGIN > s->in) { s->lim = arrived - INF_MARGIN; return 1; }
    }
}

static u32 sum(u32 a, u32 n);

/* one read for the whole block: the packed stream goes to the scratch area and is decoded into the block
 * while the rest of it is still coming in.  0 = failed (the caller reads the plain files) */
static int packload(int c, struct blk *b)
{
    struct rd r;
    u8 loc[8];
    int e;
    if (!T.pack[c].size) return 0;
    r.total = (T.pack[c].size + 2047) >> 11;
    r.base = (u8 *)SCRATCH;
    MKLOC(loc, FAKE(&T.pack[c]));
    for (;;) {                          /* the game's own sequence (0x8002dd40), without its blocking wait */
        XASTOP();
        if (!CDCONTROL(2, loc, r.res)) continue;
        CDSYNC(0, r.res);
        if (CDREAD(r.total, (u8 *)SCRATCH, 0x80)) break;
    }
    r.s.in = r.s.lim = r.base;
    r.s.out = (u8 *)b->addr;
    r.s.oend = r.s.out + b->size;
    r.s.more = more;
    r.s.lt = (iu16 *)LT_ADDR;
    r.s.dt = (iu16 *)DT_ADDR;
    r.sp = (u32 *)b->addr; r.acc = 0;
    e = inf_run(&r.s);
    if (CDREADSYNC(0, r.res) != 0 && !e) e = 0x100;             /* always let the read end before anything else uses the drive */
    if (!e && r.s.out != r.s.oend) e = 0x200;
    if (!e && r.acc + sum((u32)r.sp, b->addr + b->size - (u32)r.sp) != T.psum[c]) e = 0x300;
    if (e) { STATE->perr = e; return 0; }
    b->sum = T.psum[c];
    return 1;
}

static u32 sum(u32 a, u32 n)
{
    u32 *p = (u32 *)a, *e = (u32 *)(a + n), s = 0;
    while (p < e) {
        s += p[0]; s += p[1]; s += p[2]; s += p[3];
        p += 4;
    }
    return s;
}

static u32 ident(int c)
{
    return 1 | (T.code[c].msf ^ (T.spr[c].msf << 1) ^ (T.ap8[c].msf << 2) ^ T.code[c].size ^ (T.spr[c].size << 8) ^ (T.ap8[c].size << 20) ^ T.pack[c].msf ^ T.psum[c] ^ (T.ad8[c].msf << 3) ^ (T.ad8[c].size << 12));
}

static u32 need(int c)
{
    return R(T.code[c].size) + R(T.spr[c].size) + R(T.ap8[c].size) + R(T.ad8[c].size);
}

static struct state *state(void)
{
    struct state *st = STATE;
    int i;
    if (st->magic != ST_MAGIC) {
        st->magic = ST_MAGIC;
        st->battles = 0;
        st->effid = 0;
        st->sels = 0;
        for (i = 0; i < NBLK; i++) st->b[i].c = -1;
        for (i = 0; i < AUXN; i++) st->aux[i].size = 0;
        st->auxhits = st->auxmiss = st->auxstored = 0;
        st->corehits = st->coreloads = st->selres = st->sellow = 0;
    }
    return st;
}

/* Shared VRAM slots (frame layouts with byte 3 != 0xff: one upload shared by every object showing the frame).  The
 * engine finds a set's table through SLOTPTR[set]; an entry is { u16 users, u16 -, u32 VRAM block }, the table ends
 * with users == 0xffff.  The stock tables sit in the EXE with fixed sizes.  A set whose restored file needs more slots
 * gets a fresh, larger table here (k: index into T.slots, 19 = the effects set); every other set gets the game's table back. */
static void slots(struct state *st, int set, int k)
{
    u32 n = T.slots[k], *t = (u32 *)st->slotcur, *p = t;
    if (!n) return;                     /* the game's own table: slotreset() has put it back */
    while (n--) { p[0] = 0; p[1] = 0; p += 2; }
    p[0] = 0xffff; p[1] = 0;            /* complete and terminated before anything can see it */
    st->slotcur = (u32)(p + 2);
    SLOTPTR[set] = (u32)t;
    if (k < 19 && T.slotstock[set + 19]) SLOTPTR[set + 19] = (u32)t;    /* the reduced-partner set shares the table */
}

/* Order, traced: the game clears the tables through the pointer list in 0x8005c168 (only caller 0x80054c80, reached from
 * 0x8002a4f0: battle loader 0x8002b0e8 BEFORE the effects hook, other screen loaders, and 0x80085334 inside the fight
 * program).  It never writes the pointer list.  So: at the start of a battle load it still sees the tables of the
 * previous battle - they are intact and terminated until slotreset() below, which runs later (effects hook); during
 * a fight it sees our tables, which are terminated, and zeroes them exactly as it does with its own. */
/* every battle, also when the 2 MB loader takes it: all sets back to the game's tables (a table handed out for the
 * previous battle is about to be reused or forgotten) */
static void slotreset(struct state *st)
{
    int i;
    for (i = 0; i < 39; i++) SLOTPTR[i] = T.slotstock[i];
    st->slotcur = SLOTAREA;
}

/* Second select-screen sprite set (SPEC section 15), after section 10 has been applied.  All or nothing: every check
 * is made before the first byte of SELECT.BIN or of the set tables is changed.
 * Where it lives: `low` = the place below 2 MB where the game would have put its own SP_SEL0 (745 KB; unused here
 * because that file went above 2 MB) - memory that belongs to the select screen for as long as SELECT.BIN runs, like
 * the stock file it replaces.  [SP_SEL2][SELECT2.AP8]; the 208-byte stub is position independent and runs in place,
 * inside the patch file.  The next screen start clears the set tables (0x8002a4f0) and replaces the overlay. */
static int sel2(struct state *st, u8 *low)
{
    u8 *a = low + R(T.sel2.size);
    u32 *w = (u32 *)a, *site, *h = (u32 *)low, np, nr, ns, i, stub;
    if (!T.sel2.size || !T.selap2.size) return 0;
    LOADFILE(FAKE(&T.selap2), a);
    if (sum((u32)a, (T.selap2.size + 15) & ~15u) != T.selap2sum) return 1;
    np = w[7]; nr = w[8]; ns = w[9];
    if (w[0] != 0x02385341u || w[1] != FT_SIZE(1) || a[24] != 0x39 || a[25] != 0x27 || T.selap2.size != 44 + 8 * np + 4 * nr + 4 * ns + w[10]) return 2;
    for (i = 0; i < np; i++)
        if (w[11 + 2 * i] + 4 > w[1]) return 3;
    site = w + 11 + 2 * np + nr;
    for (i = 0; i < ns; i++)
        if (site[i] + 4 > w[1] || (site[i] & 3) || *(u32 *)(0x80098000u + site[i]) != 0x0c00c375u) return 4;
    if (SEC0[0x39] | SEC1[0x39] | SEC2[0x39] | SEC3[0x39]) return 5;
    LOADFILE(FAKE(&T.sel2), low);
    if (sum((u32)low, (T.sel2.size + 15) & ~15u) != T.sel2sum) return 6;
    /* everything is in memory and checked: install */
    SEC0[0x39] = (u32)low + h[0]; SEC1[0x39] = (u32)low + h[1]; SEC2[0x39] = (u32)low + h[2]; SEC3[0x39] = (u32)low + h[3];
    for (i = 0; i < np; i++) {
        u8 *d = (u8 *)(0x80098000u + w[11 + 2 * i]);
        u32 v = w[12 + 2 * i];
        d[0] = v; d[1] = v >> 8; d[2] = v >> 16; d[3] = v >> 24;
    }
    stub = (u32)(site + ns);
    flushcache();                       /* the stub is new code (critical section inside) */
    for (i = 0; i < ns; i++) *(u32 *)(0x80098000u + site[i]) = 0x0c000000u | ((stub & 0x0fffffffu) >> 2);
    flushcache();                       /* and the 28 call sites changed */
    return 0;
}

/* select screen, replaces SPRLOAD(0x27, off): the file goes to SELAREA instead of D130 + off.  The value returned
 * is the stock file's, so the caller's layout below 2 MB is unchanged (the space is simply not used).
 * Restored content: SELECT.AP8 is read first (behind the place of the sprite file) and checked; only then the
 * restored sprite file is loaded and the frame ids are written into SELECT.BIN (in RAM at 0x80098000, it is the
 * code that called us).  Anything wrong with the patch file = stock file, nothing patched: both or neither. */
u32 mod_sel(int set, u32 off)
{
    struct state *st = state();
    u32 keep = D130, stock = (FT_SIZE(0x5a + set) + 3) & ~3u, n, i;
    u8 *a = (u8 *)(SELAREA + R(T.sel0.size));
    u32 *w = (u32 *)a;
    const struct xent *var = 0;
    st->selhow = 1;
    st->sel2err = 0;
    if (T.sel0.size && T.selap.size && !FRAMES_OFF) {
        LOADFILE(FAKE(&T.selap), a);
        n = w[2];
        if (w[0] == 0x01385341u && w[1] == FT_SIZE(1) && T.selap.size == 28 + 8 * n) {
            for (i = 0; i < n && w[7 + 2 * i] + 4 <= w[1]; i++) ;
            if (i == n) var = &T.sel0;
        }
        if (!var) st->selhow = 3;
    }
    D130 = SELAREA - off;
    varload(SPRLOAD, set, off, var);
    D130 = keep;
    if (var) {
        n = w[2];
        for (i = 0; i < n; i++) {
            u8 *d = (u8 *)(0x80098000u + w[7 + 2 * i]);
            u32 v = w[8 + 2 * i];
            d[0] = v; d[1] = v >> 8; d[2] = v >> 16; d[3] = v >> 24;
        }
        st->selhow = 2;
        st->sel2err = sel2(st, (u8 *)(keep + off));
        if (!st->sel2err && T.sel2.size) st->selhow = 4;
    }
    st->sels++;
    st->selres = 1;                     /* SP_SEL0 (and its patch file) occupy the scratch area until the next battle load */
    st->sellow = keep + off;
    return stock;
}

/* the effects file hook: 8 MB battle or not */
/* Restored effects (SPEC 17.5 steps 2-6; step 1, the undo, has already run in the EXE: effundo()).  The restored
 * file and EFF1.AE8 sit in EFFAREA, resident like the stock file was.  Everything is checked before the first
 * record is written; any failure = 0 and the caller goes on with the stock file.  -> 0 not used, 3 read, 4 reused */
static int effrestored(struct state *st, int set)
{
    u32 nf = (T.effr.size + 15) & ~15u, na = (T.effae.size + 15) & ~15u, id = T.effr.msf ^ T.effr.size ^ T.effaesum ^ 0x40000000;
    u8 *f = (u8 *)EFFAREA, *a = f + R(T.effr.size);
    u32 *h = (u32 *)f, *w = (u32 *)a, *rec = w + 8, n, i;
    int how = 4;
    st->efferr = 0;
    if (!T.effr.size || !T.effae.size) return 0;
    if (tl_dbg.effp) { tl_dbg.effp = 0; st->efferr = 1; return 0; }
    if (st->effid != id || sum((u32)f, nf) != T.effrsum || sum((u32)a, na) != T.effaesum) {
        st->effid = 0;
        LOADFILE(FAKE(&T.effr), f);
        LOADFILE(FAKE(&T.effae), a);
        if (sum((u32)f, nf) != T.effrsum || sum((u32)a, na) != T.effaesum) { st->efferr = 2; return 0; }
        st->effid = id;
        how = 3;
    }
    n = w[3];
    if (w[0] != 0x01384541u || a[4] != set || T.effae.size != 32 + 12 * n || n > 250) { st->efferr = 3; return 0; }
    for (i = 0; i < n; i++)
        if (rec[3 * i] - EFF_LO >= EFF_LEN || (rec[3 * i] & 3) || *(u32 *)rec[3 * i] != rec[3 * i + 1]) { st->efferr = 4; return 0; }
    if (h[0] != 16 || h[0] >= h[1] || h[1] >= h[2] || h[2] >= h[3] || h[3] >= T.effr.size || ((h[1] | h[2] | h[3]) & 3)) { st->efferr = 5; return 0; }
    if ((a[5] & 1) && T.slots[19] < 255) { st->efferr = 6; return 0; }
    /* install: slot table (255 entries, always at the start of the slot area: slotreset() has just reset it), set
     * pointers, the undo list, and last the records themselves */
    slots(st, set, 19);
    SEC0[set] = (u32)f + h[0]; SEC1[set] = (u32)f + h[1]; SEC2[set] = (u32)f + h[2]; SEC3[set] = (u32)f + h[3];
    UNDOLIST[0] = n;
    for (i = 0; i < 3 * n; i++) UNDOLIST[1 + i] = rec[i];
    tl_dbg.effp = 0x5a;                 /* from here on effundo() has work to do */
    for (i = 0; i < n; i++) *(u32 *)rec[3 * i] = rec[3 * i + 2];
    return how;
}

u32 mod_eff(int set, u32 off, s16 *list)
{
    s16 *ids = IDS;
    struct state *st = state();
    int boss;
    st->selres = 0;
    boss = ids[0] == 0x10 || ids[1] == 0x10 || ids[2] == 0x10 || ids[3] == 0x10;
    slotreset(st);
    if (boss && !(ids[2] == 0x10 && ids[0] != 0x10 && ids[1] != 0x10 && list[0] >= 0 && list[2] == 8 && list[3] < 0)) {
        tl_dbg.effp = 0;                /* stock path: the records are stock (effundo), stock effects */
        return effhook(set, off, list);
    }
    tl_dbg.ap8 = 1;
    tl_dbg.dropped = boss ? BOSSNEW : 0;
    tl_dbg.fat = 0x80;                  /* stock RLE effects file */
    tl_dbg.strong = 0;
    tl_dbg.loaded = 0;
    st->effhow = FRAMES_OFF ? 0 : effrestored(st, set);
    if (!st->effhow) {                  /* stock effects file above 2 MB, resident: nothing is consumed below (returns 0) */
        u32 n = (T.eff.size + 15) & ~15u, id = T.eff.msf ^ T.eff.size ^ 0x80000000, *h = (u32 *)EFFAREA;
        if (st->effid == id && sum(EFFAREA, n) == st->effsum) {
            SEC0[set] = EFFAREA + h[0]; SEC1[set] = EFFAREA + h[1]; SEC2[set] = EFFAREA + h[2]; SEC3[set] = EFFAREA + h[3];
            st->effhow = 2;
        } else {
            u32 keep = D130;
            st->effid = 0;
            D130 = EFFAREA - off;
            varload(SETLOAD, set, off, &T.eff);
            D130 = keep;
            st->effsum = sum(EFFAREA, n);
            st->effid = id;
            st->effhow = 1;
        }
    }
    return 0;
}

static void apply(int c, u8 *ov, u8 *a, int slot)
{
    u8 *blob, *p;
    u32 frames, n, i, t;
    u32 *w = (u32 *)a;
    if (w[0] != 0x01385041u || a[4] != c) goto bad;
    blob = ov + w[2];
    for (i = 0; i < 16; i++)
        if (blob[i] != a[24 + i]) goto bad;
    frames = w[4];
    n = w[5];
    p = a + 40 + 4 * frames;
    for (i = 0; i < n; i++, p += 4) {
        u8 *r = blob + (p[0] | p[1] << 8) + 2;
        r[0] = p[2];
        r[1] = (r[1] & 0xf0) | p[3];
    }
    t = (u32)(a + 40) - (u32)blob;
    blob[8] = t; blob[9] = t >> 8; blob[10] = t >> 16; blob[11] = t >> 24;
    STATE->slot[slot] |= 0x10;
    return;
bad:
    STATE->slot[slot] |= 0x20;
}

/* PLxx.AD8 (work/ap/SPEC.md section 12): frame ids stored directly in the overlay's effect animations (capes, trails,
 * beam parts).  Applied to the fresh overlay copy; only if every record still holds its stock id (first pass), so a
 * wrong overlay is left alone as a whole.  The restored sprite file of the same content is in the same block. */
static void applyd(int c, u8 *ov, u8 *a, int slot)
{
    u32 *w = (u32 *)a, n = w[3], i, pass;
    if (w[0] != 0x01384441u || a[4] != c || w[2] != FT_SIZE(3 + c) || T.ad8[c].size != 16 + 12 * n) goto bad;
    for (pass = 0; pass < 2; pass++)
        for (i = 0; i < n; i++) {
            u8 *d = ov + w[4 + 3 * i];
            u32 v = w[6 + 3 * i];
            if (!pass) {
                if (w[4 + 3 * i] + 4 > w[2] || (d[0] | d[1] << 8 | d[2] << 16 | d[3] << 24) != w[5 + 3 * i]) goto bad;
            } else { d[0] = v; d[1] = v >> 8; d[2] = v >> 16; d[3] = v >> 24; }
        }
    STATE->slot[slot] |= 0x80;
    return;
bad:
    STATE->slot[slot] |= 0x08;
}

static int listed(s16 *list, int c)
{
    return list[0] == c || list[1] == c || list[2] == c || list[3] == c;
}

/* lowest address in the arena where n bytes are clear of every character block and every cached file (may lie past
 * ARENA_END: no room) */
static u32 findgap(struct state *st, u32 n)
{
    u32 a = ARENA;
    int k, moved;
    do {
        moved = 0;
        for (k = 0; k < NBLK; k++) {
            struct blk *b = &st->b[k];
            if (b->c >= 0 && a < b->addr + b->size && b->addr < a + n) { a = b->addr + b->size; moved = 1; }
        }
        for (k = 0; k < AUXN; k++) {
            struct aux *x = &st->aux[k];
            if (x->size && a < x->addr + R(x->size) && x->addr < a + n) { a = x->addr + R(x->size); moved = 1; }
        }
    } while (moved);
    return a;
}

/* drop the lowest-priority cached file below priority p (p = -1: any) -> 1 if one was dropped */
static int auxdrop(struct state *st, int p)
{
    int q;
    for (q = AUXN - 1; q > p; q--)
        if (st->aux[q].size) { st->aux[q].size = 0; return 1; }
    return 0;
}

/* ---- file cache (8 MB only): the files every select / win / VS screen and every fight load read again ----
 * The EXE's LOADFILE (0x8002de3c) is redirected here by loadhook() (main menu).  Two kinds:
 *  - CORE (AUX.PAK, made by the disc builder from this image's own files): portraits, SELECT.BIN, SP_SEL1, DEB.SCR and
 *    two sound headers, raw deflate, about 220 KB.  Read once into AUXAREA, a fixed area below the arena that the
 *    builder carves out of the room the four largest characters leave, so it is always resident; each request is
 *    unpacked straight into the caller's buffer.  The decode tables (LT_ADDR) lie in the scratch area, so not while the
 *    select screen's sprite files are there (selres) - the core files are all read before them anyway.
 *  - RAW copies in free arena space: the two sound banks, KANJI.TEX and the restored select-screen files.  Character
 *    blocks always win: findgap() keeps copies clear of them and mod_hook drops copies (lowest priority first) when a
 *    character needs the space.  A copy is never kept at the expense of a character.
 * Every copy is checked (word sum) before use; anything wrong = the disc, exactly as before. */
#define AUDSTOP     ((void (*)(int))0x80016454)         /* first call of LOADFILE */
#define AUXAREA     (T.auxarea)
#define PHASE       (*(volatile unsigned short *)0x80042774)   /* 8 = battle load */
#define AUX_MAGIC   0x58554158u                         /* "XAUX" */
u32 orig_loadfile(int idx, u8 *dst);                    /* ap8glue.S: the two displaced instructions, then LOADFILE+8 */
static int auxpri(int idx)
{
    static const short fixed[3] = { 264, 265, 268 };    /* SE/VB2/XS_MAIN.VB, SE/VB2/SELECT.VB, KANJI.TEX */
    int i;
    for (i = 0; i < 3; i++) if (fixed[i] == idx) return i;
    if (idx == FAKE(&T.selap)) return 3;
    if (idx == FAKE(&T.selap2)) return 4;
    if (idx == 129) return 5;                           /* A/A2/SP_SEL0.NSP: stock or (entry swapped by varload) restored */
    if (idx == FAKE(&T.sel2)) return 6;
    return -1;
}

static void wcopy(u32 *d, const u32 *s, u32 n)
{
    for (n >>= 4; n; n--) { d[0] = s[0]; d[1] = s[1]; d[2] = s[2]; d[3] = s[3]; d += 4; s += 4; }
}

static int nomore(struct inf *s) { (void)s; return 0; }

/* core: -> 1 served into dst */
static int core(struct state *st, int idx, u32 msf, u32 size, u8 *dst)
{
    u32 *h = (u32 *)AUXAREA, n, i, np = (T.auxp.size + 15) & ~15u;
    struct inf s;
    u32 tabs = LT_ADDR;
    if (!T.auxp.size) return 0;
    if (st->selres && PHASE != 8) {     /* select sprites in the scratch area: the tables go to the select screen's own free
                                           memory, behind the second sprite set (the builder checks the room) */
        if (!st->sellow) return 0;
        tabs = st->sellow + R(T.sel2.size) + R(T.selap2.size);
    }
    if (h[0] != AUX_MAGIC || sum(AUXAREA, np) != T.auxpsum) {
        st->coreloads++;
        orig_loadfile(FAKE(&T.auxp), (u8 *)AUXAREA);
        if (h[0] != AUX_MAGIC || sum(AUXAREA, np) != T.auxpsum) { h[0] = 0; return 0; }
    }
    n = h[1];
    for (i = 0; i < n; i++) {
        u32 *e = h + 2 + 5 * i;         /* idx, msf, size, offset, packed size */
        if (e[0] != (u32)idx || e[1] != msf || e[2] != size) continue;
        s.in = (const u8 *)AUXAREA + e[3];
        s.lim = s.in + e[4] + 0x10000;
        s.out = dst; s.oend = dst + R(size);
        s.more = nomore;
        s.lt = (iu16 *)tabs; s.dt = (iu16 *)(tabs + 0x10000);
        AUDSTOP(0);                     /* what LOADFILE does before reading */
        XASTOP();
        if (inf_run(&s) || s.out != s.oend) return 0;   /* (dst is the caller's: the disc read that follows rewrites it) */
        st->corehits++;
        return 1;
    }
    return 0;
}

u32 mod_loadfile(int idx, u8 *dst)
{
    struct state *st = state();
    const u8 *e = (const u8 *)(FTABLE + 8 * idx);
    u32 msf = e[0] | e[1] << 8 | e[2] << 16, size = *(const u32 *)(e + 4), n = R(size), a, got;
    int p;
    struct aux *x;
    if (!size || ((u32)dst & 3)) return orig_loadfile(idx, dst);
    if (core(st, idx, msf, size, dst)) return size;
    p = auxpri(idx);
    if (p < 0) return orig_loadfile(idx, dst);
    x = &st->aux[p];
    if (x->size == size && x->msf == msf && sum(x->addr, n) == x->sum) {
        AUDSTOP(0);
        XASTOP();
        wcopy((u32 *)dst, (const u32 *)x->addr, n);
        st->auxhits++;
        return size;
    }
    x->size = 0;
    st->auxmiss++;
    got = orig_loadfile(idx, dst);
    if (n > ARENA_END - ARENA) return got;
    for (;;) {
        a = findgap(st, n);
        if (a + n <= ARENA_END) break;
        if (!auxdrop(st, p)) return got;
    }
    wcopy((u32 *)a, (const u32 *)dst, n);
    x->msf = msf; x->addr = a; x->sum = sum(a, n); x->size = size;
    st->auxstored++;
    return got;
}

/* main menu: LOADFILE -> mod_loadfile (once per boot / reset; the EXE in RAM is fresh after a reset) */
static void loadhook(void)
{
    volatile u32 *p = (volatile u32 *)0x8002de3c;
    u32 j = 0x08000000u | ((u32)mod_loadfile >> 2 & 0x3ffffff);
    if (p[0] == j) return;
    if (p[0] != 0x27bdffe0u || p[1] != 0xafb00010u) return;    /* addiu sp,sp,-0x20 ; sw s0,0x10(sp) */
    p[1] = 0;
    p[0] = j;
    flushcache();
}

void mod_hook(int stage, s16 *list, int unused, u8 *heap)
{
    struct state *st = state();
    struct blk *b, *use[4];
    u8 *cur;
    int i, j, k;
    st->battles++;
    tl_dbg.end = 0;                     /* set again when the last character is in place */
    st->sumtime = 0;
    st->perr = st->waits = st->polls = 0;
    /* the blocks we have: needed ones must validate; the others stay as they are while there is room */
    for (i = 0; i < 4; i++) { st->slot[i] = 0; st->addr[i] = 0; st->low[i] = 0; }
    for (i = 0; i < NBLK; i++) {
        b = &st->b[i];
        st->why[i] = 0;
        if (b->c < 0) continue;
        if (b->id != ident(b->c) || b->size != need(b->c)) st->why[i] = 2;
        else if (!listed(list, b->c)) { st->why[i] = 1; continue; }
        else {
            st->sumtime += b->size >> 2;
            if (sum(b->addr, b->size) != b->sum) st->why[i] = 3;
            else b->used = 2 * st->battles + (list[0] == b->c || list[1] == b->c);   /* P1's side outlives the opponents of the same battle */
        }
        if (st->why[i]) b->c = -1;
    }
again:
    /* a block for every listed character */
    for (j = 0; j < 4; j++) {
        int c = list[j], f;
        u32 a, n;
        use[j] = 0;
        if (c < 0) continue;
        for (i = 0; i < NBLK; i++)
            if (st->b[i].c == c) use[j] = &st->b[i];
        if (use[j]) continue;
        n = need(c);
        for (;;) {
            struct blk *v = 0;
            a = findgap(st, n);         /* lowest free address, clear of every block and every cached file */
            for (f = 0; f < NBLK && st->b[f].c >= 0; f++) ;
            if (a + n <= ARENA_END && f < NBLK) break;
            for (i = 0; i < NBLK; i++) {            /* no room: the kept block that was used longest ago goes */
                b = &st->b[i];
                if (b->c >= 0 && !listed(list, b->c) && (!v || b->used < v->used)) v = b;
            }
            if (v) { v->c = -1; st->why[v - st->b] = 4; continue; }
            if (f < NBLK && auxdrop(st, -1)) continue;     /* then the cached files, lowest priority first */
            for (i = 0; i < NBLK; i++)
                if (st->b[i].c >= 0) { st->b[i].c = -1; st->why[i] = 4; }
            goto again;                 /* an empty arena takes any four characters (checked by the disc builder) */
        }
        b = &st->b[f];
        b->c = c; b->addr = a; b->size = n; b->id = 0;      /* id 0 = not read yet */
        b->used = 2 * st->battles + (j < 2);
        use[j] = b;
    }
    POOLSIZE = POOL;
    POOLINIT(stage, list[0], list[2], heap, POOL);
    cur = heap + POOL;
    tl_dbg.start = (u32)cur;
    for (;;) {                          /* ascending character number = disc order */
        int c;
        u32 code, csz, delta, t;
        u8 *hi, *spr, *ap, *ad;
        u16 *p;
        u32 *s, *d, *h;
        j = -1;
        for (i = 0; i < 4; i++)
            if (list[i] >= 0 && (j < 0 || list[i] < list[j])) j = i;
        if (j < 0) break;
        c = list[j];
        list[j] = -1;
        b = use[j];
        hi = (u8 *)b->addr;
        csz = T.code[c].size;
        spr = hi + R(csz);
        ap = spr + R(T.spr[c].size);
        ad = ap + R(T.ap8[c].size);
        if (b->id == 0) {
            st->slot[j] = 1;
            if (!packload(c, b)) {
                st->slot[j] = 0x41;
                LOADFILE(FAKE(&T.code[c]), hi);
                LOADFILE(FAKE(&T.spr[c]), spr);
                if (T.ap8[c].size) LOADFILE(FAKE(&T.ap8[c]), ap);
                if (T.ad8[c].size) LOADFILE(FAKE(&T.ad8[c]), ad);
                b->sum = sum(b->addr, b->size);
            }
            b->id = ident(c);
        } else st->slot[j] = 2;
        st->addr[j] = b->addr;
        st->low[j] = (u32)cur;
        /* overlay copy below 2 MB, relocated */
        code = FT_SIZE(3 + c);
        s = (u32 *)hi; d = (u32 *)cur;
        for (t = (code + 3) >> 2; t; t--) *d++ = *s++;
        delta = (u32)cur - LINKBASE;
        p = (u16 *)(hi + ((code + 3) & ~3u));
        for (k = 0; k < 3; k++) {
            while ((t = *p++) != 0xffff) {
                u32 *w = (u32 *)(cur + t * 4), v = *w;
                if (k == 0) v += delta;
                else if (k == 1) v = (v & 0xfc000000) | ((v + (delta >> 2)) & 0x03ffffff);
                else {
                    u32 *l = (u32 *)(cur + *p++ * 4), lv = *l;
                    u32 a = (v << 16) + (s16)lv + delta;
                    *l = (lv & 0xffff0000) | (a & 0xffff);
                    v = (v & 0xffff0000) | ((a + 0x8000) >> 16);
                }
                *w = v;
            }
        }
        if (!FRAMES_OFF) {
            if (T.ap8[c].size) apply(c, cur, ap, j);
            if (T.ad8[c].size) applyd(c, cur, ad, j);
            slots(st, c, c);
        }
        flushcache();
        ((void (*)(void))(INITTAB[c] + delta))();
        h = (u32 *)spr;
        SEC0[c] = (u32)spr + h[0];
        SEC1[c] = (u32)spr + h[1];
        SEC2[c] = (u32)spr + h[2];
        SEC3[c] = (u32)spr + h[3];
        cur += (((code >> 3) + 1) << 3);
        tl_dbg.loaded |= 1 << j;
    }
    tl_dbg.end = (u32)cur;
}

/* OPTION MODE gets a 13th line, "ARCADE FRAMES  ON  OFF" (restored frames on / off for this session; on at every boot).
 * OPDEMO.BIN (main menu + option screen, at 0x80098000) is patched in RAM from the main-menu hook, so a machine without
 * the 8 MB path keeps the stock option screen.  Option screen facts: cursor at 0x80042193 (0..11), labels drawn by the
 * loop at 0x80098bdc (items 5..7 are 8 apart, the others 16), "PRESS START BUTTON TO EXIT" at the loop's end + 8, cursor
 * wrap at 0x8009927c, pad: 0x8002c8e0(port) = held now, 0x8002c8f8(port) = held before; values are drawn like SOUND MODE
 * (x 0x110 and 0x148, chosen colour 0x30, the other 0x33). */
#define OPT_CURSOR  (*(volatile signed char *)0x80042193)
#define OPT_ITEM    12
#define PADNOW      ((u32 (*)(int))0x8002c8e0)
#define PADOLD      ((u32 (*)(int))0x8002c8f8)
#define SOUND       ((void (*)(int))0x8004d544)

/* end of the label loop: our line at y (the loop's next position); the exit line moves 8 down (back to where it was) */
static void optdraw(int y)
{
    int on = !FRAMES_OFF;
    PRINT("ARCADE FRAMES", 0x98, y, 8, OPT_CURSOR == OPT_ITEM ? 0x30 : 0x33, 1);
    PRINT("ON", 0x110, y, 8, on ? 0x30 : 0x33, 1);
    PRINT("OFF", 0x148, y, 8, on ? 0x33 : 0x30, 1);
}

/* replaces the call 0x8002c8e0(port) at 0x800994a8 (after LEFT / RIGHT of items 0..8): LEFT, RIGHT or CROSS on our line */
static u32 optinput(int port)
{
    u32 now = PADNOW(port);
    if (OPT_CURSOR == OPT_ITEM && (now & ~PADOLD(port) & 0xa040)) {
        tl_dbg.title ^= 1;              /* 2 <-> 3 */
        SOUND(0x84);
    }
    return now;
}

#define JAL(f)      (0x0c000000u | ((u32)(f) >> 2 & 0x3ffffff))
static void optpatch(void)
{
    static const u32 at[9] = { 0x80098c1c, 0x80098c44, 0x80098c48, 0x80098c4c, 0x80098c50, 0x8009927c, 0x80099280, 0x800994a8, 0x8009908c };
    static const u32 old[9] = { 0x2c420003, 0x34050098, 0x26260008, 0x00063400, 0x00063403, 0x2842000c, 0x3402000b, 0x0c00b238, 0x341100a8 };
    u32 new[9] = {
        0x2c420004,                     /* sltiu v0,v0,4: items 5..8 8 apart -> the loop ends 16 higher */
        JAL(optdraw), 0x02202021,       /* jal optdraw ; move a0,s1 */
        0x34050098, 0x26260010,         /* ori a1,zero,0x98 ; addiu a2,s1,16: the exit line */
        0x2842000d, 0x3402000c,         /* cursor 0..12 */
        JAL(optinput),
        0x341100a0 };                   /* "PRESS X BUTTON" of items 9..11 from y 160 (was 168): follows its labels */
    int i, n = 0;
    for (i = 0; i < 9; i++) {
        u32 w = *(volatile u32 *)at[i];
        if (w == new[i]) n++;
        else if (w != old[i]) return;   /* not OPDEMO.BIN as we know it: leave it alone */
    }
    if (n == 9) return;
    for (i = 0; i < 9; i++) *(u32 *)at[i] = new[i];
    flushcache();
}

/* main menu, every frame (menuhook in the EXE, only when the 8 MB path is usable) */
void mod_menu(void)
{
    optpatch();
    loadhook();
    PRINT(VERSION "  8MB", 88, 222, 8, 0x30, 1);   /* 8 px below the 2 MB line: "  8MB" would touch OPTION MODE (y 208) */
}
