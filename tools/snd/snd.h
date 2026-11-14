/* XvSF tag hack 1.2 sound banks: shared definitions of the resident part (sndres.c) and the sound directory's
 * code (snddir.c).  Layout of the sound directory (3 sectors, read to DIRBUF at every battle load):
 *      0x000  magic, sum (of the words from nwords on), nwords
 *      0x00c  cand2[16], cand8[16]    candidates: rank << 8 | XS_MAIN level << 4 | character level, 0xffff ends;
 *                                     the fitting candidate of the lowest rank wins, the most bytes among equal ranks
 *      0x04c  stash2, stash8          SP_EFF2 stash: SPU address (2 MB) / RAM address (8 MB)
 *      0x054  e[6][19][2]             level x bank (characters 0..17, 18 = XS_MAIN) x (VH, VB) file entries,
 *                                     at 4 mod 8 like the game's file table (fake file indices); size 0 = none
 *      0x774  novr, o[24]             id-list overrides: list of bank = DIRBUF + off while its level is in levmask
 *      CODE   snd_policy()            (snddir.c), then the id lists
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define FTABLE      0x8003d91cu
#define FAKE(p)     ((int)((u32)(p) - FTABLE) >> 3)
#define LOADFILE    ((int (*)(int, void *))0x8002de3cu)
#define BANKLOAD    ((void (*)(s16 *))0x8004cb18u)
#define MERGE       ((int (*)(int, int))0x8004ce34u)
#define VBLOAD      ((int (*)(int, int))0x8004d418u)
#define LISTS       ((u32 *)0x8004f7f0u)
#define IDS         ((s16 *)0x800423b2u)
#define SPUADDR     ((void (*)(u32))0x800116c8u)
#define SPUWRITE    ((void (*)(void *, u32))0x80011668u)
#define SPUWAIT     ((int (*)(int))0x80011720u)
#define DIRBUF      0x801e0000u
#define DIRSIZE     6144u
#define CODEOFF     0x7e0u
#define MAGIC       0x31535658u         /* "XVS1" */
#define NB          19                  /* characters 0..17, 18 = XS_MAIN */
#define XSB         18
#define NLEV        6
#define NOVR        24
#define SAMPLES     0x1010u             /* SsVabOpenHeadSticky address of the merged bank */
#define TOP8        0x7ea80u            /* 0x7ea80-0x80000: finish-effect palettes the game writes at boot (0x800f01c0) */

struct xent { u32 msf, size; };
struct ovr { u8 bank, levmask; u16 off; };
struct sdir {
    u32 magic, sum, nwords;
    u16 cand2[16], cand8[16];
    u32 stash2, stash8;
    struct xent e[NLEV][NB][2];
    u32 novr;
    struct ovr o[NOVR];
};
#define DIR ((struct sdir *)DIRBUF)

/* resident data (sndres.c) */
extern u32 stashbase;
extern u8 snd_on, snd_xl, snd_cl;
extern int (*ap8fn)(void);
