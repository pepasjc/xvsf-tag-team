/* mshskip.c: START skips the end of a match - Marvel Super Heroes vs. Street Fighter (mshskip.py builds it; notes in
   docs/ENGINE_NOTES.md "START skip").  Linked at BASE (kernel RAM); entry skip_entry replaces `jalr v0` at 0x800515d0
   (the per-frame scene dispatch: v0 = the scene handler). */
#include <stdint.h>
#define U8(a)  (*(volatile uint8_t*)(a))
#define S8(a)  (*(volatile int8_t*)(a))
#define U16(a) (*(volatile uint16_t*)(a))
#define S16(a) (*(volatile int16_t*)(a))

#define MODE    0x800250acu      /* 0 arcade, 1 versus, 2 training, 5 hero battle */
#define QUICK   0x80025070u      /* the game's own quick path: scene 12 without the quote (0x80058270), the map scene
                                    without the map (0x8004e8a8: next opponent / stage picked, straight to the battle load) */
#define HUMANS  0x80070a91u
#define SCENE   0x80070a94u      /* 4 map / select, 8 battle, 12 after-match, 16 continue, 28 ending */
#define QSTATE  0x80070a96u      /* quote overlay state (exit 0x0e) */
#define QSTATE2 0x80070a98u
#define SUB12   0x80071ad2u      /* scene 12: 0 = first frame (loads), 1 = quote overlay running */
#define PHASE   0x80070778u      /* +0 phase, +5 result (1 / 2 = winner side + 1), +6 s16 timer */
#define PAD0    0x80027d60u
#define PAD1    0x80027d62u
#define VCOUNT  VCOUNT_ADDR
#define PRINT   0x80022e20u      /* (text, x << 16 | y, advance << 24 | colour << 16 | 1) */
#define B_START 0x0800

typedef void (*f_print)(const char*, uint32_t, uint32_t);

struct vars { uint8_t prev, latch, ok, quick, two; };
struct vars V;                   /* (BSS: the boot copy zeroes the whole area) */

static const char notice[] = "PRESS START BUTTON TO SHORT CUT";      /* MvC's text (SLUS_010.59 0x80028ad8) */

void tick(void) {
	const uint32_t p0 = U16(PAD0), p1 = U16(PAD1);
	const uint32_t hum = U8(HUMANS) & 3;
	const int mode = S8(MODE), scene = S16(SCENE);
	uint32_t s = (((p0 & B_START) ? 1 : 0) | ((p1 & B_START) ? 2 : 0)) & hum, nw = s & ~V.prev;
	V.prev = (uint8_t)s;
	if (V.quick && scene == 8 && S8(PHASE) == 8) { U8(QUICK) = 0; V.quick = 0; }   /* the next fight runs */
	if (mode != 0 && mode != 1) { V.latch = 0; return; }
	if (scene == 8) {
		const int ph = S8(PHASE), res = S8(PHASE + 5);
		const int won = res > 0 && (hum >> (res - 1) & 1);
		if (ph < 10 || res == 0) { V.latch = 0; V.ok = 0; V.two = 0; return; }
		if (hum == 3) V.two = 1;                                      /* a two-player match (challenger): stock flow */
		V.ok = mode == 0 && !V.two && won;                          /* a human alone won an arcade match */
		if (nw) V.latch = 1;
		if (!V.latch) {
			/* the notice, as MvC: blinking, centred, low; from phase 12 (the K.O. text is gone; the WIN text is high up) */
			if (ph >= 12 && ph <= 16 && won && (U16(VCOUNT) & 63) < 35)
				((f_print)PRINT)(notice, (uint32_t)NOTICE_X << 16 | NOTICE_Y, 8u << 24 | (uint32_t)NOTICE_COL << 16 | 1);
			return;
		}
		if (ph == 12) U16(PHASE + 6) = 0;                            /* win pose */
		else if (ph == 14 && S16(PHASE + 6) < 0x35) U16(PHASE + 6) = 0;   /* the tally put the bonus in the score at 0x36 */
		return;
	}
	if (scene == 12) {
		if (nw) V.latch = 1;
		if (!V.latch || !V.ok || U8(QUICK)) return;
		if (S16(SUB12) == 0) {                                       /* its first frame: nothing loaded yet */
			if (hum) { U8(QUICK) = 1; V.quick = 1; V.latch = 0; }
			return;
		}
		if (S16(QSTATE) < 0x0e) { U16(QSTATE2) = 0; U16(QSTATE) = 0x0e; }   /* (pressed late) quote running: its exit */
		return;
	}
	V.latch = 0;
}

__asm__(
	".section .text.skip_entry,\"ax\"\n"
	".set noreorder\n"
	".globl skip_entry\n"
	"skip_entry:\n"
	"	addiu $sp, $sp, -24\n"
	"	sw $ra, 16($sp)\n"
	"	jal tick\n"
	"	sw $v0, 20($sp)\n"
	"	lw $t0, 20($sp)\n"
	"	lw $ra, 16($sp)\n"
	"	jr $t0\n"
	"	addiu $sp, $sp, 24\n"
	".set reorder\n");
