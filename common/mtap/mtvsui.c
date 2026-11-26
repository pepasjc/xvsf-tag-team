/* mtvsui.c (included by mtcore.c with MT_VSCPU): everything the character select needs - session seats, multitap
   joins, the seat setup and its panel.  Placed in the select overlay's spare bytes (in RAM only while the select runs);
   mt_tick calls mt_select() on the select scene when vs_magic is there.

   Seats: 0 P1 (side 1 first character), 1 P2 (side 2 first), 2 P3 (side 1 second), 3 P4 (side 2 second).
   Session start (first select frame after the menus): P1 = controller 1; P2 = controller 2, or CPU in VERSUS when port 2
   is empty (multitap: slot B empty too); P3 / P4 = TAG (the side's first player plays both characters, stock).
   Multitap: P3 / P4 join their seat with START (as mtap04).
   VERSUS setup panel (top of the select, always shown in VERSUS):   P1 1P  P3 TAG          P2 CPU  P4 TAG
   A human presses MT_SETUP_BTN (L2) -> setup for that controller: LEFT / RIGHT = side, UP / DOWN = first / second seat,
   CROSS = cycle the seat: first seats CPU <-> this controller, second seats TAG -> CPU -> this controller -> TAG; taking
   a seat frees the one the controller had (a first seat becomes CPU, a second seat TAG).  L2 / START = done.  While in setup the
   controller's buttons do not reach the select (route_v). */
#ifndef MT_SETUP_BTN
#define MT_SETUP_BTN 0x0001            /* raw L2 */
#endif
#define B_UP    0x1000
#define B_RIGHT 0x2000
#define B_DOWN  0x4000
#define B_LEFT  0x8000
#define B_CROSS 0x0040

#define UI __attribute__((section(".text.vsui")))
/* vs_magic = the module's FIRST word (loads that overwrite the module come from below: they hit it first) */
__asm__(".section .text.vsui,\"ax\"\n.globl vs_magic\nvs_magic:\n.word 0x55505356\n.previous\n");   /* = VS_MAGIC */
static const char vnames[6][4] __attribute__((section(".rodata.vsui"))) = { "1P", "2P", "3P", "4P", "TAG", "CPU" };
static char vbuf[20] __attribute__((section(".bss.vsui")));   /* 2 x ("x" "Pn " NAME " ") + NUL = 17 */
/* the .kc code (resident in kernel RAM, used in fights): source here in the overlay, destination, words - filled in by
   mtpatch after the link; copied once (the kernel span is never written by anything else, so it stays) */
uint32_t vs_kc[3] __attribute__((section(".rodata.vsui.kc"))) = { 0, 0, 0 };

#ifndef MT_VSMENU
UI static void vs_cycle(int k, int c) {
	int v = V.src[k], n, i;
	if (k >= 2) n = v == SEAT_TAG ? SEAT_CPU : v == SEAT_CPU ? c : SEAT_TAG;   /* second: TAG -> CPU -> you -> TAG */
	else n = v == SEAT_CPU ? c : SEAT_CPU;                                  /* first: CPU <-> you */
	if (n == c)
		for (i = 0; i < 4; i++) if (V.src[i] == c) V.src[i] = (uint8_t)(i >= 2 ? SEAT_TAG : SEAT_CPU);
	V.src[k] = (uint8_t)n;
}

UI static void vs_line(int s, int x) {             /* "P1 1P  P3 TAG" for side s (cursor mark '>' in the setup) */
	char *p = vbuf; int r, k; const char *q;
	for (r = 0; r < 2; r++) {
		k = s + 2 * r;
		*p++ = (V.edit && V.edit < 5 && V.cur == k) ? '>' : ' ';
		*p++ = 'P'; *p++ = (char)('1' + k); *p++ = ' ';
		for (q = vnames[V.src[k]]; *q; ) *p++ = *q++;
		*p++ = ' ';
	}
	*p = 0;
	MT_PRINT(vbuf, x, MT_PANEL_Y);
}
#endif

UI void mt_select(void) {
	struct mtv *m = &V;
	uint8_t *src = m->src, *eff = m->eff;
	int c, k, j = 0, f = 0, vs = MT_VERSUS(), p[2];
	{ const uint32_t *a = (const uint32_t *)vs_kc[0]; uint32_t *b = (uint32_t *)vs_kc[1];
	  for (c = vs_kc[2]; c > 0; c--) *b++ = *a++; }
	if (!m->vsinit) {
		m->vsinit = 1; m->edit = 0; m->owner[0] = m->owner[1] = 0xff;
#ifdef MT_VSMENU         /* the menu row chose the seats: the human's side = its pad, the other side = CPU */
		src[0] = (uint8_t)(vs && mt_vsmode == 2 ? SEAT_CPU : 0); src[1] = (uint8_t)(vs && mt_vsmode == 1 ? SEAT_CPU : 1);
#else
		/* P2 = a human only when someone is there: multitap slot B answers (mt_rx[12] = its 0x5a) or a pad in port 2 */
		src[0] = 0; src[1] = (uint8_t)(((m->act && mt_rx[12] == 0x5a) || MT_PORT2_OK() || !vs) ? 1 : SEAT_CPU);
#endif
		src[2] = src[3] = SEAT_TAG;
	}
#ifndef MT_VSMENU        /* (no joins, no setup panel) */
	for (c = 0; c < 4; c++) {
		uint16_t nw = m->ctl[c] & ~m->pctl[c];
		m->pctl[c] = m->ctl[c];
		if (c >= 2) {
			if (!m->act) break;
			if (src[c] == SEAT_TAG && (nw & MT_START) && !(m->join >> c & 1)) { src[c] = (uint8_t)c; continue; }   /* join */
		}
		if (!vs) continue;
		if (!m->edit) {
			if (nw & MT_SETUP_BTN) {
				m->edit = (uint8_t)(c + 1); m->cur = 0;
				for (k = 3; k >= 0; k--) if (src[k] == c) m->cur = (uint8_t)k;
			}
		} else if (m->edit == c + 5) {                 /* leaving: swallowed until all its buttons are up (the */
			if (!m->ctl[c]) m->edit = 0;               /* exit press must not reach the select: L2 picks in MvC) */
		} else if (m->edit == c + 1) {
			if (nw & (MT_SETUP_BTN | MT_START)) m->edit = (uint8_t)(c + 5);
			if (nw & (B_LEFT | B_RIGHT)) m->cur ^= 1;
			if (nw & (B_UP | B_DOWN)) m->cur ^= 2;
			if (nw & B_CROSS) vs_cycle(m->cur, c);
		}
	}
#endif
	for (c = 0; c < 4; c++) {
		int v = src[c];
		eff[c] = (uint8_t)(v == SEAT_TAG ? src[c & 1] : v);
		if (v >= 2 && v < 4) j |= 1 << v;
		if (v == SEAT_CPU) f |= 2;
		if (v != (c < 2 ? c : SEAT_TAG)) f |= 1;
	}
	m->join = (uint8_t)j;
	(void)j;
#ifdef MT_SEL_SECOND
	mt_ssec = (uint8_t)(MT_SEL_SECOND(0) | MT_SEL_SECOND(1) << 1);
#endif
	for (c = 0; c < 2; c++) { int a = eff[c], b = eff[c + 2]; p[c] = human(a) ? a : human(b) ? b : -1; }
	for (c = 0; c < 4; c++) {                          /* select: a human picks for a CPU seat (own side first; the */
		int v = eff[c], s = c & 1, q = p[s];           /* other side's human only once that side's picks are done) */
		if (q < 0) q = MT_SIDE_DONE(s ^ 1) ? p[s ^ 1] : 6;
		m->seff[c] = (uint8_t)(human(v) ? v : q < 0 ? 0 : q);
	}
	if (m->edit) { m->ctl[(m->edit - 1) & 3] = 0; f |= 1; }  /* the controller in the setup: not the game's */
	m->custom = (uint8_t)f;
#ifdef MT_AI_LEVEL
	if (f & 2) MT_AI_LEVEL();                       /* the AI's strength (nothing resets it in VERSUS) */
#endif
}

#ifndef MT_VSMENU
/* select main (table word MT_SELMAIN_PTR in the SEL01 copy points here): the stock routine, then the panel (after the
   frame begin, so the text is presented) */
UI void vs_draw(void) { if (MT_VERSUS() && V.vsinit) { vs_line(0, MT_PANEL_X0); vs_line(1, MT_PANEL_X1); } }
/* vs_selmain: draw the panel, then TAIL-jump to the stock routine with its args, ra and the caller's stack untouched
   (a wrapper frame broke the ARCADE stage screen, which runs the same routine) */
__asm__(".section .text.vsui,\"ax\"\n.set noreorder\n.globl vs_selmain\nvs_selmain:\n"
	"	addiu $sp, $sp, -40\n	sw $ra, 36($sp)\n	sw $a0, 16($sp)\n	sw $a1, 20($sp)\n	sw $a2, 24($sp)\n"
	"	jal vs_draw\n	sw $a3, 28($sp)\n"
	"	lw $ra, 36($sp)\n	lw $a0, 16($sp)\n	lw $a1, 20($sp)\n	lw $a2, 24($sp)\n	lw $a3, 28($sp)\n"
	"	j " STR(MT_SELMAIN) "\n	addiu $sp, $sp, 40\n.set reorder\n.previous\n");
#endif
