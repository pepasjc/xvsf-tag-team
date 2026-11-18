/* Boot stub of the 8 MB ("ap8") build, in dead ranges of the EXE.  Hooks:
 *      effglue8 (jal at 0x8002b154, battle loader: effects set 0x26)  ->  effhook8
 *      glue8    (jal at 0x8002b1ac, battle loader: pool init)         ->  hook8
 *      selglue8 (jal at 0x8009bc38 in SELECT.BIN: SP_SEL0, set 0x27)  ->  selhook8
 *      menuhook (j at the end of the main-menu text routine 0x80098728 in OPDEMO.BIN)
 * Every hook first asks ap8ready(): real memory probe, then the module (tools/ap8/ap8mod.c) must be valid in RAM
 * at 0x80200000 (word sum + magic) or is read from the disc.  Not ready = the hook does exactly what the 2 MB
 * build does at that place: the battle runs the 2 MB loader with the 2 MB files, the select screen loads its
 * sprite file where it always did, the menu shows the version string only.
 *
 * Probe: RAM_SIZE (0x1f801060) is first set to the value the BIOS itself writes at boot (0xB88: 8 MB
 * address window), so the test addresses cannot be "locked" (bus error) on a core that implements the
 * register.  Then for 0x80200000, 0x80400000, 0x80600000 + the offset of a word we own below 2 MB:
 * write a pattern there and read it back (RAM present), and the low word must not have changed
 * (2 MB hardware mirrors its RAM over the whole 8 MB window).  Two patterns.  Everything is restored.
 *
 * -DTITLE_ONLY: only menuhook, version string only (the optional title patch of the 2 MB build, tools/titlepatch.py).
 */
typedef unsigned int u32;
typedef short s16;
typedef unsigned char u8;

#ifndef VERSION
#define VERSION "TAG HACK 1.3"
#endif
#define PRINT       ((void (*)(const char *, int, int, int, int, int))0x8002d79c)   /* (text, x, y, x step, colour, 1) */
#define MENU_X      88                  /* left edge of the picture is about x = 72 in this routine's coordinates */
#define MENU_Y      214                 /* the menu's last line (OPTION MODE) is at 208 */
#define SEC(s) __attribute__((section(s), noinline))

#ifdef TITLE_ONLY
SEC(".chunkl") void menuhook(void)
{
    PRINT(VERSION, MENU_X, MENU_Y, 8, 0x30, 1);
}
#else

#define FTABLE      0x8003d91cu
#define LOADFILE    ((int (*)(int, u8 *))0x8002de3c)
#define SPRLOAD     ((u32 (*)(int, u32))0x80053f78)
#define FAKE(p)     ((int)((u32)(p) - FTABLE) >> 3)
#define MOD         0x80200000u
#ifndef MODWORDS
#define MODWORDS    2048                /* 4 sectors: magic at word MODWORDS-2, sum of the words before it at MODWORDS-1 */
#endif
#define MOD_MAGIC   0x384d5658u         /* "XVM8" */
#define RAM_SIZE    (*(volatile u32 *)0x1f801060)

struct xent { u32 msf; u32 size; };
extern const struct xent modent;        /* the module on the disc (disc builder); at 4 mod 8 */
/* ap8: this battle is loaded by the module.  title: 0 = not looked yet, 1 = no 8 MB, 2 = 8 MB and module usable (menu indicator),
   3 = 8 MB, restored frames switched off in OPTION MODE (the module then takes the stock content everywhere) */
/* effp: 0x5a = effect animation records of the EXE are patched (restored effects file, SPEC 17), list at UNDOLIST;
   0xee = the last undo met a word that was neither id (the module then keeps the stock effects for this fight) */
extern struct { u8 dropped; u8 loaded; u8 strong; u8 fat; u32 start, end; u8 ap8; u8 title; u8 effp; } tl_dbg;
#ifndef STATEA
#define STATEA      0x80206000u
#endif
#define UNDOLIST    ((u32 *)(STATEA + 0x400))         /* count, then { address, stock id, new id } - written by the module */
#define EFF_LO      0x80091afcu                 /* the effect animation records in the EXE image */
#define EFF_LEN     0xd48u
#define SLOT26      (*(u32 *)0x8005c6f4)        /* shared-slot table pointer of set 0x26, stock 0x8005c760 */
u32 effhook(int set, u32 off, s16 *list);
void hook(int stage, s16 *list, int unused, u8 *heap);
void flushcache(void);

SEC(".chunkh") int ap8probe(void)
{
    /* A real console's CPU has a write buffer: a read can be answered before the write in front of it has
     * reached RAM, so a write-then-read test alone can see "8 MB" on a 2 MB console (emulators and the MiSTer
     * commit writes at once).  So first a test that writes nothing: on a 2 MB console the upper addresses
     * mirror the lower 2 MB, and game code reads the same 2 MB higher.  (No data cache on this CPU: these
     * reads go to RAM.) */
    volatile u32 *lo = (volatile u32 *)&tl_dbg.start, *hi;
    const volatile u32 *c = (const volatile u32 *)0x8002dd40u;      /* game code (CD file read), never changed */
    u32 l, keep;
    int k, i, ok = 1;
    if (tl_dbg.title == 1) return 0;    /* the main menu found no 8 MB: never probe again this boot */
    l = *lo;
    RAM_SIZE = 0xb88;
    for (i = 0; i < 32 && c[i] == c[i + 0x200000 / 4]; i++) ;
    if (i == 32) return 0;
    for (k = 1; k < 4 && ok; k++) {
        hi = lo + k * (0x200000 / 4);
        keep = *hi;
        *hi = l ^ 0x5aa5c33c;           /* then: the upper word holds what is written there, and the lower one did not change */
        if (*hi != (l ^ 0x5aa5c33c) || *lo != l) ok = 0;
        *lo = l;
        *hi = keep;
    }
    return ok;
}

/* the module in RAM is intact */
SEC(".chunkh") int modok(void)
{
    u32 *p = (u32 *)MOD, sum = 0;
    int i;
    for (i = 0; i < MODWORDS - 2; i++) sum += p[i];
    return p[MODWORDS - 2] == MOD_MAGIC && p[MODWORDS - 1] == sum;
}

SEC(".chunki") int modload(void)
{
    int n;
    for (n = 0; n < 3; n++) {
        LOADFILE(FAKE(&modent), (u8 *)MOD);
        if (modok()) {
            flushcache();
            return 1;
        }
    }
    return 0;
}

SEC(".chunki") int ap8ready(void)
{
    /* the first call of a boot (from menuhook, tl_dbg.title still 0) always reads the module from the disc: upper
       RAM survives a reset / core reload on some machines (MiSTer), and a resident module of another build would
       pass modok() */
    return ap8probe() && ((tl_dbg.title && modok()) || modload());
}

/* SPEC 17.5 step 1, at EVERY fight init and before anything else, whatever loads this fight (module, 2 MB loader,
 * stock boss path, module unreadable): the EXE's effect records back to their stock ids, the stock slot table back.
 * On a machine that never took the 8 MB path the flag is never 0x5a and nothing above 2 MB is touched. */
SEC(".chunkm") void effundo(void)
{
    u32 bad = 0;
    if (tl_dbg.effp == 0x5a) {
        u32 *p = UNDOLIST, n = *p++;
        for (; n; n--, p += 3) {
            u32 *a = (u32 *)p[0];
            if (p[0] - EFF_LO < EFF_LEN) {
                if (*a == p[2]) *a = p[1];
                else if (*a != p[1]) bad = 0xee;
            }
        }
        SLOT26 = 0x8005c760;
    }
    tl_dbg.effp = bad;                  /* 0 = records are stock */
}

SEC(".chunkj") u32 effhook8(int set, u32 off, s16 *list)
{
    effundo();
    tl_dbg.ap8 = 0;
    if (ap8ready())
        return ((u32 (*)(int, u32, s16 *))MOD)(set, off, list);
    return effhook(set, off, list);
}

SEC(".chunkj") void hook8(int stage, s16 *list, int unused, u8 *heap)
{
    if (tl_dbg.ap8) ((void (*)(int, s16 *, int, u8 *))(MOD + 8))(stage, list, unused, heap);
    else hook(stage, list, unused, heap);
}

/* select screen: SPRLOAD(0x27, off) */
SEC(".chunkj") u32 selhook8(int set, u32 off)
{
    if (ap8ready())
        return ((u32 (*)(int, u32))(MOD + 16))(set, off);
    return SPRLOAD(set, off);
}

/* end of the main-menu text routine (every frame the menu is shown) */
SEC(".chunkl") void menuhook(void)
{
    if (!tl_dbg.title)                  /* once per boot; the drive is idle on this screen */
        tl_dbg.title = ap8ready() ? 2 : 1;
    if (tl_dbg.title >= 2) ((void (*)(void))(MOD + 24))();     /* module: option-screen patch + the version line with "8MB" */
    else PRINT(VERSION, MENU_X, MENU_Y, 8, 0x30, 1);
}
#endif
