/* xvex.c: XvSF tag hack 1.4 - EX OPTIONS (main-menu entry) and the in-battle options.  Built by tools/expatch.py,
   linked into the EXE's dead span 0x80056b94-0x800577c8 (tools/speed/quad.py FREED; unused since UP_FC=0 / UP_VC=0),
   so it is part of the EXE image: present on every console (no kernel RAM, no boot guard); option bytes = BSS here,
   zero at power-on, never written by the game -> kept across matches until power-off.
   Entry points:
     ex_idle      present's idle callback (tools/speed/frame gpuq.S ahook -> EBV+12; was the decode-ahead stub ahcb,
                  dropped with --noahead): every drawn frame, every scene.  Patches the main-menu overlay in RAM once per
                  load, draws the EX OPTIONS page (direct mode), applies FRAME SKIP / STAGE ANIM, draws the SPEED METER.
     ex_menuin    the title scene's calls of the main-menu routine 0x800987c0 (EXE 0x80028638; OPDEMO 0x8009bf54 in RAM)
     ex_pdraw     one-shot table entry 2 (the battle pause menu's draw, stock 0x80029278)
     (pause input: the stock routine 0x800294a4 with its cursor wrap 0..4; rows 3 / 4 change in ex_pdraw)
   Nothing lives in region RAM: no load can overwrite this code (MvC freeze / MCOPY classes). */
#include <stdint.h>

typedef void (*f_text)(const char*, int, int, int, int, int);
#define TEXT     ((f_text)0x8002d79cu)          /* small font (text, x, y, advance, colour, 1) */
#define BIG      ((f_text)0x8002d850u)          /* pause-menu font */
#define PADNOW(p) (((volatile uint16_t*)0x8004c2b0u)[p])   /* = 0x8002c8e0(p): buttons held */
#define PADOLD(p) (((volatile uint16_t*)0x800420d0u)[p])   /* = 0x8002c8f8(p): held a frame earlier */
#define SFX      ((void (*)(int))0x8004d544u)
#define MENU_FN  ((void (*)(void))0x800987c0u)
#define MENU     ((volatile uint8_t*)0x80042180u)   /* +0 state, +0x12 main cursor, +0x21 pause cursor */
#define DIRECT   (*(volatile uint8_t*)0x8003d918u)  /* text routine direct mode */
#define SCENE    (*(volatile int16_t*)0x80042774u)  /* 8 battle */
#define LOOPS    (*(volatile uint16_t*)0x800421b8u) /* main-loop counter */
#define VCOUNT   (*(volatile uint16_t*)0x800220c8u) /* vblank counter */
#define FSALLOW  (*(volatile uint8_t*)0x800421c2u)  /* the engine's present skip: allowed (set per scene; 0 in battle) */
#define FSCOUNT  (*(volatile uint8_t*)0x8003d13cu)  /* presents since the last skip */
#define ONESHOT  (*(volatile uint8_t*)0x8004218fu)
#define U32(a)   (*(volatile uint32_t*)(a))
#define B_UP 0x1000
#define B_RIGHT 0x2000
#define B_DOWN 0x4000
#define B_LEFT 0x8000
#define B_X 0x40
#define B_BACK 0x30

#ifndef EX_ARCBAL
#error EX_ARCBAL (ARCADE BALANCE byte, tools/skippatch.py) needed
#endif
#ifndef EX_FLUSH
#error EX_FLUSH (BIOS FlushCache helper, tools/tagload glue) needed
#endif

/* option values (BSS): FRAME SKIP 0 OFF 1 AUTO 2 MAX, STAGE ANIM 0 FULL 1 OFF, SPEED METER 0 OFF 1 ON,
   ACHIEVEMENT POPUP 0 ON 1 OFF (read by the achievements runtime: tools/ach/xvsf/port.h) */
uint8_t ex_opt[4];
#define FS  ex_opt[0]
#define SA  ex_opt[1]
#define SM  ex_opt[2]
#define POP ex_opt[3]
void (*ex_achmenu)(void);       /* the achievements runtime's menu wrapper (ach_menuin), written by its boot copy; 0 = none */
void (*ex_xrow)(int y, int sel, uint32_t nw);   /* an extra EX OPTIONS row (8 MB module: ARCADE FRAMES), set by its owner; 0 = none */
uint8_t ex_page, ex_sel;
static uint16_t m_vc, m_loops, m_pics, m_pics0, pg_prev;
static char m_txt[8];

/* ---------------------------------------------------------------- main menu */
static const char tab[7][16] = {
	" BATTLE MODE\0\0\0\xc8", " VERSUS MODE\0\0\0\xc8", "TRAINING MODE\0\0\xc8", "SURVIVAL MODE\0\0\xc8",
	"ACHIEVEMENTS\0\0\0\xcc", " OPTION MODE\0\0\0\xc8", "EX OPTIONS\0\0\0\0\0\xd4" };
static const char tab6[6][16] = {   /* without the achievements runtime */
	" BATTLE MODE\0\0\0\xc8", " VERSUS MODE\0\0\0\xc8", "TRAINING MODE\0\0\xc8", "SURVIVAL MODE\0\0\xc8",
	" OPTION MODE\0\0\0\xc8", "EX OPTIONS\0\0\0\0\0\xd4" };
#define JAL(t) (0x0c000000u | ((uint32_t)(t) >> 2 & 0x03ffffffu))
#define LUI_S1_STOCK 0x3c11800bu
void ex_menuin(void);

static void ovl_check(void) {
	uint32_t t, n;
	if (U32(0x80098748u) != LUI_S1_STOCK || U32(0x8009bf54u) != JAL(0x800987c0u)) return;   /* not loaded, or done */
	n = ex_achmenu ? 7 : 6;
	t = n == 6 ? (uint32_t)tab6 : (uint32_t)tab;
	U32(0x80098748u) = 0x3c110000u | ((t + 0x8000u) >> 16 & 0xffffu);   /* lui s1 */
	U32(0x8009874cu) = 0x26310000u | (t & 0xffffu);                      /* addiu s1 */
	U32(0x80098770u) = 0x9225000fu;                                       /* lbu a1, 15(s1): x per entry */
	U32(0x80098794u) = 0x2a020000u | n;                                   /* slti v0, s0, n: lines */
	U32(0x80098948u) = 0x28420000u | n;                                   /* cursor 0 .. n-1 */
	U32(0x8009894cu) = 0x34020000u | (n - 1);
	if (n == 7) {
		U32(0x80098740u) = 0x3c120000u | EX_MENU_Y;                       /* first line y (stock 0x90) */
		U32(0x80098788u) = 0x3c020000u | EX_MENU_STEP;                    /* line step (stock 16) */
	}
	U32(0x8009bf54u) = JAL(ex_menuin);
	((void (*)(void))EX_FLUSH)();
}

#ifdef EX_CARD
/* ---------------------------------------------------------------- EX OPTIONS on the memory card (--excard)
   The rows ride in the game's own option save (OPTION -> MEMORY CARD -> SAVE / LOAD, and its automatic load at
   power-on): byte +9 of the options' card image (tools/arcbalpatch.py; stock never writes it, 0 = every default):
     bit 0 ARCADE BALANCE ON, 1 STAGE ANIM OFF, 2 ACHIEVEMENT POPUP OFF, 3 INFINITE SUPER METER ON, 4 ARCADE FRAMES OFF.
   ex_cardsv / ex_cardld are called from the save / load routines' 8-word slots (OPDEMO 0x8009a1f0 / 0x8009a2dc) with
   every live register in use: they keep all caller-saved registers; the byte goes out / comes in in t9. */
uint8_t* ex_imptr;      /* INFINITE SUPER METER byte (tools/ach/xvach.py writes it into the image); only with the runtime */
uint8_t ex_afp;         /* ARCADE FRAMES from the card (8 MB disc): 0 none, 2 ON, 3 OFF; tl_dbg.title once the module is up */
uint32_t ex_card(uint32_t b, uint32_t load) {
	volatile uint8_t* ab = (volatile uint8_t*)EX_ARCBAL;
	if (!load) {
		b = (*ab & 1) | (SA & 1) << 1 | (POP & 1) << 2;
		if (ex_achmenu && ex_imptr) b |= (*ex_imptr & 1) << 3;
#ifdef EX_TLTITLE
		{ const uint8_t t = *(volatile uint8_t*)EX_TLTITLE; if (t >= 2 ? t == 3 : ex_afp == 3) b |= 16; }
#endif
		return b;
	}
	*ab = b & 1; SA = b >> 1 & 1; POP = b >> 2 & 1;
	if (ex_achmenu && ex_imptr) *ex_imptr = b >> 3 & 1;
#ifdef EX_TLTITLE
	ex_afp = (b & 16) ? 3 : 2;
	{ volatile uint8_t* t = (volatile uint8_t*)EX_TLTITLE; if (*t >= 2) *t = ex_afp; }
#endif
	return b;
}
__asm__(
"	.set push\n"
"	.set noreorder\n"
"	.set noat\n"
"	.globl ex_cardsv\n"
"	.globl ex_cardld\n"
"	ex_cardsv: b 1f\n"
"	ori $1, $0, 0\n"
"	ex_cardld: ori $1, $0, 1\n"
"	1: addiu $29, $29, -72\n"
"	sw $2, 16($29)\n"
"	sw $3, 20($29)\n"
"	sw $4, 24($29)\n"
"	sw $5, 28($29)\n"
"	sw $6, 32($29)\n"
"	sw $7, 36($29)\n"
"	sw $8, 40($29)\n"
"	sw $9, 44($29)\n"
"	sw $10, 48($29)\n"
"	sw $11, 52($29)\n"
"	sw $12, 56($29)\n"
"	sw $13, 60($29)\n"
"	sw $14, 64($29)\n"
"	sw $15, 68($29)\n"
"	sw $24, 12($29)\n"
"	sw $31, 8($29)\n"
"	move $4, $25\n"
"	jal ex_card\n"
"	move $5, $1\n"
"	move $25, $2\n"
"	lw $31, 8($29)\n"
"	lw $2, 16($29)\n"
"	lw $3, 20($29)\n"
"	lw $4, 24($29)\n"
"	lw $5, 28($29)\n"
"	lw $6, 32($29)\n"
"	lw $7, 36($29)\n"
"	lw $8, 40($29)\n"
"	lw $9, 44($29)\n"
"	lw $10, 48($29)\n"
"	lw $11, 52($29)\n"
"	lw $12, 56($29)\n"
"	lw $13, 60($29)\n"
"	lw $14, 64($29)\n"
"	lw $15, 68($29)\n"
"	lw $24, 12($29)\n"
"	jr $31\n"
"	addiu $29, $29, 72\n"
"	.set pop\n"
);
#endif

void ex_menuin(void) {
	uint32_t s;
#if defined(EX_CARD) && defined(EX_TLTITLE)
	if (ex_afp && *(volatile uint8_t*)EX_TLTITLE >= 2) { *(volatile uint8_t*)EX_TLTITLE = ex_afp; ex_afp = 0; }   /* card -> ARCADE FRAMES */
#endif
	if (ex_page) return;                                  /* the page runs in ex_idle; the menu waits */
	s = MENU[0];
#ifdef EX_VSMENU          /* --vsmenu: the VERSUS CPU row wrapper (common/mtap, tools/mtap/mtmenu.h) calls the menu */
	((void (*)(void))EX_VSMENU)();
#else
	if (ex_achmenu) ex_achmenu(); else MENU_FN();
#endif
	if (s == 0 && MENU[0] == (ex_achmenu ? 7 : 6)) {      /* EX OPTIONS chosen (state = cursor + 1) */
		MENU[0] = 0; ex_page = 1; ex_sel = 0; pg_prev = 0xffff; SFX(0x91);
	}
}

/* ---------------------------------------------------------------- EX OPTIONS page */
static const char* const lab[6] = { "ARCADE BALANCE", "FRAME SKIP", "STAGE ANIM", "SPEED METER", "ACHIEVEMENT POPUP", "EXIT" };
static const char* const val[5][3] = {
	{ "OFF", "ON", 0 }, { "OFF", "AUTO", "MAX" }, { "FULL", "OFF", 0 }, { "OFF", "ON", 0 }, { "ON", "OFF", 0 } };
static const uint8_t nval[5] = { 2, 3, 2, 2, 2 };
static const uint16_t vx[3] = { EX_VX0, EX_VX0 + 0x28, EX_VX0 + 0x50 };

static volatile uint8_t* vptr(int r) { return r ? &ex_opt[r - 1] : (volatile uint8_t*)EX_ARCBAL; }

static uint32_t pnew(int k) { return PADNOW(k) & ~PADOLD(k); }

#ifdef EX_NOFS
/* EX_NOFS (1.4 final, mktagdisc --nofskip): no FRAME SKIP row on the page or in the pause menu, FS stays 0 (OFF = the
   engine's present skip not allowed in battle, as stock).  Its slot (2nd row) is the hook ex_frow: a row drawn by its
   owner (8 MB module: ARCADE FRAMES), 0 = no row and no gap.  Page = ARCADE BALANCE, [ex_frow], STAGE ANIM, SPEED METER,
   [ACHIEVEMENT POPUP], [ex_xrow (--infmeter: INFINITE SUPER METER)], EXIT.
   EX_NOSM (--nosmeter, final builds): no SPEED METER row either (SM stays 0) and the battle pause menu stays stock. */
void (*ex_frow)(int y, int sel, uint32_t nw);
static int page(void) {
	uint8_t it[8];                                        /* page line -> 0..4 option row, 5 EXIT, 6 ex_xrow, 7 ex_frow */
	int n = 0, i, s = ex_sel, r;
	const uint32_t held = PADNOW(0) | PADNOW(1), nw = held & ~pg_prev;
	pg_prev = (uint16_t)held;
	it[n++] = 0;
	if (ex_frow) it[n++] = 7;
	it[n++] = 2;
#ifndef EX_NOSM
	it[n++] = 3;
#endif
	if (ex_achmenu) it[n++] = 4;
	if (ex_xrow) it[n++] = 6;
	it[n++] = 5;
	if (s >= n) s = n - 1;
	if (nw & B_BACK) { SFX(0x82); return 0; }
	if (nw & B_UP) s = s ? s - 1 : n - 1;
	if (nw & B_DOWN) s = s < n - 1 ? s + 1 : 0;
	if (s != ex_sel) { ex_sel = (uint8_t)s; SFX(0x84); }
	r = it[s];
	if (r == 5 && (nw & B_X)) { SFX(0x82); return 0; }
	if (r < 5 && (nw & (B_LEFT | B_RIGHT | B_X))) {
		volatile uint8_t* p = vptr(r);
		uint32_t v = *p, k = nval[r];
		v = (nw & B_LEFT) ? (v ? v - 1 : k - 1) : (v + 1 < k ? v + 1 : 0);
		*p = (uint8_t)v; SFX(0x84);
	}
	TEXT("EX OPTIONS", EX_TX, EX_TY, 8, 0x30, 1);
	for (i = 0; i < n; i++) {
		const int rr = it[i], y = EX_RY + EX_RSTEP * i;
		if (rr >= 6) { (rr == 6 ? ex_xrow : ex_frow)(y, i == s, i == s ? nw : 0); continue; }
		TEXT(lab[rr], EX_LX, y, 8, i == s ? 0x30 : 0x33, 1);
		if (rr < 5) {
			const uint32_t cur = *vptr(rr);
			uint32_t k;
			for (k = 0; k < nval[rr]; k++) TEXT(val[rr][k], vx[k], y, 8, cur == k ? 0x30 : 0x33, 1);
		}
	}
	return 1;
}
#else

static int page(void) {
	const int base = ex_achmenu ? 5 : 4, rows = base + (ex_xrow != 0);   /* our option rows (POPUP only with the runtime), + the extra row; rows = EXIT */
	const uint32_t held = PADNOW(0) | PADNOW(1), nw = held & ~pg_prev;     /* own edges: present runs after the game's pad update */
	pg_prev = (uint16_t)held;
	int i, s = ex_sel, r;
	if (nw & B_BACK) { SFX(0x82); return 0; }
	if (nw & B_UP) s = s ? s - 1 : rows;
	if (nw & B_DOWN) s = s < rows ? s + 1 : 0;
	if (s != ex_sel) { ex_sel = (uint8_t)s; SFX(0x84); }
	r = s == rows ? 5 : s < base ? s : 6;                 /* the last line is EXIT; 6 = the extra row */
	if (r == 5 && (nw & B_X)) { SFX(0x82); return 0; }
	if (r < 5 && (nw & (B_LEFT | B_RIGHT | B_X))) {
		volatile uint8_t* p = vptr(r);
		uint32_t v = *p, n = nval[r];
		v = (nw & B_LEFT) ? (v ? v - 1 : n - 1) : (v + 1 < n ? v + 1 : 0);
		*p = (uint8_t)v; SFX(0x84);
	}
	TEXT("EX OPTIONS", EX_TX, EX_TY, 8, 0x30, 1);
	for (i = 0; i <= rows; i++) {
		const int rr = i == rows ? 5 : i, y = EX_RY + EX_RSTEP * i;
		if (i == base && i < rows) { ex_xrow(y, i == s, i == s ? nw : 0); continue; }
		TEXT(lab[rr], EX_LX, y, 8, i == s ? 0x30 : 0x33, 1);
		if (rr < 5) {
			const uint32_t cur = *vptr(rr);
			uint32_t k;
			for (k = 0; k < nval[rr]; k++) TEXT(val[rr][k], vx[k], y, 8, cur == k ? 0x30 : 0x33, 1);
		}
	}
	return 1;
}
#endif

/* ---------------------------------------------------------------- battle */
static char* num(char* p, uint32_t v) { if (v >= 10) *p++ = (char)('0' + v / 10 % 10); *p++ = (char)('0' + v % 10); return p; }

/* STAGE ANIM OFF: objects whose handler (the object dispatcher 0x80033ba0: list 0x80043830 / +0x30, handler table
   0x8003d444 + type) is stage overlay code (or 0x80036a34, type 0x1c: stage-only decoration, never spawned in a fight -
   work/x14/typescan.py) keep their animation countdown (+0x48) from running out = the picture holds
   (visual only: nothing is removed, their logic still runs) */
static void sa_hold(void) {
	uint32_t p = U32(0x80043830u), n = 96;
	for (; n && (int32_t)p < 0; n--, p = U32(p + 0x30)) {
		const uint32_t h = U32(0x8003d444u + (*(volatile uint16_t*)(p + 0x24) & ~3u));
		if ((h - 0x80098000u < 0x20000u || h == 0x80036a34u) && *(volatile uint16_t*)(p + 0x48) < 8) *(volatile uint16_t*)(p + 0x48) = 8;
	}
}

static void battle(void) {
	if (SA) sa_hold();
	FSALLOW = FS != 0;                                    /* AUTO / MAX: the engine's own present skip (lag >= 2) */
	m_pics++;
	if (SM) {
		const uint16_t dv = (uint16_t)(VCOUNT - m_vc);
		if (dv >= 30) {
			uint32_t l = (uint16_t)(LOOPS - m_loops) * 60u / dv, p = (uint16_t)(m_pics - m_pics0) * 60u / dv;
			char* q = num(m_txt, l > 99 ? 99 : l);
			if (FS) { *q++ = ' '; q = num(q, p > 99 ? 99 : p); }
			*q = 0;
			m_vc = VCOUNT; m_loops = LOOPS; m_pics0 = m_pics;
		}
		DIRECT = 1; TEXT(m_txt, EX_MX, EX_MY, 8, 0x30, 1); DIRECT = 0;
	} else { m_vc = VCOUNT; m_loops = LOOPS; m_pics0 = m_pics; m_txt[0] = 0; }
}

/* every logic frame of the game proper (the START skip module's per-frame hook calls this instead of 0x80028dc8):
   FRAME SKIP MAX lets the present skip run up to EX_FSCAP pictures in a row (AUTO = the engine's rule: never two) */
static uint8_t fs_cons;
void ex_logic(void) {
	if (SCENE == 8 && FS == 2) {
		fs_cons = *(volatile uint8_t*)0x8003d13du ? (uint8_t)(fs_cons + 1) : 0;    /* this frame's picture is skipped */
		if (fs_cons < EX_FSCAP && FSCOUNT < 2) FSCOUNT = 2;
	}
	((void (*)(void))0x80028dc8u)();
}

void ex_idle(void) {
	ovl_check();
	if (ex_page) {
		DIRECT = 1; ex_page = (uint8_t)page(); DIRECT = 0;
		if (!ex_page) MENU[0] = MENU[1] = MENU[2] = MENU[3] = 0;     /* back: the menu starts again */
	}
	if (SCENE == 8) battle();
}

/* ---------------------------------------------------------------- battle pause menu (START, then SELECT) */
#if !(defined(EX_NOFS) && defined(EX_NOSM))           /* both rows gone: stock pause menu, not hooked (expatch.py) */
#ifdef EX_NOFS
#define P_ROWS 4                /* CONTINUE, KEY CONFIG., QUIT, SPEED METER (cursor wrap 0..3: expatch.py) */
#else
#define P_ROWS 5
#endif
static const char* const fs_t[3] = { "FRAME SKIP OFF", "FRAME SKIP AUTO", "FRAME SKIP MAX" };
static const char* const sm_t[2] = { "SPEED METER OFF", "SPEED METER ON" };
static int slen(const char* s) { int n = 0; while (s[n]) n++; return n; }
/* the stock input routine 0x800294a4 runs the cursor (its wrap patched to 0..4: expatch.py) and CONTINUE / KEY CONFIG. /
   QUIT; rows 3 and 4 change here (the draw runs every drawn frame while the menu is up; own edges) */
void ex_pdraw(volatile uint8_t* m) {
	const int c = (int8_t)m[0x21];
	const uint32_t held = PADNOW((int8_t)m[0xe]), nw = held & ~pg_prev;
	int i;
	pg_prev = (uint16_t)held;
	if (c >= 3 && (nw & (B_LEFT | B_RIGHT | B_X))) {
#ifdef EX_NOFS
		SM ^= 1;
#else
		if (c == 3) FS = (uint8_t)((nw & B_LEFT) ? (FS ? FS - 1 : 2) : (FS < 2 ? FS + 1 : 0));
		else SM ^= 1;
#endif
		SFX(0x84);
	}
	for (i = 0; i < P_ROWS; i++) {
#ifdef EX_NOFS
		const char* s = i < 3 ? ((const char* const*)0x8003d184u)[i] : sm_t[SM];
#else
		const char* s = i < 3 ? ((const char* const*)0x8003d184u)[i] : i == 3 ? fs_t[FS] : sm_t[SM];
#endif
		BIG(s, i < 3 ? 0xb0 : EX_PCX - 8 * slen(s), EX_PY + EX_PSTEP * i, 0x10, (int8_t)m[0x21] == i ? 0x30 : 0x33, 1);
	}
}
#endif

#ifdef EX_TRSYNC
/* --trsync (1.4, a stock XvSF bug): the attract demo's START -> title transition (EXE 0x8002b6b0 -> 0x8002a4f0) resets the
   draw-buffer allocator (0x8002ea50) and zeroes four list blocks without waiting for the GPU; START on the SCORE / VS
   RANKING screen while the previous frame is still drawing (late after a sprite-tile upload) leaves the GPU executing
   half-cleared lists -> garbage screens, broken glyphs on NOW LOADING.  0x8002a4f8 jal 0x8002ea50 -> ex_trsync: wait for
   the GPU (libgpu sync core 0x80018c38, mode 0: queue empty, DMA2 idle, GPU ready; with its own timeouts), then the reset.
   7 instructions (the 8 MB module had 32 bytes left). */
void ex_trsync(void);
__asm__(
"	.section .text.ex_trsync,\"ax\",@progbits\n"
"	.globl ex_trsync\n"
"	.set push\n"
"	.set noreorder\n"
"	ex_trsync:\n"
"	addiu $29, $29, -8\n"
"	sw    $31, 0($29)\n"
"	jal   0x80018c38\n"
"	move  $4, $0\n"
"	lw    $31, 0($29)\n"
"	j     0x8002ea50\n"
"	addiu $29, $29, 8\n"
"	.set pop\n"
"	.previous\n");
#endif
