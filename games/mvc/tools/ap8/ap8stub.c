/* SUPERSEDED 2026-11-24 by the 1.0-line 8 MB module (mkap8.py, entry8.S, ap8m.c, s8/): kept for reference, not built. */
/* Blob part of the MvC 8 MB build (tools/ap8): the entry ap8_main (entry8.S).  Kept tiny: the blob must not grow past
 * the 2 MB blob's sectors (ap8.c "Why a module").
 *   no 8 MB (probe once per boot, normally done by ap8menu.S at the first main-menu frame) -> tl_main(list), the 2 MB
 *   loader unchanged.  8 MB: the module (ap8.c, linked at MOD) is read from the disc to upper RAM at the first battle
 *   of a boot (BOOT == 0: the EXE image was just loaded; MiSTer keeps upper RAM across core reloads) or when its word
 *   sum is off, then ap8_mod(list).  A bad read -> tl_main. */
typedef unsigned int u32;
typedef unsigned char u8;
extern int tl_main(signed char *list);
extern void flushcache(void);
#define PROBE    (*(volatile u8 *)0x800858aeu)
#define BOOT     (*(u8 *)0x800858afu)
#define FTAB     ((u32 *)0x800255e4u)
#define SPARE    0x1ab
#define RD       ((int (*)(int, void *))0x80024800)
#define MOD      0x80201000u
struct dir8 { u32 magic, msf, size, sum, entry; };          /* 'AP8D'; filled by mkap8.py */
struct dir8 tl8_dir __attribute__((section(".dir8"))) = { 0x44385041 };

static int probe(void)
{
    const volatile u32 *c = (const volatile u32 *)0x80024810u;
    volatile u32 *lo = (volatile u32 *)0x800858acu, *hi;
    u32 l, keep;
    int k, i, ok = 1;
    *(volatile u32 *)0x1f801060 = 0xb88;
    for (i = 0; i < 32 && c[i] == ((const volatile u32 *)((u32)c + 0x200000u))[i]; i++) ;
    if (i == 32) return 0;
    l = *lo;
    for (k = 1; k < 4 && ok; k++) {
        hi = (volatile u32 *)((u32)lo + k * 0x200000u);
        keep = *hi;
        *hi = ~l;
        (void)*(volatile u32 *)0xbfc00000u;
        if (*hi != ~l || *lo != l) ok = 0;
        *lo = l;
        *hi = keep;
    }
    return ok;
}

static u32 msum(void)
{
    const u32 *p = (const u32 *)MOD;
    u32 s = 0, n = tl8_dir.size >> 2;
    while (n--) s += *p++;
    return s;
}

int ap8_main(signed char *list)
{
    if (!PROBE) PROBE = probe() ? 2 : 1;
    if (PROBE != 2 || !tl8_dir.size) return tl_main(list);
    if (!BOOT || msum() != tl8_dir.sum) {
        u32 om = FTAB[SPARE * 2], os = FTAB[SPARE * 2 + 1];
        BOOT = 0;                                   /* module (re)read: the cache header is wiped too (ap8.c) */
        FTAB[SPARE * 2] = tl8_dir.msf; FTAB[SPARE * 2 + 1] = tl8_dir.size;
        RD(SPARE, (void *)MOD);
        FTAB[SPARE * 2] = om; FTAB[SPARE * 2 + 1] = os;
        if (msum() != tl8_dir.sum) return tl_main(list);
        flushcache();
    }
    return ((int (*)(signed char *))tl8_dir.entry)(list);
}
