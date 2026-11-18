/* xvskip.c: START skips the end of a match - X-Men vs. Street Fighter (tools/skippatch.py builds it; notes in
   docs/ENGINE_NOTES.md "START skip").  Linked at BASE (kernel RAM); entry skip_entry replaces `jal 0x80028dc8`
   (the game's per-frame dispatch, only reached with 0x800421ad == 1: not in the attract demo). */
#include <stdint.h>
/* game addresses as offsets from a base register (smaller code) */
#define GB     0x80040000u
#define G(a)   ((volatile uint8_t*)gb + ((a) - GB))
#define U8(a)  (*(volatile uint8_t*)G(a))
#define S8(a)  (*(volatile int8_t*)G(a))
#define U16(a) (*(volatile uint16_t*)G(a))
#define S16(a) (*(volatile int16_t*)G(a))
#define U32(a) (*(volatile uint32_t*)(a))

#define MODE    0x8004218cu      /* 1 arcade, 2 versus */
#define HUMANS  0x80042771u      /* bit per pad */
#define SCENE   0x80042774u      /* 4 select, 8 battle, 12 after-match, 0x10 continue, 0x1c ending, 0x20 versus end */
#define SUB     0x80042776u
#define SUB2    0x80042778u
#define SUB3    0x8004277au
#define PHASE   0x80042348u      /* match: +0 phase, +4 round winner, +5 result (1 / 2 winner side + 1, -2 draw), +6 timer */
#define QUICK   0x800421a8u      /* the game's own quick path: after-match without the quote, select without the grid
                                    (0x80086fc4 / 0x80085a40: picker 0x800847e0, stage 0x80084744, "STAGE n ... NOW LOADING") */
#define LADDER  0x800423a0u      /* arcade fight index; the picker 0x800847e0 gives the boss at 6, its second form after */
#define PAD0    0x8004c2b0u
#define PAD1    0x8004c2b2u
#define VCOUNT  0x800220c8u
#define TEXT_FN 0x8002d79cu      /* (text, x, y, advance, colour, 1) */
#define GAME_FN 0x80028dc8u
#define OBJLIST 0x80042650u      /* object list head, +0x2c next; type at +0x24, state at +6 */
#define B_START 0x0800
#define B_SELECT 0x0100

typedef void (*f_text)(const char*, int, int, int, int, int);

struct vars { uint8_t prev, latch, sel, selprev, ok, quick, two; };
struct vars V;                   /* (BSS: the boot copy zeroes the whole area) */

static const char notice[] = "PRESS START BUTTON TO SHORT CUT";      /* MvC's text (SLUS_010.59 0x80028ad8) */

static int tally_pending(void) {
	volatile uint8_t* gb = (volatile uint8_t*)GB;
	uint32_t p = *(volatile uint32_t*)G(OBJLIST), n = 64;
	(void)gb;
	for (; n && (int32_t)p < 0; n--, p = U32(p + 0x2c))
		if (U16(p + 0x24) == 0x94 && S16(p + 6) < 6) return 1;   /* bonus tally / PERFECT letters before state 6 */
	return 0;
}

static void tick(void) {
	volatile uint8_t* gb = (volatile uint8_t*)GB;
	__asm__("" : "+r"(gb));                                       /* keep it in a register */
	const uint32_t p0 = *(volatile uint16_t*)PAD0, p1 = *(volatile uint16_t*)PAD1;
	const uint32_t hum = U8(HUMANS) & 3;
	const int mode = S8(MODE), scene = S16(SCENE);
	uint32_t s, nw;
	/* SELECT new presses per pad: the stock free-move after the KO (0x80083568) reads these instead of START */
	s = ((p0 & B_SELECT) ? 1 : 0) | ((p1 & B_SELECT) ? 2 : 0);
	V.sel = (uint8_t)(s & ~V.selprev); V.selprev = (uint8_t)s;
	s = (((p0 & B_START) ? 1 : 0) | ((p1 & B_START) ? 2 : 0)) & hum;
	nw = s & ~V.prev; V.prev = (uint8_t)s;
	if (V.quick && scene == 8 && S8(PHASE) == 8) { U8(QUICK) = 0; V.quick = 0; }   /* the next fight runs */
	if (mode != 1 && mode != 2) { V.latch = 0; return; }
	if (scene == 8) {
		const int ph = S8(PHASE), res = S8(PHASE + 5);
		if (ph < 10 || res == 0) { V.latch = 0; V.ok = 0; V.two = 0; return; }
		if (hum == 3) V.two = 1;                                      /* a two-player match (challenger): stock flow */
		V.ok = mode == 1 && !V.two && hum && res > 0 && (hum >> (res - 1) & 1);   /* a human alone won an arcade match */
		if (nw) V.latch = 1;
		if (!V.latch) {
			/* the notice, as MvC: blinking, centred, low (under the WIN text, which ends at picture y 195), from the frame the
			   K.O. text clears (phase 10 timer 0x168 -> ~0x103; MvC: from its phase 12, right after its K.O.) */
			if (((ph == 10 && S16(PHASE + 6) < NOTICE_T10) || (ph >= 12 && ph <= 16)) && res > 0 && (hum >> (res - 1) & 1) && (*(volatile uint16_t*)VCOUNT & 63) < 35)
				((f_text)TEXT_FN)(notice, NOTICE_X, NOTICE_Y, 8, NOTICE_COL, NOTICE_MODE);
			return;
		}
		if (ph == 12) U16(PHASE + 6) = 0;                            /* the wait before the win poses */
		else if (ph == 14 && !tally_pending()) U16(PHASE + 6) = 0;   /* the bonus is in the score */
		return;
	}
	if (scene == 12) {
		if (nw) V.latch = 1;
		if (!V.latch) return;
		if (S16(SUB) == 0 && S16(SUB3) == 0) {                       /* its first frame: nothing loaded yet */
			if (V.ok && mode == 1 && hum && U8(QUICK) == 0 && *(volatile int32_t*)G(LADDER) < 6) {   /* not into the boss */
				/* straight to the select scene's quick path (what 0x800851e8 and the quote's exit do, minus the quick
				   path's own init 0x80085334, which hangs (DrawSync) when the select screen's assets are not resident):
				   picker / stage / "STAGE n ... NOW LOADING" + the battle load, then the battle */
				U8(QUICK) = 1; V.quick = 1; V.latch = 0;
				U8(0x80042386) = 0; U8(0x8004278f) = 3;
				U8(0x80042a13) = (uint8_t)(hum & 1); U8(0x80042d5b) = (uint8_t)(hum >> 1 & 1);
				U16(SCENE) = 4; U16(SUB) = 0; U16(SUB2) = 0; U16(SUB3) = 0;
				U8(0x800438b9) = 1; U16(0x800438bc) = 2; U16(0x800438be) = 0; U16(0x800438c0) = 0; U16(0x800438c2) = 0;
				((void (*)(void))0x80085260)();                      /* select struct +0xe: the humans */
			}
			return;
		}
		if (S16(SUB) == 2 && S16(SUB2) < 8) U16(SUB2) = 8;           /* (pressed late) quote running: its exit */
		return;
	}
	V.latch = 0;
}

#ifdef ARCBAL
/* ARCADE BALANCE (mktagdisc --arcbal, tools/arcbalpatch.py, docs/BALANCE.md; with it this module is linked at 0x80007880).
   OPTION MODE line 12, ON / OFF for the session (OFF at every boot: BSS).  The game's PS1-mode gates for the meter
   doubling (0x80075144) and the special / super -> super cancel (0x8007d680) read arcbal instead of 0x8004278c
   (always 1), with the branch inverted: arcbal 0 = the 1.3 instructions, same count and cycles. */
uint8_t arcbal;
#define OPT_CURSOR (*(volatile int8_t *)0x80042193u)
#define OPT_ITEM   12
#define PADNOW     ((uint32_t (*)(int))0x8002c8e0u)
#define PADOLD     ((uint32_t (*)(int))0x8002c8f8u)
#define SOUND      ((void (*)(int))0x8004d544u)
/* end of the option screen's label loop (OPDEMO 0x80098c44, a0 = the loop's next y) */
void bal_optdraw(int y) {
	const f_text t = (f_text)TEXT_FN; const int on = arcbal ? 0x30 : 0x33;
	t("ARCADE BALANCE", 0x98, y, 8, OPT_CURSOR == OPT_ITEM ? 0x30 : 0x33, 1);
	t("ON", 0x110, y, 8, on, 1);
	t("OFF", 0x148, y, 8, 0x63 - on, 1);
}
/* replaces the pad call at OPDEMO 0x800994a8: LEFT, RIGHT or CROSS on our line toggles */
uint32_t bal_optinput(int port) {
	const uint32_t now = PADNOW(port);
	if (OPT_CURSOR == OPT_ITEM && (now & ~PADOLD(port) & 0xa040)) { arcbal ^= 1; SOUND(0x84); }
	return now;
}
#endif

void skip_entry(void) {
	tick();
	((void (*)(void))GAME_FN)();
}
