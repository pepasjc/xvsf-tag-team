/* Four-full-character battle loader for Marvel vs. Capcom (USA, SLUS-01059).
 *
 * Runs from the tile decode arena (ARENA in glue.S, idle during the battle load).  The resident glue (glue.S)
 * reads this blob there each battle, checks its word sum, flushes the I-cache and calls tl_main(list) in place of
 * the slot loop of the stock versus loader 0x8002b7a4 (0x8002b950..0x8002b9b0).
 *
 * list = the four deduplicated entries of the stock loader in SLOT order: P1 main, P2 main, P1 partner, P2 partner.
 * >= 0: character to load into that slot; < 0: shares the data of slot -entry-1 (the stock code after the loop
 * copies the sprite-set registrations with 0x80091d7c; code and tables are per character id anyway).
 *
 * Every listed character is loaded FULL, packed upwards from the end of the (capped) GPU primitive pool, in slot
 * order.  Per slot s, file at F (code base P = F + 0x1c, 8-aligned, avoiding the forbidden residues of the code):
 *     [item: header + code (relocated at load with the tools/reloc.py table that follows it) + kind-6 set]
 *         -> init entry INITM[c] + (P - SLOT0)
 *         -> kind-6 set: pixels stashed in SPU RAM (0x800921a8, set s+4) at an address planned here, the rest of
 *            the set stays (stock rounding); if the SPU area is full the whole set stays in RAM (0x80091e74)
 *     [sprite file: one of the tiers]  -> set s
 *     mains: [SPVCxx DSP]              -> set 0xe + s (the Cross Over loader loads it; tag rules may draw it)
 * Sound: mains upload their CHRxx SE file as bank s+1 (stock); partners upload the stock partner bank (section 2
 * of PLxx_11.A0: the bank areas of slots 2/3 in SPU RAM are only 14 KB).  Both are read to the top of the region
 * first (scratch).
 *
 * Tier policy: everybody on the smallest tier; if that does not fit: return 0 (stock loader, cut-down partners,
 * stock rules).  Then, while anything fits, the upgrade (any slot, any larger tier) with the largest saving of
 * expected decode cost per extra byte; mains weigh 3, partners 2.
 *
 * Only VERSUS / ARCADE battles with a human (tools/gameplay/tagmode.py switches those to the tag rules).
 * tl_dbg: [0] 1 loaded / 0xfe no fit / 0xfc char not handled / 0xfd bad dir / 0xf9 mode / (glue: 0xfb bad blob)
 *         [1] tier P1 main | P1 partner << 4, [2] same for P2 (10 = shared with another slot)
 *         [3] bit0..3: slot's kind-6 set in RAM; bit7: arena changed during the load (glue)
 *         (0xf8: --stockmeter baseline build)
 *         [4..7] end of the loaded data, [8..11] end of the GPU pool (heapcap), [12..15] fragments in use (bit k)
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define SLOT0        0x800c5000u            /* code base of the slot-0 link (PLxx_10) */
#define REGION_START 0x800c4fe4u            /* stock: pool ends 0x800c4fd8 */
#define TOP0         0x801fe000u            /* stack and its margin above */
#define TOP_ONSL     0x801f7200u            /* stage 9 with Onslaught: the stage owns 0x801f7200-0x801fe800 */
#ifdef AP8UP                                /* (test builds only) characters' code in upper RAM [AP8_START, AP8_TOP): a
                                               CPU Zangief move jumped into data (work/m8 arcfz.py): code stays in 2 MB */
#define RTOP AP8_TOP
#else
#define RTOP TOP                            /* top of the placement region (2 MB: TOP) */
#endif
#ifdef AP8MOD
#define NOT8 0                              /* 8 MB: no decoded-tile caches / decode-ahead / KO cache (stock decode) */
#else
#define NOT8 1
#endif
static u32 TOP, STRONG, CACHE;              /* per battle: end of our region, decoder payload address, bytes of the
                                             decoded-tile cache below STRONG (0: none) */
#define FTAB         ((u32 *)0x800255e4u)   /* file table: 8-byte entries (BCD MSF, size) */
#define SPARE        0x1ab                  /* CAPMOV.BIN entry: borrowed for our reads, restored */
#define INITM        ((u32 *)0x8006a70cu)   /* char init entry (linked for slot 0) */
#define SPU0         0x68000u               /* kind-6 set area in SPU RAM (stock: 4 fixed slots) */
#define SPU1         0x75800u               /* SP_EFF2 (set 0xc) from here */
#define LOADER_FULL  (*(u8 *)0x800858acu)   /* dead EXE span, see glue.S */   /* tools/gameplay/tagmode.py: bit0 P1 partner full, bit1 P2 */
#define ASSIST_BITS  (*(u8 *)0x8007b744u)   /* bit per side: special partner chosen */
#define MODE         (*(signed char *)0x8007b740u)
#define HUMANS       (*(u8 *)0x8007bdc9u)
#define MMVAR        (*(u8 *)0x8007b8e3u)   /* Mega Man variant (main loader) */

typedef int  (*rd_t)(int idx, void *dst);
typedef void (*snd_t)(int bank, void *src, int size, int chr);
typedef int  (*stash_t)(int set, void *src, int kind, int size, u32 spu);
typedef void (*reg_t)(int set, void *dsp, int mode);
typedef void (*init_t)(u32 *ent, u32 base0);
typedef int  (*rand_t)(void);
typedef void (*d04_t)(int set, int mode, void *pix, void *s1, void *s2, void *s3, int kind);
#define RD    ((rd_t)0x80024800)
#define SND   ((snd_t)0x800870e0)
#define STASH ((stash_t)0x800921a8)
#define REG   ((reg_t)0x80091e74)
#define RAND  ((rand_t)0x8003bc88)
#define D04   ((d04_t)0x80091d04)     /* set registration core: pointers only */

extern void flushcache(void);
#ifdef BGFAST                               /* incremental stage-BG rebuild engine (bgfast.py) */
#include "bgfast.h"
#endif
#ifdef DXAHEAD                              /* decode-ahead (tools/speed4/dxahead.py) */
#include "dxahead.h"
#endif
#ifdef KOCACHE                              /* free-on-KO tile cache (kocache.py) */
#include "kocache.h"
#endif
#ifdef CUTGUARD                             /* super cut-in guard (cutguard.py, integrator) */
#include "cutguard.h"
#endif
#ifdef CHK                                  /* checker tile form (tools/speed5/chkrt.py, fx worker) */
#include "chkrt.h"
#endif
#ifdef UPSKIP                               /* redundant tile-upload skip (upskip.py) */
#include "upskip.h"
#endif
#ifdef FECACHE                              /* decoded-tile cache (--cache; never enabled: build without it) */
#include "fecache.h"                        /* fe_code[], FE_DSH, FE_DSA (mktag.py from fecache.S) */
#endif
extern u32 dshptr, dsaptr;                  /* glue.S .res: the dispatch jumps through these */
extern u8 tl_dbg[16];
/* full sound banks for every character (games/mvc/tools/snd/snd.c) */
extern void snd_reset(void);
extern void snd_plan(signed char *list);
extern int snd_load(int s, int c, u32 top);
extern void snd_finish(void);
extern u32 snd_need_min(signed char *list);
extern u32 snd_spu_end;

struct fent { u32 msf, size; };
#define NT 13               /* sprite tiers, smallest first (mktag.py TIERS); the last one is the stock RLE file */
#define NF 6                /* forbidden base residue intervals */
#define NFR 32              /* fragments */
struct chr {
    struct fent a0;         /* part A: header + code (+ Onslaught block), resident at F; size = setoff */
    struct fent st;         /* part B: kind-6 set (setsize, padded to 4) + relocation table, read to scratch */
    u32 a0size;             /* offset of the relocation table in part B */
    u32 hdr;                /* header bytes before the code: 0x1c, Onslaught 0x24 */
    u32 xoff;               /* Onslaught: offset of the giant-form block (pointer 0x80078a4c), else 0 */
    u32 setoff, setsize;    /* kind-6 set in the item */
    u32 kept;               /* RAM bytes the set keeps after the SPU stash (stock rounding: ((r >> 3) + 1) << 3) */
    u32 spu;                /* SPU bytes of the set (multiple of 64) */
    u16 forb[2 * NF];       /* (P - SLOT0) & 0xffff residues [lo, hi) the code base must avoid; lo == hi: unused */
    struct fent t[NT];      /* sprite files without their tables: header + pixel section (size 0: tier missing) */
    struct fent tb[NT];     /* their tables: sections 1, 2, 3 (same sizes for every tier) */
    u32 tabsz, toff[3];     /* table bytes, offsets of sections 1/2/3 in them */
    u16 cost[NT];           /* expected decode cost per tier (cycles/byte x 10, play-weighted) */
    u8 pb, pu;              /* --share pair entries (directory index >= 0x17): base / variant char ids; else 0 */
#ifdef SPUSTORE                             /* --spustore (tools/spustore): per tier the store variant (cold streams at
                                               the end of the pixel part), its tables, the cold-suffix sizes / 8 */
    struct fent tv[NT];     /* variant pixel file (size 0: none) */
    u32 bvmsf[NT];          /* variant tables (same size as tb[]) */
    u8 ncut[NT];            /* cold region = ncut exact 2 KB groups (the share = k groups) */
    u16 ntile;              /* 5-byte tile table entries (sec2) */
#endif
};
struct dir {
    u32 magic;
    u32 strong_size;        /* bytes of the payload at tl_strong (decoders, meter), copied to strong_at after the reads */
    u32 strong_at;
    u32 dec_size;           /* bytes of the decoders at the start of the payload (DSH1 at 0, DSA1 at dsa_off) */
    u32 dsa_off;            /* 0: no DSA1 decoder */
    u32 ncut;               /* tiers 0..ncut-1 are frame-cut tiers (last resort, reported in the meter as 0) */
    u32 nstrong;            /* tiers 0..nstrong-1 need the RAM decoders; flags bit4: the dispatch jumps through
                               dshptr/dsaptr (else the decoders only work at strong_at: Onslaught battles skip them) */
    u32 flags;              /* bit0: load SPVC for the mains; bit1: test builds: force the team force[] */
    signed char force[4];   /* P1 main, P1 partner, P2 main, P2 partner (char ids) */
    u32 nfrag;
    u32 frag[3 * NFR];      /* lo, hi, flags: bits 0-9 stages where usable, bit 31 EXE RAM (restored after the battle;
                               else stage RAM, which the next battle reloads anyway) */
    u32 exe_msf;            /* SLUS_010.59 on the disc (restore of the fragments after the battle) */      /* RAM ranges [lo, hi) free during a tag battle (battle-cold, restored afterwards):
                               sprite tables and SPVC portraits go there first */
#ifdef DIRX                                 /* --dirx (dx worker): the full directory is a disc item, read to the
                                               region start at load; only the 4 battle characters are copied here */
    struct fent full;
    struct chr c[4];
#else
    struct chr c[0x17];
#endif
};
extern u32 tl_strong[];
struct dir tl_dir __attribute__((section(".dir"))) = { 0x4c474154, 0 };    /* 'TAGL' */

#ifdef DIRX
static struct chr *dirp[0x17];
#define CHR(x) (*dirp[x])
#ifdef L2PC                                 /* --l2pc (fx worker, rc4 per-character L2): the directory item holds after
                                               the chr entries one alternate per entry: the UNPACKED (stock sec1) tables.
                                               The planner swaps them into a slot's chr when packing gains it nothing. */
struct l2x {
    struct fent tbu[NT];    /* unpacked tables per tier (same sizes for every tier) */
    u32 tabszu, toffu[3];
    u32 bvu[NT];            /* --spustore variant tables, unpacked (0 without --spustore) */
};
static struct chr *dir0;                    /* first chr entry of the item (index into l2xp) */
static struct l2x *l2xp;
#endif
#if defined(HRFX) && defined(ASSIST)
#error "--assist excludes --hrfx (the assists take the RAM HI-RES FX AUTO would use; store and HRFX do not mix)"
#endif
#ifdef HRFX                                 /* --hrfx (memory worker, rc4.2 HI-RES FX): full-res effect tier variants.  Item
                                               tail: n x {u32 char, struct hrx}, then u32 n.  AUTO keeps a variant only when
                                               every slot's final tier equals the half-res plan's (no tier loss, no fallback) */
struct hrx {
    struct fent t[NT];      /* pixel files */
    struct fent tb[NT];     /* tables, packed sec1 (--l2g) */
    u32 tabsz, toff[3];
#ifdef L2PC
    struct fent tbu[NT];    /* tables, unpacked sec1 */
    u32 tabszu, toffu[3];
#endif
};
static int hrn; static volatile int hrhave;                   /* hrhave: slots on full res this battle (tests read it by symbol) */
static volatile u8 hrtier[4];               /* final tier per slot (tests compare AUTO / OFF) */
static u32 *hrp;                            /* n x {char, struct hrx} */
#endif
#else
#define CHR(x) (tl_dir.c[x])
#endif
#ifdef SHARE                                /* store-once sprite pairs (tools/speed5/pairs.py, fx worker) */
static int npair, psb[2], psu[2];          /* pairs in this battle (max 2): slots of the base / variant character */
static struct chr *pent[2];                 /* each pair's two directory entries (base, variant) */
static struct chr *pdir;                    /* first pair entry (full directory + 0x17) */
static int pnum;                            /* pair entries / 2 */
#endif
#if defined(SHARE) && defined(ASSIST)
static int npair_dbg(void) { return npair; }
#endif
#ifdef SPUSTORE                             /* SPU store (tools/spustore, docs/TAGLOAD.md "SPU store") */
#include "spsfe.h"
#define SPS_TAIL    0x7e180u                /* after SP_EFF2 (0x75800-0x7e180) */
#define SPS_TAILEND 0x7ffc0u                /* below the reverb word 0x7fff0 (reverb off) */
static const u8 SPS_BLK[8] = { 1, 2, 3, 4, 6, 8, 16, 32 };   /* 64-byte blocks per length class (spsfe.py DATA+0x60) */
#define SPS_STG     2112u                   /* staging buffer: <= 32 x 64 bytes per fetch (+ slack) */
#define TAB11       (*(u32 *)0x80092b5cu)   /* decoder slot 11: never used by the game (all RAM dumps) */
#define SPUWR       ((u32 (*)(void *, u32))0x8001bc88)    /* libspu SpuWrite (transfer from the cached address) */
#define SPUDONE     ((int (*)(int))0x8001aea8)            /* SpuIsTransferCompleted(1): wait */
#ifdef SPSWAIT   /* rc4.8 tester (2026-11-21, MiSTer in-battle hang): SpuIsTransferCompleted can return while the SPU DMA
                  * still reads the buffer (stale "transfer done" event, real-HW timing); as_cut / sps_cut then write the
                  * offset table into that very buffer -> corrupted SPU store -> first fetch decodes garbage.  Also wait on
                  * the hardware too: DMA4 CHCR busy (the DMA has read the whole buffer when it clears). */
#define SPUFIN() do { SPUDONE(1); while (*(volatile u32 *)0x1f8010c8u & 0x01000000u) ; } while (0)
#else
#define SPUFIN() SPUDONE(1)
#endif
#ifdef SPSDRAIN   /* (--spsdrain, 2026-11-25) MiSTer core: an upload's tail can still be in the SPU write FIFO when the next
                   * transfer address is written (it then lands there): drain wait before / after the store uploads */
#define SPS_DRAIN() do { volatile u32 i_; for (i_ = 0; i_ < 3000; i_++) ; } while (0)
#else
#define SPS_DRAIN() do { } while (0)
#endif
#ifdef SPSPAD    /* (--spspad, 2026-11-25) MiSTer core: libspu ends an upload (mode 00) while the SPU write FIFO still drains,
                  * so the last <= 64 halfwords never reach SPU RAM.  Every store / assist upload carries 128 B of padding
                  * (reserved after its span), so only padding is lost.  A real SPU stores the padding too: 128 B per slot. */
#define SPS_PAD 128u
#else
#define SPS_PAD 0u
#endif
extern u32 snd_end_plan(signed char *list, u32 end);
extern void snd_table(void *dst);
static int sps_ok;                          /* this battle may use the store (TOP == TOP0) */
#if defined(SPS_NOSTORE) || defined(AP8MOD)
#define SPS_LIVE 0                          /* --spsnostore: the store code is never reached; constant 0 lets the compiler
                                               drop it (sps_pick / sps_cut / the front end: ~1.5 KB of blob, memory worker) */
#else
#define SPS_LIVE 1
#endif
static u32 sps_lo[3], sps_hi[3];            /* free SPU spans: sound gap, after the kind-6 sets, tail */
static u32 sps_mv[4], sps_at[4], sps_stg;   /* per slot: bytes moved to SPU, their SPU address; staging buffer */
static u32 sps_own[4][4];                   /* front-end owner table {spu lo, spu hi, section, 0} */
#endif
#ifdef ASSIST                               /* --assist (assists lead, rc4.4): special-partner assists in tag battles.
                                               Mains: fast tiers only (no DSR / DSA1 class, cost >= 3000), floor AS_TMIN;
                                               assists: DSR tier after the mains (code relocated, init = code + 4, set
                                               8 + side; the same assist on both sides = one copy for both sets); their
                                               SPCxx sound at the top of the bank area, entries in COMMON's free table
                                               slots; the RAM shortfall goes to the SPU store (mains' cold tiles), the
                                               SPU for it from the sound ladder (best voice level that fits). */
#define AS_SAVE   (*(volatile u8 *)0x8001176bu)   /* side bits for the battle-init stub (tagmode.py --assist) */
#define AS_IDS    ((s16 *)0x8007b8d8u)            /* assist id * 4 per side */
#ifdef ASHUD    /* assist bugs (--ashud): the HUD assist portrait (tiles 0xc9 / 0xdb of the HUD page) = stock 0x8002adfc(assist,
                 * 4 + side, 1): LoadImage from the pointer the assist's init put in 0x80079da0[assist] (stock versus loader
                 * 0x8002ba98 / the P2 twin); the tag loader never called it -> stale tile.  After the init (and D04). */
#define AS_HUD(q) ((void (*)(int, int, int))0x8002adfcu)(as_a[q], 4 + (q), 1)
#else
#define AS_HUD(q)
#endif
#define AS_LINK   0x80150d00u                     /* code base of the DAxx_11 link */
#ifndef AS_TMIN
#define AS_TMIN   2                               /* first fast tier (mktag TIERS: dsh_cut48) */
#endif
#ifndef VHQ_SH                                   /* (voice) --voicehq: voice search cost slack kt >> VHQ_SH (rc4.14: 5) */
#define VHQ_SH 5
#endif
#ifndef AS_LVF
#define AS_LVF    28                              /* voice floor of the mains-first search (sndbank.LADDER: 3.7 kHz) */
#endif
#ifdef ASRLE                                      /* --asrle (asdip lead, rc4.6): + RLE with its streams in SPU (tier 1) */
#define NAT 5
#define AS_RL (AT(q) == 1)                        /* owner section bit 0: the front end routes the fetch to the RLE decoder */
#else
#define NAT 4                                     /* assist pixel tiers, fastest first (mktag ASSIST_TIERS): stock RLE,
                                                     DSX, DSX / DSH with every stream in SPU (tools/assist/asvar*.py) */
#define AS_RL 0
#endif
struct asx { struct fent a0; u32 codesz, tabsz, toff[3]; struct fent tb[NAT], t[NAT];
             u32 keep[NAT], spu[NAT];             /* RAM bytes the pixel file keeps / bytes uploaded to SPU (SPU tier) */
             u16 cost[NAT]; u16 ntile, pad; };   /* mktag assist_table() */
struct fent tl_asx __attribute__((section(".dir"))) = { 0, 0 };   /* 22 x struct asx (disc item) */
static struct asx as_e[2], *asd;
static int as_on, as_a[2], as_same;
static int as_t;                             /* assist tier this battle (0 fastest) */
#ifdef ASSIDE                                /* --asside (asdip lead, rc4.7): a tier per side (pair search in as_plan) */
static volatile u8 as_tq[2];
#define AT(q) as_tq[q]
#else
#define AT(q) as_t
#endif
static u32 as_pat;                           /* SPU address of the assists' pixel streams (SPU tier) */
static int as_nown(void)                     /* store owners the assists take (SPU tier): the mains get the rest */
{
    int q, n = 0;
    for (q = 0; q < 2; q++) if (as_a[q] >= 0 && !(q && as_same) && as_e[q].spu[AT(q)]) n++;
    return n;
}
static int as_quick;                         /* 1 while as_plan probes (no exact planner) */

static u32 as_spu, as_cap;                   /* SPC area start in SPU (top of the bank area); sound budget */
static volatile u8 astier[4], aslv;
static volatile u32 askey[3];                /* tests: rc4.3 bar, densest-tier key, chosen key */          /* final main tiers / sound level (tests read them by symbol) */
extern u32 snd_end_lv(signed char *list, int L);
#ifdef AS_DBG
static u32 asd_n, asd_why, asd_fe;
#endif
extern int snd_assist(u8 *T, u32 size, u32 a, int k0);
#endif
#ifdef STRONGX                              /* --strongx: the strong payload, the g2get image and the vcache image are disc
                                               items (blob space), read straight to where they are installed */
struct fent tl_sx __attribute__((section(".dir"))) = { 0, 0 };
struct fent tl_l2x __attribute__((section(".dir"))) = { 0, 0 };
struct fent tl_vcx __attribute__((section(".dir"))) = { 0, 0 };
#ifdef SPS_ITEM
struct fent tl_spx __attribute__((section(".dir"))) = { 0, 0 };   /* --asrle: the SPU front-end code (spsfe.h sps_code) */
#endif
const u32 tl_nometer[1] = { 0 };            /* the meter's battle-init copy (MCOPY) checks its magic here: never set */
#endif
static u32 a8(u32 x) { return (x + 7) & ~7u; }
static u32 sec(u32 x) { return (x + 2047) & ~2047u; }          /* CD reads write whole sectors */
static u32 rnd8(u32 x) { return ((x >> 3) + 1) << 3; }          /* stock rounding after a stash */

static int rd_item(const struct fent *f, void *dst)
{
    FTAB[SPARE * 2] = f->msf;
    FTAB[SPARE * 2 + 1] = f->size;
    return RD(SPARE, dst);
}

/* stock file indices (0x8002aeec main loader, 0x8002b1ec partner loader) */
static int main_se(int c, int s)
{
    int k = 3 * (c - 1) + 66 * s + 10;
    if (c <= 0x10) { if (s) k += 5; }
    else k += 5 * (s + 1);
    return k;
}
static int main_vc(int c, int s) { return main_se(c, s) + (c == 0x10 ? 7 : 2); }
#ifdef AP8MOD
static int stock_a0(int c) { return main_vc(c, 0) - 1; }                 /* PLxx_10.A0 (the main loader's file) */
extern void ap8_uncut(int c, u8 *F);                                      /* ap8m.c: stock frame tables back (redcut / wmhover) */
extern u8 *ap8_a0(int idx);                                               /* ap8m.c: the stock A0 from the upper-RAM cache */
#ifdef AP8FR
extern u8 *ap8_aspatch(int a, u8 *P);                                     /* ap8r.c: assist record (arcade frames) or 0 */
#endif
#endif
static int part_chr(int c, int s)
{
    if (c == 9) {
        signed char st = *(signed char *)(0x8007b8e4u + s);      /* 0x8007b828 + 0xbc + slot */
        if (st == 2) return 0x17;
        if (st == 4) return 0x18;
    }
    return c;
}
static int part_a0(int c, int s) { return (part_chr(c, s) - 1) * 2 + (s - 2) * 48 + 0x98; }
static u32 fsize(int idx) { return FTAB[idx * 2 + 1]; }

static u32 place(u32 cur, const struct chr *h)
{
    u32 p = a8(cur + h->hdr);                   /* P = code base (8-aligned), file at P - hdr */
    int k, moved;
    do {
        moved = 0;
        for (k = 0; k < NF; k++) {
            u32 lo = h->forb[2 * k], hi = h->forb[2 * k + 1];
            u32 r = (p - SLOT0) & 0xffff;
            if (lo != hi && r >= lo && r < hi) { p += a8(hi - r); moved = 1; }
        }
    } while (moved);
    return p;
}

static int ramset[4];               /* 1: the slot's kind-6 set stays in RAM */
static u32 spuat[4];
static u32 tabat[4][3], vcat[2];    /* fragment address of the slot's sprite table sections 1-3 / SPVC, 0: main region */

static u32 vcsz(int c, int s) { return (s < 2 && (tl_dir.flags & 1)) ? fsize(main_vc(c, s)) : 0; }
/* flags bit7 ("post VC", mktag --postvc, with the tile-decode arena cut to 12 KB): the mains' SPVC files do not use the
 * region; after tl_main the resident post routine (glue.S .post, copied with the strong payload) reads them into the
 * freed arena tail PA_LO..PA_HI and registers them.  The blob occupies that RAM during the load, hence after it. */
#define PA_LO  0x80095c40u                  /* ARENA + 0x3000 (new arena size) */
#define PA_HI  0x8009a8a4u                  /* ARENA + 0x7c64 (stock arena end): SPVC data stays below */
#define PA_LIM 0x8009ac40u                  /* ARENA + 16 sectors: what the blob read itself overwrites (sector tails) */
static int postvc;
static u8 vcpend[2];
u32 tl_postfn, tl_postarg;                  /* blob entry wrapper (glue.S): tail call into the post routine */
#ifdef KORELOAD                             /* KO reload (tools/koreload): resident image right below STRONG */
#include "krl.h"                            /* KRL_AT, KRL_SIZE, KRL_D, KRL_KD, krl_img[] */
#include "krl_data.h"
static int krlon;
static u32 kp0[4], kp1[4], kf0[4];
static struct krl_fent kpl[4][NT];          /* the 4 fighters' switch items (directory item read at load) */
#endif
#ifdef L2G                                  /* packed frame groups (games/mvc/tools/l2, fx worker): g2get image */
#include "l2g.h"                            /* L2G_N words l2g_img[], L2G_RAM, L2G_ENTRY (offset of g2get) */
#define L2RES0 ((L2G_N * 4u + L2G_RAM + 128u + 7u) & ~7u)    /* reserved below STRONG - CACHE (+128: alignment) */
#ifdef L2PC
#ifndef L2PC_MIN
#define L2PC_MIN 0u                                  /* weighted planner cost a packed plan must save (mktag --l2pcmin=) */
#endif
static u32 l2res = L2RES0;                  /* 0 when no slot of this battle keeps packed tables (no g2get) */
#define L2RES l2res
#else
#define L2RES L2RES0
#endif
#define L2_SITE 0x8008f694u                 /* per-object draw: nop before `addu v0, v0, v1` (group pointer) */
#else
#define L2RES 0u
#endif
#ifdef HOOKGATE
#include "hookgate.h"                       /* freeze worker (hook-lifecycle audit): HG_AT gate in kernel RAM, hg_img[] */
static u32 hg_jal(u32 t) { return 0x0c000000u | (t >> 2 & 0x3ffffffu); }
/* gate slot k: the site calls E_k (kernel); E_k calls `on` only in the battle scene with tag data present and the
 * image's first / last code words intact, else `off` (0 = return: the site was a nop) - tools/tagload/hookgate.py */
static void hg_set(int k, u32 e_k, u32 site, u32 on, u32 off, u32 a0, u32 a1, u32 a2)
{
    volatile u32 *T = (volatile u32 *)HG_T + 8 * k;
    T[0] = on; T[1] = off; T[2] = a0; T[3] = *(u32 *)a0; T[4] = a1; T[5] = *(u32 *)a1; T[6] = a2; T[7] = *(u32 *)a2;
    *(volatile u32 *)site = hg_jal(e_k);
}
#endif
#ifdef L1B                                  /* sec3 offset remap (games/mvc/tools/sec3/l1b.py, memory worker, rc4 L1b) */
#include "l1b.h"                            /* L1B_N words l1b_img[] (position independent), L1B_SITE0 / 1 */
#define L1RES ((L1B_N * 4u + 7u) & ~7u)     /* reserved right below the L2G reservation */
#else
#define L1RES 0u
#endif
#ifdef CUTIN                                /* super cut-in decoded in bands (games/mvc/tools/sec3/cutinfix.py, rc3 hang fix) */
#include "cutin.h"                          /* CUTIN_N words cutin_img[] (position independent), CUTIN_SITE_DEC / _LI + stock words */
#define CTRES ((CUTIN_N * 4u + 7u) & ~7u)   /* reserved right below the L1B reservation */
#else
#define CTRES 0u
#endif
#ifdef VCACHE                               /* VRAM tile cache (tools/vcache2/vcache.py): image below STRONG */
#include "vcache.h"                         /* VC_AT, VC_SIZE, VC_FLAG, vc_img[] */
static int vcon;
#endif
#ifdef LDBUF                                /* rc4.10 --ldbuf: the stock post-battle loading screen (scene 12, 0x8002c960)
                                               renders the winner as a frozen sprite (0x80090534, 40 B per part) into a
                                               FIXED prim buffer 0x801fce00 = free top RAM in the stock game, our g2get /
                                               vcache / strong payload in a tag battle (and rewritten by the next load's
                                               resident copies while the loading screen still shows it).  The EXE sites
                                               read the address from LDBUF_W: in a TOP0 tag battle a fixed 4 KB buffer
                                               (102 parts; win / stand frames <= 51) right below the lowest possible
                                               resident block; the planner region always ends below it, so no stage
                                               load, character load or resident copy ever writes it.  LDBUF_W is a
                                               constant written by mktag (EXE data) = ldbuf_at */
#define LDBUF_W     0x80011764u
#define LDBUF_SZ    0x1000u
#define LDBUF_STOCK 0x801fce00u
#ifdef VCACHE
#define LD_RTOP     VC_AT
#else
#define LD_RTOP     0x801fd400u
#endif
#ifdef L2G
#define LD_L2       ((L2G_N * 4u + L2G_RAM + 128u + 7u) & ~7u)
#else
#define LD_L2       0u
#endif
#define LDBUF_AT    ((LD_RTOP - LD_L2 - L1RES - CTRES - LDBUF_SZ) & ~127u)
#if defined(SXFIX) && defined(STRONGX)       /* --sxfix (onslaught, 2026-11-22): the strong payload item is read to TOP - 4096
                                               (2 sectors) before its copy down to STRONG; in Onslaught battles (TOP_ONSL, small
                                               dec_size) that span reaches ~1.7 KB into the region under the residents and
                                               overwrote the top of the plan (decoder spin at a tag-in, work/onsl): cap there */
#define RLIM (TOP == TOP0 ? LDBUF_AT : (STRONG - CACHE - L2RES - L1RES - CTRES < TOP - 4096u ? STRONG - CACHE - L2RES - L1RES - CTRES : TOP - 4096u))
#else
#define RLIM (TOP == TOP0 ? LDBUF_AT : STRONG - CACHE - L2RES - L1RES - CTRES)   /* TOP0: always above LDBUF_AT + SZ */
#endif
const u32 ldbuf_at = LDBUF_AT;              /* mktag writes it to LDBUF_W in the EXE (static: blob space; tl never
                                               declines a human battle, attract (0xf9) never reaches scene 12: ldchk.py) */
#else
#define RLIM (STRONG - CACHE - L2RES - L1RES - CTRES)
#endif
#ifdef AP8UP
#undef RLIM
#define RLIM AP8_TOP
#endif
extern u32 post[], post_list[];             /* glue.S .post (linked for offsets only; copied after the decoders) */
static u32 vcreg(int c, int s) { return postvc ? 0 : vcsz(c, s); }
static u32 secsz(const struct chr *h, int k) { return (k < 2 ? h->toff[k + 1] : h->tabsz) - h->toff[k]; }

/* first fit, largest piece first, into the fragments */
#ifdef FRAGS
static void plan_frag(signed char *list)
{
    u32 lo[NFR];
    u32 *at[14], sz[14];
    int n = 0, i, j, k, q;
    for (k = 0; k < 4; k++) { tabat[k][0] = tabat[k][1] = tabat[k][2] = 0; if (k < 2) vcat[k] = 0; }
    u32 stg = 1u << *(u8 *)0x8007bdd9u;               /* stage of this battle */
    for (k = 0; k < (int)tl_dir.nfrag; k++) lo[k] = (tl_dir.frag[3 * k + 2] & stg) ? tl_dir.frag[3 * k] : tl_dir.frag[3 * k + 1];
    for (k = 0; k < 4; k++) {
        if (list[k] < 0) continue;
        for (q = 0; q < 3; q++) { at[n] = &tabat[k][q]; sz[n++] = secsz(&CHR(list[k]), q); }
        if (k < 2 && vcreg(list[k], k)) { at[n] = &vcat[k]; sz[n++] = vcsz(list[k], k); }
    }
    for (i = 0; i < n; i++) {                       /* largest first, best fit */
        int b = -1, bf = -1;
        u32 bl = 0xffffffffu;
        for (j = 0; j < n; j++) if (*at[j] == 0 && sz[j] && (b < 0 || sz[j] > sz[b])) b = j;
        if (b < 0) break;
        for (k = 0; k < (int)tl_dir.nfrag; k++) {
            u32 room = tl_dir.frag[3 * k + 1] - lo[k];
            if (room >= a8(sz[b]) && room < bl) { bl = room; bf = k; }
        }
        if (bf >= 0) { *at[b] = lo[bf]; lo[bf] += a8(sz[b]); }
        else *at[b] = 1;                              /* no room: main region (1 = tried) */
        sz[b] = 0;
    }
    for (k = 0; k < 4; k++) {
        for (q = 0; q < 3; q++) if (tabat[k][q] == 1) tabat[k][q] = 0;
        if (k < 2 && vcat[k] == 1) vcat[k] = 0;
    }
}
#else
static void plan_frag(signed char *list) { int k; (void)list; for (k = 0; k < 4; k++) { tabat[k][0] = tabat[k][1] = tabat[k][2] = 0; if (k < 2) vcat[k] = 0; } }
#endif

/* plan the SPU addresses of the kind-6 sets, slot order; a set that does not fit stays in RAM */
/* 2026-11-18: when the four sets miss the area by <= 8 KB (e.g. War Machine + Jin + Strider + Mega Man: 56,384 B for
 * 55,296 B), the area starts lower for this battle when the sound banks still fit below it at their lowest level
 * (snd_plan then picks the level for snd_spu_end = spu0): a set that stayed in RAM cost ~14 KB of the region */
static u32 spu0 = SPU0;
#ifdef VOICEHI
/* (voice 2) --voicehi: EX OPTIONS "VOICE QUALITY" NORMAL (0, default) / HIGH (1) at VQ_BYTE, read at every battle load.
 * HIGH: the four kind-6 sets stay in RAM (the stock "does not fit" path) and the sound banks get SPU up to SPU1
 * (0x75800, as the 8 MB loader); every slot on a fast tier (no DSR / DSA1 class, as assist battles); with assists the
 * tier probe runs at the voice floor VQ_LVF.  No such plan: the battle loads as NORMAL (vq_plan). */
#define VQ_BYTE (*(volatile u8 *)0x80011763u)
#ifndef VQ_LVF
#define VQ_LVF 21                                  /* sndbank.LADDER: voices 5.5 kHz */
#endif
static int vqhi;
#define FASTONLY (as_on || vqhi)
#else
#define FASTONLY as_on
#endif
static void plan_spu(signed char *list)
{
    int s;
    u32 at, need = 0;
    spu0 = SPU0;
    for (s = 0; s < 4; s++) if (list[s] >= 0) need += CHR(list[s]).spu;
    if (need > SPU1 - SPU0 && need - (SPU1 - SPU0) <= 0x2000) {
        u32 lo = (SPU1 - need) & ~63u;
        if (snd_need_min(list) <= lo) spu0 = lo;
    }
#ifdef VOICEHI
    if (vqhi) spu0 = SPU1;                           /* HIGH: no kind-6 set in SPU */
#endif
    at = spu0;
    for (s = 0; s < 4; s++) {
        const struct chr *h;
        ramset[s] = 0; spuat[s] = 0;
        if (list[s] < 0) continue;
        h = &CHR(list[s]);
        if (at + h->spu <= SPU1) { spuat[s] = at; at += h->spu; }
        else ramset[s] = 1;
    }
#ifdef SPUSTORE
#ifdef ASSIST
    if (as_on) {                                     /* SPC of the assists at the top of the bank area, sound below as_cap */
        u32 n = 0x7f;
        if (as_a[0] >= 0) n += fsize(0xf8 + 2 * as_a[0]) + ((as_e[0].spu[AT(0)] + 63) & ~63u) + SPS_PAD;
        if (as_a[1] >= 0 && !as_same) n += fsize(0xf8 + 44 + 2 * as_a[1]) + 0x40 + ((as_e[1].spu[AT(1)] + 63) & ~63u) + SPS_PAD;
        as_spu = (spu0 - n) & ~63u;
        if (!as_cap || as_cap > as_spu) as_cap = as_spu;
        sps_lo[0] = (snd_end_plan(list, as_cap) + 63) & ~63u; sps_hi[0] = as_spu;
    } else
#endif
    { sps_lo[0] = (snd_end_plan(list, spu0) + 63) & ~63u; sps_hi[0] = spu0 & ~63u; }
    sps_lo[1] = (at + 63) & ~63u; sps_hi[1] = SPU1;
#ifdef SPS_NOTAIL
    sps_lo[2] = sps_hi[2] = SPS_TAIL;                /* (2026-11-25 MiSTer test) the reverb-area tail span unused */
#else
    sps_lo[2] = SPS_TAIL; sps_hi[2] = SPS_TAILEND;
#endif
#endif
}

/* walk the layout: returns the end of the data, 0 when a read or a scratch file would pass TOP */
static u8 ord[4] = { 0, 1, 2, 3 };  /* placement order of the slots in RAM (the planner picks a permutation) */

#ifdef SPUSTORE
/* SPU share of slot s for its tier: the largest cut that fits a span (best fit); rem = the spans' next free address */
static u32 sps_pick(int s, const struct chr *h, int t, u32 *rem)
{
    int k, i, bi;
    for (k = (int)h->ncut[t] - 1; k >= 0; k--) {
        u32 m = (u32)(k + 1) << 11, a = ((m + 63) & ~63u) + SPS_PAD, bl = 0xffffffffu;
        if (!m) continue;
        for (i = 0, bi = -1; i < 3; i++)
            if (rem[i] + a <= sps_hi[i] && sps_hi[i] - rem[i] < bl) { bl = sps_hi[i] - rem[i]; bi = i; }
        if (bi < 0) continue;
        sps_at[s] = rem[bi]; rem[bi] += a; sps_mv[s] = m;
        return m;
    }
    return 0;
}
#endif

#ifdef SPUSTORE
static u32 total_s(signed char *list, int *tier, u32 start, int st);
/* with the store when it fits, else exactly the plain plan (the floor fit is never worse than without --spustore) */
static u32 total(signed char *list, int *tier, u32 start)
{
    u32 r = SPS_LIVE && sps_ok ? total_s(list, tier, start, 1) : 0;
    return r ? r : total_s(list, tier, start, 0);
}
static u32 total_s(signed char *list, int *tier, u32 start, int st)
#else
static u32 total(signed char *list, int *tier, u32 start)
#endif
{
    int s, x, o;
    u32 cur = start;
#ifdef SPUSTORE
    u32 rem[3] = { sps_lo[0], sps_lo[1], sps_lo[2] }, any = 0;
    for (s = 0; s < 4; s++) sps_mv[s] = 0;
#endif
#ifdef ASSIST
    int own = 4;                                     /* store owners left for the mains */
    if (as_on) {                                     /* assists FIRST (region start: their files are read whole, the SPU
                                                        tier keeps only header + model): code (+ relocation table),
                                                        tables, pixels */
        int q;
        own -= as_nown();
        for (q = 0; q < 2; q++) {
            const struct asx *e = &as_e[q];
            if (as_a[q] < 0 || (q && as_same)) continue;
            if (cur + sec(e->a0.size) > RTOP) return 0;
            cur = a8(cur + e->codesz);
            if (cur + sec(e->tb[AT(q)].size) > RTOP) return 0;
            cur = a8(cur + e->tabsz);
            if (cur + sec(e->t[AT(q)].size) > RTOP) return 0;
            cur = a8(cur + e->keep[AT(q)]);
        }
    }
#endif
    for (o = 0; o < 4; o++) {
        s = ord[o];
        const struct chr *h;
        u32 p, f, d, scratch;
        int c = list[s];
        if (c < 0) continue;
        h = &CHR(c);
        scratch = s < 2 ? fsize(main_se(c, s)) : fsize(part_a0(c, s));
        if (cur + sec(scratch) > RTOP) return 0;                  /* sound file read to the top first */
        p = place(cur, h); f = p - h->hdr;
        if (f + h->setoff + sec(h->st.size) > RTOP) return 0;    /* part A at F, part B as scratch above it */
        cur = a8(f + h->setoff + (ramset[s] ? rnd8(h->setsize) : h->kept));
#ifdef AP8MOD
        if (vcreg(c, s)) { if (cur + sec(vcsz(c, s)) > RTOP) return 0; cur = a8(cur + vcsz(c, s)); }
        continue;                                                /* the stock A0: ap8m.c cache (not in the region) */
#endif
        /* tables before the pixels: read to the top as scratch, the region sections copied below it */
        d = cur;
        for (x = 0; x < 3; x++) if (!tabat[s][x]) d = a8(d + secsz(h, x));
        if (d > RTOP - sec(h->tabsz)) return 0;
        cur = d;
        if (vcreg(c, s)) {
            if (cur + sec(vcsz(c, s)) > RTOP) return 0;          /* read in place, or to the top for a fragment */
            if (!vcat[s]) cur = a8(cur + vcsz(c, s));
        }
#ifdef SPUSTORE
        if (SPS_LIVE && st && h->tv[tier[s]].size && cur + sec(h->tv[tier[s]].size) <= RTOP
#ifdef ASSIST
            && h->bvmsf[tier[s]] && !(h->pb | h->pu)   /* --share union entries have no variants of their own */
            && own > 0                                   /* a free front-end owner */
#endif
            ) {
            u32 m = sps_pick(s, h, tier[s], rem);                /* store variant: read whole, its cold suffix */
            if (m) {                                             /* goes to SPU and is truncated */
                cur = a8(cur + h->tv[tier[s]].size - m);
                any |= m;
#ifdef ASSIST
                own--;
#endif
                continue;
            }
        }
#endif
        if (cur + sec(h->t[tier[s]].size) > RTOP) return 0;     /* pixels last */
        cur = a8(cur + h->t[tier[s]].size);
    }
#ifdef SPUSTORE
#ifdef ASSIST
    if (as_on && own < 4) any = 1;                   /* assists in SPU: the front end too */
#endif
    if (SPS_LIVE && any) { sps_stg = cur; cur = a8(cur + SPS_STG + 4 * SPS_N); }  /* staging, then the front-end code */
#endif
    if (cur > RLIM) return 0;
    return cur;
}

static void copy(u8 *d, const u8 *s, u32 n)
{
    u32 *D = (u32 *)d; const u32 *S = (const u32 *)s;
    n = (n + 3) >> 2;
    while (n--) *D++ = *S++;
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

static void mmvariant(int s)
{
    /* Mega Man main: the stock loader picks one of 6 SE variants at random (0x8002af60..0x8002b004); variant 5 not
     * with Roll (char 8) as the partner of the same slot pair */
    static const u16 team_of[4] = { 2, 6, 0, 4 };   /* TEAM byte offset checked per slot (stock: b8ac/b8b0/b8aa/b8ae) */
    int v;
    do v = RAND() & 7; while (v >= 6);
    if (v == 5 && *(s16 *)(0x8007b8aau + team_of[s]) == 0x10) v = 0;
    MMVAR = (u8)v;
}

static void upgrade(signed char *list, int *tier, u32 start);
static void rescue(signed char *list, int *tier, u32 start, int tmin);
/* tier planning (floor at tmin, best placement order, greedy upgrades) for the region below STRONG - CACHE; 1 = fits */
#ifdef XPLAN
/* monotone planner (fx worker, tools/speed5/planx.py = its model + the all-teams proof): after the greedy, an exact
 * branch & bound over the four slots' tiers.  Key = play-weighted decode cost (mains x3, partners x2; mktag --xplan
 * prices DSA1 cut tiers like DSA1 + the cut penalty, not 20000 + 900 n), the greedy plan is the incumbent (never worse than it).  A plan counts when it fits in ANY of the 24
 * placement orders; the layout end only grows with the start address and with every size (place() = smallest allowed
 * base >= cur), so more RAM can only add plans: the optimum is monotone.  Prune: candidates per slot = tiers >= tmin
 * not dominated (another tier both smaller and cheaper), by cost; bound = prefix key + each remaining slot's cheapest;
 * size bound = start + every fixed part + the pixels (placements only move data up) must stay <= STRONG - CACHE. */
static const u8 xperm[24][4] = { {0,1,2,3},{0,1,3,2},{0,2,1,3},{0,2,3,1},{0,3,1,2},{0,3,2,1},{1,0,2,3},{1,0,3,2},
    {1,2,0,3},{1,2,3,0},{1,3,0,2},{1,3,2,0},{2,0,1,3},{2,0,3,1},{2,1,0,3},{2,1,3,0},{2,3,0,1},{2,3,1,0},
    {3,0,1,2},{3,0,2,1},{3,1,0,2},{3,1,2,0},{3,2,0,1},{3,2,1,0} };
static u32 xkey(signed char *list, const int *tier)
{
    int s; u32 wc = 0;
    for (s = 0; s < 4; s++) {
        u32 c;
        if (list[s] < 0) continue;
        c = CHR(list[s]).cost[tier[s]];
        wc += c * (s < 2 ? 3 : 2);
    }
    return wc;                                       /* play-weighted decode cost (mktag --xplan: speed costs) */
}
static u32 xbest_order(signed char *list, int *tier, u32 start)   /* best placement order of a plan -> ord; 0: none */
{
    int i, k, bi = -1;
    u32 be = 0xffffffffu, e;
    for (i = 0; i < 24; i++) {
        for (k = 0; k < 4; k++) ord[k] = xperm[i][k];
        e = total(list, tier, start);
        if (e && e < be) { be = e; bi = i; }
        if (e && bi < 0) bi = i;
    }
    if (bi < 0) return 0;
    for (k = 0; k < 4; k++) ord[k] = xperm[bi][k];
    return be;
}
static int xfits(signed char *list, int *tier, u32 start)
{
    int i, k;
    for (i = 0; i < 24; i++) {
        for (k = 0; k < 4; k++) ord[k] = xperm[i][k];
        if (total(list, tier, start)) return 1;
    }
    return 0;
}
static void xplan(signed char *list, int *tier, u32 start, int tmin)
{
    int cand[4][NT], nc[4], sl[4], idx[4], tr[4], best[4], ns = 0, s, t, u, i, j, d, q;
    u32 bkey = xkey(list, tier), fixed = 0, minpix[4], lim = RLIM;
    u8 sord[4];
    for (s = 0; s < 4; s++) { best[s] = tier[s]; tr[s] = tier[s]; sord[s] = ord[s]; }
    for (s = 0; s < 4; s++) {
        const struct chr *h;
        int c = list[s], m = 0, x;
        nc[s] = 0;
        if (c < 0) continue;
        h = &CHR(c);
        for (t = tmin; t < NT; t++) {
            int dom = 0;
            if (!h->t[t].size) continue;
#ifdef ASSIST
            if (FASTONLY && h->cost[t] >= 3000) continue;           /* assists on: no slow tier for a main */
#endif
            for (u = tmin; u < NT && !dom; u++)
                if (u != t && h->t[u].size && h->t[u].size <= h->t[t].size && h->cost[u] < h->cost[t]
#ifdef ASSIST
                    && !(FASTONLY && h->cost[u] >= 3000)
#endif
                    ) dom = 1;
            if (!dom) cand[s][m++] = t;
        }
        for (i = 0; i < m; i++)
            for (j = i + 1; j < m; j++)
                if (h->cost[cand[s][j]] < h->cost[cand[s][i]]) { x = cand[s][i]; cand[s][i] = cand[s][j]; cand[s][j] = x; }
        nc[s] = m;
        if (!m) return;
        minpix[s] = h->t[cand[s][0]].size;
        for (i = 1; i < m; i++) if (h->t[cand[s][i]].size < minpix[s]) minpix[s] = h->t[cand[s][i]].size;
        fixed += h->setoff + (ramset[s] ? rnd8(h->setsize) : h->kept);
        for (x = 0; x < 3; x++) if (!tabat[s][x]) fixed += secsz(h, x);
        if (vcreg(c, s) && !vcat[s]) fixed += vcsz(c, s);
        sl[ns++] = s;
    }
    d = 0; idx[0] = 0;
    while (d >= 0) {
        if (d == ns) {
            u32 k = xkey(list, tr);
            if (k < bkey && xfits(list, tr, start)) { bkey = k; for (q = 0; q < 4; q++) best[q] = tr[q]; }
            if (--d >= 0) idx[d]++;
            continue;
        }
        s = sl[d];
        if (idx[d] >= nc[s]) { if (--d >= 0) idx[d]++; continue; }
        tr[s] = cand[s][idx[d]];
        {
            u32 wc = 0, sz = start + fixed, lb;
            for (q = 0; q < ns; q++) {
                int sq = sl[q], tq = q <= d ? tr[sq] : cand[sq][0];
                u32 c = CHR(list[sq]).cost[tq];
                wc += c * (sq < 2 ? 3 : 2);
                sz += q <= d ? CHR(list[sq]).t[tr[sq]].size : minpix[sq];
            }
            lb = wc;
            if (sz > lim) { idx[d]++; continue; }                /* too big: the next (pricier) may be smaller */
            if (lb >= bkey) { if (--d >= 0) idx[d]++; continue; }   /* the rest of this slot only costs more */
        }
        if (++d < ns) idx[d] = 0;
    }
    for (s = 0; s < 4; s++) tier[s] = best[s];
    if (!xbest_order(list, tier, start)) for (s = 0; s < 4; s++) ord[s] = sord[s];
}
#endif

static int plan_tiers(signed char *list, int *tier, u32 start, int tmin)
{
    int s, k;
#ifdef SPUSTORE
    int ok0 = sps_ok;                                /* placement order and tiers first as without --spustore */
#ifdef ASSIST
    if (!as_on)                                      /* assists: the store counts from the floor on */
#endif
    sps_ok = 0;
#endif
    for (s = 0; s < 4; s++) tier[s] = tmin;
    plan_spu(list);
    plan_frag(list);
    {                                                /* placement order: the permutation with the lowest end */
        static const u8 perm[24][4] = { {0,1,2,3},{0,1,3,2},{0,2,1,3},{0,2,3,1},{0,3,1,2},{0,3,2,1},{1,0,2,3},{1,0,3,2},
            {1,2,0,3},{1,2,3,0},{1,3,0,2},{1,3,2,0},{2,0,1,3},{2,0,3,1},{2,1,0,3},{2,1,3,0},{2,3,0,1},{2,3,1,0},
            {3,0,1,2},{3,0,2,1},{3,1,0,2},{3,1,2,0},{3,2,0,1},{3,2,1,0} };
        int i, bi = 0;
        u32 be = 0xffffffffu, e;
        for (i = 0; i < 24; i++) {
            for (k = 0; k < 4; k++) ord[k] = perm[i][k];
            e = total(list, tier, start);
            if (e && e < be) { be = e; bi = i; }
        }
        for (k = 0; k < 4; k++) ord[k] = perm[bi][k];
    }
#ifdef AS_DBG
    asd_fe = total(list, tier, start); asd_why = 1;
#endif
#ifdef SPUSTORE
    if (!total(list, tier, start)) { sps_ok = ok0; return 0; }
#else
    if (!total(list, tier, start)) return 0;
#endif
    upgrade(list, tier, start);
    if (tl_dir.flags & 256) rescue(list, tier, start, tmin);
#ifdef XPLAN
#ifdef ASSIST
    if (!as_quick)                                   /* assists: probes plan greedy only, the final plan exactly */
#endif
    xplan(list, tier, start, tmin);
#endif
#ifdef ASSIST
    if (FASTONLY)                                    /* assists on: a main on a slow tier = no plan */
        for (s = 0; s < 4; s++)
            if (list[s] >= 0 && CHR(list[s]).cost[tier[s]] >= 3000) {
#ifdef AS_DBG
                asd_why = 0x100 | s | tier[s] << 4;
#endif
#ifdef SPUSTORE
                sps_ok = ok0;
#endif
                return 0;
            }
#endif
#ifdef SPUSTORE
    sps_ok = ok0;                                    /* then the store may only add upgrades on top of the plain */
    if (SPS_LIVE && sps_ok) {                        /* plan: no character ends below it (greedy order effects); */
        int t0[4], same = 1;                         /* no upgrade bought -> no store (= the plain build) */
        for (s = 0; s < 4; s++) t0[s] = tier[s];
        upgrade(list, tier, start);
        for (s = 0; s < 4; s++) if (tier[s] != t0[s]) same = 0;
#ifdef ASSIST
        if (as_on) same = 0;                         /* the assists' plan was made with the store */
#endif
        if (same) sps_ok = 0;
    }
#endif
    return 1;
}

#ifdef ASSIST
extern const int snd_nlv;
/* assists on: the best sound level (smallest ladder index) whose SPU leaves the store enough room for a plan with
 * every main on a fast tier (binary search; more SPU never removes a plan) */
#ifdef AS_DBG                                       /* TEST builds: per probe {L, ok, floor end, why} at 0x8000C800 (Beetle) */
static void __attribute__((noinline)) asd_put(u32 L, u32 ok)
{
    u32 *q_ = (u32 *)0x8000C800u + 4 * (asd_n & 31);
    q_[0] = L; q_[1] = ok; q_[2] = asd_fe; q_[3] = asd_why; asd_n++; *(u32 *)0x8000C7FCu = asd_n;
}
#define ASD(L, ok) asd_put((u32)(L), (u32)(ok))
#else
#define ASD(L, ok)
#endif
static u32 wcost(signed char *list, const int *tier);
#ifdef SHARE
static int npair_dbg(void);
#else
static int npair_dbg(void) { return 0; }
#endif
static int as_probe(signed char *list, int *tier, u32 start, int tmin, int L)
{
    int ok;
    as_cap = snd_end_lv(list, L);
    ok = plan_tiers(list, tier, start, tmin);
    ASD(L | as_t << 8, ok);
    return ok;
}
/* assists on (probes greedy only):
 * 1. voice floor lf (AS_LVF = 3.7 kHz, or the first level whose sound fits): the densest assist tier (DSR) gives the
 *    mains' reference cost kf; if nothing fits there, the best voice level below the floor with DSR assists.
 * 2. assist tier: the fastest (RLE, then DSH) whose plan at lf costs the mains at most kf + kf / 16, else DSR.
 * 3. voice: the best level (binary search above lf) whose plan costs at most the chosen tier's cost at lf + 1/32.
 * 4. the final plan once more with the exact planner. */
static int as_plan(signed char *list, int *tier, u32 start, int tmin, int tmin43)
{
    int lo = 0, hi, L, best = -1, lf, t;
    u32 kf, kt, k43 = 0;
    {                                                /* rc4.3's own plan (no assists, no store): the mains' bar */
        as_on = 0;
#ifdef SPUSTORE
        sps_ok = 0;
#endif
        as_quick = 1;                                /* greedy, as the probes it is compared with */
        if (plan_tiers(list, tier, start, tmin43)) k43 = wcost(list, tier);
        as_on = 1;
#ifdef SPUSTORE
        sps_ok = TOP == TOP0 && tl_dir.strong_size;
#endif
    }
    as_quick = 1; as_cap = 0;
    plan_spu(list);                                  /* as_spu */
    while (lo < snd_nlv && snd_end_lv(list, lo) > as_spu) lo++;
    if (lo >= snd_nlv) { as_quick = 0; return 0; }
#ifdef VOICEHI
    {
        int fl = vqhi ? VQ_LVF : AS_LVF;
        lf = fl < lo ? lo : (fl < snd_nlv ? fl : snd_nlv - 1);
    }
#else
    lf = AS_LVF < lo ? lo : (AS_LVF < snd_nlv ? AS_LVF : snd_nlv - 1);
#endif
    as_t = NAT - 1;
#ifdef ASSIDE
    as_tq[0] = as_tq[1] = NAT - 1;
#endif
    if (!as_probe(list, tier, start, tmin, lf)) {    /* below the floor: smallest level with a plan (binary) */
        int l2 = lf + 1, h2 = snd_nlv - 1;
        while (l2 <= h2) { L = (l2 + h2) >> 1; if (as_probe(list, tier, start, tmin, L)) { best = L; h2 = L - 1; } else l2 = L + 1; }
        if (best < 0) { as_quick = 0; as_cap = 0; return 0; }
        aslv = (u8)best;
        as_cap = snd_end_lv(list, best);
        return plan_tiers(list, tier, start, tmin);
    }
    kf = wcost(list, tier); kt = kf;
    {
        u32 kd = kf;
        if (k43 > kf + (kf >> 4)) kf = k43 - (kf >> 4);  /* the mains may cost what rc4.3's plan costs */
        kt = kd;
    }
#ifdef ASSIDE
    {                                                /* pairs {bigger assist's tier, other's}, fastest first: the bigger
                                                        assist (RLE pixels = decode volume) never on the slower tier of a
                                                        mixed pair; the same assist on both sides: uniform only */
        static const u8 pr[][2] = { {0,0},{0,1},{1,1},{0,2},{1,2},{2,2},{3,3} };
        int hv = as_e[1].t[0].size > as_e[0].t[0].size;
        for (t = 0; t < 7; t++) {
            if (as_same && pr[t][0] != pr[t][1]) continue;
            as_tq[hv] = pr[t][0]; as_tq[hv ^ 1] = pr[t][1];
            if (as_probe(list, tier, start, tmin, lf) && (kt = wcost(list, tier)) <= kf + (kf >> 4)) break;
        }
        if (t == 7) { as_tq[0] = as_tq[1] = NAT - 1; as_probe(list, tier, start, tmin, lf); kt = wcost(list, tier); }
    }
#else
    for (t = 0; t < NAT - 1; t++) {
        as_t = t;
        if (as_probe(list, tier, start, tmin, lf) && (kt = wcost(list, tier)) <= kf + (kf >> 4)) break;
    }
    if (t == NAT - 1) { as_t = NAT - 1; as_probe(list, tier, start, tmin, lf); kt = wcost(list, tier); }
#endif
    if (k43 > kt) kt = k43;
    askey[0] = k43; askey[1] = kf; askey[2] = kt;
    best = lf; hi = lf - 1;
    while (lo <= hi) {
        L = (lo + hi) >> 1;
        if (as_probe(list, tier, start, tmin, L) && wcost(list, tier) <= kt + (kt >> VHQ_SH)) { best = L; hi = L - 1; } else lo = L + 1;
    }
    aslv = (u8)best;
    as_cap = snd_end_lv(list, best);
    L = plan_tiers(list, tier, start, tmin);         /* assist battles plan greedy only (load time: the exact planner
                                                        with the store's layouts took up to +60 s) */
    ASD(0x1000 | best | as_t << 8, L);
    return L;
}
#define PLAN0(l, t, st, tm) (as_on ? as_plan((l), (t), (st), (tm), tmin_st) : plan_tiers((l), (t), (st), (tm)))
#ifdef VOICEHI
static int vq_plan(signed char *list, int *tier, u32 start, int tm, int tmin_st)
{
    int s, r, k = VQ_BYTE == 1;
    for (;;) {
        int t = k && tm < AS_TMIN ? AS_TMIN : tm;
        vqhi = k;
        r = as_on ? as_plan(list, tier, start, t, tmin_st) : plan_tiers(list, tier, start, t);
        if (r || !k) return r;
        for (s = 0; s < 4; s++) tier[s] = 0;
        k = 0;
    }
}
#define PLAN(l, t, st, tm) vq_plan((l), (t), (st), (tm), tmin_st)
#else
#define PLAN PLAN0
#endif
#else
#define PLAN plan_tiers
#endif
#ifdef L2PC
/* --l2pc: slot s's chr <-> its unpacked alternate (tables, their sizes / offsets, store-variant tables) */
static void l2sw(signed char *list, int s)
{
    struct chr *h = dirp[list[s]];
    struct l2x *x = l2xp + (h - dir0);
    u32 t, k;
    for (k = 0; k < NT; k++) {
        t = h->tb[k].msf; h->tb[k].msf = x->tbu[k].msf; x->tbu[k].msf = t;
        t = h->tb[k].size; h->tb[k].size = x->tbu[k].size; x->tbu[k].size = t;
#ifdef SPUSTORE
        t = h->bvmsf[k]; h->bvmsf[k] = x->bvu[k]; x->bvu[k] = t;
#endif
    }
    t = h->tabsz; h->tabsz = x->tabszu; x->tabszu = t;
    for (k = 0; k < 3; k++) { t = h->toff[k]; h->toff[k] = x->toffu[k]; x->toffu[k] = t; }
}
static u32 l2cost(signed char *list, int *tier)
{
    u32 c = 0; int s;
    for (s = 0; s < 4; s++) if (list[s] >= 0) c += (u32)CHR(list[s]).cost[tier[s]] * (s < 2 ? 3 : 2);
    return c;
}
/* after the plan: packed frame groups only where they buy a cheaper plan.  First everybody unpacked with no g2get
 * reserve (the rc3.1 tables); if that plan costs no more, L2 is off for this battle.  Else everybody packed, then each
 * slot back to unpacked when the plan still costs no more.  -> slot mask of packed tables (0: no g2get) */
static int l2decide(signed char *list, int *tier, u32 start, int tmin)
{
    int s, m = 0;
    u32 cb = l2cost(list, tier), c, cu;
#ifdef L2PCDBG
    for (s = 0; s < 4; s++) ((volatile u8 *)0x8000ce18u)[s] = (u8)tier[s];      /* packed plan's tiers */
#endif
    for (s = 0; s < 4; s++) if (list[s] >= 0) l2sw(list, s);
    l2res = 0;
    cu = plan_tiers(list, tier, start, tmin) ? l2cost(list, tier) : 0xffffffffu;
#ifdef L2PCDBG                                       /* TEST builds only (Beetle: BIOS data on hardware): the costs */
    ((volatile u32 *)0x8000ce00u)[0] = 0x4c32504bu; ((volatile u32 *)0x8000ce00u)[1] = cb; ((volatile u32 *)0x8000ce00u)[2] = cu;
    for (s = 0; s < 4; s++) ((volatile u8 *)0x8000ce14u)[s] = (u8)tier[s];      /* unpacked plan's tiers */
#endif
    if (cu != 0xffffffffu && cu <= cb + L2PC_MIN) return 0;   /* packing must save more than L2PC_MIN (g2get's cost) */
    for (s = 0; s < 4; s++) if (list[s] >= 0) { l2sw(list, s); m |= 1 << s; }
    l2res = L2RES0;
    for (s = 0; s < 4; s++) {
        if (list[s] < 0) continue;
        l2sw(list, s);
        if (plan_tiers(list, tier, start, tmin) && (c = l2cost(list, tier)) + L2PC_MIN < cu && c <= cb + L2PC_MIN / 2) m &= ~(1 << s);
        else l2sw(list, s);
    }
    if (!m) l2res = 0;
    plan_tiers(list, tier, start, tmin);             /* the chosen tables (fit: an earlier plan) */
#ifdef L2PCDBG
    ((volatile u32 *)0x8000ce00u)[3] = l2cost(list, tier); ((volatile u32 *)0x8000ce00u)[4] = (u32)m;
#endif
    return m;
}
#endif

#ifdef HRFX
static struct hrx *hrfind(int c)
{
    int i;
    for (i = 0; i < hrn; i++) if ((int)hrp[i * (1 + sizeof(struct hrx) / 4)] == c) return (struct hrx *)(hrp + i * (1 + sizeof(struct hrx) / 4) + 1);
    return 0;
}
static void sw32(u32 *a, u32 *b, int n) { u32 t; while (n-- > 0) { t = *a; *a++ = *b; *b++ = t; } }
/* slot s's chr (+ its l2x) <-> its full-res variant; tables must be in the packed state (l2x holds the unpacked ones) */
static void hrsw(signed char *list, int s)
{
    struct chr *h = dirp[list[s]];
    struct hrx *y = hrfind(list[s]);
    sw32((u32 *)h->t, (u32 *)y->t, 2 * NT); sw32((u32 *)h->tb, (u32 *)y->tb, 2 * NT);
    sw32(&h->tabsz, &y->tabsz, 4);
#ifdef L2PC
    {
        struct l2x *x = l2xp + (h - dir0);
        sw32((u32 *)x->tbu, (u32 *)y->tbu, 2 * NT); sw32(&x->tabszu, &y->tabszu, 4);
    }
#endif
}
/* plan + (--l2pc) per-slot packing as tl_main does; 0 = no plan */
static int hrplan(signed char *list, int *tier, u32 start, int tmin, int *l2m)
{
    if (!plan_tiers(list, tier, start, tmin)) return 0;
#ifdef L2PC
    *l2m = l2decide(list, tier, start, tmin);
#endif
    return 1;
}
#ifdef L2PC
static void l2back(signed char *list, int m)    /* l2decide's result (unpacked = not in m) back to all packed */
{
    int s;
    for (s = 0; s < 4; s++) if (list[s] >= 0 && !(m >> s & 1)) l2sw(list, s);
}
#endif
/* AUTO: swap in the variants of the slots in `add` (on top of `have`); keep them when every final tier equals t0, else
 * restore the previous state (same inputs -> same plan).  -> 1 kept */
static int hrtry(signed char *list, int *tier, u32 start, int tmin, const int *t0, int *l2m, int have, int add)
{
    int s, ok, pl, m = 0;
#ifdef L2PC
    l2back(list, *l2m);
#endif
    for (s = 0; s < 4; s++) if (add >> s & 1) hrsw(list, s);
    ok = pl = hrplan(list, tier, start, tmin, &m);
    for (s = 0; s < 4; s++) if (list[s] >= 0 && tier[s] != t0[s]) ok = 0;
    if (ok) { *l2m = m; return 1; }
#ifdef L2PC
    if (pl) l2back(list, m);                        /* (a failed plan_tiers left the tables packed) */
#endif
    for (s = 0; s < 4; s++) if (add >> s & 1) hrsw(list, s);
    hrplan(list, tier, start, tmin, l2m);           /* the previous state again (same inputs -> same plan) */
    (void)have; (void)pl;
    return 0;
}
#endif

/* greedy upgrades: repeatedly the tier change with the best decode-cost saving per extra byte that still fits */
static void upgrade(signed char *list, int *tier, u32 start)
{
    int s;
    for (;;) {
        int bs = -1, bt = 0;
        u32 bg = 0, bd = 1;
        for (s = 0; s < 4; s++) {
            const struct chr *h;
            int t, old = tier[s];
            if (list[s] < 0) continue;
            h = &CHR(list[s]);
            for (t = old + 1; t < NT; t++) {
                u32 g, d, a, b;
                if (!h->t[t].size || h->cost[t] >= h->cost[old]) continue;
                g = (u32)(h->cost[old] - h->cost[t]) * (s < 2 ? 3 : 2);
                a = h->t[t].size; b = h->t[old].size;
                d = a > b ? ((a - b) >> 8) + 1 : 1;
                if (g * bd <= bg * d) continue;
                tier[s] = t;
                if (total(list, tier, start)) { bs = s; bt = t; bg = g; bd = d; }
                tier[s] = old;
            }
        }
        if (bs < 0) break;
        tier[bs] = bt;
    }
}

/* flags bit8 (mktag --rescue): the greedy order can leave a character on DSA1 (cost >= 3000) although its smallest
 * non-DSA1 tier would fit with the others lower (fitmodel.py plan(rescue)): try each DSA1 character on that tier,
 * the others back at the floor and upgraded again; keep the plan with fewer DSA1 characters, then the lower cost */
static int ndsa(signed char *list, const int *tier)
{
    int s, n = 0;
    for (s = 0; s < 4; s++) if (list[s] >= 0 && CHR(list[s]).cost[tier[s]] >= 3000) n++;
    return n;
}
static u32 wcost(signed char *list, const int *tier)
{
    int s; u32 w = 0;
    for (s = 0; s < 4; s++) if (list[s] >= 0) w += (u32)CHR(list[s]).cost[tier[s]] * (s < 2 ? 3 : 2);
    return w;
}
static void rescue(signed char *list, int *tier, u32 start, int tmin)
{
    int s, k, t, best[4], cand[4], tr[4], have;
    for (k = 0; k < 4; k++) best[k] = tier[k];
    while (ndsa(list, best)) {
        have = 0;
        for (s = 0; s < 4; s++) {
            const struct chr *h;
            int t2 = -1;
            if (list[s] < 0) continue;
            h = &CHR(list[s]);
            if (h->cost[best[s]] < 3000) continue;
            for (t = tmin; t < NT; t++)
                if (h->t[t].size && h->cost[t] < 3000 && (t2 < 0 || h->t[t].size < h->t[t2].size)) t2 = t;
            if (t2 < 0) continue;
            for (k = 0; k < 4; k++) tr[k] = tmin;
            tr[s] = t2;
            if (!total(list, tr, start)) continue;
            upgrade(list, tr, start);
            if (ndsa(list, tr) > ndsa(list, best) || (ndsa(list, tr) == ndsa(list, best) && wcost(list, tr) >= wcost(list, best))) continue;
            if (have && (ndsa(list, tr) > ndsa(list, cand) || (ndsa(list, tr) == ndsa(list, cand) && wcost(list, tr) >= wcost(list, cand)))) continue;
            for (k = 0; k < 4; k++) cand[k] = tr[k];
            have = 1;
        }
        if (!have) break;
        for (k = 0; k < 4; k++) best[k] = cand[k];
    }
    for (k = 0; k < 4; k++) tier[k] = best[k];
}

#ifdef ASSIST
static u32 as_own[2][4];                    /* the assists' front-end owners {spu lo, spu hi, section, streams} */
/* an SPU-tier assist file at D (n bytes, tools/assist/asvar.py): streams [keep, n) -> SPU at a, every tile entry of the
 * tile table tab (ntile x 5 B) becomes a proxy (as sps_cut); the stream starts are 8-aligned, sorted in the freed tail */
static void as_cut(int q, u8 *D, u32 n, u32 keep, u32 a, u8 *tab, int ntile)
{
    u32 m = n - keep, sec0 = (u32)D + 0x14, len0 = n - 0x14, cs = len0 - m, *U = (u32 *)(D + keep);
    int i, k, nu = 0, lo, hi;
    u8 *tmp = D + keep;                              /* streams uploaded first, then the tail is the scratch */
    SPS_DRAIN();
    *(u16 *)0x8001e90cu = (u16)(a >> 3); *(volatile u16 *)0x1f801da6u = (u16)(a >> 3);
    SPUWR(tmp, ((m + 63) & ~63u) + SPS_PAD);
    SPUFIN();
    SPS_DRAIN();
    for (i = 0; i < ntile; i++) {
        u8 *e = tab + 5 * i;
        u32 off = e[0] | e[1] << 8 | (e[2] & 0x3f) << 16;
        if (off < cs || off >= len0) continue;
        for (k = nu; k > 0 && U[k - 1] > off; k--) ;
        if (k > 0 && U[k - 1] == off) continue;
        for (lo = nu; lo > k; lo--) U[lo] = U[lo - 1];
        U[k] = off; nu++;
    }
    for (i = 0; i < ntile; i++) {
        u8 *e = tab + 5 * i;
        u32 off = e[0] | e[1] << 8 | (e[2] & 0x3f) << 16, nx, px;
        if (off < cs || off >= len0) continue;
        for (lo = 0, hi = nu - 1; lo < hi; ) { k = (lo + hi) >> 1; if (U[k] < off) lo = k + 1; else hi = k; }
        nx = lo + 1 < nu ? U[lo + 1] : len0;
        for (k = 0, lo = (nx - off + 63) >> 6; k < 7 && SPS_BLK[k] < lo; k++) ;
        px = SPS_WB + ((u32)k << 16 | (a + off - cs) >> 3);
        px -= sec0;
        e[0] = px; e[1] = px >> 8; e[2] = (e[2] & 0xc0) | ((px >> 16) & 0x3f);
    }
    as_own[q][0] = a; as_own[q][1] = a + ((m + 63) & ~63u); as_own[q][2] = sec0 | AS_RL; as_own[q][3] = nu;
}
#endif
#ifdef SPUSTORE
/* slot s: its store variant was read to D (n bytes); the last sps_mv[s] bytes (cold streams, 8-aligned, <= 2048 B
 * each) go to SPU at sps_at[s]; their tile-table entries become proxies 0x80210000 + (class << 16 | spu >> 3) (as an
 * offset from the section: the engine adds it back).  The freed RAM tail is the scratch for the sorted offsets. */
static void sps_cut(int s, const struct chr *h, u8 *D, u32 n, u8 *tab)
{
    u32 m = sps_mv[s], sec0 = (u32)D + 0x14, len0 = n - 0x14, cs = len0 - m, *U = (u32 *)(D + n - m);
    int i, k, nu = 0, lo, hi;
    /* SpuSetTransferStartAddr refuses starts > 0x7eff8 (the tail span reaches 0x7ffc0): its two stores by hand */
    SPS_DRAIN();
    *(u16 *)0x8001e90cu = (u16)(sps_at[s] >> 3); *(volatile u16 *)0x1f801da6u = (u16)(sps_at[s] >> 3);
    SPUWR(D + n - m, ((m + 63) & ~63u) + SPS_PAD);
    SPUFIN();
    SPS_DRAIN();
    for (i = 0; i < h->ntile; i++) {
        u8 *e = tab + 5 * i;
        u32 off = e[0] | e[1] << 8 | e[2] << 16;
        if (off < cs || off >= len0) continue;
        for (k = nu; k > 0 && U[k - 1] > off; k--) ;
        if (k > 0 && U[k - 1] == off) continue;
        for (lo = nu; lo > k; lo--) U[lo] = U[lo - 1];
        U[k] = off; nu++;
    }
    for (i = 0; i < h->ntile; i++) {
        u8 *e = tab + 5 * i;
        u32 off = e[0] | e[1] << 8 | e[2] << 16, nx, px;
        if (off < cs || off >= len0) continue;
        for (lo = 0, hi = nu - 1; lo < hi; ) { k = (lo + hi) >> 1; if (U[k] < off) lo = k + 1; else hi = k; }
        nx = lo + 1 < nu ? U[lo + 1] : len0;
        for (k = 0, lo = (nx - off + 63) >> 6; k < 7 && SPS_BLK[k] < lo; k++) ;   /* length class */
        px = SPS_WB + ((u32)k << 16 | (sps_at[s] + off - cs) >> 3);   /* < 2 MB: --chk owns offset bit 21 */
        px -= sec0;                           /* < 4 MB: the entry parser 0x8008cac8 keeps 22 offset bits */
        e[0] = px; e[1] = px >> 8; e[2] = (e[2] & 0xc0) | ((px >> 16) & 0x3f);
    }
    sps_own[s][0] = sps_at[s]; sps_own[s][1] = sps_at[s] + ((m + 63) & ~63u); sps_own[s][2] = sec0; sps_own[s][3] = nu;
}
#endif

int tl_main(signed char *list)
{
    int s, k, o, tier[4], tmin0;
#ifdef ASSIST
    int tmin_st;
#endif
    u32 cur, p, start;
#ifdef L2PC
    int l2mask = 0;
#endif
    u32 old_msf = FTAB[SPARE * 2], old_size = FTAB[SPARE * 2 + 1];
#ifdef KOCACHE
    u32 kof[8];                                             /* per slot: the sprite file's {msf, size} (kocache.py) */
#endif

    tl_dbg[0] = 0; tl_dbg[1] = 0; tl_dbg[2] = 0; tl_dbg[3] = 0;
#ifdef ONSL
    *(volatile u32 *)0x8004b694u = 0x08012db6u;     /* --onsl: stock time-over join (j 0x8004b6d8); an Onslaught load below
                                                       hooks it to his time-over stub (gameplay/onsl.py), every load resets */
#ifndef L2G
    flushcache();
#endif
#endif
#ifdef L2G
    *(volatile u32 *)L2_SITE = 0;                   /* stock nop: no g2get call unless this battle installs it below */
    flushcache();
#endif
#ifdef L1B
    *(volatile u32 *)L1B_SITE0 = 0; *(volatile u32 *)L1B_SITE1 = 0;   /* stock nops: no remap unless installed below */
    flushcache();
#endif
#ifdef CUTIN
    *(volatile u32 *)CUTIN_SITE_DEC = CUTIN_W_DEC; *(volatile u32 *)CUTIN_SITE_LI = CUTIN_W_LI;   /* stock cut-in path */
    flushcache();
#endif
#ifdef KOFIX
    *(volatile u32 *)0x80045f24u = 0x0c0229c0u;     /* stock rematch path (jal 0x8008a700: stage only), see below */
#endif
    CACHE = 0;
    tl_postfn = 0; postvc = 0; vcpend[0] = vcpend[1] = 0;
#ifdef VCACHE
    *(volatile u32 *)VC_FLAG = 0; vcon = 0;                  /* stub (EXE) takes the stock path until the copy below */
#endif
#ifdef KOCACHE
    for (k = 0; k < 8; k++) kof[k] = 0;
#endif
    snd_reset();                                     /* stock bank addresses (also when declining) */
#ifdef SPUSTORE
    TAB11 = 0; sps_ok = 0;                           /* no proxy section unless this battle installs one */
    for (s = 0; s < 4; s++) sps_mv[s] = 0;
#ifdef SPS_FIX
    /* --spsfix (rc4): the front end serves proxies by its owner table alone; dxahead still decodes the previous
     * battle's (proxied) tiles during this load (scene 8), and that fetch's SPU DMA cut the COMMON upload below
     * after ~8 KB (RAM table / SPU at different levels -> a looping voice froze the post-Onslaught ending).
     * No owners until this battle installs its own (below): stale proxies take the front end's error return. */
    { u32 *d = (u32 *)SPS_DATA; for (s = 8; s < 24; s++) d[s] = 0; }
#endif
#endif
    LOADER_FULL = 0;
#ifdef ASSIST
    AS_SAVE = 0; as_on = 0; as_cap = 0; aslv = 0xff; as_quick = 0;
#endif
#ifdef STAGEANIM
    *(volatile u32 *)STAGEANIM_SA = 0;      /* STAGE ANIM RAM part (stageanim.py): its magic off while the reads below use
                                               the top of RAM as scratch (the object walkers keep running on the loading
                                               screen); the strong-payload copy at the end restores it */
#endif
    if (tl_dir.magic != 0x4c474154) { tl_dbg[0] = 0xfd; return 0; }
#ifdef DIRX
    {                                                /* full directory to the region start (nothing placed yet) */
        u32 st0 = *(u32 *)(tl_dbg + 8);
        if (st0 < 0x80090000u || st0 > REGION_START) st0 = REGION_START;
        st0 = a8(st0);
        rd_item(&tl_dir.full, (void *)st0);
        for (k = 0; k < 0x17; k++) dirp[k] = (struct chr *)st0 + k;
#ifdef L2PC
        dir0 = (struct chr *)st0;                    /* alternates after the chr entries: n chr + n l2x */
#ifdef HRFX
        hrn = *(int *)(st0 + tl_dir.full.size - 4);
        hrp = (u32 *)(st0 + tl_dir.full.size - 4 - hrn * (4 + sizeof(struct hrx)));
        l2xp = (struct l2x *)(st0 + ((u32)hrp - st0) / (sizeof(struct chr) + sizeof(struct l2x)) * sizeof(struct chr));
#else
        l2xp = (struct l2x *)(st0 + tl_dir.full.size / (sizeof(struct chr) + sizeof(struct l2x)) * sizeof(struct chr));
#endif
        l2res = L2RES0;
#endif
#ifdef KORELOAD
        {                                            /* switch directory [0x17][NT] after it (frag[0..1] = its fent) */
            struct krl_fent *kd = (struct krl_fent *)a8(st0 + tl_dir.full.size);
            struct fent kf; int q, t;
            kf.msf = tl_dir.frag[0]; kf.size = tl_dir.frag[1];
            rd_item(&kf, kd);
            for (q = 0; q < 4; q++)
                for (t = 0; t < NT; t++) {
                    if (list[q] >= 0 && list[q] < 0x17) kpl[q][t] = kd[list[q] * NT + t];
                    else { kpl[q][t].msf = 0; kpl[q][t].size = 0; }
                }
        }
#endif
#ifdef SPUSTORE
        snd_table((void *)(st0 + a8(tl_dir.full.size)));   /* SNDX: sound level table after it */
#endif
#ifdef ASSIST
        asd = 0;                                     /* assist table after the sound table (8 KB) */
        if (tl_asx.size) { asd = (struct asx *)(st0 + a8(tl_dir.full.size) + 0x2000); rd_item(&tl_asx, asd); }
#endif
#ifdef SHARE
        npair = 0;                                   /* pair entries after the 0x17 characters: base, variant */
        pdir = (struct chr *)st0 + 0x17;
#ifdef L2PC
        pnum = (int)((tl_dir.full.size / (sizeof(struct chr) + sizeof(struct l2x)) - 0x17) / 2);
#else
        pnum = (int)((tl_dir.full.size / sizeof(struct chr) - 0x17) / 2);
#endif
#ifdef AP8MOD
        pnum = 0;                                    /* 8 MB: every character its own stock file */
#endif
#endif
    }
#endif
    if (MODE < 0 || MODE == 2 || MODE > 3 || !HUMANS) { tl_dbg[0] = 0xf9; return 0; }   /* 0 ARCADE, 1 VERSUS, 3 TRAINING (gameplay/selscreen.py: real dummy partner) */
#if !defined(ONSL) && !defined(ONSLP1)    /* --onsl / --onslp1: blob space (mktag asserts no --force with them; with it
                                              --onsl = 31,920 B > 31,800: the block costs 232 B under -Os) */
    if (tl_dir.flags & 2) {                          /* test builds: fixed team (hardware runs without RAM pokes) */
        static const u8 slot_of[4] = { 0, 2, 1, 3 }; /* TEAM order -> slot order */
        signed char ch[4];
        for (k = 0; k < 4; k++) {
            *(s16 *)(0x8007b8aau + 2 * k) = (s16)(tl_dir.force[k] * 2);
            ch[slot_of[k]] = tl_dir.force[k];
        }
        for (s = 0; s < 4; s++) {                    /* the stock dedup: a repeated character shares the first slot */
            list[s] = ch[s];
            for (k = 0; k < s; k++)
                if (ch[k] == ch[s]) { list[s] = -(k + 1); break; }
        }
    }
#endif
    if (tl_dir.flags & 4) { tl_dbg[0] = 0xf8; return 0; }      /* A/B baseline builds: stock loading, same team */
    for (s = 0; s < 4; s++) {
        int c = list[s];
        tier[s] = 0;
        if (c < 0) { tl_dbg[1 + (s & 1)] |= 10 << (4 * (s >> 1)); continue; }
#if defined(ONSLP1) || defined(ONSL)   /* --onslp1 (assist bugs lead): ARCADE played by P2 -> the CPU boss Onslaught is the P1
         * main: accepted (before: 0xfc -> stock loading under the tag build -> NOW LOADING hang); --onsl: a human Onslaught
         * (playable, tools/gameplay/onsl.py) on either side, same rules */
        if (c < 1 || c > 0x16 || (c == 0x11 && s > 1) || !CHR(c).a0.size) { tl_dbg[0] = 0xfc; return 0; }
#else
        if (c < 1 || c > 0x16 || (c == 0x11 && s != 1) || !CHR(c).a0.size) { tl_dbg[0] = 0xfc; return 0; }
#endif
    }
    /* Onslaught (P2 main, its partner word shares slot 0): on stage 9 the stage code copies its data to
     * 0x801fa200-0x801fe800 and uses 0x801f7200 as a buffer (0x8002b544 -> 0x800a0bd0 / 0x800a0c04) */
#if defined(ONSLP1) || defined(ONSL)   /* --onslp1 / --onsl: either side; the P1 Onslaught's stage buffer is moved to the same
         * P2-partner-slot area by the EXE word 0x8002b730 (tools/gameplay/onslp1.py; --onsl adds it too) */
    if (list[0] == 0x11 || list[1] == 0x11) { TOP = TOP_ONSL; STRONG = TOP_ONSL - ((tl_dir.dec_size + 7) & ~7u); }
#else
    if (list[1] == 0x11) { TOP = TOP_ONSL; STRONG = TOP_ONSL - ((tl_dir.dec_size + 7) & ~7u); }
#endif
    else { TOP = TOP0; STRONG = tl_dir.strong_size ? tl_dir.strong_at : TOP0; }
#ifndef KO_RD
#define KO_RD KO_AT                      /* --kosplit (dx): the 2-sector KO item starts below KO_AT */
#endif
#ifdef PAL8
    if (TOP == TOP0 && *(volatile u8 *)0x8007bdd9u == 8) {      /* stage-8 palette rows to VRAM (pal8.py): the KO + pal8
                                                                    code sector, upload through the free top of RAM, hooks */
        static const struct fent p8s = { KO_MSF, KO_SIZE };
        rd_item(&p8s, (void *)KO_RD);
        ((void (*)(u32))P8UP)(P8BUF);
        *(u32 *)P8APSITE = 0x08000000u | ((P8AP >> 2) & 0x03ffffffu);     /* stage-8 frame apply -> packed lists */
        *(u32 *)(P8APSITE + 4) = 0;
        *(u32 *)P8HSITE = 0x0c000000u | ((P8HC >> 2) & 0x03ffffffu);
        flushcache();
    }
#endif
#ifdef SPUSTORE
    sps_ok = TOP == TOP0 && tl_dir.strong_size;      /* Onslaught: stage 9 owns the kernel span; plain tier files */
#ifdef SPS_NOSTORE
    sps_ok = 0;                                      /* --spsnostore: store never used (rc3; spustore pieces in SPU RAM broke the
                                                        post-Onslaught ending: a voice never ends, 0x8008707c waits forever) */
#endif
#endif
    postvc = (tl_dir.flags & 128) && TOP == TOP0 && tl_dir.strong_size;
    start = *(u32 *)(tl_dbg + 8);
    if (start < 0x80090000u || start > REGION_START) start = REGION_START;
    start = a8(start);
#ifdef AP8UP
    start = AP8_START;
#endif
    /* ARCADE: the CPU team's partner word equals its main (the stock arcade has no CPU partner); give the CPU a
     * distinct random partner when four full characters fit, else keep the mirror (shared data) */
    if (MODE == 0 && list[3] < 0 && list[1] != 0x11 && *(s16 *)0x8007b8b0u == *(s16 *)0x8007b8aeu) {
        int p2 = *(s16 *)0x8007b8aeu / 2;                   /* CPU main (list[1] may share slot 0: mirror) */
        int pass, cand[16], nc = 0;
        for (k = 0; k < 16; k++) {                   /* a random order of the candidates */
            int c = (RAND() & 15) + 1, j;
            if (c == list[0] || c == p2 || c == list[2] || !CHR(c).a0.size) continue;
            for (j = 0; j < nc && cand[j] != c; j++) ;
            if (j == nc) cand[nc++] = c;
        }
        {
            signed char keep = list[3];
            list[3] = -1;
            for (pass = 0; pass < 2 && list[3] < 0; pass++) {   /* first without frame cuts, then any */
            for (s = 0; s < 4; s++) tier[s] = pass ? 0 : (int)tl_dir.ncut;
            for (k = 0; k < nc; k++) {
                list[3] = (signed char)cand[k];
                plan_spu(list);
                plan_frag(list);
                if (total(list, tier, start)) { *(s16 *)0x8007b8b0u = (s16)(cand[k] * 2); break; }
                list[3] = -1;
            }
            }
            if (list[3] < 0) list[3] = keep;
        }
        for (s = 0; s < 4; s++) tier[s] = 0;
        tl_dbg[2] &= 0x0f;
        if (list[3] < 0) tl_dbg[2] |= 10 << 4;
    }
    {
        int tmin = (TOP != TOP0 && !(tl_dir.flags & 16)) ? (int)tl_dir.nstrong : 0;
        tmin0 = tmin;
#ifdef AP8MOD
        tmin0 = NT - 1;                              /* stock RLE sprite files only (no cut / codec tiers) */
#endif
    }
#ifdef ASSIST
    {                                                /* the select's assists (bit + id per side) */
#ifndef ASARC
        int q, b = ASSIST_BITS & 3;
#else   /* assist bugs (--asarc): EXE function (tools/gameplay/asarc.py, 0x8003c310) = the bits, but 3 in ARCADE with one
         * human, as assistsel.py's VS-screen stub `vsas`: START after a win skips the stage + VS screens (EXE path
         * 0x80046d3c), vsas never ran -> no assists from stage 2 on.  Onslaught on the P1 side (human on P2): none. */
        int q, b = ((int (*)(void))0x8003c310u)();
        if (list[0] == 0x11) b &= 2;
#endif
#ifdef ASPS3
        /* (--asps3, 2026-11-26) PS2 / PS3 PS1-mode ROM (BCD date at 0xbfc00100 >= 2001, as the ach boot stub): no assists,
         * hence no SPU store (sps_ok follows as_on: no front end, fake section, mirror proxies or raw DMA4) -
         * the store froze every assist battle on the PS3 (webMAN ps1_netemu). */
        if (*(volatile u32 *)0xbfc00100u >= 0x20010000u) b = 0;   /* the row bytes stay untouched (forcing them froze the
                                                                         EX OPTIONS page on the PS3, mvc_ps3t_gate) */
#endif
        if (list[1] == 0x11) b &= 1;                 /* Onslaught: the boss side has none */
        for (q = 0; q < 2; q++) {
            int a = AS_IDS[q] >> 2;
            as_a[q] = ((b >> q) & 1) && a >= 0 && a < 0x16 && asd ? a : -1;
            if (as_a[q] >= 0) copy((u8 *)&as_e[q], (const u8 *)&asd[a], sizeof(struct asx));
        }
        as_same = as_a[0] >= 0 && as_a[0] == as_a[1];
        as_on = as_a[0] >= 0 || as_a[1] >= 0;
#ifdef SPUSTORE
        sps_ok = as_on && TOP == TOP0 && tl_dir.strong_size;   /* the store only in assist battles */
#endif
    }
#endif
#ifdef ASSIST
    tmin_st = tmin0;
    if (as_on && tmin0 < AS_TMIN) tmin0 = AS_TMIN;
#endif
    CACHE = 0;
#ifdef SHARE
    {                                                /* pairs in the final list (after the ARCADE partner pick) */
        int q;
        npair = 0;
        for (q = 0; q < pnum && npair < 2; q++) {
            int sb = -1, su = -1;
            for (s = 0; s < 4; s++) {
                if (list[s] == pdir[2 * q].pb) sb = s;
                if (list[s] == pdir[2 * q].pu) su = s;
            }
            if (sb >= 0 && su >= 0) { psb[npair] = sb; psu[npair] = su; pent[npair] = pdir + 2 * q; npair++; }
        }
    }
    if (npair) {                                     /* the pairs' union pixel files serve both slots; if that plan */
        struct chr *ob[2], *ou[2];                   /* does not fit, the normal one */
        int q;
        for (q = 0; q < npair; q++) {
            ob[q] = dirp[list[psb[q]]]; ou[q] = dirp[list[psu[q]]];
            dirp[list[psb[q]]] = pent[q]; dirp[list[psu[q]]] = pent[q] + 1;
        }
        for (s = 0; s < 4; s++) tier[s] = 0;
        if (!PLAN(list, tier, start, tmin0)) {
            for (q = 0; q < npair; q++) { dirp[list[psb[q]]] = ob[q]; dirp[list[psu[q]]] = ou[q]; }
            npair = 0;
            for (s = 0; s < 4; s++) tier[s] = 0;
        }
    }
    if (!npair)
#endif
#ifdef ASSIST
    if (!PLAN(list, tier, start, tmin0)) {           /* no plan with the assists: this battle without them */
        ASD(0xdead, npair_dbg());
        as_on = 0; as_a[0] = as_a[1] = -1; as_cap = 0; tmin0 = tmin_st; as_quick = 0;
#ifdef SPUSTORE
        sps_ok = 0;
#endif
        if (!plan_tiers(list, tier, start, tmin0)) { tl_dbg[0] = 0xfe; return 0; }
    }
#else
    if (!plan_tiers(list, tier, start, tmin0)) { tl_dbg[0] = 0xfe; return 0; }
#endif
#ifdef FECACHE
    if ((tl_dir.flags & 64) && TOP == TOP0 && tl_dir.strong_size) {  /* decoded-tile cache (fecache.S): only RAM the tiers */
        static const u32 csz[2] = { 0xa20 + 0x4000, 0xa20 + 0x2000 };  /* can spare: no character may get a DSA1 tier */
        int t0[4], q, ok;                                             /* it did not have without the cache, and */
        u32 c0 = 0, c1;                                               /* the weighted tier cost may rise <= 1/16 */
        for (s = 0; s < 4; s++) {                                     /* (measured: a cache bought with upgrades */
            t0[s] = tier[s];                                          /* worth more than that was a net loss) */
            if (list[s] >= 0) c0 += (u32)CHR(list[s]).cost[tier[s]] * (s < 2 ? 3 : 2);
        }
        for (q = 0; q < 2; q++) {
            CACHE = a8(csz[q]);
            ok = plan_tiers(list, tier, start, tmin0);
            for (s = 0, c1 = 0; ok && s < 4; s++) {
                if (list[s] < 0) continue;
                if (CHR(list[s]).cost[tier[s]] >= 3000 && CHR(list[s]).cost[t0[s]] < 3000) ok = 0;
                c1 += (u32)CHR(list[s]).cost[tier[s]] * (s < 2 ? 3 : 2);
            }
            if (ok && c1 > c0 + (c0 >> 4)) ok = 0;
            if (ok) break;
            CACHE = 0;
        }
        if (!CACHE) plan_tiers(list, tier, start, tmin0);
    }
#endif
#ifdef KORELOAD
    krlon = 0;
    if (TOP == TOP0 && tl_dir.strong_size && STRONG == KRL_AT + KRL_SIZE) {
        int t0[4];
        for (s = 0; s < 4; s++) t0[s] = tier[s];
        CACHE = KRL_SIZE;
        if (plan_tiers(list, tier, start, tmin0)) krlon = 1;
        else { CACHE = 0; for (s = 0; s < 4; s++) tier[s] = t0[s]; plan_tiers(list, tier, start, tmin0); }
    }
#define VC_TOP (VC_AT + VC_SIZE + KRL_SIZE)
#else
#define VC_TOP (VC_AT + VC_SIZE)
#endif
#ifdef VCACHE
    if (NOT8 && TOP == TOP0 && tl_dir.strong_size && STRONG == VC_TOP
        && (VC_STAGES >> (*(volatile u8 *)0x8007bdd9u & 15) & 1)                 /* per-stage VRAM budget (vcache.py) */
#if defined(PAL8) && !defined(VCP8SMALL)
        && *(volatile u8 *)0x8007bdd9u != 8          /* --pal8 owns stage 8's free VRAM; the 4 KB rest cost more RAM than it gave */
#endif
        ) {   /* the cache only when no character gets a */
        int t0[4], ok;                                       /* DSA1 tier it did not have without it */
        for (s = 0; s < 4; s++) t0[s] = tier[s];
        CACHE = STRONG - VC_AT;                      /* (--koreload: its image above the cache) */
        ok = plan_tiers(list, tier, start, tmin0);
#ifdef VCGATE                                        /* VCGATE (test builds): no cache when a tier drops to DSA1 */
        for (s = 0; ok && s < 4; s++)
            if (list[s] >= 0 && CHR(list[s]).cost[tier[s]] >= 3000 && CHR(list[s]).cost[t0[s]] < 3000) ok = 0;
#endif
        if (!ok) {
#ifdef KORELOAD
            CACHE = krlon ? KRL_SIZE : 0;
#else
            CACHE = 0;
#endif
            plan_tiers(list, tier, start, tmin0);
        }
        vcon = ok;
    }
#endif
#ifdef L2PC
    l2mask = l2decide(list, tier, start, tmin0);      /* packed frame groups only where they buy a cheaper plan */
#ifdef AP8MOD
    l2mask = 0;                                      /* 8 MB: stock tables (no g2get) */
#endif
    if (l2mask) tl_dbg[3] |= 0x10;
#endif
#ifdef HRFX
    hrhave = 0;
    if (hrn && !*(volatile u8 *)HRFX_BYTE) {           /* HI-RES FX AUTO: full-res variants that cost no tier */
        int t0[4], want = 0, have = 0, m0 = 0;
#ifdef L2PC
        m0 = l2mask;
#endif
        for (s = 0; s < 4; s++) { t0[s] = tier[s]; if (list[s] >= 0 && hrfind(list[s])) want |= 1 << s; }
#ifdef SHARE
        {   /* (integrator, rc4.3) a slot of an active --share pair draws through the pair's union entry (dirp -> pent,
               the variant slot reads the base's pixels): hrsw would put one character's full-res files under the
               union tables -> broken partner (tagchk c,6,e,12: Red Venom never entered).  Pairs stay half res. */
            int q;
            for (q = 0; q < npair; q++) want &= ~((1 << psb[q]) | (1 << psu[q]));
        }
#endif
        if (want && hrtry(list, tier, start, tmin0, t0, &m0, 0, want)) have = want;
        else for (s = 0; s < 4; s++) if ((want >> s & 1) && hrtry(list, tier, start, tmin0, t0, &m0, have, 1 << s)) have |= 1 << s;
#ifdef L2PC
        l2mask = m0;
        if (l2mask) tl_dbg[3] |= 0x10; else tl_dbg[3] &= ~0x10;
#endif
        hrhave = have;
    }
    for (s = 0; s < 4; s++) hrtier[s] = (u8)tier[s];
#endif
    {                                                        /* [12..15] = fragments in use (tl_restore) */
        u32 m = 0, a;
        for (s = 0; s < 14; s++) {
            a = s < 12 ? tabat[s / 3][s % 3] : vcat[s - 12];
            if (!a) continue;
            for (k = 0; k < (int)tl_dir.nfrag; k++)
                if (a >= tl_dir.frag[3 * k] && a < tl_dir.frag[3 * k + 1] && (tl_dir.frag[3 * k + 2] >> 31)) m |= 1u << k;
        }
        *(u32 *)(tl_dbg + 12) = m;
    }

#ifdef DIRX
    for (s = 0; s < 4; s++)                          /* before the first placement overwrites the region start */
        if (list[s] >= 0) { copy((u8 *)&tl_dir.c[s], (const u8 *)dirp[list[s]], sizeof(struct chr)); dirp[list[s]] = &tl_dir.c[s]; }
#endif
#ifdef SPUSTORE
    total(list, tier, start);                        /* the final plan's SPU shares (sps_mv / sps_at / sps_stg) */
#endif
    snd_spu_end = spu0;                              /* plan_spu may have lowered the kind-6 area */
#ifdef ASSIST
    if (as_on) snd_spu_end = as_cap;                 /* assists: the level as_search found, SPC + store above it */
#ifdef AP8MOD
    if (as_on) snd_spu_end = as_spu;                 /* 8 MB streaming: up to the assists' SPC area (pool region 1) */
#endif
    for (s = 0; s < 4; s++) astier[s] = (u8)tier[s];
#endif
    snd_plan(list);                                  /* sound level, SPU layout, COMMON (tools/snd) */
#ifdef ASSIST
    if (as_on) {                                     /* SPCxx: samples at as_spu.., entries in COMMON slots 127.. */
        int q, k0 = 127;
        u32 a = as_spu;
        for (q = 0; q < 2; q++) {
            int idx;
            u8 *T;
            if (as_a[q] < 0 || (q && as_same)) continue;
            idx = 0xf8 + 44 * q + 2 * as_a[q];
            T = (u8 *)((RTOP - sec(fsize(idx))) & ~7u);
            RD(idx, T);
            k0 += snd_assist(T, fsize(idx), a, k0);
            a = (a + fsize(idx) + 63) & ~63u;
        }
        as_pat = a;                                  /* then the SPU-tier streams */
    }
#endif
    /* load, in the planned order */
    cur = start;
#ifdef ASSIST
    if (as_on) {                                     /* assists first, as total() placed them */
        int q;
        u8 *Tq = 0, *Dq = 0;
#ifdef AP8FR
        u8 *Rq = 0;
#endif
        u32 sa = as_pat;
        as_own[0][0] = as_own[0][1] = as_own[1][0] = as_own[1][1] = 0;
        for (q = 0; q < 2; q++) {
            const struct asx *e = &as_e[q];
            u8 *P, *T, *D;
            int d;
            u32 n;
            if (as_a[q] < 0) continue;
#ifdef AP8FR
            if (q && as_same && Rq) { u32 *dh = (u32 *)Rq; D04(9, 0, Rq + 0x14, Rq + dh[2], Rq + dh[3], Rq + dh[4], 8); AS_HUD(q); continue; }
#endif
            if (q && as_same) { D04(9, 0, Dq + 0x14, Tq + e->toff[0], Tq + e->toff[1], Tq + e->toff[2], 8); AS_HUD(q); continue; }
            P = (u8 *)cur;
            rd_item(&e->a0, P);
#ifdef AP8FR
            Rq = ap8_aspatch(as_a[q], P);                /* 8 MB arcade frames: stock table + restored records, sprite file */
            if (Rq) Rq += ((u32 *)Rq)[3];                /* from the upper-RAM record (Rq = the DSP) */
#endif
            d = (int)((u32)P - AS_LINK);
            reloc((u32 *)P, (const u16 *)(P + e->codesz), d);
            flushcache();
            ((void (*)(int))((u32)P + 4))(d);            /* init: per-assist handler pointers */
            cur = a8(cur + e->codesz);
#ifdef AP8FR
            if (Rq) { u32 *dh = (u32 *)Rq; D04(8 + q, 0, Rq + 0x14, Rq + dh[2], Rq + dh[3], Rq + dh[4], 8); AS_HUD(q); continue; }
#endif
            T = (u8 *)cur; rd_item(&e->tb[AT(q)], T); cur = a8(cur + e->tabsz);
            D = (u8 *)cur; n = rd_item(&e->t[AT(q)], D);
            if (e->spu[AT(q)]) { as_cut(q, D, n, e->keep[AT(q)], sa, T + e->toff[1], e->ntile); sa += ((e->spu[AT(q)] + 63) & ~63u) + SPS_PAD; }
            cur = a8(cur + e->keep[AT(q)]);
            D04(8 + q, 0, D + 0x14, T + e->toff[0], T + e->toff[1], T + e->toff[2], 8);
            AS_HUD(q);
            Tq = T; Dq = D;
        }
        tl_dbg[3] |= 0x20;
        AS_SAVE = (u8)((as_a[0] >= 0) | (as_a[1] >= 0) << 1);
    }
#endif
#ifdef SHARE
    u8 *sh_d[4]; u8 *sh_p[4][3];
#endif
    for (o = 0; o < 4; o++) {
        s = ord[o];
        const struct chr *h;
        u8 *F, *T, *D;
        u32 *hdr, kept;
        int c = list[s], n;
        if (c < 0) continue;
        h = &CHR(c);
        /* sound bank first, read to the top of the region (tools/snd: the full bank of every character) */
        if (s < 2 && c == 0x10) mmvariant(s);
        if (snd_load(s, c, RTOP)) ;
        else if (s < 2) {
            int idx = main_se(c, s);
            if (c == 0x10) idx += MMVAR;
            T = (u8 *)((RTOP - sec(fsize(idx))) & ~7u);
            n = RD(idx, T);
            SND(s + 1, T, n, c);
        } else {
            T = (u8 *)((RTOP - sec(fsize(part_a0(c, s)))) & ~7u);
            RD(part_a0(c, s), T);
            hdr = (u32 *)T;                                   /* u32 3, (off, size) x 3: section 3 = bank */
            SND(s + 1, T + hdr[5], hdr[6], part_chr(c, s));
        }
        /* code + set */
        p = place(cur, h);
        F = (u8 *)(p - h->hdr);
        rd_item(&h->a0, F);
#ifdef AP8MOD
        ap8_uncut(c, F);                                         /* 8 MB: no frame substitution (stock tables) */
#endif
        T = (u8 *)((RTOP - sec(h->st.size)) & ~7u);              /* part B: set + relocation table, scratch */
        rd_item(&h->st, T);
        reloc((u32 *)F, (const u16 *)(T + h->a0size), (int)(p - SLOT0));
        flushcache();
        ((init_t)(INITM[c] + (p - SLOT0)))(&INITM[c], SLOT0);
        if (h->xoff) *(u32 *)0x80078a4cu = (u32)F + h->xoff;     /* Onslaught: giant-form block (stock main loader) */
#ifdef ONSL
        if (h->xoff) *(volatile u32 *)0x8004b694u = 0x08000000u | ((((u32)F + h->xoff - ONSL_TO) >> 2) & 0x03ffffffu);
#endif
        if (ramset[s]) {
            copy(F + h->setoff, T, h->setsize);
            REG(s + 4, F + h->setoff, 0);
            kept = rnd8(h->setsize);
            tl_dbg[3] |= 1 << s;
        } else {                                                /* pixels to SPU from the scratch copy, then the */
            u32 r = STASH(s + 4, T, 4, h->setsize, spuat[s]);   /* kept part down to F + setoff, pointers moved  */
            int dl = (int)(F + h->setoff - T);
            copy(F + h->setoff, T, r);
            ((u32 *)0x8009cf40u)[s + 4] += dl;
            ((u32 *)0x80092b90u)[s + 4] += dl;
            ((u32 *)0x8009c210u)[s + 4] += dl;
            kept = rnd8(r);
#ifdef ONS_DBG
            ((volatile u32 *)0x8000C900u)[8 + 2 * s] = r; ((volatile u32 *)0x8000C900u)[9 + 2 * s] = h->kept;
#endif
        }
        cur = a8((u32)F + h->setoff + kept);
#ifdef AP8MOD
        {                                                /* 8 MB: SPVC (mains), then the stock PLxx_10.A0 whole; its DSP
                                                            (section 1) registered in place: the PS1's own full sprite file */
            u8 *A; u32 *ah, *dh;
            if (vcsz(c, s) && postvc) vcpend[s] = 1;
            else if (vcsz(c, s)) { T = (u8 *)cur; RD(main_vc(c, s), T); cur = a8(cur + vcsz(c, s)); REG(0xe + s, T, 0); }
            A = ap8_a0(stock_a0(c));
            ah = (u32 *)A; D = A + ah[3]; dh = (u32 *)D;
            D04(s, 0, D + 0x14, D + dh[2], D + dh[3], D + dh[4], 8);
#ifdef KOCACHE
            kof[2 * s] = 0; kof[2 * s + 1] = 0;
#endif
#ifdef SHARE
            sh_d[s] = D; sh_p[s][0] = D + dh[2]; sh_p[s][1] = D + dh[3]; sh_p[s][2] = D + dh[4];
#endif
        }
        if (0)
#endif
        {                                                /* tables: scratch at the top, sections to their places, */
            u8 *S = (u8 *)(RTOP - sec(h->tabsz)), *P[3];  /* then SPVC, then the pixels (largest read last)       */
#ifdef SPUSTORE
            if (SPS_LIVE && sps_mv[s]) { struct fent b = { h->bvmsf[tier[s]], h->tb[tier[s]].size }; rd_item(&b, S); } else
#endif
            rd_item(&h->tb[tier[s]], S);
            for (k = 0; k < 3; k++) {
                if (tabat[s][k]) P[k] = (u8 *)tabat[s][k];
                else { P[k] = (u8 *)cur; cur = a8(cur + secsz(h, k)); }
                copy(P[k], S + h->toff[k], secsz(h, k));
            }
            if (vcsz(c, s) && postvc) {             /* after the load (post routine) */
                vcpend[s] = 1;
            } else if (vcsz(c, s)) {
                if (vcat[s]) { RD(main_vc(c, s), (void *)(RTOP - sec(vcsz(c, s)))); T = (u8 *)vcat[s]; copy(T, (u8 *)(RTOP - sec(vcsz(c, s))), vcsz(c, s)); }
                else { T = (u8 *)cur; RD(main_vc(c, s), T); cur = a8(cur + vcsz(c, s)); }
                REG(0xe + s, T, 0);
            }
            D = (u8 *)cur;
#ifdef SPUSTORE
            if (SPS_LIVE && sps_mv[s]) {
                n = rd_item(&h->tv[tier[s]], D);
                sps_cut(s, h, D, n, P[1]); n -= sps_mv[s];
            } else
#endif
            n = rd_item(&h->t[tier[s]], D);
            cur = a8((u32)D + n);
#ifdef KORELOAD
            kp0[s] = (u32)P[0]; kp1[s] = (u32)P[1]; kf0[s] = (u32)D;
#endif
#ifdef KOCACHE
#if defined(KOFIX) && defined(SPUSTORE)
            /* --kofix: KOR's read-back (continue / rematch) must read the file this slot was loaded from: the store
               variant (other stream order, proxied entries) when the slot has an SPU share */
            kof[2 * s] = (SPS_LIVE && sps_mv[s]) ? h->tv[tier[s]].msf : h->t[tier[s]].msf; kof[2 * s + 1] = n;
#else
            kof[2 * s] = h->t[tier[s]].msf; kof[2 * s + 1] = n;
#endif
#endif
            D04(s, 0, D + 0x14, P[0], P[1], P[2], 8);
#ifdef SHARE
            sh_d[s] = D; sh_p[s][0] = P[0]; sh_p[s][1] = P[1]; sh_p[s][2] = P[2];
#endif
        }
        {                                                /* meter digit: tier - number of cut tiers (cuts show 0) */
            int dg = tier[s] - (int)tl_dir.ncut;
            if (dg < 0) dg = 0;
            if (dg > 9) dg = 9;
            tl_dbg[1 + (s & 1)] |= dg << (4 * (s >> 1));
        }
    }
#ifdef SHARE
    for (k = 0; k < npair; k++) {                    /* the variant: base's pixel section + tile table, own sec1 / sec3 */
        int b = psb[k], u = psu[k];
        D04(u, 0, sh_d[b] + 0x14, sh_p[u][0], sh_p[b][1], sh_p[u][2], 8);
        tl_dbg[3] |= 0x40;
#ifdef KOCACHE
        kof[2 * u] = 0; kof[2 * u + 1] = 0;          /* no file of its own (kocache: mirror rule = same slot pointer) */
#endif
    }
#endif
#ifdef STRONGX
    if (tl_dir.strong_size) {                        /* strong payload item: 2 sectors to the top of the region (free:
                                                        above every reservation), copied down (backwards) to STRONG */
        u32 *src = (u32 *)(TOP - 4096), *dst = (u32 *)STRONG;
        int n = (int)((TOP == TOP0 ? tl_dir.strong_size : tl_dir.dec_size) >> 2);
        rd_item(&tl_sx, src);
#ifdef KOFIX
        {                                            /* --kofix: CHK image at item +3072, before the (overlapping) copy */
            int i;
            for (i = 0; i < CHK_N; i++) ((u32 *)CHK_AT)[i] = src[0xc00 / 4 + i];
        }
#endif
        while (n-- > 0) dst[n] = src[n];
    }
#endif
#ifdef KOCACHE
    if (NOT8 && TOP == TOP0) {                                   /* code + data (1 disc sector) to 0x8000F040, the slots'*/
        static const struct fent kos = { KO_MSF, KO_SIZE };     /* files into its data; Onslaught: stage 9 owns that RAM */
        rd_item(&kos, (void *)KO_RD);
        for (k = 0; k < 8; k++) ((u32 *)(KO_AT + KO_FOFF))[k] = kof[k];
    } else *(u32 *)KO_AT = 0;
#endif
    FTAB[SPARE * 2] = old_msf; FTAB[SPARE * 2 + 1] = old_size;
#ifdef BGFAST
    if (TOP == TOP0) {                                           /* engine + tables (1 disc sector) to 0x801fe000, state cleared */
        static const struct fent bgf = { BG_MSF, BG_SIZE };
        rd_item(&bgf, (void *)BG_AT);
        for (k = 0; k < BG_NSTATE / 4; k++) ((u32 *)BG_STATE)[k] = 0;
    } else *(u32 *)BG_AT = 0;                                    /* Onslaught: stage 9 owns that RAM */
#endif
#ifdef CUTGUARD
    {                                                            /* the cut-in decode / upload calls park and restore
                                                                    the arena tail (SPVC) around the cut-in (flushed below) */
        for (k = 0; k < CG_N; k++) ((u32 *)CG_AT)[k] = cg_code[k];
        *(u32 *)CG_SITE_DEC = CG_JAL_DEC;
        *(u32 *)CG_SITE_UP = CG_JAL_UP;
    }
#endif
#ifdef CHK
    {                                                            /* checker tiles: decode routine to the kernel span,
                                                                    hook on the part decode call (flushed below) */
#ifndef KOFIX                                    /* --kofix: copied from the strong item (STRONGX block) */
        for (k = 0; k < CHK_N; k++) ((u32 *)CHK_AT)[k] = chk_code[k];
#endif
#ifdef VCACHE
        if (vcon) *(u32 *)CHK_SITE = VC_STUBJAL;               /* the site is --vcache's; CHK runs as its NEXT module */
        else
#endif
        *(u32 *)CHK_SITE = CHK_HOOK;
#ifdef AP8MOD
        *(u32 *)CHK_SITE = 0x0c0230c6u;                         /* 8 MB: the stock decode call (jal 0x8008c318) */
#endif
    }
#endif
#ifdef UPSKIP
    {                                                            /* War Machine teams only (fxscan.py: 31 % of his decode
                                                                    is redundant, 3-5 % for the others): code (1 disc sector)
                                                                    to the kernel span, tables cleared, hooks into the RAM
                                                                    EXE; other teams: the stock words back (flushed below) */
        int wm = 0;
        for (s = 0; s < 4; s++) if (list[s] == 0x01 || list[s] == 0x14) wm = 1;
        for (k = 0; k < UP_NTAB; k++) ((u32 *)UP_TAB)[k] = 0;
        if (wm) {
            static const struct fent upf = { UP_MSF, UP_SIZE };
            rd_item(&upf, (void *)UP_AT);
            *(u32 *)UP_H1 = UP_H1W; *(u32 *)(UP_H1 + 4) = 0;
            *(u32 *)UP_H2 = UP_H2W;
        } else {
            *(u32 *)UP_H1 = 0x27bdffe0u; *(u32 *)(UP_H1 + 4) = 0x00804021u;
            *(u32 *)UP_H2 = 0x0c0230c6u;
        }
    }
#endif
#ifdef DXAHEAD
    {                                                            /* decode-ahead (tools/speed4/dxahead.py): state
                                                                    cleared; code (1 sector) + hooks, stock words in
                                                                    Onslaught battles (flushed below) */
        for (k = 0; k < DX_NST; k++) ((u32 *)DX_ST)[k] = 0;
        if (NOT8 && TOP == TOP0) {
            static const struct fent dxf = { DX_MSF, DX_SIZE };
            rd_item(&dxf, (void *)DX_AT);
#ifdef DX_AT2
            {
                static const struct fent dxf2 = { DX_MSF2, DX_SIZE2 };   /* aux sector (DSA1 slices, BUILD) */
                rd_item(&dxf2, (void *)DX_AT2);
            }
#endif
#ifdef DX_AT3
            {
                static const struct fent dxf3 = { DX_MSF3, DX_SIZE3 };   /* --koprefill sector */
                rd_item(&dxf3, (void *)DX_AT3);
            }
#endif
            *(u32 *)DX_H1 = DX_H1W; *(u32 *)DX_H2 = DX_H2W; *(u32 *)DX_H3 = DX_H3W;
        } else { *(u32 *)DX_H1 = DX_H1W0; *(u32 *)DX_H2 = DX_H2W0; *(u32 *)DX_H3 = DX_H3W0; }
    }
#endif
#ifdef KORELOAD
    if (krlon) {                                     /* resident image (disc item, fent in frag[2..3]); its sector tail */
        struct fent kf;                              /* runs into the strong payload area, copied right after this */
        kf.msf = tl_dir.frag[2]; kf.size = tl_dir.frag[3];
        rd_item(&kf, (void *)KRL_AT);
    }
#endif
#ifdef HOOKGATE
    for (k = 0; k < HG_NW; k++) ((u32 *)HG_AT)[k] = hg_img[k];      /* gate code (kernel); flushed below */
#endif
#ifdef L2G
#ifdef L2PC
    if (l2mask)                                                  /* --l2pc: only when a slot keeps packed tables */
#endif
    {                                                            /* after the last read: g2get image, 128-aligned, at
                                                                    the top of the region the planner left free */
        u32 at = (STRONG - CACHE - L2G_N * 4u - L2G_RAM) & ~127u, *G = (u32 *)at;
#ifdef STRONGX
        rd_item(&tl_l2x, G);                         /* 2 sectors: inside the L2G reservation (L2G_N * 4 + L2G_RAM) */
#else
        for (k = 0; k < L2G_N; k++) G[k] = l2g_img[k];
#endif
        for (k = 0; k < (int)(L2G_RAM / 4); k++) G[L2G_N + k] = 0;
#ifdef HOOKGATE
        hg_set(0, HG_E_L2, L2_SITE, at + L2G_ENTRY, 0, at, at + 4u * (L2G_N - 1), at + 4u * (L2G_N / 2));
#else
        *(volatile u32 *)L2_SITE = 0x0c000000u | ((at + L2G_ENTRY) >> 2 & 0x3ffffffu);   /* flushed below */
#endif
    }
#endif
#ifdef L1B
    {                                                            /* after the last read: REMAP right below the L2G
                                                                    reservation (packed sec3 sections start 'S3RM') */
        u32 at = (STRONG - CACHE - L2RES - L1B_N * 4u) & ~7u, *G = (u32 *)at;
        for (k = 0; k < L1B_N; k++) G[k] = l1b_img[k];
#ifdef HOOKGATE
        hg_set(1, HG_E_L1B0, L1B_SITE0, at, 0, at, at + 4u * (L1B_N - 1), at + 4u * (L1B_N / 2));
        hg_set(2, HG_E_L1B1, L1B_SITE1, at, 0, at, at + 4u * (L1B_N - 1), at + 4u * (L1B_N / 2));
#else
        *(volatile u32 *)L1B_SITE0 = 0x0c000000u | (at >> 2 & 0x3ffffffu);   /* flushed below */
        *(volatile u32 *)L1B_SITE1 = 0x0c000000u | (at >> 2 & 0x3ffffffu);
#endif
    }
#endif
#ifdef CUTIN
    {                                                            /* after the last read: banded cut-in decode (the
                                                                    SPVC portraits in the arena tail stay intact) */
        u32 at = (STRONG - CACHE - L2RES - L1RES - CUTIN_N * 4u) & ~7u, *G = (u32 *)at;
        for (k = 0; k < CUTIN_N; k++) G[k] = cutin_img[k];
        *(volatile u32 *)CUTIN_SITE_DEC = 0x0c000000u | (at >> 2 & 0x3ffffffu);   /* flushed below */
        *(volatile u32 *)CUTIN_SITE_LI = 0;
    }
#endif
    if (tl_dir.strong_size) {                                    /* after the last read: decoders (+ meter) */
        u32 *d = (u32 *)STRONG, n = (TOP == TOP0 ? tl_dir.strong_size : tl_dir.dec_size) >> 2;
#ifndef STRONGX
        for (k = 0; k < (int)n; k++) d[k] = tl_strong[k];
#else
        (void)d;
#endif
        /* the meter RAM part is installed now; MCOPY (battle init, tools/speed/meter.S) would copy it again from the
         * arena, where the post routine may already have read SPVC portrait bytes over it (RI exception at 0x801fdd24,
         * ARCADE fight 2, mvc_spsV1; unconditional since rc1): clear the arena copy's magic so MCOPY skips this battle (0x800 = MRAM - STRONG_AT) */
#ifndef STRONGX                                     /* --strongx: MCOPY reads a zero word (mktag) */
        if (n > 0x200) tl_strong[0x200] = 0;
#endif
        dshptr = STRONG;
        dsaptr = tl_dir.dsa_off ? STRONG + tl_dir.dsa_off : 0;
#ifdef VCACHE
        if (vcon) {                                              /* image (code + tables), zeroed index, then the flag */
            u32 *V = (u32 *)VC_AT;
#ifdef STRONGX
            rd_item(&tl_vcx, V);                     /* 1 sector: inside VC_SIZE */
            k = (int)(tl_vcx.size >> 2);
#else
            for (k = 0; k < (int)(sizeof vc_img / 4); k++) V[k] = vc_img[k];
#endif
            for (; k < (int)(VC_SIZE / 4); k++) V[k] = 0;
#ifdef CHK
            *(volatile u32 *)VC_NEXT = 0x80000000u | (CHK_HOOK & 0x3ffffffu) << 2;   /* chain: vcache -> CHK -> decoder */
#endif
            *(volatile u32 *)VC_FLAG = 1;
#ifdef HOOKGATE
#ifdef CHK
            hg_set(3, HG_E_VC, CHK_SITE, 0x80000000u | (VC_STUBJAL & 0x3ffffffu) << 2, 0x80000000u | (CHK_HOOK & 0x3ffffffu) << 2, VC_AT, VC_AT + 4u, VC_AT + 8u);
#endif
#endif
        }
#endif
#ifdef KORELOAD
        *(volatile u32 *)KRL_D = 0;                              /* magic off until filled */
        if (krlon) {
            struct krl_data *D_ = (struct krl_data *)KRL_D; int q, t;
            D_->kd = KRL_KD;
#ifdef VCACHE
            D_->vc_at = vcon ? VC_AT : 0;
#endif
            D_->hsite = 0x8002b528u;
            for (q = 0; q < 4; q++) {
                struct krl_slot *d = &D_->s[q];
                int c = list[q];
                if (c < 0 || !kf0[q]) continue;
                d->ch = c; d->tier0 = tier[q]; d->cost0 = CHR(c).cost[tier[q]];
                d->p0 = kp0[q]; d->p1 = kp1[q]; d->n0 = secsz(&CHR(c), 0); d->n1 = secsz(&CHR(c), 1);
                d->pix0.msf = CHR(c).t[tier[q]].msf; d->pix0.size = CHR(c).t[tier[q]].size;
                d->tab0.msf = CHR(c).tb[tier[q]].msf; d->tab0.size = CHR(c).tb[tier[q]].size;
                d->file0 = kf0[q];
                d->ok = !(CHR(c).pb | CHR(c).pu) && c != 0x11
#ifdef SPUSTORE
                        && !(SPS_LIVE && sps_mv[q])
#endif
                        ;
                {                                        /* pareto targets: cheaper AND each smaller than the last kept */
                    u32 lim = 0xffffffffu; int n = 0;
                    for (t = NT - 1; t >= 0 && n < KRL_NTG; t--) ;
                    for (;;) {                           /* repeat: cheapest tier whose pixel file is < lim */
                        int bt = -1; u32 bc = 0xffff;
                        for (t = 0; t < NT; t++) {
                            if (!CHR(c).t[t].size || !kpl[q][t].size || t >= NT - 2) continue;   /* no dsm / rle (HMM crash open) */
                            if (CHR(c).cost[t] >= d->cost0 || CHR(c).t[t].size >= lim) continue;
                            if (CHR(c).cost[t] < bc) { bc = CHR(c).cost[t]; bt = t; }
                        }
                        if (bt < 0 || n >= KRL_NTG) break;
                        d->t[n].pix.msf = CHR(c).t[bt].msf; d->t[n].pix.size = CHR(c).t[bt].size;
                        d->t[n].sw = kpl[q][bt]; d->t[n].cost = bc; d->t[n].tier = bt; n++;
                        lim = CHR(c).t[bt].size;
                    }
                    d->n = n;
                }
            }
            D_->magic = KRL_MAGIC;
        }
#endif
#ifdef FECACHE
        if (CACHE) {                                             /* fecache.S at STRONG - CACHE, in front of both */
            u32 *B = (u32 *)(STRONG - CACHE), *C = B + 0x200 / 4;
            for (k = 0; k < (int)(sizeof fe_code / 4); k++) B[k] = fe_code[k];
            for (k = 0; k < 0x820 / 4; k++) C[k] = 0;            /* control + index */
            C[1] = CACHE - 0xa20;                                /* ring size (power of 2) */
            C[6] = dsaptr; C[7] = dshptr;
            dshptr = (u32)B + FE_DSH;
            if (dsaptr) dsaptr = (u32)B + FE_DSA;
        }
#endif
#ifdef SPUSTORE
        if (SPS_LIVE && (sps_mv[0] | sps_mv[1] | sps_mv[2] | sps_mv[3]
#ifdef ASSIST
                         | as_own[0][1] | as_own[1][1]
#endif
            )) {  /* front end (region, after the staging */
            u32 *d = (u32 *)SPS_DATA, *f = (u32 *)SPS_FAKE;               /* buffer) + its data / fake section   */
#ifdef SPS_ITEM
            rd_item(&tl_spx, (void *)sps_stg);       /* 1 sector into the staging buffer (SPS_STG >= 2048), then */
            for (k = 0; k < SPS_N; k++) ((u32 *)(sps_stg + SPS_STG))[k] = ((u32 *)sps_stg)[k];   /* behind it */
#ifdef ASGOV
            flushcache();                            /* fresh code in the region */
            ((void (*)(void))(sps_stg + SPS_STG + SPS_GOVI))();   /* --asgov: install the assist draw governor */
#endif
#else
            for (k = 0; k < SPS_N; k++) ((u32 *)(sps_stg + SPS_STG))[k] = sps_code[k];
#endif
            d[0] = 0x31485344; d[1] = 0x81000000u - SPS_FAKE; d[2] = dshptr; d[3] = sps_stg;
            for (k = 0; k < 8; k++) ((u8 *)(d + 24))[k] = SPS_BLK[k];
            d[4] = d[5] = d[6] = 0; d[7] = sps_mv[0] + sps_mv[1] + sps_mv[2] + sps_mv[3];
            for (s = 0; s < 4; s++) for (k = 0; k < 4; k++) d[8 + 4 * s + k] = sps_mv[s] ? sps_own[s][k] : 0;
#ifdef ASSIST
            {                                        /* the assists' owners into the slots the mains left free */
                int q;
                for (q = 0, s = 0; q < 2; q++) {
                    if (!as_own[q][1]) continue;
                    while (s < 4 && sps_mv[s]) s++;
                    if (s < 4) { for (k = 0; k < 4; k++) d[8 + 4 * s + k] = as_own[q][k]; s++; }
                }
            }
#endif
            f[0] = d[0]; f[1] = d[1];                /* 2 MB: the same word (mirror); 8 MB machines: real RAM */
            d[26] = sps_stg + SPS_STG;               /* DATA+0x68: front end, reached only through the trampoline */
#ifdef SPS_ITEM
            for (k = 0; k < 12; k++) ((u32 *)SPS_TRAMP)[k] = ((u32 *)sps_stg)[SPS_N + k];   /* item: code, tramp */
#else
            for (k = 0; k < (int)(sizeof sps_tramp / 4); k++) ((u32 *)SPS_TRAMP)[k] = sps_tramp[k];
#endif
            dshptr = SPS_TRAMP;                      /* kernel RAM: stays valid after the battle (17:45 freeze) */
            TAB11 = SPS_FAKE;
#ifdef KOFIX
            /* --kofix: an ARCADE continue / rematch (0x8007b75a == 2) re-inits the battle WITHOUT the character loader,
               but the SPU store does not survive the continue screens (sound RAM reused) -> garbage store tiles.
               After a battle with the store live, that path takes the full load (0x80045f14 -> 0x8002b7a4 -> tl_main) */
            *(volatile u32 *)0x80045f24u = 0x08000000u | ((0x80045f14u >> 2) & 0x03ffffffu);   /* j 0x80045f14 */
#endif
            flushcache();
        }
#endif
        if (postvc && (vcpend[0] || vcpend[1])) {                /* SPVC read list for the post routine */
            u32 *L = (u32 *)(STRONG + a8(tl_dir.dec_size) + ((u32)post_list - (u32)post));
            u32 n = 0, a = 0, b = 0, ia = 0, ib = 0, sa = 0, sb = 0, bs, as;
            for (s = 0; s < 2; s++) if (vcpend[s]) {
                int c = list[s];
                if (!n) { ia = main_vc(c, s); a = vcsz(c, s); sa = 0xe + s; }
                else { ib = main_vc(c, s); b = vcsz(c, s); sb = 0xe + s; }
                n++;
            }
            if (n == 1) { L[0] = 1; L[1] = ia; L[2] = PA_LO; L[3] = sa; }
            else {                                   /* the second read ends at its sector boundary <= PA_LIM, its data
                                                        below PA_HI; the first starts at PA_LO (its sector tail is
                                                        overwritten by the second read) */
                int sw;
                for (sw = 0; sw < 2; sw++) {
                    bs = (PA_HI - b) & ~7u;
                    if (bs + sec(b) > PA_LIM) bs = (PA_LIM - sec(b)) & ~7u;
                    as = PA_LO;
                    if (as + a <= bs) break;
                    { u32 t = a; a = b; b = t; t = ia; ia = ib; ib = t; t = sa; sa = sb; sb = t; }
                }
                L[0] = 2; L[1] = ia; L[2] = PA_LO; L[3] = sa; L[4] = ib; L[5] = bs; L[6] = sb;
                if (sw == 2) L[0] = 1;               /* cannot happen (mktag checks every SPVC pair) */
            }
            tl_postarg = (u32)L;
            tl_postfn = STRONG + a8(tl_dir.dec_size);
        }
        if (TOP != TOP0)                                         /* no meter in Onslaught battles: MCOPY would */
#ifndef STRONGX
            tl_strong[(0x801fdc00u - 0x801fd400u) >> 2] = 0;     /* overwrite the stage block; kill its magic */
#endif
        flushcache();
    }
#ifndef ASSIST_TESTKEEP
    ASSIST_BITS &= ~3;                  /* no special partner: the stock code after the loop must not load DA files */
#else
    ASSIST_BITS &= 2;                   /* TEST builds (--assisttest): P2's stock DA load stays (shared-slot teams only) */
#endif
    snd_finish();                                    /* bank addresses + swap code (tools/snd) */
    LOADER_FULL = 3;
    *(u32 *)(tl_dbg + 4) = cur;
#ifdef ONS_DBG
    { volatile u32 *q = (u32 *)0x8000C900u; q[0] = RLIM; q[2] = cur; }
#endif

    tl_dbg[0] = 1;
    return 1;
}

/* After a tag battle that used fragments: re-read the EXE sectors that cover them (into the character region, dead
 * by then) and copy the fragments back, so the code / data there is the stock again before anything uses it.
 * Called through glue with tl_entry = ARENA + 8 by the restore hook.  Returns 1 (glue must not take its decline path). */
#ifdef FRAGS
int tl_restore(void)
{
    extern u32 tl_pend;
    u32 lo = 0xffffffffu, hi = 0, k, used = tl_pend;
    u8 *tmp = (u8 *)REGION_START;
    u32 old_msf = FTAB[SPARE * 2], old_size = FTAB[SPARE * 2 + 1];
    struct fent f;
    if (!used || !tl_dir.nfrag) return 1;
    for (k = 0; k < tl_dir.nfrag; k++) {
        if (!(used >> k & 1)) continue;
        if (tl_dir.frag[3 * k] < lo) lo = tl_dir.frag[3 * k];
        if (tl_dir.frag[3 * k + 1] > hi) hi = tl_dir.frag[3 * k + 1];
    }
    {
        u32 o = (lo - 0x80010000u + 0x800u) & ~2047u;          /* EXE file offset, sector aligned */
        u32 lba = 0, m = tl_dir.exe_msf, b;
        b = (m & 0xff); lba = ((b >> 4) * 10 + (b & 15)) * 4500;
        b = (m >> 8) & 0xff; lba += ((b >> 4) * 10 + (b & 15)) * 75;
        b = (m >> 16) & 0xff; lba += (b >> 4) * 10 + (b & 15);
        lba += o / 2048;
        m = lba;                                                  /* back to BCD MSF */
        f.msf = ((m / 4500) / 10 << 4 | (m / 4500) % 10) | (((m / 75 % 60) / 10 << 4 | (m / 75 % 60) % 10) << 8) |
                (((m % 75) / 10 << 4 | (m % 75) % 10) << 16);
        f.size = hi - (o + 0x80010000u - 0x800u);
        rd_item(&f, tmp);
        for (k = 0; k < tl_dir.nfrag; k++) {
            u32 a = tl_dir.frag[3 * k], e = tl_dir.frag[3 * k + 1];
            if (!(used >> k & 1)) continue;
            copy((u8 *)a, tmp + (a - (o + 0x80010000u - 0x800u)), e - a);
        }
    }
    FTAB[SPARE * 2] = old_msf; FTAB[SPARE * 2 + 1] = old_size;
    flushcache();
    tl_pend = 0;
    return 1;
}
#else
int tl_restore(void) { return 1; }                  /* no fragments in this build (rhook not patched in) */
#endif
