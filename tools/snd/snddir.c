/* XvSF tag hack 1.2: the sound directory's code (runs at DIRBUF + CODEOFF, see snd.h), called by snd_list (sndres.c)
 * with the battle loader's character list and its bank list buffer (bk[0] = XS_MAIN, bk[1..4] = characters, -1 none).
 *  - one bank per character (char 0x12 = Chun-Li's bank 0x0b), partners included (stock: HELP banks)
 *  - 8 MB when the 8 MB build's ap8ready() says so and the module will take this battle (ap8mod.c mod_eff's boss rule)
 *  - of the candidates (XS_MAIN level, character level) whose VB bytes fit the sample area (2 MB 0x1010..stash2, the
 *    stash at the SPU top; 8 MB 0x1010..0x7fff0, the stash in main RAM) the one of the lowest rank, the most bytes
 *    among equal ranks
 *  - id-list overrides for the load, the bank loader with vh_w / vb_w active, then the lists back */
#include "snd.h"
#define SEC(s) __attribute__((section(s)))

SEC(".text.entry") void snd_policy(s16 *ch, s16 *bk)
{
    struct sdir *d = DIR;
    u32 keep[NOVR], lim, best;
    u16 *cand;
    int k, i, pick = 0, is8 = 0;
    for (k = 1; k < 5; k++) {
        int c = bk[k];
        if (c == 0x12) c = 0x0b;
        for (i = 1; i < k; i++) if (bk[i] == c) c = -1;
        bk[k] = c;
    }
    if (ap8fn && ap8fn()) {
        s16 *id = IDS;
        int boss = id[0] == 0x10 || id[1] == 0x10 || id[2] == 0x10 || id[3] == 0x10;
        is8 = !boss || (id[2] == 0x10 && id[0] != 0x10 && id[1] != 0x10 && ch[0] >= 0 && ch[2] == 8 && ch[3] < 0);
    }
    lim = (is8 ? TOP8 : d->stash2) - SAMPLES;
    cand = is8 ? d->cand8 : d->cand2;
    for (i = 0, best = 0xffffffffu; i < 16 && cand[i] != 0xffff; i++) {
        u32 t, z, xl = cand[i] >> 4 & 15, cl = cand[i] & 15;
        t = z = d->e[xl][XSB][1].size;
        for (k = 1; k < 5; k++)
            if (bk[k] >= 0) { u32 n = d->e[cl][bk[k]][1].size; t += n; if (!n) z = 0; }
        t = (u32)(cand[i] >> 8) << 20 | (0xfffffu - t);      /* rank, then the most bytes (t < 1 MB) */
        if (z && (0xfffffu - (t & 0xfffffu)) <= lim && t < best) { best = t; pick = i; }
    }
    if (best == 0xffffffffu) pick = i - 1;          /* nothing fits: the last (smallest) candidate */
    snd_xl = cand[pick] >> 4 & 15; snd_cl = cand[pick] & 15;
    stashbase = is8 ? d->stash8 : d->stash2;
    for (i = 0; i < (int)d->novr; i++) {
        struct ovr *o = &d->o[i];
        keep[i] = LISTS[o->bank];
        if (o->levmask >> (o->bank == 0x26 ? snd_xl : snd_cl) & 1) LISTS[o->bank] = DIRBUF + o->off;
    }
    snd_on = 1;
    BANKLOAD(bk);
    snd_on = 0;
    while (--i >= 0) LISTS[d->o[i].bank] = keep[i];
}
