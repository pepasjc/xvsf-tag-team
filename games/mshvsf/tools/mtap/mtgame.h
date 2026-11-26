/* mtgame.h: MSHvSF (SLUS-00793) addresses for common/mtap/mtcore.c (notes: docs/MULTITAP.md "mtap04") */
#define MT_SCENE_V()  S16(0x80070a94u)   /* 0 title / menus, 4 select, 8 battle */
#define MT_SC_MENU    0
#define MT_SC_SELECT  4
#define MT_SC_FIGHT   8
#define CUR           0x80027db4u     /* raw words, current (P1, P2): 0x80023b88 builds them from libpad's buffers */
#define PADW          0x80027d60u     /* P1, P2, or, and */
#define MT_STOCK_UPDATE() ((f_void)0x80023b88)()
#define MT_PORT2_WORD()   U16(CUR + 2)
#define MT_PORT2_OK()     ((f_int)0x80023b04)()
#define MT_WRITE(a, b) do { U16(CUR) = (a); U16(CUR + 2) = (b); U16(PADW) = (a); U16(PADW + 2) = (b); \
                            U16(PADW + 4) = (a) | (b); U16(PADW + 6) = (a) & (b); } while (0)
/* 0x80023b54: disconnected-pad mask; its first two words (addiu sp,sp,-0x18; sw ra,0x14(sp)) are replayed by mt_mask */
#define MT_MASK_AT 0x80023b54
#define MT_MASK_W0 0x27bdffe8
#define MT_MASK_W1 0xafbf0014
/* raw bits R1 + R2 = the default HP + HK keys (tag) */
#define MT_TAGMASK 0x000a

/* the side's second character on point: select = picks made (side struct +2); fight = partner object active and
   not (main active and partner benched +0x263) */
#ifdef MT_VSCPU
extern uint8_t mt_ssec;
#define MT_SEL_SECOND(s)  (S8(0x80071af4u + (s) * 0x2c + 2) > 0)
MT_PSFN int MT_POINT_SECOND(int s, int sc) {
	uint32_t a = 0x80070b50u + s * 0x3c0, b = s ? 0x800716c8u : 0x80071310u;
	if (sc != MT_SC_FIGHT) return mt_ssec >> s & 1;
	if (!U8(b) || U16(b + 4) != 2) return 0;
	return !(U8(a) && U16(a + 4) == 2 && U8(b + 0x263));
}
#else
static inline int MT_POINT_SECOND(int s, int sc) {
	uint32_t a = 0x80070b50u + s * 0x3c0, b = s ? 0x800716c8u : 0x80071310u;
	if (sc == MT_SC_SELECT) return S8(0x80071af4u + s * 0x2c + 2) > 0;
	if (sc != MT_SC_FIGHT || !U8(b) || U16(b + 4) != 2) return 0;
	return !(U8(a) && U16(a + 4) == 2 && U8(b + 0x263));
}
#endif

/* ---- vs CPU (MT_VSCPU, mktag --vscpu; research work/vscpu_xvmsh.md) */
#define MT_VERSUS()       (U8(0x800250acu) == 1)      /* mode 0x800250ac: 0 arcade, 1 versus, 2 training */
#define MT_PORT1_WORD()   U16(CUR)
#define MT_PORT1_OK()     ((f_int)0x80023ab4)()
#define MT_PORT1_OK_FN    0x80023ab4
#define MT_OBJ(k)         ((k) == 0 ? 0x80070b50u : (k) == 1 ? 0x80070f10u : (k) == 2 ? 0x80071310u : 0x800716c8u)
#define MT_SET_HUMAN(k, h) (U8(MT_OBJ(k) + 3) = (uint8_t)(h))
/* select main 0x8009513c (SEL.ARC entry 0 = SELECT.BIN code at 0x80094800, called from EXE 0x8004e898): its
   `jal 0x800a3050` at 0x80095168 (SEL.ARC +0x994) runs every select frame -> jal vs_selmain.  (The state handlers are
   a 3-word table at 0x80094804, copied to the stack: [2] = 0x80095c94 select running only.) */
#define MT_SELMAIN        0x800a3050u
#define MT_SELMAIN_JAL    0x80095168u
#define MT_SIDE_DONE(s)   (U8(0x80071ad4u) >> (s) & 1)
/* text 0x80022e20(text, x << 16 | y, advance << 24 | colour << 16 | 1); screen ~ (x - 0x40, y - 8) */
#define MT_PRINT(s, x, y) ((void (*)(const char *, uint32_t, uint32_t))0x80022e20u)((s), (uint32_t)((x) + 0x40) << 16 | ((y) + 8), 8u << 24 | 0x26u << 16 | 1)
#define MT_PANEL_X0 8
#define MT_PANEL_X1 176
#define MT_PANEL_Y  16
/* AI level 0x80070b41 (0..31); VERSUS: not updated (0x8002d63c skips humans == 3); the stock VS COM rule
   0x8002e618 = difficulty 0x8002506c * 4 */
#define MT_AI_LEVEL()     (U8(0x80070b41u) = (uint8_t)(U8(0x8002506cu) * 4))
