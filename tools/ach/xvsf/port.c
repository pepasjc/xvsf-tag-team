/* port.c: XvSF side of the built-in achievements (see port.h, tools/ach/ach.c, docs/ACHIEVEMENTS.md) */
#include "port.h"

/* derived bytes, read by the set (set.py names them): the linker puts them at ACH_BASE + 0x20 */
struct vars {
	uint8_t side;        /*  0: human side 1 = P1, 2 = P2 (one human), 3 = two humans (versus), 0 = none (demo) */
	uint8_t team[3];     /*  1: the human team (P1's with two humans), bit (id) per character id 0..23 */
	uint8_t act;         /*  4: on-point human character id * 2 (0xff without a human) */
	uint8_t act_partner; /*  5: 1 while the human team's second pick is on point */
	uint8_t combo;       /*  6: hit count of the human's current combo */
	uint8_t kos;         /*  7: opponents knocked out (counts up, wraps) */
	uint8_t full;        /*  8: 1 while both human characters have full life */
	uint8_t wins;        /*  9: rounds the human side won in this match */
	uint8_t clear;       /* 10: 1 on the frame the human team beats Apocalypse in arcade */
	uint8_t alive;       /* 11: human characters still standing (0..2) */
	uint8_t mode;        /* 12: 1 arcade, 2 versus, 3 training, 4 survival */
	uint8_t run_ok;      /* 13: 1 while this arcade run started at the first fight and lost none */
	uint8_t vs_wins;     /* 14: versus matches won by either player with two humans (counts up, wraps) */
	uint8_t pad;
};
struct vars ach_v __attribute__((section(".vars")));

/* game bytes, as offsets from G = 0x80040000 */
#define G       ((const uint8_t*)0x80040000u)
#define G8(o)   G[o]
#define G16(o)  (*(const uint16_t*)(G + (o)))
#define OBJ_P1  0x2a10         /* objects 0x348 bytes: P1, P2, P1 partner, P2 partner */
#define OBJ_P2  0x2d58
#define PARTNER 0x0768         /* partner object = main + 0x768 */
#define LIFE    0x224
#define ID      0x54
#define COMBO   0x115
#define IDS     0x23b2         /* 4 x s16 id * 2: P1, P1 partner, P2, P2 partner (the picks) */
#define HUMANS  0x2771         /* 1 P1, 2 P2, 3 both, 0 demo */
#define MODE    0x218c
#define PHASE   0x2348         /* match: +0 phase (8 fight, 10 KO), +2 / +3 rounds won P1 / P2 */
#define STAGE   0x2781
#define APOC    0x10           /* Apocalypse id * 2 */

static uint8_t oalive_op, owins_op, owin2[2];

static uint32_t alive2(uint32_t o) { return (G16(o + LIFE) != 0) + (G16(o + PARTNER + LIFE) != 0); }

void port_derive(void) {
	struct vars* v = &ach_v;
	const uint32_t hum = G8(HUMANS), phase = G8(PHASE);
	const uint32_t side = hum > 3 ? 0 : hum, p2 = side == 2;
	const uint32_t me = p2 ? OBJ_P2 : OBJ_P1, op = p2 ? OBJ_P1 : OBJ_P2;
	const int fight = phase == 8 || phase == 10;
	uint32_t k, t;
	v->side = (uint8_t)side;
	v->mode = G8(MODE);
	v->team[0] = v->team[1] = v->team[2] = 0;
	v->act = 0xff; v->act_partner = v->combo = v->full = v->wins = v->alive = 0; v->clear = 0;
	if (side) {
		const uint32_t a = (uint16_t)G16(IDS + 4 * p2) >> 1;
		for (k = 0; k < 2; k++) {
			t = (uint16_t)G16(IDS + 4 * p2 + 2 * k) >> 1;
			if (t < 24) v->team[t >> 3] |= (uint8_t)(1u << (t & 7));
		}
		v->act = (uint8_t)G16(me + ID);                 /* the swap moves the characters: the main object is on point */
		v->act_partner = (uint32_t)(v->act >> 1) != a;
		v->combo = G8(me + COMBO);
		v->full = G16(me + LIFE) == 144 && G16(me + PARTNER + LIFE) == 144;
		v->wins = G8(PHASE + 2 + p2);
		v->alive = (uint8_t)alive2(me);
	}
	/* opponents knocked out: the number of standing opponents goes down (the swap moves lives between objects) */
	t = fight ? alive2(op) : 0;
	if (side && side != 3 && t < oalive_op) {
		v->kos += (uint8_t)(oalive_op - t);
		if (t == 0 && v->mode == 1 && v->alive && (G16(op + ID) == APOC || G16(op + PARTNER + ID) == APOC)) v->clear = 1;
	}
	oalive_op = (uint8_t)t;
	/* the arcade run: starts at the first fight with one human, broken by a lost fight or by leaving arcade */
	t = side && side != 3 ? G8(PHASE + 2 + (side == 1)) : 0;
	if (v->mode != 1 || side == 0 || side == 3) v->run_ok = 0;
	else if (G8(STAGE) == 0 && phase == 8) v->run_ok = 1;
	if (t > owins_op) v->run_ok = 0;
	owins_op = (uint8_t)t;
	/* versus between two humans: either side's win count goes up */
	for (k = 0; k < 2; k++) {
		t = G8(PHASE + 2 + k);
		if (side == 3 && v->mode == 2 && t > owin2[k]) v->vs_wins++;
		owin2[k] = (uint8_t)t;
	}
}

static int slen(const char* s) { int n = 0; while (s[n]) n++; return n; }
void port_text(const char* s, int x, int y, int col) { ((f_text)TEXT_FN)(s, x, y, 8, col, 1); }

/* popup: two centred lines under the HUD (picture centre = routine x 254 (measured: tools work/ach/popmeasure.py)) */
void port_popup(const char* head, const char* line, int first) {
	(void)first;
	if (!*head) { ((f_text)TEXT_FN)(line, 254 - 4 * slen(line), 0x15, 8, 0x30, 1); return; }   /* card notice: top line, above the menu logo */
	((f_text)TEXT_FN)(head, 254 - 4 * slen(head), 0x44, 8, 0x30, 1);
	((f_text)TEXT_FN)(line, 254 - 4 * slen(line), 0x50, 8, 0x33, 1);
}

uint16_t port_pad_held(void) { return (uint16_t)(((f_pad)PAD_NOW)(0) | ((f_pad)PAD_NOW)(1)); }

uint16_t port_pad_new(void) {
	uint32_t k, n = 0;
	for (k = 0; k < 2; k++) n |= ((f_pad)PAD_NOW)(k) & ~((f_pad)PAD_OLD)(k);
	return (uint16_t)n;
}

/* ------------------------------------------------------------------------ */
/* main menu (OPDEMO, struct 0x80042180: +0 state, +0x12 cursor).  6 items drawn from our table; ACHIEVEMENTS
   (cursor 4) opens the page here, OPTION moved to cursor 5: the menu sets state = cursor + 1 = 6, put back to 5. */
#define MENU    ((volatile uint8_t*)0x80042180u)
extern const char ach_menutab[6][16];
#define MENU_LOADED (*(const uint32_t*)0x80098748u == (0x3c110000u | (((uint32_t)ach_menutab + 0x8000u) >> 16)))
int port_card_safe(void) { return !(MENU[0] == 5 && MENU_LOADED); }
int port_card_idle(void) { return MENU[0] == 0 && MENU_LOADED; }

/* the menu overlay (OPDEMO, at 0x80098000) is patched in RAM, by us, once it is loaded (the disc keeps the stock
   file: without our runtime - boot guard - the game runs stock).  Recognised by the sum of the stock words at the
   patched sites (PORT_OVL_SUM, from the user's disc at build time); afterwards the sum differs, so it is done once
   per load.  FlushCache after the stores (the overlay may already have run from the I-cache). */
#define JAL(t) (0x0c000000u | ((uint32_t)(t) >> 2 & 0x03ffffffu))
static const uint32_t ovl_at[7] = { 0x80098748u, 0x8009874cu, 0x80098770u, 0x80098794u, 0x80098948u, 0x8009894cu, 0x8009bf54u };
void bios_flushcache(void);
__attribute__((section(".keeptext"))) void ach_menuin(void);
void port_ovl(void) {
	uint32_t s = 0, i, w[7];
	for (i = 0; i < 7; i++) s += *(volatile uint32_t*)ovl_at[i];
	if (s != (uint32_t)PORT_OVL_SUM) return;
	{
		const uint32_t t = (uint32_t)ach_menutab;
		w[0] = 0x3c110000u | ((t + 0x8000u) >> 16 & 0xffffu); w[1] = 0x26310000u | (t & 0xffffu);   /* lui / addiu s1, our table */
		w[2] = 0x9225000fu;                         /* x = byte 15 of the entry */
		w[3] = 0x2a020006u;                         /* 6 lines */
		w[4] = 0x28420006u; w[5] = 0x34020005u;     /* cursor 0..5 */
		w[6] = JAL(ach_menuin);                     /* the title scene's call of the menu routine */
	}
	for (i = 0; i < 7; i++) *(volatile uint32_t*)ovl_at[i] = w[i];
	bios_flushcache();
}

int ach_page(void);
static uint8_t page;
uint32_t port_menu_frame;
__attribute__((section(".keeptext"))) void ach_menuin(void) {
	uint32_t s, c;
	if (page) return;                        /* the page runs in port_page_idle; the menu waits */
	port_menu_frame = ach_dbg_frames();
	s = MENU[0]; c = MENU[0x12];
	((void (*)(void))MENU_FN)();
	if (s == 0 && MENU[0] == 5 && c == 4) { MENU[0] = 0; page = 1; }      /* ACHIEVEMENTS chosen */
	else if (s == 0 && MENU[0] == 6) MENU[0] = 5;                        /* OPTION, now on cursor 5 */
}

uint16_t port_page_cost[2];                                            /* hblanks of the last page call, the most (tests) */
void port_page_idle(void) {
	uint16_t t;
	if (!page) return;
	t = *(volatile uint16_t*)0x1F801110u;
	*(volatile uint8_t*)0x8003d918u = 1;                                  /* direct mode (as the one-shot screens) */
	page = (uint8_t)ach_page();
	*(volatile uint8_t*)0x8003d918u = 0;
	t = (uint16_t)(*(volatile uint16_t*)0x1F801110u - t);
	port_page_cost[0] = t;
	if (t > port_page_cost[1]) port_page_cost[1] = t;
	if (!page) { MENU[0] = MENU[1] = MENU[2] = MENU[3] = 0; }              /* back: the menu starts again */
}

/* menu strings, 16-byte stride; byte 15 = the x of the line (the draw loop reads it: xvach.py), so that
   ACHIEVEMENTS (12 characters) is centred like the others, which centre with leading spaces */
const char ach_menutab[6][16] __attribute__((section(".keep"))) = {
	" BATTLE MODE\0\0\0\xc8", " VERSUS MODE\0\0\0\xc8", "TRAINING MODE\0\0\xc8", "SURVIVAL MODE\0\0\xc8",
	"ACHIEVEMENTS\0\0\0\xcc", " OPTION MODE\0\0\0\xc8" };

/* memory card file: title (Shift-JIS "XvSF ACHIEVEMENTS") */
const uint8_t ach_file_title[64] = {
	0x82,0x77, 0x82,0x96, 0x82,0x72, 0x82,0x65, 0x81,0x40,
	0x82,0x60, 0x82,0x62, 0x82,0x67, 0x82,0x68, 0x82,0x64, 0x82,0x75, 0x82,0x64, 0x82,0x6c, 0x82,0x64, 0x82,0x6d,
	0x82,0x73, 0x82,0x72, 0 };
