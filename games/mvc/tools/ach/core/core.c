/* core.c: MvC built-in achievements, resident core (freeze worker, rc4 line 2026-11-20; docs/ACHIEVEMENTS.md "rc4 core").

   Lives in kernel RAM in every scene (corebuild.py packs it into the real-PS1-proven spans rc4 leaves free).  Once per
   main-loop frame (ach_frame, from the call at 0x80022fe8): the derived bytes of port.c (same results: host/derive_diff),
   the evaluation of the adapted set (corec.py tables: 74 pure achievements as templates, 112518 by hand below; both
   exact to rcheevos 12.5 frame by frame: host/core_diff), the unlock bits and the popup ("ACHIEVEMENT UNLOCKED" + title
   + points; not drawn while the EX OPTIONS byte ACHIEVEMENT POPUP 0x8001175d is 1 = OFF; unlocks are recorded either
   way).  The main menu's ACHIEVEMENTS item, the list page and the memory card are the menu module's (module.c), read
   from the disc when the main menu is up; it reads / sets c_done, c_dirty, c_page. */
#include <stdint.h>
#include "core_set.h"

#ifdef HOST
extern uint8_t* host_ram;
#define GB(o) host_ram[(o) & 0x1FFFFFu]
#define G16(o) (uint32_t)(GB(o) | GB((o) + 1) << 8)
#define G32(o) (uint32_t)(GB(o) | GB((o) + 1) << 8 | GB((o) + 2) << 16 | (uint32_t)GB((o) + 3) << 24)
#define c_vars (host_ram + 0xc020)       /* the oracle's set reads them at V = 0x00c020 (set.py) */
#else
/* game bytes 0x8007xxxx through one base register (signed 16-bit offsets from 0x80078000) */
#define GBASE ((const uint8_t*)0x80078000u)
#define GB(o) GBASE[(int)(o) - 0x78000]
#define G16(o) (uint32_t)*(const uint16_t*)(GBASE + ((int)(o) - 0x78000))
#define G32(o) *(const uint32_t*)(GBASE + ((int)(o) - 0x78000))
uint8_t c_vars[16];
#endif

/* ---- derived bytes (port.c port_derive) --------------------------------------------------------------------- */
enum { SIDE, MAIN, ACT, COMBO, FULL, CLEAR, CLEAR8, GATE, FIN, GROUP, MGROUP, SGATE, CGATE, RYU, NODOWN, MVL };
#define OBJ_P1 0x7be90
#define OBJ_P2 0x7c2a0
#define LIFE   0x294
#define CMB    0x138
static uint16_t olife[2];

static uint32_t group_of(uint32_t id) {
	return id == 0xff || id == 34 ? 0 : ((id >= 2 && id <= 14) || id == 36 || id == 38 || id == 40) ? 1 : 2;
}

#ifndef HOST
static void derive(void) {
	uint8_t* v = c_vars;
	const uint32_t hum = GB(0x7bdc9);
	const uint32_t p2 = hum == 2, side = hum ? 1 + p2 : 0;
	const uint32_t mo = p2 ? OBJ_P2 : OBJ_P1, po = mo + 0x860 - 8 * p2;       /* partners: P1 + 0x860, P2 + 0x858 */
	const uint32_t mode = GB(0x7b740), diff = GB(0x7b71c), stage = GB(0x7bdf2), bdc8 = GB(0x7bdc8);
	const uint32_t battle = mode == 0, nbeg = GB(0x7c16d) <= 1, d1 = diff >= 1;
	const uint32_t lm = G16(mo + LIFE), lp = G16(po + LIFE);
	uint32_t k, t;
	v[SIDE] = (uint8_t)side;
	k = GB(mo + CMB); t = GB(po + CMB);
	v[COMBO] = (uint8_t)(side ? (k > t ? k : t) : 0);
	v[FULL] = (uint8_t)(side && lm == 144 && lp == 144);
	k = 0x7b8aa + 4 * p2;
	v[MAIN] = side ? (uint8_t)G16(k) : 0xff;
	v[ACT] = side ? (uint8_t)G16(k + 2 * (!GB(mo) & (GB(po) != 0))) : 0xff;
	v[GROUP] = (uint8_t)group_of(v[ACT]);
	v[MGROUP] = (uint8_t)group_of(v[MAIN]);
	t = battle & nbeg & (stage >= 7) & (GB(0x7cf10) == 2);
	v[CLEAR] = (uint8_t)(t & d1);
	v[CLEAR8] = (uint8_t)(t & (diff == 7));
	t = battle & (bdc8 != 0) & nbeg & d1;
	v[SGATE] = (uint8_t)t;
	v[GATE] = (uint8_t)(t & !GB(0x7cafb) & !GB(0x7c534));
	k = GB(0x7b82a);
	v[FIN] = k == 1 ? GB(0x7b770) : k == 2 ? GB(0x7b772) : 0;
	v[CGATE] = (uint8_t)(nbeg & (battle | (mode == 3)));
	v[RYU] = battle & (bdc8 == 1) ? GB(0x7b8e4) : 0;
	if (!battle || !side) v[NODOWN] = 0;
	else {
		if (stage == 0 && !GB(0x7b82b) && v[FULL]) v[NODOWN] = 1;
		if ((olife[0] && !lm) || (olife[1] && !lp)) v[NODOWN] = 0;
	}
	olife[0] = side ? lm : 0; olife[1] = side ? lp : 0;
#ifdef ACHFIX
	/* (ach audit, --achfix) the human's side instead of P1 (rounds won 0x7b82a / 0x7b82b, finish codes 0x7b770 /
	   0x7b778, score main +0x2d8, the opponent's partner human flag and main life), plus:
	   SGATE = the score gate ? 1 + score tier (>= 600,000 / 800,000 / 1,000,000) : 0;
	   GATE  also needs the human side's round win (Perfect opened when only the opponent's first character fell);
	   RYU   = the form byte of the human's on-point object (0x7b8e4 + object: P1 / P2 main, P1 / P2 partner; Ryu's
	           style, Mech Zangief);
	   MVL   = 0x80 | the move number (+0x98) of the human's on-point object, latched on the first frame of the win
	           (whatever finish code the game gives: Proton Cannon 4, War Destroyer 6); 0x80 when the last opponent was
	           hit by an assist object (0x8007bb90 / 0x8007bca8: the point character keeps its old move number). */
	{
		const uint32_t oppm = p2 ? OBJ_P1 : OBJ_P2, oppp = p2 ? 0x7c6f0 : 0x7caf8;
		const uint32_t w = GB(0x7b82a + p2), fb = 0x7b770 + 8 * p2;
		const uint32_t onp = !GB(mo) & (GB(po) != 0), ao = onp ? po : mo;
		const uint32_t sg = battle & (bdc8 != 0) & nbeg & d1 & (side != 0);
		const uint32_t sc = G32(mo + 0x2d8);
		v[SGATE] = sg ? (uint8_t)(1 + (sc >= 600000) + (sc >= 800000) + (sc >= 1000000)) : 0;
		v[GATE] = (uint8_t)(sg & !GB(oppp + 3) & !GB(oppm + LIFE) & (w != 0));
		v[FIN] = w == 1 ? GB(fb) : w == 2 ? GB(fb + 2) : 0;
		v[RYU] = battle & (bdc8 == 1) & (side != 0) ? GB(0x7b8e4 + p2 + 2 * onp) : 0;
		if (!side || !w) v[MVL] = 0;
		else if (!v[MVL]) {
			const uint32_t a = G32((GB(oppp) ? oppp : oppm) + 0xa0) - 0x8007bb90u;
			v[MVL] = (uint8_t)(a < 0x230 ? 0x80 : 0x80 | GB(ao + 0x98));
		}
	}
#endif
}
#endif

/* ---- evaluation ------------------------------------------------------------------------------------------- */
#define NB ((NACH + 7) / 8)
uint8_t c_done[NB];          /* unlocked (this session or loaded from the card by the module): never tested again */
uint8_t c_wait[NB] = { [0 ... NB - 1] = 0xff };   /* rcheevos WAITING: true at activation, false once before it can trigger */
uint8_t c_dirty;             /* unlocks the card does not have yet (the module saves them) */
static uint8_t dprev, dval;  /* the one delta of the set: the combo count one evaluation ago (rcheevos memref delta) */
static uint8_t s_any, s_hit, s_hh, s_prevb;   /* 112518: some hit count != 0, the .1. target's count, has_hits, delta */

static int pure(const uint8_t* r) {
	const uint8_t* t = c_tpl + c_toff[r[0] & 15];
	for (; *t != 0xff; t += 3) {
		const uint32_t w = c_ref[t[0]], m = t[1] >> 3;
		const uint32_t p = m & 1 ? r[1] : r[2];
		const uint32_t v = !m ? c_const[t[2]] : m <= 2 ? p : m <= 4 ? c_const[p] : p - 1;
		uint32_t a;
		if (w & 0x8000) a = w & 0x4000 ? dval : c_vars[w & 15];
		else a = w & 0x2000 ? G32(0x7b000 + (w & 0x1fff)) : GB(0x7b000 + (w & 0x1fff));
		if (!(t[1] & (a < v ? 4 : a == v ? 2 : 1))) return 0;
	}
	return 1;
}
#define BIT(a, i) ((a)[(i) >> 3] >> ((i) & 7) & 1)
#define CLR(a, i) ((a)[(i) >> 3] &= (uint8_t)~(1u << ((i) & 7)))

/* 112518 "R:0xH07b740!=0_N:0xH07bdf2=0_0xH07b82b=0.1._N:0xH07b82b=2_R:d0xH07b82b=1_N:0xH07b82b=1_N:d0xH07b82b=0_
   R:0xH07bdf2=7_0xH07c16d<=1_0xH07b71c>=1_T:0xH07bdf2>=7_T:0xH07cf10=2" in rcheevos' part order (setc.py): the ResetIf
   chains, the hit-target chain, the rest; tools/ach/eval.c's semantics.  A hit count matters only as != 0 (has_hits),
   except the .1. target's (0 / 1).  Returns 1 = trigger. */
#define H(x) ((x) ? (s_any = 1) : 0)
static int special(int waiting, uint32_t b) {
	const uint32_t st = GB(0x7bdf2), db = s_prevb;
	int reset, an, t;
	reset = H(GB(0x7b740) != 0);
	an = H(b == 2); reset |= H(an && db == 1);
	an = H(b == 1); an = H(an && db == 0); reset |= H(an && st == 7);
	if (reset) {
		s_any = s_hit = 0;
		if (s_hh) s_hh = 0; else CLR(c_wait, SPECIAL_IDX);
		return 0;
	}
	an = H(st == 0);
	if (H(an && b == 0)) s_hit = 1;
	t = s_hit;
	t &= H(GB(0x7c16d) <= 1);
	t &= H(GB(0x7b71c) >= 1);
	t &= H(st >= 7);
	t &= H(GB(0x7cf10) == 2);
	if (t) {
		if (waiting) { s_any = s_hit = s_hh = 0; return 0; }
		return 1;
	}
	s_hh = s_any;
	CLR(c_wait, SPECIAL_IDX);
	return 0;
}

#ifdef HOST
static uint8_t c_queue[NACH], c_nq;
#else
static uint8_t c_queue[8], c_nq;
#endif
static void eval(void) {
	uint32_t i;
	const uint32_t b = GB(0x7b82b);
	dval = dprev; dprev = c_vars[DELTA_VAR];
	for (i = 0; i < NACH; i++) {
		uint8_t* const d = &c_done[i >> 3];
		const uint32_t m = 1u << (i & 7);
		int t;
		if (*d & m) continue;
		if (i == SPECIAL_IDX) t = special(BIT(c_wait, i), b);
		else {
			t = pure(c_rec[i]);
			if (!t) { c_wait[i >> 3] &= (uint8_t)~m; continue; }
			if (c_wait[i >> 3] & m) continue;
		}
		if (!t) continue;
		*d |= (uint8_t)m; c_dirty = 1;
		if (c_nq < sizeof(c_queue)) c_queue[c_nq++] = (uint8_t)i;
	}
	s_prevb = (uint8_t)b;
}
#ifdef HOST
uint32_t c_frame(uint8_t* out) {      /* host: one evaluation, the newly unlocked indices */
	uint32_t n0 = c_nq, k;
	eval();
	for (k = n0; k < c_nq; k++) out[k - n0] = c_queue[k];
	n0 = c_nq - n0; c_nq = 0;
	return n0;
}
#endif

#ifndef HOST
/* ---- popup ------------------------------------------------------------------------------------------------ */
#define PRINT_FN 0x80020f10u          /* (text, x << 16 | y, advance << 24 | colour << 16 | 1) */
#define SFX_FN   0x80085a7cu
#define POPUP_OFF (*(const volatile uint8_t*)0x8001175du)     /* EX OPTIONS "ACHIEVEMENT POPUP": 0 ON, 1 OFF (fx worker) */
#define POP_FRAMES 210
uint8_t c_page;                        /* the module's page is open: no popup */
static uint8_t c_pop;
static char line[60];
static void text(const char* s, uint32_t y, uint32_t col) {
	const char* e = s;
	while (*e) e++;
	((void (*)(const char*, uint32_t, uint32_t))PRINT_FN)(s, (256 - 4 * (uint32_t)(e - s)) << 16 | y, 8u << 24 | col << 16 | 1);
}
/* title i (corec.py: phrase symbol + Huffman, titles one after another) into d; returns the end */
char* c_title(char* d, uint32_t i) {
	uint32_t b = 0, n;
	char* p = d;
	for (;;) {
		n = 0;
		do { n = c_hnode[n][c_hdat[b >> 3] >> (b & 7) & 1]; b++; } while (!(n & 0x80));
		n &= 0x7f;
		if (!n) { if (!i--) { *p = 0; return p; } p = d; continue; }
		if (n == 1) { const char* q = c_phrase; while (*q) *p++ = *q++; }
		else *p++ = (char)(n - 2 + 0x20);
	}
}
static void popup(void) {
	if (c_pop) {
		c_pop--;
		if (c_page) c_pop = 0;
		else if (!POPUP_OFF) { text("ACHIEVEMENT UNLOCKED", 0x4a, 0x26); text(line, 0x56, 0x24); }
		return;
	}
	if (!c_nq || c_page) return;
	{
		const uint32_t i = c_queue[0], p = c_ptab[c_rec[i][0] >> 4];
		uint32_t k;
		char* d = c_title(line, i);
		*d++ = ' '; *d++ = '(';
		if (p >= 10) *d++ = (char)('0' + p / 10);
		*d++ = (char)('0' + p % 10); *d++ = ')'; *d = 0;
		for (k = 1; k < c_nq; k++) c_queue[k - 1] = c_queue[k];
		c_nq--;
		c_pop = POP_FRAMES;
		if (!POPUP_OFF) ((void (*)(uint32_t))SFX_FN)(0);
	}
}

/* ---- main menu: the module (menu words, page, card), read from the disc into MOD_AT while the main menu is up ----- */
#define MENU ((volatile uint8_t*)0x8007b6e8u)          /* +0 state, +1 != 0 when the menu is up (the title has 0) */
#define STATE5 (*(const uint32_t*)(0x800b5bf8u + 4 * 5))  /* OPDEMO.ARC state table entry 5: menus.py's MENUS5 / ours */
#define MOD ((const uint32_t*)MOD_AT)
uint32_t c_mod[2] = { 0, 0 };          /* the module's disc item: BCD MSF, size (mvcore.py patches them) */
static uint8_t mod_tries;
static int mod_get(void) {
	uint32_t k, s, n;
	for (k = 0; ; k++) {
		s = 0; n = MOD[3] >> 2;           /* +0xc: end of code + rodata (data / BSS are not summed) */
		if (MOD[0] == 0x4d484341u && n <= MOD_MAX / 4 && n >= 8) {
			uint32_t j;
			for (j = 4; j < n; j++) s += MOD[j];
			if (s == MOD[2]) return 1;
		}
		if (k || mod_tries >= 3) return 0;   /* (a bad read: no retry storm; again on the next menu visit) */
		mod_tries++;
		{	/* the game's file read through a borrowed file-table entry (CAPMOV.BIN 0x1ab, as tl_main), restored */
			uint32_t* f = (uint32_t*)0x800255e4u + 2 * 0x1ab;
			const uint32_t a = f[0], b = f[1];
			f[0] = c_mod[0]; f[1] = c_mod[1];
			((int (*)(int, void*))0x80024800u)(0x1ab, (void*)MOD_AT);
			f[0] = a; f[1] = b;
		}
	}
}
#define MOD_CALL(off) ((int (*)(void))(MOD_AT + (off)))()
void c_state(void);
void c_menu(void) {                     /* OPDEMO state 5 (ACHIEVEMENTS), once a frame while the page is open */
	if (!mod_get() || !MOD_CALL(0x10)) { MENU[0] = 0; MENU[1] = 0; MENU[2] = 0; MENU[3] = 0; c_page = 0; }
}
__asm__(".set push\n.set noreorder\n.section .text.c_state,\"ax\"\n.globl c_state\nc_state:\n jal c_menu\n nop\n"
        " j 0x800a2df8\n nop\n.set pop\n");
/* the main menu's 7 strings (13-byte stride; mvcore.py writes the last line; the module points OPDEMO's table here) */
char c_menutab[7][13] __attribute__((section(".keep.menutab"))) = { "BATTLE", "VERSUS", "TRAINING", "GALLERY", "ACHIEVEMENTS", "OPTION", "" };

/* ---- the hook: the frame routine's `jal 0x8002097c` (ClearOTag x3) at 0x80022fe8 calls us instead ---------------- */
void ach_frame(uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3) {
	((void (*)(uint32_t, uint32_t, uint32_t, uint32_t))0x8002097cu)(a0, a1, a2, a3);
	derive();
	eval();
	popup();
	if (STATE5 == MENUS5 && MENU[1]) { if (mod_get()) MOD_CALL(0x20); }   /* main menu, overlay unpatched: the module patches it */
	else if (MENU[0] == 0 && MENU[1] && STATE5 == (uint32_t)c_state) { if (mod_get()) MOD_CALL(0x18); }   /* card */
	else mod_tries = 0;
}
#endif
