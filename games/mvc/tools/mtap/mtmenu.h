/* mtmenu.h (MvC, included by common/mtap/mtcore.c with MT_VSMENU; mktag --vscpu without --mtap): main-menu row VERSUS
   CPU right below VERSUS.  The 8-line menu (BATTLE VERSUS VERSUS-CPU TRAINING GALLERY ACHIEVEMENTS OPTION EX-OPTIONS)
   is written by the achievements menu module (tools/ach/mvcach.menu_patch); its confirm path (OPDEMO 0x800a2d50..)
   calls mt_vsconf(cursor) for the new state: rows below VERSUS CPU = cursor + 1, VERSUS CPU -> state 2 (VERSUS) with
   mt_vsmode = the confirming pad + 1 (OPDEMO wrote the pad index 0 / 1 to menu +0x59 = 0x8007b741 the same frame), rows
   from TRAINING on = cursor (the stock state table, unchanged).  mt_select seats that pad's side human, the other CPU. */
int mt_vsconf(int c) {
	mt_vsmode = 0;
	if (c < 2) return c + 1;
	if (c == 2) { mt_vsmode = (uint8_t)((U8(0x8007b741u) & 1) + 1); return 2; }
	return c;
}

/* Lean resident select part (MT_OWN_SELECT: replaces common/mtap/mtvsui.c's mt_select for MvC).  rc4.14 kept the select
   module in place in SEL01 0x801ed180: those bytes are the VS screen's bottom-left background texture, uploaded to VRAM
   when the select starts -> a garbage line under NOW LOADING (rc4.15 VS-screen glitch).  Now nothing of ours is in SEL01.
   Same seat rule as mtvsui.c with MT_VSMENU: mt_vsmode side = its pad, the other side CPU; the human picks the CPU team
   once its own side is done; AI level = difficulty x 4.  Normal VERSUS / other modes: custom 0 = stock words. */
__asm__(".section .text.vs_magic,\"ax\"\n.globl vs_magic\nvs_magic:\n.word 0x55505356\n.previous\n");   /* (always there) */
void mt_select(void) {
	struct mtv *m = &V;
	int h = mt_vsmode && MT_VERSUS() ? mt_vsmode - 1 : -1, c, q;
	if (!m->vsinit) {
		m->vsinit = 1; m->owner[0] = m->owner[1] = 0xff;
		for (c = 0; c < 4; c++) {
			m->src[c] = (uint8_t)(c >= 2 ? SEAT_TAG : h < 0 || c == h ? c : SEAT_CPU);
			m->eff[c] = (uint8_t)(h < 0 || (c & 1) == h ? (c & 1) : SEAT_CPU);
		}
		m->custom = (uint8_t)(h < 0 ? 0 : 3);
	}
	if (!m->custom) return;
	h = m->eff[0] == SEAT_CPU;                          /* the human's side */
	mt_ssec = (uint8_t)(MT_SEL_SECOND(0) | MT_SEL_SECOND(1) << 1);
	q = MT_SIDE_DONE(h) ? h : 6;                        /* the CPU side: its picks by the human once its own are done */
	for (c = 0; c < 4; c++) m->seff[c] = (uint8_t)((c & 1) == h ? h : q);
	MT_AI_LEVEL();
}
