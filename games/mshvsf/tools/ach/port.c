/* port.c: MSHvSF side of the built-in achievements (see port.h, tools/ach/ach.c, docs/ACHIEVEMENTS.md) */
#include "port.h"

/* derived bytes, read by the set (set.py names them): the linker puts them at ACH_BASE + 0x20 */
struct vars {
	uint8_t side;        /*  0: human side 1 = P1, 2 = P2 (one human, or P1 when both), 0 = none (demo) */
	uint8_t team[4];     /*  1: human team, bit (id / 2) per character */
	uint8_t act;         /*  5: on-point human character id * 2 (0xff without a human) */
	uint8_t act_partner; /*  6: 1 while the human team's second character is on point */
	uint8_t combo;       /*  7: hit count of the human's current combo */
	uint8_t kos;         /*  8: opponents knocked out (counts up, wraps) */
	uint8_t full;        /*  9: 1 while both human characters have full life */
	uint8_t wins;        /* 10: rounds the human side won in this match */
	uint8_t clear;       /* 11: 1 on the frame an arcade run is cleared (stage 7 -> 8) */
	uint8_t boss;        /* 12: opponent's main character id * 2 */
	uint8_t diff_ok;     /* 13: difficulty default or higher */
	uint8_t mode;        /* 14: menu mode (0 arcade, 1 versus, 2 training, 5 hero battle) */
	uint8_t run_ok;      /* 15: 1 while this arcade run started at the first stage and lost no fight */
};
struct vars ach_v __attribute__((section(".vars")));

#define U8(a)  (*(const uint8_t*)(a))
#define U16(a) (*(const uint16_t*)(a))
/* game bytes, as offsets from G = 0x80070000 */
#define G       ((const uint8_t*)0x80070000u)
#define OBJ_P1  0x0b50
#define OBJ_P2  0x0f10
#define PARTNER 0x07c0         /* partner object = main + 0x7c0 */
#define LIFE    0x254
#define ID      0x4e
#define COMBO   0x114
#define ONPOINT 0x143          /* main object: 0xff while the partner is on point */
#define G8(o)   G[o]
#define G16(o)  (*(const uint16_t*)(G + (o)))

static uint16_t olife[2];
static uint8_t ostage, owins_opp;

void port_derive(void) {
	struct vars* v = &ach_v;
	const uint32_t hum = G8(0x0a91);
	const uint32_t side = hum == 2 ? 2 : hum ? 1 : 0, p2 = side == 2;
	const uint32_t me = p2 ? OBJ_P2 : OBJ_P1, op = p2 ? OBJ_P1 : OBJ_P2;
	const uint32_t phase = G8(0x0778), stage = G8(0x07c4);
	uint32_t k, t;
	v->side = (uint8_t)side;
	v->mode = U8(0x800250acu);
	v->diff_ok = U8(0x8002506cu) >= 2;
	*(uint32_t*)((uint8_t*)v + 0) &= 0xff;                    /* team[0..2] (side stays) */
	v->team[3] = 0;
	v->act = 0xff; v->act_partner = v->combo = v->full = v->wins = 0; v->boss = 0xff;
	if (side) {
		for (k = 0; k < 2; k++) {
			t = G16(0x07ea + 4 * p2 + 2 * k) >> 1;
			if (t < 32) v->team[t >> 3] |= (uint8_t)(1u << (t & 7));
		}
		k = G8(me + ONPOINT) == 0xff;
		v->act_partner = (uint8_t)k;
		v->act = (uint8_t)G16(me + PARTNER * k + ID);
		k = G8(me + COMBO); t = G8(me + PARTNER + COMBO);
		v->combo = (uint8_t)(k > t ? k : t);
		v->full = G16(me + LIFE) == 144 && G16(me + PARTNER + LIFE) == 144;
		v->wins = G8(0x077a + p2);
		v->boss = (uint8_t)G16(op + ID);
	}
	/* opponent KOs: a life that drops to 0 during the fight (phase 8 fight, 10 KO) */
	for (k = 0; k < 2; k++) {
		t = phase == 8 || phase == 10 ? G16(op + PARTNER * k + LIFE) : 0;
		if (side && olife[k] && !t) v->kos++;
		olife[k] = (uint16_t)t;
	}
	/* the arcade run: starts at stage 0 with one human, broken by a lost fight or by leaving arcade */
	t = side ? G8(0x077a + (side == 1)) : 0;
	if (v->mode != 0 || hum == 0 || hum == 3) v->run_ok = 0;
	else if (stage == 0 && phase == 8) v->run_ok = 1;
	if (side && t > owins_opp) v->run_ok = 0;
	owins_opp = (uint8_t)t;
	v->clear = side && hum != 3 && v->mode == 0 && ostage == 7 && stage == 8;
	ostage = (uint8_t)stage;
}

static int slen(const char* s) { int n = 0; while (s[n]) n++; return n; }
/* the game's text routine, 8 pixel cells */
void port_text(const char* s, int x, int y, int col) {
	((f_print)PRINT_FN)(s, (uint32_t)x << 16 | (uint32_t)y, 8u << 24 | (uint32_t)col << 16 | 1);
}

/* ------------------------------------------------------------------------ */
/* the popup.  The game's text routine costs ~400 cycles a character, too much for every frame of a fight, so the
   first frame draws it with that routine and keeps the sprites it made (position, texture, CLUT); later frames put
   copies into the game's sprite pool and link them like the routine does (~40 cycles a character).
   Draw buffer *0x80027bf8: +0/4/8 last primitive of the 3 layer lists, +0xc texture-page primitives used (16 at +0x10,
   12 bytes each), +0xd0 texture page per layer, +0xd8 sprite pool (20-byte SPRT), +0xdc pool size, +0xde used. */
#define GBUF (*(uint8_t* const*)0x80027bf8u)
#define POP_MAX 46
static struct { int16_t layer, n, tp, pad; uint32_t code, wh, xy[POP_MAX], uvc[POP_MAX]; } cap __attribute__((section(".bdat")));
typedef void (*f_tp)(void*, int, int, int, int);
typedef void (*f_add)(void*, int);

static void popup_line(const char* s, int y, int col) {
	((f_print)PRINT_FN)(s, (uint32_t)(255 - 4 * slen(s)) << 16 | (uint32_t)y, 8u << 24 | (uint32_t)col << 16 | 1);
}

void port_popup(const char* head, const char* line, int first) {
	uint8_t* b = GBUF;
	int16_t* used = (int16_t*)(b + 0xde);
	uint32_t i;
	if (first || cap.layer < 0) {
		uint32_t tails[3], i0 = (uint16_t)*used;
		for (i = 0; i < 3; i++) tails[i] = ((uint32_t*)b)[i];
		popup_line(head, 0x4a, 0x22);
		popup_line(line, 0x56, 0x20);
		cap.layer = -1;
		for (i = 0; i < 3; i++) if (((uint32_t*)b)[i] != tails[i]) cap.layer = (int16_t)i;
		if (U8(0x8002474cu) || cap.layer < 0) return;          /* (debug path: draws straight to the GPU) */
		cap.n = 0;
		for (i = i0; i < (uint16_t)*used && cap.n < POP_MAX; i++) {
			const uint32_t* p = (const uint32_t*)(*(uint8_t**)(b + 0xd8) + 20 * i);
			cap.code = p[1]; cap.wh = p[4];
			cap.xy[cap.n] = p[2]; cap.uvc[cap.n] = p[3]; cap.n++;
		}
		cap.tp = *(int16_t*)(b + 0xd0 + 2 * cap.layer);
		return;
	}
	{
		const int l = cap.layer;
		int16_t* tp = (int16_t*)(b + 0xd0 + 2 * l);
		uint32_t** tail = (uint32_t**)b + l;
		if (*tp != cap.tp) {                                      /* texture page, as 0x80022c1c does */
			int* k = (int*)(b + 0xc);
			if (*k >= 16) return;
			{
				void* p = b + 0x10 + 12 * *k;
				(*k)++;
				((f_tp)0x80017318u)(p, 1, 0, *(const int16_t*)(0x80025100u + 2 * cap.tp), 0);
				((f_add)0x800226fcu)(p, l);
				*tp = cap.tp;
			}
		}
		for (i = 0; i < (uint32_t)cap.n && *used < *(int16_t*)(b + 0xdc); i++) {
			uint32_t* p = (uint32_t*)(*(uint8_t**)(b + 0xd8) + 20 * *used);
			(*used)++;
			p[0] = 0x04ffffffu; p[1] = cap.code; p[2] = cap.xy[i]; p[3] = cap.uvc[i]; p[4] = cap.wh;
			**tail = (**tail & 0xff000000u) | ((uint32_t)p & 0x00ffffffu);
			*tail = p;
		}
	}
}

/* ------------------------------------------------------------------------ */
/* memory card: the game's own card code runs only in the OPTION screen of the main menu (OPDEMO / OPE.ARC,
   state 0x80025040 == 6).  Idle = the main menu's root state with the overlay in RAM. */
void ach_state(void);
#define MENU_LOADED (*(void (* const*)(void))0x800b6274u == ach_state)     /* our state-table entry: the overlay is in RAM */
int port_card_safe(void) { return !(U8(0x80025040u) == 6 && MENU_LOADED); }
int port_card_idle(void) { return U8(0x80025040u) == 0 && MENU_LOADED; }

/* main-menu state handler of the ACHIEVEMENTS item (state table 0x800b6260 entry 5); runs in the
   dispatcher's frame and leaves through its epilogue 0x80099e98 */
int ach_page(void);
void ach_menu(void) {
	if (!ach_page()) {
		volatile uint8_t* m = (volatile uint8_t*)0x80025040u;
		m[0] = 0; m[1] = 0; m[2] = 0; m[3] = 0;          /* back to the main menu */
	}
}
__asm__(".set push\n.set noreorder\n.globl ach_state\nach_state:\n jal ach_menu\n nop\n j 0x80099e98\n nop\n.set pop\n");

/* memory card file: title (Shift-JIS "MSHvSF ACHIEVEMENTS") */
const uint8_t ach_file_title[64] = {
	0x82,0x6c, 0x82,0x72, 0x82,0x67, 0x82,0x96, 0x82,0x72, 0x82,0x65, 0x81,0x40,
	0x82,0x60, 0x82,0x62, 0x82,0x67, 0x82,0x68, 0x82,0x64, 0x82,0x75, 0x82,0x64, 0x82,0x6c, 0x82,0x64, 0x82,0x6d,
	0x82,0x73, 0x82,0x72, 0 };

/* the main menu's text table (OPDEMO 0x80099404 draws 7 entries from here at stride 13; mshach.py) */
const char ach_menutab[7][13] __attribute__((section(".keep"))) = { "BATTLE", "VERSUS", "TRAINING", "HERO BATTLE", "ACHIEVEMENTS", "OPTION", "GALLERY" };

/* the menu overlay (OPDEMO / OPE.ARC entry 0) is patched in RAM, by us, once it is loaded (the disc keeps the stock
   file: without our runtime - boot guard - the game runs stock).  Recognised by the sum of the words at the sites as
   the disc has them (PORT_OVL_SUM, computed at build time); afterwards the sum differs.  FlushCache after the stores. */
void bios_flushcache(void);
static const uint32_t ovl_at[9] = { 0x8009942cu, 0x80099434u, 0x800994b8u, 0x800994c0u, 0x80099c8cu, 0x80099c90u,
	0x800b6274u, 0x800b6278u, 0x800b627cu };
void port_ovl(void) {
	uint32_t s = 0, i, w[9];
	const uint32_t t = (uint32_t)ach_menutab;
	for (i = 0; i < 9; i++) s += *(volatile uint32_t*)ovl_at[i];
	if (s != (uint32_t)PORT_OVL_SUM) return;
	w[0] = 0x3c020000u | ((t + 0x8000u) >> 16 & 0xffffu);   /* lui v0, %hi(tab) */
	w[1] = 0x24520000u | (t & 0xffffu);                     /* addiu s2, v0, %lo(tab) */
	w[2] = 0x2a220007u; w[3] = 0x2652000du;                 /* 7 entries, stride 13 */
	w[4] = 0x28420007u; w[5] = 0x24020006u;                 /* cursor wraps in 0..6 */
	w[6] = (uint32_t)ach_state; w[7] = 0x80099e44u; w[8] = 0x80099e90u;   /* states 5 (ours), 6 OPTION, 7 GALLERY */
	for (i = 0; i < 9; i++) *(volatile uint32_t*)ovl_at[i] = w[i];
	bios_flushcache();
}
