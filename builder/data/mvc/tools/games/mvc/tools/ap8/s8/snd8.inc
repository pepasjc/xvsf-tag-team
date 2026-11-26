/* 8 MB battle sound with voice streaming (MvC tag hack, tools/ap8): included by tools/snd/snd.c when it is compiled
 * for the 8 MB module (-DSND8 -I tools/ap8/s8); the blob's snd.o (2 MB path) never has it.  Port of
 * games/mshvsf/tools/ap8/s8/snd8e.c onto snd.c's table scheme (lists in SPU, swap code, assist SPC slots unchanged).
 *
 * SPU in a streaming battle:
 *   0x01010            COMMON residents (effects, looping samples; COMMON.SN8), 64 B one-shot silent block, then
 *                      pool region 0 .. CHARS (survives the menus: COMMON voices stream there between battles too)
 *   CHARS = 0x315b0    the four characters' residents (64-byte steps), the lists (4 x FULLB) + owner map (OWNB),
 *                      then pool region 1 .. snd_spu_end (kind-6 sets / assists' SPC area above, as the 2 MB plan)
 * Voices (and every COMMON voice) stream from upper RAM: S8_COM (COMMON.SN8, read once per boot), S8_SLOT + s * S8_SLOTSZ
 * (each slot's .SN8, read again only when the slot's file changed).  Every entry carries S8_MARK in byte 0x13. */
#define S8_CHARS 0x315b0u
static const struct sn8 *s8f[4];
static u8 *s8stg;

static u32 s8wsum(const u32 *p, u32 n)
{
    u32 s = 0x5a17u;
    n = (n + 3) >> 2;
    while (n--) s += *p++;
    return s;
}

static int s8rd(const struct s8fent *f, void *dst)
{
    struct slev v;
    v.msf = f->msf;
    return rdfile(&v, f->size, dst);
}

static u32 s8samp(int c, int s)                      /* resident bytes of slot s's bank (Mega Man: the biggest variant) */
{
    int v; u32 m = 0;
    if (c != 0x10) return r64(s8d.b[bix(c, 2)].samp);
    if (s >= 2) return r64(s8d.b[22].samp);
    for (v = 0; v < 6; v++) if (r64(s8d.b[22 + v].samp) > m) m = r64(s8d.b[22 + v].samp);
    return m;
}

static u32 s8_need(signed char *list)                /* SPU end of residents + lists (the planner's sound end) */
{
    int s;
    u32 a = S8_CHARS;
    for (s = 0; s < 4; s++) if (list[s] >= 0) a += s8samp(list[s], s);
    return a + 4 * FULLB + OWNB;
}

static void s8_fresh(void)
{
    u32 i;
    if (ST->magic != S8_MAGIC) {                     /* first streaming battle of this boot (upper RAM survives resets on
                                                        some machines: the BOOT byte of entry8.S is not ours here) */
        u8 *p = (u8 *)ST;
        for (i = 0; i < sizeof(struct s8st); i++) p[i] = 0;
        for (i = 0; i < NVOICE; i++) ST->vspu[i] = ~0u;
        ST->magic = S8_MAGIC;
    }
}

/* snd_plan for streaming battles: COMMON.SN8, SPU layout, COMMON upload, empty lists / owner map, region 0 */
static void s8_plan(signed char *list)
{
    const struct sn8 *com = (const struct sn8 *)S8_COM;
    const struct s8fent *cf = &s8d.b[0];
    u32 a, lo0;
    int s, i, k, fresh;
    s8_fresh();
    s8_flush();
    ST->used = 0;
    for (i = 0; i < 8; i++) ST->ldbg[i] = 0;
    s8stg = (u8 *)S8_STG;
    if (ST->commsf != cf->msf || ST->comn != cf->size || s8wsum((u32 *)S8_COM, cf->size) != ST->comsum) {
        s8rd(cf, (void *)S8_COM);
        ST->commsf = cf->msf; ST->comn = cf->size; ST->comsum = s8wsum((u32 *)S8_COM, cf->size);
        TABK(1)[0x13] = 0;                           /* upload it again */
    }
    for (s = 0; s < 4; s++) {
        lsl[s] = list[s] >= 0 ? s : -1;
        if (list[s] < 0) { k = ~list[s]; lsl[s] = (k >= 0 && k < 4) ? k : -1; }
    }
    lvl = 0;
    a = S8_CHARS;
    for (s = 0; s < 4; s++) if (list[s] >= 0) { at[s] = a; a += s8samp(list[s], s); }
    lbase = a; own = a + 4 * FULLB;
    ST->ldbg[1] = own + OWNB <= snd_spu_end;
    voices_idle();
    for (i = 1; i < 5; i++) UNLOAD(i);
    /* COMMON (bank 0): our entries (stock order and ids) + residents, unless the table holds them already */
    fresh = TABK(1)[0x13] != S8_MARK || CNT[0] != (s16)com->nent;
    if (fresh) {
        const u8 *E = (const u8 *)com + com->bank + 0x14;
        ST->self = 1;
        SPUWV(SPU_COMMON, (void *)((const u8 *)com + com->bank + 20 * (com->nent + 1)), com->samp);
        ST->self = 0;
        for (i = 0; i < (int)com->nent; i++) {
            u8 *d = TABK(1 + i);
            for (k = 0; k < 20; k++) if (k != 0x11 && k != 0x12) d[k] = E[20 * i + k];
        }
        REG0();
        ST->ldbg[2] = 1;
    }
    for (i = 0; i < 4 * FULLB + OWNB; i++) s8stg[i] = i >= 4 * FULLB ? 0xff : 0;
    SPUWV(lbase, s8stg, 4 * FULLB + OWNB);
    ST->vox[0] = (const struct s8vox *)((const u8 *)com + com->vox);
    for (s = 1; s < 5; s++) ST->vox[s] = 0;
    lo0 = r64(SPU_COMMON + com->samp) + 64;          /* 64 B below region 0: the one-shot silent block */
    if (fresh || !ST->reg[0].on || ST->reg[0].lo != lo0) {
        static const u8 blk[64] = { 0, 1 };          /* block 0: end flag, no repeat; then zeros */
        s8_region(0, lo0, S8_CHARS);
        ST->self = 1;
        SPUW(lo0 - 64, (void *)blk, 64);
        ST->self = 0;
        ST->silent = lo0 - 64;
    } else {                                         /* COMMON kept: its cached voices stay, the last battle's go */
        u32 vlo = (u32)ST->vox[0], vhi = vlo + com->voxlen;
        for (k = 0; k < (int)ST->nseg; k++)
            if (ST->seg[k].reg == 0 && ST->seg[k].key && (ST->seg[k].key < vlo || ST->seg[k].key >= vhi)) ST->seg[k].key = 0;
    }
    s8_region(1, 0, 0);                              /* region 1 after the loads (snd_finish) */
    snd_dbg[0] = 0; snd_dbg[1] = 1; snd_dbg[3] = ST->ldbg[1];
}

/* the slot's .SN8 in upper RAM (read when the file or its contents changed) -> its bank image */
static u8 *s8_file(int s, int c)
{
    const struct s8fent *f = &s8d.b[bix(c, s)];
    u8 *P = (u8 *)(S8_SLOT + s * S8_SLOTSZ);
    if (ST->smsf[s] != f->msf || ST->sn[s] != f->size || s8wsum((u32 *)P, f->size) != ST->ssum[s]) {
        s8rd(f, P);
        ST->smsf[s] = f->msf; ST->sn[s] = f->size; ST->ssum[s] = 0;   /* sum after the bank bytes (below) */
    }
    s8f[s] = (const struct sn8 *)P;
    return P + s8f[s]->bank;
}

static void s8_fetchall(void)                        /* prefetch: mains, partners, COMMON in turns, shortest first */
{
    static const u8 ord[5] = { 1, 3, 2, 4, 0 };
    u32 i, k, got = 0;
    for (i = 0; i < 64; i++) {
        int more = 0;
        for (k = 0; k < 5; k++) {
            int b = ord[k], s;
            const struct s8vox *x = ST->vox[b];
            const struct sn8 *f = 0;
            const u16 *pf;
            if (!b) f = (const struct sn8 *)S8_COM;
            else for (s = 0; s < 4; s++) if (BANK[s] == b && lsl[s] == s) f = s8f[s];
            if (!x || !f || i >= f->npf) continue;
            more = 1;
            pf = (const u16 *)((const u8 *)f + f->pf);
            got += s8_fetch(x, pf[i]);
        }
        if (!more) break;
    }
    ST->ldbg[3] = got > 255 ? 255 : got;
}

static void s8_hooks(void)
{
    u32 *w = (u32 *)0x80086fc8u;
    /* play: move a0,s1 / jal s8_play / move a1,s2 / sw v0,0x34(sp) / nop x5 (stock: SPUTAB[bank] + off * 8) */
    if (w[0] == 0x92230011u && w[8] == 0xafa30034u) {
        w[0] = 0x02202021u;
        w[1] = 0x0c000000u | (((u32)s8_play >> 2) & 0x03ffffffu);
        w[2] = 0x02402821u;
        w[3] = 0xafa20034u;
        w[4] = w[5] = w[6] = w[7] = w[8] = 0;
    }
    w = (u32 *)0x8001bc88u;                          /* SpuWrite: j s8_wrstub / nop */
    if (w[0] == 0x27bdffe8u && w[1] == 0xafb00010u) {
        w[0] = 0x08000000u | (((u32)s8_wrstub >> 2) & 0x03ffffffu);
        w[1] = 0;
    }
    w = (u32 *)0x80022f54u;                          /* main loop ResetRCnt(2) -> s8_tick(2) */
    if (w[0] == 0x0c005c98u) w[0] = 0x0c000000u | (((u32)s8_tick >> 2) & 0x03ffffffu);
    ST->installed++;
}

/* snd_finish for streaming battles (after the bank addresses / swap code): shared slots' stores, region 1, prefetch,
 * hooks */
static void s8_finish(void)
{
    int s;
    u32 lo1 = r64(own + OWNB);
    for (s = 0; s < 4; s++) if (lsl[s] >= 0 && lsl[s] != s) ST->vox[BANK[s]] = ST->vox[BANK[lsl[s]]];
    if (lo1 < snd_spu_end) s8_region(1, lo1, snd_spu_end & ~63u);
    s8_fetchall();
    s8_hooks();
    ST->used = 1;
    ST->ldbg[0] = 1;
}
