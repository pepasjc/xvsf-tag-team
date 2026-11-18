/*
	ach.c: built-in achievements runtime shared by the tag hacks (XvSF, MSHvSF, MvC).

	The set is compiled on the PC (tools/ach/setc.py) into the tables of eval.h; eval.c tests
	them once per game frame like rcheevos.  The game's port (games/<g>/tools/ach/port.h + port.c,
	included / linked in) supplies the text routine, sounds, pad, the derived bytes and when the
	memory card may be used.  Nothing is sent anywhere.

	  - every frame (ach_frame, from the game's present routine): derived bytes, evaluation,
	    unlock popup ("ACHIEVEMENT UNLOCKED" + title, POP_FRAMES frames, unlock sound), card write;
	  - the ACHIEVEMENTS page (ach_page, from the main menu): list, count, points, description;
	  - memory card: its own file (PORT_FILE), read from both slots (unlocks merged) the first time
	    the card may be used, made in slot 1 (slot 2 if that fails) when neither has it; an unlock
	    rewrites the sector of our block with the BIOS's queued sector write.
*/
#include <stdint.h>
#include "eval.h"
#include "meta.h"
#include "port.h"

void* memset(void* d, int c, unsigned n) { uint8_t* p = d; while (n--) *p++ = (uint8_t)c; return d; }
void* memcpy(void* d, const void* s, unsigned n) { uint8_t* p = d; const uint8_t* q = s; while (n--) *p++ = *q++; return d; }

/* debug block (start.S +0x18): frames, eval cost (root counter 1 = hblanks), card state */
struct ach_dbg { uint32_t frames; uint16_t cost, cost_max; int16_t card_port, card_res; uint8_t loaded, pending, tries, last, force, pad[3]; uint16_t pcost, pcost_max; };
struct ach_dbg ach_dbg = { .card_port = -1 };      /* -1 not located yet, -2 no card / no room */
uint32_t ach_dbg_frames(void) { return ach_dbg.frames; }

#ifndef ACH_NOWD
/* watchdog: our read-only code and data (achbuild build_spans: one range per span, ach_wd_tab) are summed WD_STEP
   words a frame; a full pass that differs from the builder's sum at entry +0x1c means something else writes our
   kernel-RAM spans: the runtime stops (hooks pass straight to the game, no evaluation, no card writes, no page) */
#define WD_STEP 16
extern const uint32_t ach_wd_tab[][2];
extern const uint32_t ach_wd_n;
uint8_t ach_off;
static uint32_t wd_sum, wd_i;
static const uint32_t* wd_p;
static void wd_step(void) {
	int k;
	for (k = 0; k < WD_STEP; k++) {
		if (wd_p && wd_p < (const uint32_t*)ach_wd_tab[wd_i][1]) { wd_sum += *wd_p++; continue; }
		if (wd_p && ++wd_i >= ach_wd_n) {
			wd_i = 0;
			if (wd_sum != *(volatile uint32_t*)(ACH_BASE + 0x1c)) ach_off = 1;
			wd_sum = 0;
		}
		wd_p = (const uint32_t*)ach_wd_tab[wd_i][0];
	}
}
#define WD_OFF() ach_off
#else
#define WD_OFF() 0
#endif

#define NACH_MAX 128
#define NBYTES   (NACH_MAX / 8)
uint8_t ach_bits[NBYTES];
#define bits ach_bits
static int bit(uint32_t i) { return bits[i >> 3] >> (i & 7) & 1; }

static char* fmt_num(char* p, uint32_t v) {
	char t[10]; int n = 0;
	do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v);
	while (n) *p++ = t[--n];
	*p = 0;
	return p;
}
static char* cat(char* d, const char* s) { while (*s) *d++ = *s++; *d = 0; return d; }
#ifdef ACH_GDIAG
/* guard diagnostic build: the boot copy (achbuild.copy_stub_spans gd) records per segment the first non-zero
   address, the last, the count of non-zero words and of words neither 0 nor FFFFFFFF (X0 = a plain FF fill), then
   copies anyway; records 10, 11 probe F000-FFFF and E500-E5FF (P lines); drawn every frame */
uint32_t ach_gd[ACH_GDIAG * 4];
static char* hx(char* p, uint32_t v, int n) { while (n--) *p++ = "0123456789ABCDEF"[v >> (n * 4) & 15]; *p = 0; return p; }
static void gdiag_draw(void) {         /* two failed spans per page (the text routines drop long frames), page every 3 s */
	char l[40], *p; int i, k = 0, y = 12, bad = 0, pg;
	for (i = 0; i < ACH_GDIAG; i++) if (ach_gd[i * 4]) bad++;
	pg = bad ? (int)(ach_dbg.frames / 180 % (uint32_t)((bad + 1) / 2)) : 0;
	p = cat(l, "GUARD "); p = bad ? fmt_num(cat(p, "FAIL "), (uint32_t)bad) : cat(p, "CLEAN");
	if (bad > 2) { p = fmt_num(cat(p, " P"), (uint32_t)pg + 1); p = fmt_num(cat(p, "/"), (uint32_t)(bad + 1) / 2); }
	PORT_TEXT(l, PAGE_X, PAGE_Y + PAGE_LINE * 11, PORT_COL_HEAD);         /* lower half: clear of the logos */
	for (i = 0; i < ACH_GDIAG; i++) {
		const uint32_t* r = &ach_gd[i * 4];
		if (!r[0] || k++ / 2 != pg) continue;
		p = cat(l, i >= ACH_GDIAG - 2 ? "P" : "S"); p = fmt_num(p, (uint32_t)i); p = cat(p, " "); p = hx(p, r[0], 5);
		p = cat(p, "-"); p = hx(p, r[1], 5); p = cat(p, " N"); p = fmt_num(p, r[2]); p = cat(p, " X"); fmt_num(p, r[3]);
		PORT_TEXT(l, PAGE_X, PAGE_Y + PAGE_LINE * y++, PORT_COL_OFF);
	}
}
#endif
static const uint8_t* nth(const uint8_t* p, uint32_t n) { while (n--) while (*p++) ; return p; }
static char* unpack(char* d, const uint8_t* s, int stop_nl) {
	for (; *s && !(stop_nl && *s == '\n'); s++)
		d = *s >= 0x80 ? cat(d, (const char*)nth((const uint8_t*)ra_dict, *s - 0x80)) : (*d++ = (char)*s, d);
	*d = 0;
	return d;
}
#define RA_TITLE(i) nth(ra_text, 2 * (i))
#define RA_DESC(i)  nth(ra_text, 2 * (i) + 1)
static uint32_t unlocked(uint32_t* pts) {
	uint32_t i, n = 0, p = 0;
	for (i = 0; i < ra_nach; i++) if (bit(i)) { n++; p += ra_points[i]; }
	*pts = p;
	return n;
}

/* ------------------------------------------------------------------------ */
/* memory card */
#define BLK_MAGIC 0x56484341u     /* "ACHV" */
#define BLK_OFF   0x200           /* our block: the file's 5th sector */
struct ra_block { uint32_t magic; uint16_t n, version; uint8_t bits[NBYTES]; uint32_t sum; };
static const char* const path[2] = { "bu00:" PORT_FILE, "bu10:" PORT_FILE };
extern const uint8_t ach_icon[];  /* palette (32 bytes) + 16x16 4-bit icon (128) */
extern const uint8_t ach_file_title[];

struct ps_dirent { char name[20]; int attr; int size; void* next; int head; char sys[4]; };
int bios_open(const char* name, int mode);
int bios_lseek(int fd, int off, int whence);
int bios_read(int fd, void* buf, int n);
int bios_write(int fd, const void* buf, int n);
int bios_close(int fd);
void* bios_firstfile(const char* name, struct ps_dirent* d);
int bios_card_write(int port, int sector, const void* buf);

static uint8_t sec[0x80] __attribute__((aligned(4)));
static int rt_sector, rt_wait;

static uint32_t block_sum(const struct ra_block* b) {
	const uint8_t* p = (const uint8_t*)b;
	uint32_t s = 0x1234567u, i;
	for (i = 0; i < sizeof(*b) - 4; i++) s = (s << 5 | s >> 27) + p[i];
	return s;
}
static void make_block(void* buf) {
	struct ra_block* b = buf;
	memset(buf, 0, 0x80);
	b->magic = BLK_MAGIC; b->n = ra_nach; b->version = 1;
	memcpy(b->bits, bits, NBYTES);
	b->sum = block_sum(b);
}
static int block_ok(const struct ra_block* b) {
	return b->magic == BLK_MAGIC && b->n == ra_nach && b->version == 1 && b->sum == block_sum(b);
}

/* the sector of our block, from the directory (the name is checked: firstfile's return value
   is not reliable on every BIOS) */
static void locate(void) {
	struct ps_dirent d;
	int k, i;
	ach_dbg.card_port = -1;
	for (k = 0; k < 2; k++) {
		memset(&d, 0, sizeof(d));
		bios_firstfile(path[k], &d);
		for (i = 0; PORT_FILE[i] && d.name[i] == PORT_FILE[i]; i++) ;
		if (PORT_FILE[i] || d.name[i] || d.head < 64 || d.head >= 1024 || (d.head & 63)) continue;
		ach_dbg.card_port = k ? 0x10 : 0x00; rt_sector = d.head + BLK_OFF / 0x80;
		return;
	}
}

/* no file on either card: make one in slot 1, else slot 2 (header with the icon, our block) */
static void create(void) {
	uint8_t buf[BLK_OFF + 0x80] __attribute__((aligned(4)));
	int k, fd = -1;
	for (k = 0; k < 2 && fd < 0; k++) fd = bios_open(path[k], (1 << 16) | 0x200);   /* create, 1 block */
	if (fd < 0) return;
	bios_close(fd);
	memset(buf, 0, sizeof(buf));
	buf[0] = 'S'; buf[1] = 'C'; buf[2] = 0x11; buf[3] = 1;   /* 1 icon frame, 1 block */
	memcpy(buf + 4, ach_file_title, 64);
	memcpy(buf + 0x60, ach_icon, 32 + 128);
	make_block(buf + BLK_OFF);
	fd = bios_open(path[k - 1], 2);
	if (fd >= 0) { bios_write(fd, buf, sizeof(buf)); bios_close(fd); }
}

/* what the player is told about saving: 1 saved (card_port 0 / 0x10), 2 no usable card (none, or not formatted),
   3 a card is there but our file could not be made (full).  On every main-menu visit; the first time it is not 1, a
   notice is queued (once per session).  Unsaved unlocks stay pending, so a card inserted later gets them. */
static uint8_t card_state, card_told;
static void queue_card(void);
static void card_status(void) {
	uint32_t i;
	if (ach_dbg.card_port >= 0) { card_state = 1; return; }
	card_state = 2;
#ifndef CARD_SIMPLE
	for (i = 0; i < 2; i++) {
		struct ps_dirent d;
		memset(&d, 0, sizeof(d));
		if (bios_firstfile(i ? "bu10:*" : "bu00:*", &d)) card_state = 3;   /* files there, ours could not be made */
	}
#endif
	for (i = 0; i < NBYTES; i++) if (bits[i]) ach_dbg.pending = 1;
	if (!card_told) { card_told = 1; queue_card(); }
}
static char card_saved[] = "SAVED ON MEMORY CARD 1";
#ifdef CARD_SIMPLE                     /* (MSHvSF: no room to tell "full" from "none") */
static const char* const card_word[] = { "NO MEMORY CARD / CARD FULL" };
#else
static const char* const card_word[] = { "NO MEMORY CARD", "MEMORY CARD FULL" };
#endif
static const char* card_text(void) {
	if (card_state == 1) { card_saved[21] = ach_dbg.card_port ? '2' : '1'; return card_saved; }
	return card_state >= 2 ? card_word[card_state - 2] : "";
}

/* first time the card may be used: read the file of both slots, make one if none */
static void card_load(void) {
	int k, found = 0;
	for (k = 0; k < 2; k++) {
		const int fd = bios_open(path[k], 1);
		if (fd < 0) continue;
		found = 1;
		if (bios_lseek(fd, BLK_OFF, 0) == BLK_OFF && bios_read(fd, sec, 0x80) == 0x80 && block_ok((struct ra_block*)sec)) {
			const struct ra_block* b = (const struct ra_block*)sec;
			uint32_t i;
			for (i = 0; i < NBYTES; i++) bits[i] |= b->bits[i];
		}
		bios_close(fd);
	}
	if (!found) create();
	locate();
	if (ach_dbg.card_port < 0) ach_dbg.card_port = -2;      /* (no card / no room: -2) */
	card_status();
	{ uint32_t i; for (i = 0; i < ra_nach; i++) if (bit(i)) ra_st[i] = ST_OFF; }
	ach_dbg.loaded = 1;
}

/* once per frame: card work.  The blocking BIOS calls (directory, open, read, create) run only where the port
   says the game is idle (main menu): there the file is read once, and located again on every visit (a card may have
   been swapped).  An unlock elsewhere is written with the BIOS's queued sector write (returns at once) to the sector
   located at the last visit, unless the game itself may be using the card. */
static int idle_seen;
static uint16_t recheck;
static void card_tick(void) {
	if (PORT_CARD_IDLE()) {
		if (!idle_seen) {
			idle_seen = 1;
			if (!ach_dbg.loaded) card_load();
			else { locate(); if (ach_dbg.card_port < 0 && ach_dbg.pending) { create(); locate(); }  card_status(); }
			ach_dbg.tries = 0;
		} else if (ach_dbg.loaded && ++recheck >= 240) {     /* every 4 s at the main menu: a card inserted / pulled */
			recheck = 0;
			locate(); if (ach_dbg.card_port < 0 && ach_dbg.pending) { create(); locate(); }
			card_status(); ach_dbg.tries = 0;
		}
	} else idle_seen = 0;
	if (rt_wait) { rt_wait--; return; }
	if (!ach_dbg.pending || ach_dbg.card_port < 0 || rt_sector < 64 || ach_dbg.tries >= 3 || !PORT_CARD_SAFE()) return;
	make_block(sec);
	ach_dbg.card_res = (int16_t)bios_card_write(ach_dbg.card_port, rt_sector, sec);
	if (ach_dbg.card_res == 1) { ach_dbg.pending = 0; rt_wait = 120; }
	else { rt_wait = 60; ach_dbg.tries++; }
}

/* ------------------------------------------------------------------------ */
/* unlock popup */
#define POP_FRAMES 210
static uint8_t queue[8], nqueue;
static int pop_frames, page_open;
static char pop_line[48];

static const char* pop_head;
static void queue_card(void) { if (nqueue < sizeof(queue)) queue[nqueue++] = 0xfe; }
static void popup_tick(void) {
	if (pop_frames) {
		if (page_open) { pop_frames = 0; return; }
		pop_frames--;
		if (PORT_POPUP_OK()) PORT_POPUP(pop_head, pop_line, pop_frames == POP_FRAMES - 1);
		return;
	}
	if (!nqueue || page_open || !PORT_POPUP_OK()) return;
#ifdef PORT_NOTICE_OK
	if (queue[0] == 0xfe && !PORT_NOTICE_OK()) return;      /* the card notice: where the port can show it */
#endif
	if (queue[0] == 0xfe) {                 /* the memory-card notice (card_status) */
#ifdef PORT_NOTICE_ONE_LINE              /* one line, where the port puts it (XvSF: above the menu's logo) */
		pop_head = "";
		cat(pop_line, card_state == 3 ? "ACHIEVEMENTS NOT SAVED (CARD FULL)" : "ACHIEVEMENTS NOT SAVED (NO CARD)");
#else
		pop_head = card_word[card_state - 2];
		cat(pop_line, card_state == 3 ? "NEED 1 FREE BLOCK" : "ACHIEVEMENTS NOT SAVED");          /* (3 only without CARD_SIMPLE) */
#endif
	} else {
		const uint32_t i = queue[0];
		char* p = unpack(pop_line, RA_TITLE(i), 0);
		p = cat(p, " ("); p = fmt_num(p, ra_points[i]); cat(p, ")");
#ifdef CARD_SIMPLE
		pop_head = "ACHIEVEMENT UNLOCKED";
#else
		pop_head = card_state >= 2 ? "UNLOCKED (NOT SAVED)" : "ACHIEVEMENT UNLOCKED";
#endif
	}
	nqueue--;
	memcpy(queue, queue + 1, sizeof(queue) - 1);
	pop_frames = POP_FRAMES;
	PORT_SFX_UNLOCK();
}

/* ------------------------------------------------------------------------ */
static uint8_t out[NACH_MAX];
/* the evaluation, where the game waits anyway (port: before its GPU / vblank wait) */
void ach_idle(ACH_IDLE_ARGS) {
	uint32_t n, k;
	uint16_t t = *(volatile uint16_t*)0x1F801110u;
	if (WD_OFF()) { PORT_IDLE_PREV(); return; }
#ifndef ACH_NOWD
	wd_step();
#endif
#ifdef ACH_COSTX
	{ int r; for (r = 1; r < ACH_COSTX; r++) { port_derive(); ra_eval_frame(out); } }
#endif
	ach_dbg.frames++;
#if defined(ACH_DIAG) && ACH_DIAG == 1
	(void)k; PORT_IDLE_PREV(); return;      /* bisect 1: runtime copied, hooks in, nothing runs (no card code at all) */
#endif
	port_derive();
	n = ra_eval_frame(out);
	if (ach_dbg.force) { out[n++] = ach_dbg.force - 1; ach_dbg.force = 0; }    /* test aid: unlock one */
	for (k = 0; k < n; k++) {
		const uint32_t i = out[k];
		bits[i >> 3] |= (uint8_t)(1u << (i & 7)); ra_st[i] = ST_OFF;
		if (nqueue < sizeof(queue)) queue[nqueue++] = (uint8_t)i;
		ach_dbg.pending = 1; ach_dbg.tries = 0; ach_dbg.last = (uint8_t)i;
	}
#if !defined(ACH_DIAG) || ACH_DIAG >= 3
	card_tick();
#endif
#ifndef ACH_NOCOST
	t = (uint16_t)(*(volatile uint16_t*)0x1F801110u - t);
	ach_dbg.cost = t;
	if (t > ach_dbg.cost_max) ach_dbg.cost_max = t;
#endif
#ifdef PORT_IDLE_EXTRA
	PORT_IDLE_EXTRA();                  /* port: work that needs this point of the frame (XvSF: the page) */
#endif
	PORT_IDLE_PREV();
}

/* the popup, where the game starts building a frame (port: after its OT clear) */
void ach_frame(ACH_FRAME_ARGS) {
	uint16_t t;
	if (WD_OFF()) { PORT_FRAME_PREV(); return; }
#ifdef PORT_FRAME_EXTRA
	PORT_FRAME_EXTRA();                 /* port: per-frame work before the game's (XvSF: patch the menu overlay in RAM) */
#endif
	PORT_FRAME_PREV();
#ifdef ACH_GDIAG
	gdiag_draw();
#endif
#ifdef ACH_DIAG
	{	/* bisect builds: status line top left: build, our frame count, card port + 3 */
		char l[40], *p = cat(l, "ACH D"); p = fmt_num(p, ACH_DIAG); p = cat(p, " F"); p = fmt_num(p, ach_dbg.frames);
		p = cat(p, " C"); p = fmt_num(p, (uint32_t)(ach_dbg.card_port + 3)); (void)p;
		PORT_TEXT(l, PAGE_X, PAGE_Y, PORT_COL_HEAD);
	}
#endif
	t = *(volatile uint16_t*)0x1F801110u;
#if !defined(ACH_DIAG) || ACH_DIAG >= 2
	popup_tick();
#endif
#ifndef ACH_NOCOST
	t = (uint16_t)(*(volatile uint16_t*)0x1F801110u - t);
	ach_dbg.pcost = t;
	if (t > ach_dbg.pcost_max) ach_dbg.pcost_max = t;
#endif
}

/* ------------------------------------------------------------------------ */
/* the page: header, PAGE_ROWS titles, the selected one's state, points and description */
#ifdef PAGE_CACHE
/* cached variant (XvSF: its page is drawn in the text routine's direct mode, so a frame costs more than a
   vblank): the lines are composed only when the selection, the scroll position or the count change; the pad is
   read on every call with our own edge detection (no press is lost however long the frame takes) and held
   directions repeat by the vblank counter (PORT_VCOUNT): PAGE_REP_FIRST, then every PAGE_REP_NEXT vblanks. */
static int sel, top;
static struct {
	int16_t sel, top, n, ok;
	uint16_t held, rep_at;
	char head[48], rows[PAGE_ROWS][PAGE_COLS + 1], title[72], stat[24], desc[PAGE_DESC][72];
	uint8_t col[PAGE_ROWS];
} pc __attribute__((section(".bdat")));       /* image B (region A is full) */
#define PC_DIRS (PORT_B_UP | PORT_B_DOWN | PORT_B_LEFT | PORT_B_RIGHT)
static uint16_t page_input(void) {
	const uint16_t held = PORT_PAD_HELD(), now = PORT_VCOUNT();
	const uint16_t nw = (uint16_t)(held & ~pc.held);
	pc.held = held;
	if (nw & PC_DIRS) { pc.rep_at = (uint16_t)(now + PAGE_REP_FIRST); return nw; }
	if ((held & PC_DIRS) && (int16_t)(now - pc.rep_at) >= 0) {
		pc.rep_at = (uint16_t)(now + PAGE_REP_NEXT);
		return (uint16_t)(nw | (held & (held & (PORT_B_UP | PORT_B_DOWN) ? (PORT_B_UP | PORT_B_DOWN) : PC_DIRS)));
	}
	return nw;
}
static void page_compose(uint32_t n, uint32_t pts) {
	char desc[200];
	const char* d;
	uint32_t i;
	char* p = cat(pc.head, "ACHIEVEMENTS "); p = fmt_num(p, n); p = cat(p, "/"); p = fmt_num(p, ra_nach);
	p = cat(p, "  "); p = fmt_num(p, pts); p = cat(p, "/"); p = fmt_num(p, ra_total_points); cat(p, " PTS");
	for (i = 0; i < PAGE_ROWS; i++) {
		const uint32_t j = top + i;
		pc.rows[i][0] = 0;
		if (j >= ra_nach) continue;
		p = cat(pc.rows[i], j == (uint32_t)sel ? ">" : " ");
		p = cat(p, bit(j) ? "+" : " ");
		unpack(desc, RA_TITLE(j), 0);
		desc[PAGE_COLS - 2] = 0;
		cat(p, desc);
		pc.col[i] = (uint8_t)(j == (uint32_t)sel ? PORT_COL_SEL : bit(j) ? PORT_COL_ON : PORT_COL_OFF);
	}
	unpack(pc.title, RA_TITLE(sel), 0);
	p = cat(pc.stat, bit(sel) ? "UNLOCKED  " : "LOCKED  ");
	p = fmt_num(p, ra_points[sel]); cat(p, ra_points[sel] == 1 ? " PT" : " PTS");
	unpack(desc, RA_DESC(sel), 0);
	d = desc;
	for (i = 0; i < PAGE_DESC; i++) {
		char* q = pc.desc[i];
		while (*d && *d != '\n') *q++ = *d++;
		*q = 0;
		if (*d == '\n') d++;
	}
	pc.sel = (int16_t)sel; pc.top = (int16_t)top; pc.n = (int16_t)n; pc.ok = 1;
}
int ach_page(void) {
	uint32_t pts, n, i;
	uint16_t pad;
	if (WD_OFF()) return 0;
	if (!page_open) { page_open = 1; sel = top = 0; pc.ok = 0; pc.held = PORT_PAD_HELD(); PORT_SFX_CONFIRM(); }
	pad = page_input();
	if (pad & PORT_B_BACK) { page_open = 0; PORT_SFX_CANCEL(); return 0; }
	{
		int s = sel;
		if (pad & PORT_B_UP) s = s > 0 ? s - 1 : ra_nach - 1;
		if (pad & PORT_B_DOWN) s = s < ra_nach - 1 ? s + 1 : 0;
		if (pad & PORT_B_LEFT) s = s >= PAGE_ROWS ? s - PAGE_ROWS : 0;
		if (pad & PORT_B_RIGHT) s = s + PAGE_ROWS < ra_nach ? s + PAGE_ROWS : ra_nach - 1;
		if (s != sel) {
			sel = s;
			if (sel < top) top = sel;
			if (sel >= top + PAGE_ROWS) top = sel - PAGE_ROWS + 1;
			PORT_SFX_CURSOR();
		}
	}
	n = unlocked(&pts);
	if (!pc.ok || pc.sel != sel || pc.top != top || pc.n != (int16_t)n) page_compose(n, pts);
	PORT_TEXT(pc.head, PAGE_X, PAGE_Y, PORT_COL_HEAD);
	PORT_TEXT(card_text(), PAGE_X, PAGE_Y + PAGE_LINE, card_state >= 2 ? PORT_COL_OFF : PORT_COL_ON);
	for (i = 0; i < PAGE_ROWS; i++)
		if (pc.rows[i][0]) PORT_TEXT(pc.rows[i], PAGE_X, PAGE_Y + PAGE_LINE * (2 + i), pc.col[i]);
	PORT_TEXT(pc.title, PAGE_X, PAGE_Y + PAGE_LINE * (3 + PAGE_ROWS), PORT_COL_SEL);
	PORT_TEXT(pc.stat, PAGE_X, PAGE_Y + PAGE_LINE * (4 + PAGE_ROWS), bit(sel) ? PORT_COL_ON : PORT_COL_OFF);
	for (i = 0; i < PAGE_DESC && pc.desc[i][0]; i++)
		PORT_TEXT(pc.desc[i], PAGE_X, PAGE_Y + PAGE_LINE * (5 + PAGE_ROWS + i), PORT_COL_HEAD);
	return 1;
}
#else
static int sel, top;
/* returns 1 while open, 0 when the player leaves (the port goes back to its menu) */
int ach_page(void) {
	char line[64], desc[200];
	uint32_t pts, n, i;
	if (WD_OFF()) return 0;
#ifdef ACH_GDIAG_NOPAGE
	return 0;                           /* guard diagnostic build without room for the page (MSHvSF) */
#endif
#ifdef PORT_PAD_HELD
	/* our own edge detection, read on every call, held directions repeat by the vblank counter (PAGE_REP_FIRST, then
	   every PAGE_REP_NEXT): no press is lost however slow the frame */
	static uint16_t held, rep_at;
	uint16_t pad;
	{
		const uint16_t h = PORT_PAD_HELD(), now = PORT_VCOUNT(), dirs = PORT_B_UP | PORT_B_DOWN | PORT_B_LEFT | PORT_B_RIGHT;
		if (!page_open) held = h;
		pad = (uint16_t)(h & ~held); held = h;
		if (pad & dirs) rep_at = (uint16_t)(now + PAGE_REP_FIRST);
		else if ((h & dirs) && (int16_t)(now - rep_at) >= 0) {
			rep_at = (uint16_t)(now + PAGE_REP_NEXT);
			pad |= (uint16_t)(h & ((h & (PORT_B_UP | PORT_B_DOWN)) ? (PORT_B_UP | PORT_B_DOWN) : dirs));
		}
	}
#else
	const uint16_t pad = PORT_PAD_NEW();
#endif
	const char* d;
	if (!page_open) { page_open = 1; sel = top = 0; PORT_SFX_CONFIRM(); }
	if (pad & PORT_B_BACK) { page_open = 0; PORT_SFX_CANCEL(); return 0; }
	{
		int s = sel;
		if (pad & PORT_B_UP) s = s > 0 ? s - 1 : ra_nach - 1;
		if (pad & PORT_B_DOWN) s = s < ra_nach - 1 ? s + 1 : 0;
		if (pad & PORT_B_LEFT) s = s >= PAGE_ROWS ? s - PAGE_ROWS : 0;
		if (pad & PORT_B_RIGHT) s = s + PAGE_ROWS < ra_nach ? s + PAGE_ROWS : ra_nach - 1;
		if (s != sel) {
			sel = s;
			if (sel < top) top = sel;
			if (sel >= top + PAGE_ROWS) top = sel - PAGE_ROWS + 1;
			PORT_SFX_CURSOR();
		}
	}
	n = unlocked(&pts);
#ifndef PAGE_COLS
#define PAGE_COLS 64
#endif
#ifndef PORT_COL_SEL
#define PORT_COL_SEL 0xffff                 /* (none: the row's own colour) */
#endif
	{
		char* p = cat(line, "ACHIEVEMENTS "); p = fmt_num(p, n); p = cat(p, "/"); p = fmt_num(p, ra_nach);
		p = cat(p, "  "); p = fmt_num(p, pts); p = cat(p, "/"); p = fmt_num(p, ra_total_points); cat(p, " PTS");
		PORT_TEXT(line, PAGE_X, PAGE_Y, PORT_COL_HEAD);
		PORT_TEXT(card_text(), PAGE_X, PAGE_Y + PAGE_LINE, card_state >= 2 ? PORT_COL_OFF : PORT_COL_ON);
	}
	for (i = 0; i < PAGE_ROWS && top + i < ra_nach; i++) {
		const uint32_t j = top + i;
		int col = bit(j) ? PORT_COL_ON : PORT_COL_OFF;
		char* p = cat(line, j == (uint32_t)sel ? ">" : " ");
		p = cat(p, bit(j) ? "+" : " ");
		unpack(desc, RA_TITLE(j), 0);
		desc[PAGE_COLS - 2] = 0;                   /* the list shows what fits; the info part the whole title */
		cat(p, desc);
		if (j == (uint32_t)sel && PORT_COL_SEL != 0xffff) col = PORT_COL_SEL;
		PORT_TEXT(line, PAGE_X, PAGE_Y + PAGE_LINE * (2 + i), col);
	}
#ifdef PAGE_INFO_TITLE
	unpack(line, RA_TITLE(sel), 0);
	PORT_TEXT(line, PAGE_X, PAGE_Y + PAGE_LINE * (3 + PAGE_ROWS), PORT_COL_SEL != 0xffff ? PORT_COL_SEL : PORT_COL_HEAD);
#define INFO_K (4 + PAGE_ROWS)
#else
#define INFO_K (3 + PAGE_ROWS)
#endif
	{
		char* p = cat(line, bit(sel) ? "UNLOCKED  " : "LOCKED  ");
		p = fmt_num(p, ra_points[sel]); cat(p, ra_points[sel] == 1 ? " PT" : " PTS");
		PORT_TEXT(line, PAGE_X, PAGE_Y + PAGE_LINE * INFO_K, bit(sel) ? PORT_COL_ON : PORT_COL_OFF);
	}
	unpack(desc, RA_DESC(sel), 0);
	d = desc;
	for (i = 0; i < PAGE_DESC && *d; i++) {
		char* q = line;
		while (*d && *d != '\n') *q++ = *d++;
		*q = 0;
		if (*d == '\n') d++;
		PORT_TEXT(line, PAGE_X, PAGE_Y + PAGE_LINE * (INFO_K + 1 + i), PORT_COL_HEAD);
	}
	return 1;
}

#endif

int ach_is_open(void) { return page_open; }
