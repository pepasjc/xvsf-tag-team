/* mtap.c: 3-4 player VERSUS with the PS1 multitap - Marvel Super Heroes vs. Street Fighter (SLUS-00793) tag hack.
   Built by mtap.py (notes: games/mshvsf/docs/MULTITAP.md).  Linked at BASE (kernel RAM); the entry mt_entry replaces
   `jal 0x80023b88` at 0x80020c8c (the game's per-frame pad update, end of the main loop).

   The game reads the pads with Psy-Q libpad (PadInitDirect, buffers 0x80027d68 port 1 / 0x80027d90 port 2) in its
   VBlank handler; a multitap there delivers slot A only.  0x80023b88 turns the buffers into raw words
   (0x80027db4/6 current, 0x80027dc0/2 last frame) and 0x80027d60 (+0 P1, +2 P2, +4 or, +6 and), 0x80027db8 (last frame,
   same layout).  The next frame starts with 0x800237ac, which maps 0x80027db4/6 through the key config
   (0x80027d10 / 0x80027d30) into the game's pads.  So the side words written here are all the game sees.

   We read the multitap ourselves (direct SIO, interrupts off, after libpad's read): a slot-A access with the multitap
   request flag (3 bytes), then the long access (35 bytes) with the flag clear, so libpad's next access gets slot A
   again (psx-spx "multitap" request rules). */
#include <stdint.h>
#define U8(a)  (*(volatile uint8_t*)(a))
#define S8(a)  (*(volatile int8_t*)(a))
#define U16(a) (*(volatile uint16_t*)(a))
#define S16(a) (*(volatile int16_t*)(a))
#define U32(a) (*(volatile uint32_t*)(a))

#define MODE    0x800250acu      /* 1 = VERSUS */
#define HUMANS  0x80070a91u
#define SCENE   0x80070a94u      /* 0 title / menus, 4 select, 8 battle */
#define CUR     0x80027db4u      /* raw words, current (P1, P2) */
#define LAST    0x80027dc0u      /* raw words, last frame (saved by 0x80023b88 from CUR) */
#define PADW    0x80027d60u      /* P1, P2, or, and */
#define PADP    0x80027db8u      /* last frame: P1, P2, or, and */
#define KEYCFG  0x80027d10u      /* side * 0x20: u16 function per raw bit */
#define SEL     0x80071af4u      /* select struct side 0 (side 1 at +0x2c): +2 picks made */
#define OBJ0    0x80070b50u      /* player objects: side s main = OBJ0 + s*0x3c0; partners OBJ2 (side 0), OBJ3 (side 1) */
#define OBJ2    0x80071310u
#define OBJ3    0x800716c8u
#define PRINT   0x80022e20u
#define VCOUNT  0x8001d210u
#define B_START 0x0800
#define B_SEL   0x0100
#define B_UP    0x1000
#define B_RIGHT 0x2000
#define B_DOWN  0x4000
#define B_LEFT  0x8000
#define B_CROSS 0x0040
#define B_TRI   0x0010
#define B_BTNS  0x0fff           /* everything but the directions */

#define JOY_DATA (*(volatile uint8_t*)0x1f801040)
#define JOY_STAT (*(volatile uint32_t*)0x1f801044)
#define JOY_MODE (*(volatile uint16_t*)0x1f801048)
#define JOY_CTRL (*(volatile uint16_t*)0x1f80104a)
#define JOY_BAUD (*(volatile uint16_t*)0x1f80104e)
#define I_STAT   (*(volatile uint32_t*)0x1f801070)
#define RCNT2    (*(volatile uint32_t*)0x1f801120)
#define RCNT1    (*(volatile uint32_t*)0x1f801110)

typedef void (*f_void)(void);
typedef int (*f_int)(void);
typedef void (*f_print)(const char*, uint32_t, uint32_t);

#define NC 5                      /* controllers: 0..3 multitap slots A-D on port 1, 4 = port 2 */

struct vars {
	uint8_t state;                /* 0 not in versus / undecided, 1 assignment screen, 2 routing, 3 stock (fewer than 3) */
	uint8_t ncon;                 /* controllers found at the last detection */
	uint8_t conn;                 /* bit per controller connected (last read) */
	uint8_t join;                 /* bit per controller joined (assignment) */
	uint8_t ready;                /* bit per controller ready */
	uint8_t side[NC];             /* 0 / 1 side of a joined controller */
	uint8_t own[2][2];            /* [side][0 first player, 1 second]: controller or 0xff */
	uint8_t owner[2];             /* controller driving each side last frame */
	uint8_t tapok;                /* last long read gave 0x80 */
	uint8_t fails;
	uint16_t pad[NC];             /* game-format words (1 = held) */
	uint16_t prev[NC];
	uint16_t mask[2];             /* buttons held by a new owner at the hand-over: ignored until released */
	uint16_t t_read;              /* root counter 2 ticks of the last read */
	uint16_t t_max;
	uint8_t rx[36];
	uint16_t t_rc1;               /* root counter 1 (hblank) ticks of the last read */
	uint16_t rc2mode;
	uint8_t nlong;                /* bytes of the long access: up to the buttons of the last slot found at the detection */
	uint8_t nrx, err;             /* bytes received by the last long access; RX timeout (0x80 | byte index) */
	uint16_t okcnt;               /* long reads with ID 0x80 */
	uint8_t tries;                /* detection frames so far */
	uint8_t sid[5];               /* slot IDs of the last good long read (FF = none); [4] port 2 present */
	uint8_t pinit, pres;          /* menu probe: done once, multitap with >= 2 pads found */
	uint16_t plast;               /* vblank count of the last menu probe */
	uint16_t hooks;               /* mt_mask calls (menu / pause pad check) */
	uint8_t probes, pok;          /* menu probes, probes that found >= 2 multitap pads */
	uint8_t n1, sid1[4];          /* first long read of the last probe: bytes, slot IDs */
};
struct vars V;

/* ------------------------------------------------------------------------------------------------- SIO */
static void spin(int n) { while (n-- > 0) __asm__ volatile("nop"); }

/* one access on port 1: send tx[0..n-1] (0 after len), store replies; returns the number of bytes received */
static int xfer(const uint8_t *tx, int len, int n) {
	int i;
	JOY_CTRL = 0;                 /* (no SIO reset: bit 6 makes the next transfer fail in Beetle; a stale RX byte is drained below) */
	JOY_MODE = 0x0d; JOY_BAUD = 0x88;
	JOY_CTRL = 0x1003;            /* TX enable, /JOY1, ACK interrupt enable */
	spin(SEL_DELAY);
	while (JOY_STAT & 2) (void)JOY_DATA;
	for (i = 0; i < n; i++) {
		int t;
		JOY_DATA = i < len ? tx[i] : 0;
		for (t = 0; !(JOY_STAT & 2); t++) if (t > RX_WAIT) { V.err = (uint8_t)(0x80 | i); goto done; }
		V.rx[i] = JOY_DATA;
		if (i == n - 1) { i++; break; }
		for (t = 0; !(JOY_STAT & 0x200); t++) if (t > ACK_WAIT) { i++; goto done; }   /* /ACK interrupt latch: the device wants more */
		JOY_CTRL = 0x1013;        /* acknowledge */
	}
done:
	JOY_CTRL = 0;
	return i;
}

static const uint8_t req1[3] = { 0x01, 0x42, 0x01 };
static const uint8_t req0[35] = { 0x01, 0x42, 0x00, 0x42, 0, 0, 0, 0, 0, 0, 0, 0x42, 0, 0, 0, 0, 0, 0, 0,
                                  0x42, 0, 0, 0, 0, 0, 0, 0, 0x42, 0, 0, 0, 0, 0, 0, 0 };

static void mt_read(void) {
	uint32_t sr, t0, h0;
	int n, s;
	__asm__ volatile("mfc0 %0, $12" : "=r"(sr));
	__asm__ volatile("mtc0 %0, $12; nop; nop" : : "r"(sr & ~1u));
	t0 = RCNT2; h0 = RCNT1;
	xfer(req1, 3, 3);
	spin(GAP_DELAY);
	n = xfer(req0, 35, V.nlong ? V.nlong : 35);
	spin(60);
	I_STAT = ~0x80u;              /* our ACK interrupts: not for libpad */
	{ uint16_t d = (uint16_t)(RCNT2 - t0); V.t_read = d; if (d > V.t_max) V.t_max = d;
	  V.t_rc1 = (uint16_t)(RCNT1 - h0); V.rc2mode = *(volatile uint16_t*)0x1f801124; }
	__asm__ volatile("mtc0 %0, $12; nop; nop" : : "r"(sr));
	V.nrx = (uint8_t)n;
	V.tapok = n >= 3 && V.rx[1] == 0x80;
	if (!V.tapok) { V.fails++; V.conn &= 0x10; return; }
	V.okcnt++;
	for (s = 0; s < 4; s++) {
		const uint8_t *r = V.rx + 3 + 8 * s;
		int ok = 3 + 8 * s + 4 <= n && r[0] != 0xff && r[1] == 0x5a;
		if (3 + 8 * s + 4 > n) { V.conn &= ~(1 << s); V.pad[s] = 0; V.sid[s] = 0xee; continue; }   /* (beyond the trimmed read) */
		int ty = r[0] >> 4;
		V.sid[s] = ok ? r[0] : 0xff;
		if (ok) {
			V.conn |= 1 << s;
			(void)ty;                 /* any pad ID (0x41 digital, 0x73 / 0x53 analog, ...): digital button bytes only */
			V.pad[s] = (uint16_t)~(r[2] << 8 | r[3]);
		} else { V.conn &= ~(1 << s); V.pad[s] = 0; }
	}
}

/* port 2 from the game's own read (libpad buffer, checked by 0x80023b04) */
static void port2(uint16_t stock_p2) {
	if (((f_int)0x80023b04)()) { V.conn |= 0x10; V.pad[4] = stock_p2; }
	else { V.conn &= ~0x10; V.pad[4] = 0; }
}

static int popc(uint32_t m) { int c = 0; while (m) { c += m & 1; m >>= 1; } return c; }

/* ------------------------------------------------------------------------------------------------- text */
__attribute__((section(".text.ui"))) static void pr(const char *s, int x, int y, int col) {
	((f_print)PRINT)(s, (uint32_t)x << 16 | (uint32_t)y, 8u << 24 | (uint32_t)col << 16 | 1);
}
static const char *const cname[NC] = { "1A", "1B", "1C", "1D", "2" };

__attribute__((section(".text.ui"))) static void assign_draw(void) {
	int c, s, k;
	pr("MULTITAP VERSUS", TX0, TY0, 0x26);
	pr("START JOIN  LEFT RIGHT SIDE", TX0, TY0 + 16, 0);
	pr("START AGAIN READY  TRIANGLE LEAVE", TX0, TY0 + 26, 0);
	pr("SIDE 1", TX0, TY0 + 46, 0x26);
	pr("SIDE 2", TX0 + TCOL, TY0 + 46, 0x26);
	for (s = 0; s < 2; s++)
		for (k = 0; k < 2; k++) {
			int ctl = V.own[s][k];
			if (ctl == 0xff) continue;
			pr(cname[ctl], TX0 + s * TCOL, TY0 + 60 + k * 12, 0);
			pr(k ? "CHAR 2" : "CHAR 1", TX0 + s * TCOL + 24, TY0 + 60 + k * 12, 0);
			if (V.ready >> ctl & 1) pr("OK", TX0 + s * TCOL + 80, TY0 + 60 + k * 12, 0x26);
		}
	k = 0;
	for (c = 0; c < NC; c++)
		if ((V.conn >> c & 1) && !(V.join >> c & 1)) {
			pr(cname[c], TX0 + k * 24, TY0 + 100, 0); k++;
		}
	if (k) pr("PRESS START", TX0 + k * 24 + 8, TY0 + 100, 0);
}

__attribute__((section(".text.ui"))) static void unlink(int c) {
	int s, k;
	for (s = 0; s < 2; s++) {
		if (V.own[s][0] == c) { V.own[s][0] = V.own[s][1]; V.own[s][1] = 0xff; }
		else if (V.own[s][1] == c) V.own[s][1] = 0xff;
		(void)k;
	}
	V.join &= ~(1 << c); V.ready &= ~(1 << c);
}

__attribute__((section(".text.ui"))) static int put(int c, int s) {          /* c onto side s (as second if the first is taken) */
	if (V.own[s][0] == 0xff) V.own[s][0] = c;
	else if (V.own[s][1] == 0xff) V.own[s][1] = c;
	else return 0;
	V.side[c] = s; V.join |= 1 << c;
	return 1;
}

__attribute__((section(".text.ui"))) static void assign_step(void) {
	int c;
	for (c = 0; c < NC; c++) {
		uint32_t nw = V.pad[c] & ~V.prev[c];
		if (!(V.conn >> c & 1)) { if (V.join >> c & 1) unlink(c); continue; }
		if (!(V.join >> c & 1)) {
			if (nw & B_START) {
				int s = (V.own[0][0] == 0xff || (V.own[1][0] != 0xff && V.own[0][1] == 0xff)) ? 0 : 1;
				if (!put(c, s)) put(c, s ^ 1);
			}
			continue;
		}
		if (nw & B_TRI) { unlink(c); continue; }
		if (nw & (B_LEFT | B_RIGHT)) {
			int s = (nw & B_LEFT) ? 0 : 1;
			if (s != V.side[c] && V.own[s][1] == 0xff) { unlink(c); put(c, s); }
			continue;
		}
		if (nw & B_START) V.ready |= 1 << c;
	}
	if (V.own[0][0] != 0xff && V.own[1][0] != 0xff && V.join && (V.ready & V.join) == V.join) {
		V.state = 2;
		V.owner[0] = V.owner[1] = 0xff;
	}
}

/* ------------------------------------------------------------------------------------------------- routing */
static int point_second(int s) {          /* 1 when the side's second character (partner object) is on point */
	const uint32_t a = OBJ0 + s * 0x3c0, b = s ? OBJ3 : OBJ2;
	if (S16(SCENE) == 4) return S8(SEL + s * 0x2c + 2) > 0;         /* select: second player picks the second character */
	if (!U8(b) || U16(b + 4) != 2) return 0;
	if (U8(a) && U16(a + 4) == 2 && U8(b + 0x263)) return 0;
	return 1;
}

static uint16_t tagbits(int s) {           /* raw bits configured exactly as HP / HK on this side */
	uint16_t hp = 0, hk = 0; int b;
	for (b = 0; b < 8; b++) {
		uint16_t f = U16(KEYCFG + s * 0x20 + b * 2);
		if (f == 0x40) hp |= 1 << b;
		if (f == 0x400) hk |= 1 << b;
	}
	return (hp && hk) ? (uint16_t)(hp | (hk << 8)) : 0;   /* packed: lo = HP bits, hi = HK bits */
}

static uint16_t route(int s) {
	int a = V.own[s][0], b = V.own[s][1], o, p;
	uint16_t w, pw;
	if (a == 0xff) return 0;
	if (b == 0xff) { o = a; p = 0xff; }
	else if (point_second(s)) { o = b; p = a; } else { o = a; p = b; }
	w = V.pad[o];
	if (o != V.owner[s]) { V.mask[s] = w & B_BTNS; V.owner[s] = (uint8_t)o; }
	V.mask[s] &= w;
	w &= ~V.mask[s];
	if (p != 0xff) {
		pw = V.pad[p];
		w |= pw & B_START;                                  /* either player may pause */
		if (S16(SCENE) == 8) {                              /* the waiting partner may call the tag-in (its HP + HK) */
			uint16_t t = tagbits(s), hp = t & 0xff, hk = t >> 8;
			if (t && (pw & hp) && (pw & hk)) w |= pw & (hp | hk);
		}
	}
	return w;
}

#if DIAG
static char dbuf[144] __attribute__((section(".text.ui.buf")));
/* one line at the top of the versus select screen:
   MT <tap ID> N<controllers> S<state> T<detect tries> A<id> B<id> C<id> D<id> P<port 2 0/1> OK<good long reads> F<failed> E<rx timeout> R<bytes> */
__attribute__((section(".text.ui"))) static char *hx(char *p, uint32_t v, int nd) {
	int k;
	for (k = nd - 1; k >= 0; k--) { uint32_t d = (v >> (4 * k)) & 15; *p++ = (char)(d < 10 ? '0' + d : 'A' + d - 10); }
	return p;
}
__attribute__((section(".text.ui"))) static void diag_draw(void) {
	char *p = dbuf, *q; int s;
	*p++ = 'M'; *p++ = 'T'; p = hx(p, V.rx[1], 2);
	*p++ = ' '; *p++ = 'N'; p = hx(p, V.ncon, 1);
	*p++ = ' '; *p++ = 'S'; p = hx(p, V.state, 1);
	*p++ = ' '; *p++ = 'K'; p = hx(p, V.okcnt, 4);
	*p++ = ' '; *p++ = 'F'; p = hx(p, V.fails, 2);
	*p++ = ' '; *p++ = 'E'; p = hx(p, V.err, 2);
	*p++ = ' '; *p++ = 'R'; p = hx(p, V.nrx, 2);
	*p++ = ' '; *p++ = 'H'; p = hx(p, V.hooks, 4);
	*p++ = 0;
	pr(dbuf, DIAG_X, DIAG_Y, 0x26);
	q = p;
	for (s = 0; s < 4; s++) { *p++ = (char)('A' + s); p = hx(p, V.sid[s], 2); *p++ = ' '; }
	*p++ = 'P'; p = hx(p, V.conn >> 4 & 1, 1);
	*p++ = ' '; *p++ = 'Q'; p = hx(p, V.probes, 2); *p++ = ' '; *p++ = 'V'; p = hx(p, V.pok, 2);
	*p++ = ' '; *p++ = '1'; *p++ = ':'; p = hx(p, V.n1, 2);
	for (s = 0; s < 4; s++) p = hx(p, V.sid1[s], 2);
	*p++ = 0;
	pr(q, DIAG_X, DIAG_Y + 10, 0x26);
	q = p; *p++ = 'X';
	for (s = 0; s < 14; s++) p = hx(p, V.rx[s], 2);
	*p++ = 0;
	pr(q, DIAG_X, DIAG_Y + 20, 0x26);
	q = p;
	for (s = 0; s < 5; s++) { *p++ = (char)(s < 4 ? 'A' + s : 'P'); p = hx(p, V.pad[s], 4); *p++ = ' '; }
	*p = 0;
	pr(q, DIAG_X, DIAG_Y + 30, 0x26);
}
#endif

static void probe(void);

/* ------------------------------------------------------------------------------------------------- per frame */
void mt_tick(void) {
	int c;
	uint16_t w0, w1;
	((f_void)0x80023b88)();                                 /* stock pad update */
#if DIAG
	if (S16(SCENE) == 0) { probe(); diag_draw(); }       /* title / menus: what the multitap answers (diagnostic build) */
#endif
	if (S8(MODE) != 1 || U8(HUMANS) != 3 || S16(SCENE) == 0) {
		V.state = 0; return;
	}
	if (V.state == 3) {
#if DIAG
		if (S16(SCENE) == 4) diag_draw();
#endif
		return;
	}
	for (c = 0; c < NC; c++) V.prev[c] = V.pad[c];
	if (V.state == 0) {                                     /* detection: retried on the first DETECT_FRAMES select frames */
		if (S16(SCENE) != 4) { V.tries = 0; return; }
		port2(U16(CUR + 2));
		V.nlong = 0;
		if (V.tries == 0) mt_read();                        /* (a multitap may answer its slots only after one long access) */
		mt_read();
		V.tries++;
		V.ncon = (uint8_t)popc(V.conn);
		if (V.ncon < 3 && !(V.ncon >= 2 && !(V.conn & 0x10))) {   /* 3+ controllers, or 2 on the multitap with port 2 empty */
			if (V.tries >= DETECT_FRAMES) V.state = 3;
#if DIAG
			diag_draw();
#endif
			return;
		}
		for (c = 3; c >= 0; c--) if (V.conn >> c & 1) { V.nlong = (uint8_t)(3 + 8 * c + 4); break; }
		V.state = 1; V.join = V.ready = 0;
		V.own[0][0] = V.own[0][1] = V.own[1][0] = V.own[1][1] = 0xff;
		for (c = 0; c < NC; c++) V.prev[c] = V.pad[c];
		return;
	}
	port2(U16(CUR + 2));
	mt_read();
	if (V.state == 1) {
		assign_step();
		if (V.state == 1) {
			assign_draw();
			w0 = w1 = 0;
		} else { w0 = w1 = 0; V.mask[0] = V.mask[1] = 0xffff; }
	} else {
		w0 = route(0); w1 = route(1);
	}
#if DIAG
	if (S16(SCENE) == 4) diag_draw();
#endif
	U16(CUR) = w0; U16(CUR + 2) = w1;
	U16(PADW) = w0; U16(PADW + 2) = w1; U16(PADW + 4) = w0 | w1; U16(PADW + 6) = w0 & w1;
}

/* 0x80023b54 (disconnected-pad mask, bit 0 port 1, bit 1 port 2; read by the main menu, which hides VERSUS unless
   both ports have a pad, and by the battle pause) is replaced by this.  Port 2 empty (the MiSTer core even switches
   port 2 off while its multitap is on): a multitap with at least 2 pads counts as both ports.  With a pad in port 2
   (the normal 2-pad setup) nothing is read and the stock result is returned. */
__attribute__((section(".text.ui"))) static void slots_id(uint8_t *out) { int k; for (k = 0; k < 4; k++) out[k] = V.sid[k]; }

/* two complete request + long accesses: on the MiSTer core a slot answers only if the previous long access sent 0x42 as
   that slot's first byte, and libpad's own accesses (01 42 01 ...) keep the port in multitap mode, so a single read
   after libpad's can see four empty slots */
__attribute__((section(".text.ui"))) static void probe(void) {
	uint8_t nl;
	if (V.pinit && (uint16_t)(U16(VCOUNT) - V.plast) < 30) return;
	nl = V.nlong;
	V.pinit = 1; V.plast = U16(VCOUNT);
	V.nlong = 0;
	mt_read(); V.n1 = V.nrx; slots_id(V.sid1);
	mt_read();
	V.nlong = nl;
	V.pres = V.tapok && popc(V.conn & 15) >= 2;
	V.probes++; if (V.pres) V.pok++;
}

int mt_mask(void) {
	int m = (((f_int)0x80023ab4)() ^ 1) | ((((f_int)0x80023b04)() ^ 1) << 1);
	V.hooks++;
	if (!(m & 2)) return m;
	if (V.state == 1 || V.state == 2) return 0;
	probe();
	return V.pres ? 0 : m;
}

/* 0x80029338 `jal 0x80023b54` (pause when a pad is unplugged, bit per port): while the multitap drives the sides,
   ports are not players any more */
int mt_conn(void) {
	if (V.state == 1 || V.state == 2) return 0;
	return ((f_int)0x80023b54)();
}

__asm__(
	".section .text.mt_entry,\"ax\"\n"
	".set noreorder\n"
	".globl mt_entry\n"
	"mt_entry:\n"
	"	j mt_tick\n"
	"	nop\n"
	".set reorder\n");
