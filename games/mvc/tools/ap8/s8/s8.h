/* MvC 8 MB voice streaming (tools/ap8/s8): engine state + the module's directory of the .SN8 files.  Port of
 * games/mshvsf/tools/ap8/s8/s8.h; the engine and the battle part are linked into the 8 MB module (tools/ap8/mkap8.py),
 * the state lives at ST (outside the module: the module is read again every battle). */
typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define S8_ST     0x807e0000u               /* engine state (struct s8st), persists across battles */
#define S8_COM    0x80600000u               /* COMMON.SN8 (read once per boot, word sum checked) */
#define S8_COMMAX 0x60000u
#define S8_SLOT   0x80660000u               /* slot s's .SN8 at S8_SLOT + s * S8_SLOTSZ */
#define S8_SLOTSZ 0x38000u
#define S8_STG    0x807d0000u               /* staging (lists / owner map, 6,464 B) */
#define S8_MAGIC  0x53385643u               /* 'CV8S' */
#define NSEG      160
#define NREG      2
#define NVOICE    24
#define CHUNK     1024u
#define SILENT    0x1000u                   /* libspu's silent block (loops) */
#define S8_MARK   0xc1                      /* entry byte 0x13 of every entry from a .SN8 file (sn8build.MARK) */

struct s8item { u32 off; u32 size; u16 bpf; u16 pad; };
struct s8vox { u32 n; struct s8item it[1]; };
struct sn8 { u32 magic, nent, bank, banklen, samp, vox, voxlen, npf, pf; };

struct s8seg { u32 key; u32 spu; u32 size; u32 last; u32 up; u32 tot; u32 t0; const u8 *src; u16 bpf; u8 reg; u8 pend; };
struct s8reg { u32 lo, hi, on; };

struct s8st {
    u32 magic;
    u32 nseg;
    struct s8reg reg[NREG];
    const struct s8vox *vox[5];             /* bank 0 COMMON, 1-4 */
    u32 vspu[NVOICE];
    u32 vt[NVOICE];
    u32 self;
    u32 hits, miss, chunks, fails, foreign, starve, prefetch, keys;
    u32 installed;
    u32 commsf, comn, comsum;               /* COMMON.SN8 in upper RAM */
    u32 smsf[4], sn[4], ssum[4];            /* slot .SN8 files in upper RAM (key + word sum after our bank bytes) */
    u8 ldbg[8];                             /* [0] used, [1] fits, [2] COMMON uploaded, [3] prefetched, [5] exit reason */
    u32 used;
    u32 dbgplay;                            /* tests: id | 0x10000 -> played from the next tick */
    u32 silent;
    struct s8seg seg[NSEG];
};
#define ST ((struct s8st *)S8_ST)

/* .SN8 directory in the module (section .dir8m, filled by mkap8.py when the files are on the disc) */
struct s8fent { u32 msf, size, samp; };
struct s8dir { u32 magic, on; struct s8fent b[28]; };      /* 'SN8D'; sndbank.bank_names() order = snd.c bix() */
extern struct s8dir s8d;

u32 s8_play(u8 *e, u32 mask);
void s8_tick(int a0);
int s8_fetch(const struct s8vox *x, int i);
void s8_flush(void);
void s8_region(int r, u32 lo, u32 hi);
void s8_wrstub(void);
