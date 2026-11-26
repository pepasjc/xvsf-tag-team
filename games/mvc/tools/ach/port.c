/* port.c: MvC side of the built-in achievements (see port.h, tools/ach/ach.c, docs/ACHIEVEMENTS.md).
   Our own state lives only in our RAM (kernel RAM A/B): no game byte is written except the main menu's state
   block when the page closes (as the game's own handlers do). */
#include "port.h"

/* derived bytes, read by the set (set.py names them): the linker puts them at ACH_BASE + 0x20 */
struct vars {
	uint8_t side;        /*  0: human side 1 = P1, 2 = P2 (P1 when both), 0 = none (demo) */
	uint8_t main;        /*  1: the human side's first pick id * 2 (0xff without a human) */
	uint8_t act;         /*  2: on-point human character id * 2 (0xff without a human) */
	uint8_t combo;       /*  3: hit count of the human's current combo */
	uint8_t full;        /*  4: 1 while both human characters have full life */
	uint8_t clear;       /*  5: the set's Battle-mode clear: mode BATTLE, beginner off, difficulty >= 2, stage >= 7, ending */
	uint8_t clear8;      /*  6: the same on difficulty 8 */
	uint8_t gate;        /*  7: the set's finish gate (BATTLE, 0x07cafb == 0, 0x07bdc8 != 0, beginner off, diff >= 2, 0x07c534 == 0) */
	uint8_t fin;         /*  8: finish code of the last round end (0x07b770 when 0x07b82a == 1, 0x07b772 when 2) */
	uint8_t group;       /*  9: on-point character: 1 Marvel, 2 Capcom */
	uint8_t mgroup;      /* 10: first pick: 1 Marvel, 2 Capcom */
	uint8_t sgate;       /* 11: the set's score gate (BATTLE, 0x07bdc8 != 0, beginner off, diff >= 2) */
	uint8_t cgate;       /* 12: combos: beginner off, BATTLE or TRAINING */
	uint8_t ryu;         /* 13: Ryu's form byte 0x07b8e4 in BATTLE with 0x07bdc8 == 1, else 0 */
	uint8_t nodown;      /* 14: 1 while this Battle run started at the first stage and no human character fell */
	uint8_t pad;
};
struct vars ach_v __attribute__((section(".vars")));

/* game bytes, offsets from G = 0x80070000 */
#define G       ((const uint8_t*)0x80070000u)
#define G8(o)   G[o]
#define G16(o)  (*(const uint16_t*)(G + (o)))
#define OBJ_P1  0xbe90         /* objects 0x408 bytes: P1 0x8007be90, P2 0x8007c2a0, P1 partner +0x860, P2 partner +0x858 */
#define OBJ_P2  0xc2a0
#define P1P     0xc6f0
#define P2P     0xcaf8
#define LIFE    0x294
#define COMBO   0x138
#define TEAM    0xb8aa         /* s16[4] id * 2: P1 main, P1 partner, P2 main, P2 partner */
#define MODE    0xb740         /* 0 BATTLE, 1 VERSUS, 2 CROSS OVER, 3 TRAINING (written by the menu) */
#define HUMANS  0xbdc9         /* 1 P1, 2 P2, 3 both, 0 demo */
#define STAGE   0xbdf2

/* Marvel ids * 2 (the set's own groups): War Machine 2, Captain America 4, Hulk 6, Wolverine 8, Gambit 10, Venom 12,
   Spider-Man 14, Red Venom 36, Orange Hulk 38, Gold War Machine 40 */
static uint32_t group_of(uint32_t id) {
	return id == 0xff || id == 34 ? 0 : ((id >= 2 && id <= 14) || id == 36 || id == 38 || id == 40) ? 1 : 2;   /* Onslaught 34: neither */
}

static uint16_t olife[2];

void port_derive(void) {
	struct vars* v = &ach_v;
	const uint32_t hum = G8(HUMANS);
	const uint32_t side = hum == 2 ? 2 : hum ? 1 : 0, p2 = side == 2;
	const uint32_t mo = p2 ? OBJ_P2 : OBJ_P1, po = p2 ? P2P : P1P;
	const uint32_t mode = G8(MODE), beg = G8(0xc16d), diff = G8(0xb71c), stage = G8(STAGE);
	const uint32_t battle = mode == 0, base = battle && beg <= 1;
	uint32_t k, t;
	v->side = (uint8_t)side;
	if (side) {
		v->main = (uint8_t)G16(TEAM + 4 * p2);
		v->act = (uint8_t)G16(TEAM + 4 * p2 + 2 * (!G8(mo) && G8(po)));   /* main object inactive, partner active */
		k = G8(mo + COMBO); t = G8(po + COMBO);
		v->combo = (uint8_t)(k > t ? k : t);
		v->full = G16(mo + LIFE) == 144 && G16(po + LIFE) == 144;
	} else {
		v->main = v->act = 0xff; v->combo = v->full = 0;
	}
	v->group = (uint8_t)group_of(v->act);
	v->mgroup = (uint8_t)group_of(v->main);
	t = base && stage >= 7 && G8(0xcf10) == 2;
	v->clear = (uint8_t)(t && diff >= 1);
	v->clear8 = (uint8_t)(t && diff == 7);
	v->gate = battle && !G8(0xcafb) && G8(0xbdc8) && beg <= 1 && diff >= 1 && !G8(0xc534);
	k = G8(0xb82a);
	v->fin = k == 1 ? G8(0xb770) : k == 2 ? G8(0xb772) : 0;
	v->sgate = battle && G8(0xbdc8) && beg <= 1 && diff >= 1;
	v->cgate = beg <= 1 && (battle || mode == 3);
	v->ryu = battle && G8(0xbdc8) == 1 ? G8(0xb8e4) : 0;
	/* the Battle run (the set's own latch: stage 0 with 0x07b82b == 0), broken when a human character falls */
	if (!battle || !side) v->nodown = 0;
	else {
		if (stage == 0 && !G8(0xb82b) && v->full) v->nodown = 1;
		for (k = 0; k < 2; k++) {
			t = G16((k ? po : mo) + LIFE);
			if (olife[k] && !t) v->nodown = 0;
		}
	}
	olife[0] = side ? G16(mo + LIFE) : 0; olife[1] = side ? G16(po + LIFE) : 0;
}

static int slen(const char* s) { int n = 0; while (s[n]) n++; return n; }
void port_text(const char* s, int x, int y, int col) {
	((f_print)PRINT_FN)(s, (uint32_t)x << 16 | (uint32_t)y, 8u << 24 | (uint32_t)col << 16 | 1);
}

uint16_t port_pad_new(void) {
	static const uint16_t m[] = { PORT_B_UP, PORT_B_DOWN, PORT_B_LEFT, PORT_B_RIGHT, 0x0010, 0x0020 };
	uint32_t k, n = 0;
	for (k = 0; k < sizeof(m) / sizeof(m[0]); k++) if (((uint32_t (*)(uint32_t, uint32_t))0x8002518cu)(4, m[k])) n |= m[k];
	return (uint16_t)n;
}

/* ------------------------------------------------------------------------ */
/* the popup: as MSHvSF (same engine): the first frame through the text routine, then copies of its sprites.
   Draw buffer *0x800263c8 (+0/4/8 layer tails, +0xc tpage prims used, +0x10 tpage prims, +0xd0 tpage per layer,
   +0xd8 sprite pool, +0xdc size, +0xde used); SetDrawTPage 0x80017318, add-to-layer 0x80020818, tpage table
   0x80028618, debug path flag 0x80025574. */
#define GBUF (*(uint8_t* const*)0x800263c8u)
#define POP_MAX 46
static struct { int16_t layer, n, tp, pad; uint32_t code, wh, xy[POP_MAX], uvc[POP_MAX]; } cap __attribute__((section(".bdat")));
typedef void (*f_tp)(void*, int, int, int, int);
typedef void (*f_add)(void*, int);

static void popup_line(const char* s, int y, int col) {
	((f_print)PRINT_FN)(s, (uint32_t)(256 - 4 * slen(s)) << 16 | (uint32_t)y, 8u << 24 | (uint32_t)col << 16 | 1);
}

void port_popup(const char* head, const char* line, int first) {
	uint8_t* b = GBUF;
	int16_t* used = (int16_t*)(b + 0xde);
	uint32_t i;
	if (first || cap.layer < 0) {
		uint32_t tails[3], i0 = (uint16_t)*used;
		for (i = 0; i < 3; i++) tails[i] = ((uint32_t*)b)[i];
		popup_line(head, 0x4a, PORT_COL_ON);
		popup_line(line, 0x56, PORT_COL_HEAD);
		cap.layer = -1;
		for (i = 0; i < 3; i++) if (((uint32_t*)b)[i] != tails[i]) cap.layer = (int16_t)i;
		if (*(const uint8_t*)0x80025574u || cap.layer < 0) return;
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
		if (*tp != cap.tp) {
			int* k = (int*)(b + 0xc);
			if (*k >= 16) return;
			{
				void* p = b + 0x10 + 12 * *k;
				(*k)++;
				((f_tp)0x80017318u)(p, 1, 0, *(const int16_t*)(0x80028618u + 2 * cap.tp), 0);
				((f_add)0x80020818u)(p, l);
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
/* main menu (OPDEMO.ARC, state block 0x8007b6e8: +0 state, +0xc cursor).  The game's card code runs in OPTION
   (state 6 after our reorder) and EX OPTION (8). */
void ach_state(void);
#define MENU ((volatile uint8_t*)0x8007b6e8u)
#define MENU_LOADED (*(void (* const*)(void))(0x800b5bf8u + 4 * 5) == ach_state)
int port_card_safe(void) { return !((MENU[0] == 6 || MENU[0] == 8) && MENU_LOADED); }
int port_card_idle(void) { return MENU[0] == 0 && MENU[1] && MENU_LOADED; }     /* main menu up (+1 != 0; the title has 0) */

int ach_page(void);
void ach_menu(void) {
	if (!ach_page()) { MENU[0] = 0; MENU[1] = 0; MENU[2] = 0; MENU[3] = 0; }
}
__asm__(".set push\n.set noreorder\n.globl ach_state\nach_state:\n jal ach_menu\n nop\n j 0x800a2df8\n nop\n.set pop\n");

/* our copy of the menu strings (13-byte stride): mvcach.py fills the version line from menus.py's output */
char ach_menutab[7][13] __attribute__((section(".keep"))) = { "BATTLE", "VERSUS", "TRAINING", "GALLERY", "ACHIEVEMENTS", "OPTION", "" };

/* memory card file: title (Shift-JIS "MVC ACHIEVEMENTS") */
const uint8_t ach_file_title[64] = {
	0x82,0x6c, 0x82,0x96, 0x82,0x62, 0x81,0x40,
	0x82,0x60, 0x82,0x62, 0x82,0x67, 0x82,0x68, 0x82,0x64, 0x82,0x75, 0x82,0x64, 0x82,0x6c, 0x82,0x64, 0x82,0x6d,
	0x82,0x73, 0x82,0x72, 0 };
