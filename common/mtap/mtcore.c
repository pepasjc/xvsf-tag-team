/* mtcore.c: PS1 multitap (SCPH-1070) 2-4 players for the Capcom tag hacks (XvSF, MSHvSF, MvC).
   Built per game by common/mtap/mtbuild.py with the game's mtgame.h (addresses + the point/scene rules).
   Notes: games/mshvsf/docs/MULTITAP.md ("mtap04").

   The games read the pads with Psy-Q libpad in the VBlank IRQ; with a multitap in port 1 libpad sees slot A only.
   Once per main-loop frame (hook on the game's pad-word update) we read the multitap ourselves over SIO (interrupts
   off, polled): a slot-A access with the multitap request flag (01 42 01), then the long access (01 42 00 + 4 x 42 ...)
   whose reply is 80 5A + 4 slots of 8 bytes.  The long access has the flag clear, so libpad's next access gets slot A.

   Players (fixed, no assignment screen): P1 = slot A, P2 = slot B (or the pad in port 2 when slot B is empty),
   P3 = slot C, P4 = slot D.  Team 1 = P1 (first character) + P3 (second), team 2 = P2 + P4.  P3 / P4 join by
   pressing START on the character select screen and stay in until the title / main menu.  A joined player drives
   the side while its own character is on point (select: the second pick); START of the waiting player passes
   (pause), and in a fight its own tag buttons (MT_TAGMASK, the default HP + HK keys) pass so it can call itself in.  Not joined:
   the side's first player plays both characters (stock).

   Cost: no SIO access at all with a pad in port 2 and no multitap (the normal 2-pad setup) except one short probe
   when the character select screen opens; with port 2 empty a short probe (6 bytes) every 32 frames on the title /
   menus only; never in a fight unless a multitap is active.  Active: one read per frame up to the last slot needed. */
#include <stdint.h>
/* game RAM (not volatile: the compiler may keep a value between two calls of ours) */
#define U8(a)  (*(uint8_t*)(a))
#define S8(a)  (*(int8_t*)(a))
#define U16(a) (*(uint16_t*)(a))
#define S16(a) (*(int16_t*)(a))
#define U32(a) (*(uint32_t*)(a))
typedef int (*f_int)(void);
typedef void (*f_void)(void);

#ifdef MT_VSCPU                     /* kernel spans (real-PS1 proven, achbuild SPANS): .kz = zero at boot (vars), */
#define MT_KC __attribute__((section(".text.kc.point")))   /* .kc = copied there by mt_select (select overlay) */
#define MT_PSFN static __attribute__((noinline, section(".text.kc.point")))
#define MT_BSS(n) __attribute__((section(".bss.kz." n)))
#else
#define MT_KC
#define MT_PSFN static inline
#define MT_BSS(n) __attribute__((section(".bss." n)))
#endif
#include "mtgame.h"

#ifndef MT_START
#define MT_START 0x0800
#endif
#ifndef MT_DIRS
#define MT_DIRS 0xf000
#endif
#ifndef SEL_DELAY
#define SEL_DELAY 100
#endif
#ifndef GAP_DELAY
#define GAP_DELAY 1000
#endif
#ifndef RX_WAIT
#define RX_WAIT 8000
#endif
#ifndef ACK_WAIT
#define ACK_WAIT 6000
#endif
#ifndef MT_OFF_FAILS
#define MT_OFF_FAILS 60
#endif

#define JOY_DATA (*(volatile uint8_t*)0x1f801040)
#define JOY_STAT (*(volatile uint32_t*)0x1f801044)
#define JOY_MODE (*(volatile uint16_t*)0x1f801048)
#define JOY_CTRL (*(volatile uint16_t*)0x1f80104a)
#define JOY_BAUD (*(volatile uint16_t*)0x1f80104e)
#define I_STAT   (*(volatile uint32_t*)0x1f801070)
#define RCNT2    (*(volatile uint32_t*)0x1f801120)

struct mtv {
	uint8_t act;          /* 1 = a multitap answers: we drive the side words */
	uint8_t fails;        /* consecutive failed reads (active) */
	uint8_t join;         /* bit 2 = P3, bit 3 = P4 joined */
	uint8_t cnt;          /* frame counter (probe every 32 frames) */
	uint8_t owner[2];     /* 1 = the side's second player drove it last frame */
	uint16_t mask[2];     /* buttons held by a new owner at the hand-over: ignored until released */
	uint16_t pad[4];      /* slot words, game format (1 = held) */
#ifdef MT_DIAG
	uint16_t t_read, t_max;   /* root counter 2 ticks of the last / longest read */
	uint16_t reads, probes;
#endif
#ifdef MT_VSCPU
	uint8_t src[4];       /* seats 0 P1 (side 1 first), 1 P2 (side 2 first), 2 P3 (side 1 second), 3 P4 (side 2 second):
	                         0..3 = controller (0 port 1 / slot A, 1 port 2 / slot B, 2 slot C, 3 slot D),
	                         SEAT_TAG = the side's first seat plays this character too (stock), SEAT_CPU = the AI */
	uint8_t vsinit;       /* seats set up for this VERSUS session */
	uint8_t edit;         /* controller + 1 in the select setup (its input does not reach the game), 0 = none */
	uint16_t ctl[4];      /* controller words this frame */
	uint16_t pctl[4];     /* last frame's (setup edges) */
	uint8_t cur;          /* setup cursor: seat */
	uint8_t custom;       /* bit 0 seats differ from the stock ones, bit 1 a CPU seat (VERSUS) */
	uint8_t eff[4];       /* seat -> controller (TAG resolved) or SEAT_CPU */
	uint8_t seff[4];      /* the same on the select: a CPU seat -> the human who picks for it */
#endif
};
struct mtv V MT_BSS("mtv");
uint8_t mt_rx[36] MT_BSS("mtrx");
#ifdef MT_VSMENU          /* main-menu VERSUS CPU (mt_vsmenu): 0 none, 1 human side 1 (port 1), 2 human side 2 (port 2); own
                             section: the game's span list may give it a fixed address (other runtimes read it) */
uint8_t mt_vsmode __attribute__((section(".bss.vsmbyte")));
#endif
#ifdef MT_VSCPU
uint8_t mt_ssec MT_BSS("ssec");          /* select: bit s = side s picks its second character (MT_SEL_SECOND) */
#endif   /* bytes of the last long access */

/* request access (01 42 01), then the long access (01 42 00, 42 at each slot's first byte) */
const uint8_t mt_req[38] __attribute__((section(".rodata.mtreq"))) = { 0x01, 0x42, 0x01,
                                 0x01, 0x42, 0x00, 0x42, 0, 0, 0, 0, 0, 0, 0, 0x42, 0, 0, 0, 0, 0, 0, 0,
                                 0x42, 0, 0, 0, 0, 0, 0, 0, 0x42, 0, 0, 0, 0, 0, 0, 0 };

/* int mt_read(int n): request access + long access of n bytes, interrupts off, polled SIO on port 1;
   1 when the multitap answered all n bytes with ID 0x80.  No SIO reset (JOY_CTRL bit 6: it drops the multitap
   request in Beetle); a stale RX byte is drained instead.  Our ACK interrupt flag (I_STAT bit 7) is cleared before
   interrupts come back, so libpad never sees it.  (mtsio.inc) */
int mt_read(int n);
#define STR_(x) #x
#define STR(x) STR_(x)
#include "mtsio.inc"
#ifdef MT_VSCPU
/* ------------------------------------------------------------------ vs CPU: seats (all modes; CPU seats only in VERSUS) */
#define SEAT_TAG 4
#define SEAT_CPU 5
#define SEATS_FIGHT(sc) ((sc) == MT_SC_FIGHT)
#define human(v) ((v) < 4)

/* side s's raw word: the seat whose character is on point (select: whose pick it is).  V.eff[k] = the controller that
   drives seat k (TAG resolved) or SEAT_CPU; V.pick[s] = the controller that picks for side s's CPU seats (mt_select) */
static __attribute__((noinline)) uint16_t route_v(int s, int sc) {
	const uint8_t *t = sc == MT_SC_FIGHT ? V.eff : V.seff;
	int k = MT_POINT_SECOND(s, sc) ? 2 + s : s, v = t[k], w = t[k ^ 2];
	uint16_t o = human(v) ? V.ctl[v] : 0, p = human(w) && w != v ? V.ctl[w] : 0;
	if (v != V.owner[s]) { V.mask[s] = o & ~MT_DIRS; V.owner[s] = (uint8_t)v; }
	V.mask[s] &= o;
	o &= ~V.mask[s];
	o |= p & MT_START;                                 /* the other player of the side may pause */
#ifdef MT_TAGMASK
	if (sc == MT_SC_FIGHT && (p & MT_TAGMASK) == MT_TAGMASK) o |= MT_TAGMASK;   /* the waiting player calls the tag */
#endif
	return o;
}
#endif

static __attribute__((noinline)) uint16_t route(int s, uint16_t wa, int cb, int sc) {
	uint16_t o, p;
	int sec;
	if (!(V.join >> cb & 1)) return wa;
	sec = MT_POINT_SECOND(s, sc);
	o = V.pad[cb]; p = wa;
	if (!sec) { p = o; o = wa; }
	if (sec != V.owner[s]) { V.mask[s] = o & ~MT_DIRS; V.owner[s] = (uint8_t)sec; }
	V.mask[s] &= o;
	o &= ~V.mask[s];
	o |= p & MT_START;                                     /* either player may pause */
#ifdef MT_TAGMASK
	if (sc == MT_SC_FIGHT && (p & MT_TAGMASK) == MT_TAGMASK) o |= MT_TAGMASK;   /* the waiting player calls the tag */
#endif
	return o;
}

#ifdef MT_VSCPU
#define VS_MAGIC 0x55505356u                           /* 'VSPU' */

/* (kernel copy) each seat's object +3: 1 human, 0 the AI plays it */
static __attribute__((noinline, section(".text.kc.fight"))) void vs_fight(void) {
	U8(MT_OBJ(0) + 3) = (uint8_t)human(V.eff[0]); U8(MT_OBJ(1) + 3) = (uint8_t)human(V.eff[1]);
	U8(MT_OBJ(2) + 3) = (uint8_t)human(V.eff[2]); U8(MT_OBJ(3) + 3) = (uint8_t)human(V.eff[3]);
}
extern const uint32_t vs_magic;
void mt_select(void);                                  /* select overlay (mtvsui.c): session seats, joins, setup panel */

static void vs_body(void) {
	int sc = MT_SCENE_V(), s, hi;
	uint16_t w0, w1;
	V.ctl[0] = MT_PORT1_WORD(); V.ctl[1] = MT_PORT2_WORD(); V.ctl[2] = V.ctl[3] = 0;
	if (sc == MT_SC_MENU) V.vsinit = 0;
#ifndef MT_VSMENU                                      /* (VERSUS CPU menu row, no multitap: V.act stays 0, no SIO) */
	if (!V.act) {                                      /* probe every 32 frames: select screen, or menus with port 2 empty */
		if ((++V.cnt & 31) == 1 && (sc == MT_SC_SELECT || (sc == MT_SC_MENU && !MT_PORT2_OK())) && mt_read(3)) {
			V.act = 1; V.fails = 0; V.owner[0] = V.owner[1] = 0xff; V.mask[0] = V.mask[1] = 0xffff;
		}
	} else {
		hi = (sc == MT_SC_SELECT || (V.join & 8)) ? 3 : (V.join & 4) ? 2 : 1;
		if (mt_read(3 + 8 * hi + 4)) {
			V.fails = 0;
			for (s = 0; s < 4; s++) {
				const uint8_t *r = mt_rx + 3 + 8 * s;
				V.ctl[s] = s <= hi && r[1] == 0x5a ? (uint16_t)~(r[2] << 8 | r[3]) : 0;
			}
			if (mt_rx[12] != 0x5a) V.ctl[1] = MT_PORT2_WORD();
		} else if (++V.fails >= MT_OFF_FAILS) V.act = 0;   /* (failed read: the stock words) */
	}
#endif
	if (sc == MT_SC_SELECT && *(volatile const uint32_t *)&vs_magic == VS_MAGIC) mt_select();
	if (!V.vsinit || (!V.act && !V.custom)) return;   /* stock seats, no multitap: the stock words */
	w0 = route_v(0, sc); w1 = route_v(1, sc);
	MT_WRITE(w0, w1);
	if (sc == MT_SC_FIGHT && (V.custom & 2)) vs_fight();   /* VERSUS with CPU seats */
}

/* disconnected-pad mask: 0 with the multitap, else only port 1 counts (VERSUS without a pad in port 2: CPU seat) */
#ifdef MT_VSMENU          /* menu VERSUS CPU: the stock mask, but in its VERSUS only the human side's port counts */
#ifndef MT_MASK_RAW       /* (the stock routine: its two replaced words replayed) */
int mt_mask_stock(void);
__asm__(".section .text.mt_mask_stock,\"ax\"\n.set noreorder\n.globl mt_mask_stock\nmt_mask_stock:\n"
	"	.word " STR(MT_MASK_W0) "\n	j " STR(MT_MASK_AT) " + 8\n	.word " STR(MT_MASK_W1) "\n.set reorder\n.previous\n");
#define MT_MASK_RAW() mt_mask_stock()
#endif
int mt_mask_v(void) { int m = MT_MASK_RAW(); if (mt_vsmode && MT_VERSUS()) m &= mt_vsmode; return m; }
#include "mtmenu.h"       /* the game's main-menu row (mt_vsmenu) */
#elif defined(MT_MASK_V)
int mt_mask_v(void) { return V.act ? 0 : MT_MASK_V(); }          /* (the game's own port-1 bit) */
#else
__asm__(".section .text.mt_mask_v,\"ax\"\n.set noreorder\n.globl mt_mask_v\nmt_mask_v:\n"
	"	lui $t0, %hi(V)\n	lbu $t0, %lo(V)($t0)\n	addiu $sp, $sp, -24\n	sw $ra, 16($sp)\n"
	"	bnez $t0, 1f\n	move $v0, $0\n"
	"	jal " STR(MT_PORT1_OK_FN) "\n	nop\n	sltiu $v0, $v0, 1\n"
	"1:	lw $ra, 16($sp)\n	addiu $sp, $sp, 24\n	jr $ra\n	nop\n.set reorder\n.previous\n");
#endif
#ifndef MT_OWN_SELECT    /* (MvC rc4.15: the game's mtmenu.h has its own lean, resident mt_select + vs_magic) */
#include "mtvsui.c"
#endif
#endif

/* replaces the game's per-frame pad-word update (hook in the main loop).  MT_AFTER (MvC): a stock step that must see
   our words (the key mapper) runs once after them, on every path */
#ifdef MT_VSCPU
#ifndef MT_AFTER
#define MT_AFTER() ((void)0)
#endif
void mt_tick(void) { MT_STOCK_UPDATE(); vs_body(); MT_AFTER(); }
static __attribute__((unused)) void mt_old(void) {          /* (the mtap04 body: not used with seats) */
#elif defined(MT_AFTER)
static void mt_body(void);
void mt_tick(void) { mt_body(); MT_AFTER(); }
static __attribute__((noinline)) void mt_body(void) {
#else
void mt_tick(void) {
#endif
	int sc, hi, s;
	uint16_t w0, w1;
	MT_STOCK_UPDATE();
	sc = MT_SCENE_V();
	if (sc == MT_SC_MENU) V.join = 0;
	if (!V.act) {                                          /* probe every 32 frames: select screen, or menus with port 2 empty */
		if ((++V.cnt & 31) != 1 || (sc != MT_SC_SELECT && (sc != MT_SC_MENU || MT_PORT2_OK()))) return;
#ifdef MT_DIAG
		V.probes++;
#endif
		if (!mt_read(3)) return;
		V.act = 1; V.fails = 0; V.owner[0] = V.owner[1] = 0; V.mask[0] = V.mask[1] = 0xffff;
	}
	if (!V.join && sc != MT_SC_SELECT && MT_PORT2_OK()) return;   /* 2 players, P2 in port 2: libpad's words are enough */
	hi = (sc == MT_SC_SELECT || (V.join & 8)) ? 3 : (V.join & 4) ? 2 : 1;
	if (!mt_read(3 + 8 * hi + 4)) {                        /* keep the stock words (slot A / port 2 through libpad) */
		if (++V.fails >= MT_OFF_FAILS) V.act = 0;
		return;
	}
	V.fails = 0;
	for (s = 0; s <= hi; s++) {
		const uint8_t *r = mt_rx + 3 + 8 * s;
		V.pad[s] = r[1] == 0x5a ? (uint16_t)~(r[2] << 8 | r[3]) : 0;      /* (an empty slot answers FF) */
	}
	if (sc == MT_SC_SELECT)                                /* P3 / P4 join with START */
		V.join |= (V.pad[2] & MT_START ? 4 : 0) | (V.pad[3] & MT_START ? 8 : 0);
	w1 = mt_rx[12] == 0x5a ? V.pad[1] : MT_PORT2_WORD();
	w0 = route(0, V.pad[0], 2, sc); w1 = route(1, w1, 3, sc);
	MT_WRITE(w0, w1);
}

/* entry of the game's disconnected-pad mask (MT_MASK_AT: `j mt_mask; nop`; bit 0 port 1, bit 1 port 2; the main menu
   hides VERSUS without a pad in port 2 - the MiSTer core switches port 2 off while its multitap is on - and a fight
   pauses on it): 0 while the multitap is active, else the stock routine (its two replaced words replayed) */
#define STR_(x) #x
#define STR(x) STR_(x)
#ifndef MT_VSCPU
__asm__(".section .text.mt_mask,\"ax\"\n.set noreorder\n.globl mt_mask\nmt_mask:\n"
	"	lui $t0, %hi(V)\n	lbu $t0, %lo(V)($t0)\n	nop\n	bnez $t0, 1f\n	move $v0, $0\n"
	"	.word " STR(MT_MASK_W0) "\n	j " STR(MT_MASK_AT) " + 8\n	.word " STR(MT_MASK_W1) "\n"
	"1:	jr $ra\n	nop\n.set reorder\n.previous\n");
#endif
