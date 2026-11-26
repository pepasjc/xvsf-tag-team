/* 8 MB module entry (tools/ap8, linked at MOD with tools/tagload/tagload.c built with AP8MOD and tools/snd/snd.c):
 * the blob's directories (snd_dir .. blob end, filled on the disc by mktag.py) are copied over the module's own copy
 * (same sources, same layout: mkap8.py checks it), then the module's tl_main.  modent: the tl_wrap of glue.S. */
typedef unsigned int u32;
extern u32 m_sdir[], m_end[];
extern int tl_main(signed char *list);

__asm__(
    ".section .text.start, \"ax\"\n"
    ".set noreorder\n"
    "  addiu $sp, $sp, -24\n"
    "  sw $ra, 16($sp)\n"
    "  jal ap8_modmain\n"
    "  nop\n"
    "  lw $ra, 16($sp)\n"
    "  addiu $sp, $sp, 24\n"
    "  beqz $v0, 1f\n"
    "  nop\n"
    "  la $t0, tl_postfn\n"
    "  lw $t0, 0($t0)\n"
    "  la $a0, tl_postarg\n"
    "  beqz $t0, 1f\n"
    "  lw $a0, 0($a0)\n"
    "  jr $t0\n"
    "  nop\n"
    "1: jr $ra\n"
    "  nop\n"
    ".set reorder\n"
    ".text\n");

/* stock frame tables back in a character's code item (2 MB builds substitute near-identical frames: --redcut, War
 * Machine --wmhover): uncut.h = per character {char id, count, (item offset, stock u16) x count}, 0-terminated */
typedef unsigned short u16;
typedef unsigned char u8;
#include "uncut.h"
#ifdef AP8FR
static void r8_patch(int c, u8 *F);
#endif
void ap8_uncut(int c, u8 *F)
{
    const u32 *t = uncut_tab;
    while (*t) {
        int k, n = t[1];
        if (t[0] == (u32)c) for (k = 0; k < n; k++) *(u16 *)(F + t[2 + 2 * k]) = (u16)t[3 + 2 * k];
        t += 2 + 2 * n;
    }
#ifdef AP8FR
    r8_patch(c, F);                                  /* arcade frames (ap8r.c) */
#endif
}

/* stock PLxx_10.A0 cache (upper RAM, AP8_A0C .. 0x80600000, AP8_A0SZ per slot): the sprite file is registered in place
 * (the game only reads it), so a character met again (ARCADE: the player's team every fight) is not read again.  Entry
 * key = the file's disc position + size, checked by a word sum; LRU among the slots this battle does not use. */
#define FTAB    ((u32 *)0x800255e4u)
#define RD      ((int (*)(int, void *))0x80024800)
#ifdef AP8FR
#include "ap8r.c"                                /* --frames8: the arena of restored sprite records replaces this cache */
#else
#define A0H     0x807df000u
#define A0MAGIC 0x43304138u                      /* '8A0C' */
#define NA0     ((0x80600000u - AP8_A0C) / AP8_A0SZ)
struct a0e { u32 msf, size, sum, used; };
struct a0h { u32 magic, tick, hits, reads; struct a0e e[8]; };
static u32 a0busy, a0tick;
static u32 a0sum(const u32 *p, u32 n) { u32 s = 0x5a17u; n = (n + 3) >> 2; while (n--) s += *p++; return s; }
u8 *ap8_a0(int idx)
{
    struct a0h *H = (struct a0h *)A0H;
    u32 msf = FTAB[idx * 2], size = FTAB[idx * 2 + 1];
    int k, best = -1;
    if (H->magic != A0MAGIC) { u32 *w = (u32 *)H; for (k = 0; k < (int)(sizeof *H / 4); k++) w[k] = 0; H->magic = A0MAGIC; }
    if (!a0tick) { a0tick = ++H->tick; H->hits = H->reads = 0; }
    for (k = 0; k < (int)NA0 && k < 8; k++) {
        struct a0e *e = &H->e[k];
        u8 *P = (u8 *)(AP8_A0C + k * AP8_A0SZ);
        if (e->msf == msf && e->size == size && size && !(a0busy >> k & 1) && a0sum((u32 *)P, size) == e->sum) {
            a0busy |= 1u << k; e->used = a0tick; H->hits++;
            return P;
        }
    }
    for (k = 0; k < (int)NA0 && k < 8; k++) {
        if (a0busy >> k & 1) continue;
        if (!H->e[k].size) { best = k; break; }
        if (best < 0 || H->e[k].used < H->e[best].used) best = k;
    }
    {
        struct a0e *e = &H->e[best];
        u8 *P = (u8 *)(AP8_A0C + best * AP8_A0SZ);
        e->size = 0;
        RD(idx, P);
        e->msf = msf; e->size = size; e->sum = a0sum((u32 *)P, size); e->used = a0tick;
        a0busy |= 1u << best; H->reads++;
        return P;
    }
}

#endif

int ap8_modmain(signed char *list)
{
    u32 *d = m_sdir;
    const u32 *s = (const u32 *)AP8_BSDIR;
    while (d < m_end) *d++ = *s++;
#ifdef AP8FR
#ifdef AP8FR_LAZY
    r8list = list;
#else
    r8_prefetch(list);
#endif
#endif
    return tl_main(list);
}
