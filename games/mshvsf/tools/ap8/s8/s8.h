/* MSHvSF 8 MB voice streaming (tools/ap8/s8): shared layout of the resident engine (s8.c, linked at S8_CODE) and the
 * battle loader part in the blob (snd8.c).  Notes: games/mshvsf/docs/SOUND.md "8 MB voice streaming". */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define S8_CODE   0x807f0000u               /* engine code (s8.bin, copied from the blob every 8 MB battle) */
#define S8_CODEMAX 0x3000u
#define S8_ST     0x807f4000u               /* engine state (struct s8st), persists across battles */
#define S8_MAGIC  0x53385653u               /* 'SV8S' */
#define NSEG      160
#define NREG      2
#define NVOICE    24
#define CHUNK     1024u                     /* trickle chunk; the first chunk is uploaded at key-on */
#define SILENT    0x1000u                   /* libspu's 16-byte silent block (loops: a voice keyed on it never ends) */
#define S8_MARK   0xc1                      /* entry byte 0x13 (spare, 0 in every stock .SE): streamed entry of ours */

/* voice store (in the .SN8 file): u32 n, n x item, then data; item data = zero block + ADPCM blocks (end flag) */
struct s8item { u32 off; u32 size; u16 bpf; u16 pad; };     /* off from the store start; size 64-rounded; bpf: bytes
                                                                 the SPU plays per 1/60 s x 16 */
struct s8vox { u32 n; struct s8item it[1]; };

struct s8seg { u32 key; u32 spu; u32 size; u32 last; u32 up; u32 tot; u32 t0; const u8 *src; u16 bpf; u8 reg; u8 pend; };
struct s8reg { u32 lo, hi, on; };

struct s8st {
    u32 magic;
    u32 nseg;
    struct s8reg reg[NREG];
    const struct s8vox *vox[5];             /* bank 0 COMMON, 1-4 list slots */
    u32 vspu[NVOICE];                       /* SPU start the voice was last keyed with through the hook (~0: none) */
    u32 vt[NVOICE];
    u32 self;                               /* our own SpuWrite in progress */
    u32 hits, miss, chunks, fails, foreign, starve, prefetch, keys;
    u32 installed;
    u32 commsf, comn, comsum;             /* COMMON .SN8 in upper RAM (snd8.c): disc key + word sum */
    u8 ldbg[8];                           /* snd8e.c: [0] used, [1] fits, [2] COMMON uploaded, [3] prefetched, [4] OVF, [5] begin exit */
    u32 used, comat;                      /* snd8e.c battle state */
    const void *sn[4];
    u32 stash[4], at[4];
    u32 dbgplay;                          /* tests (s8voices.py): id | 0x10000 -> played from the next tick */
    struct s8seg seg[NSEG];
    u32 silent;                           /* SPU one-shot silent block (end flag, no repeat; snd8e.c), 0: none */
};
#define ST ((struct s8st *)S8_ST)

/* ap8.c's directory of the streaming files (blob .dir8, filled by mkap8.py) */
struct s8fent { u32 msf, size; };
struct s8dir {
    u32 magic;                              /* 'SN8D' */
    u32 on;                                 /* streaming files on this disc */
    u32 codesum;                            /* word sum of the engine binary (S8_CODE) */
    u32 comat;                              /* COMMON.SN8 in upper RAM; the cache arena ends there */
    struct s8fent code, com;
    struct s8fent c[0x17];
};

u32 s8_play(u8 *e, u32 mask);
void s8_tick(int a0);
int s8_fetch(const struct s8vox *x, int i);
void s8_flush(void);
void s8_region(int r, u32 lo, u32 hi);
int s8_begin(signed char *list, u8 *const *p, const struct s8dir *d, const u32 *stash, int first);
void s8_load(int s);
void s8_end(void);
u32 s8_stash(int s);

/* engine entry points (fixed: s8.c puts a jump table at S8_CODE) */
#define S8_PLAY     (S8_CODE + 0x00)        /* u32 s8_play(u8 *entry, u32 mask)         (play hook, 0x8007ad0c) */
#define S8_TICK     (S8_CODE + 0x08)        /* void s8_tick(int a0)                       (main loop, 0x80020c84) */
#define S8_WRHOOK   (S8_CODE + 0x10)        /* SpuWrite entry stub                        (0x8001bca8) */
#define S8_FETCH    (S8_CODE + 0x18)        /* int s8_fetch(const struct s8vox *, int i)  (prefetch at load) */
#define S8_FLUSH    (S8_CODE + 0x20)        /* void s8_flush(void)                        (finish pending uploads) */
#define S8_RESET    (S8_CODE + 0x28)        /* void s8_region(int r, u32 lo, u32 hi)      (region reset, on) */
#define S8_BEGIN    (S8_CODE + 0x30)        /* snd8e.c, called by ap8.c */
#define S8_LOAD     (S8_CODE + 0x38)
#define S8_END      (S8_CODE + 0x40)
#define S8_STASH    (S8_CODE + 0x48)
