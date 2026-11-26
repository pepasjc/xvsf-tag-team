/* mtgame.h: MvC (SLUS-01059) addresses for common/mtap/mtcore.c (evidence: games/mvc/work/mtap/mvc_padmap.md).
   Same Capcom framework as MSHvSF, but the per-frame builder 0x80024c40 ends with the key mapper call
   (0x80024d44 jal 0x8002489c: raw words -> game pads 0x80085040[4] through the key config 0x80028810), so
   the hook is that mapper call: mt_tick writes our raw words first, then runs the mapper once (MT_AFTER). */
#define MT_SCENE_V()  S16(0x8007bdccu)   /* 0 title / menus, 4 select, 8 battle (scene table 0x80071494[sc/4]) */
#define MT_SC_MENU    0
#define MT_SC_SELECT  4
#define MT_SC_FIGHT   8
#define CUR           0x800287b0u     /* raw words, current P1, P2 (+4/+6 = slots 3/4, always 0); previous 0x80028808 */
#define GPAD          0x80085040u     /* mapped game pads [4]; previous frame 0x80085030 [4] */
/* hook: 0x80024d44 `jal 0x8002489c` (stock word 0x0c009227) -> jal mt_tick (inside the builder 0x80024c40, which is
   called from the main loop 0x80022f84 and from the wait loop 0x800242c4).  Not patched by rc4.3. */
#define MT_HOOK_AT    0x80024d44
#define MT_HOOK_W     0x0c009227
#define MT_STOCK_UPDATE() ((void)0)                /* the builder already ran (we are its last call) */
#define MT_AFTER()        ((f_void)0x8002489c)()  /* key mapper: raw words -> game pads */
#define MT_PORT2_WORD()   U16(CUR + 2)
#define MT_PORT2_OK()     ((f_int)0x80024bb8)()
#define MT_WRITE(a, b) do { U16(CUR) = (a); U16(CUR + 2) = (b); } while (0)
/* 0x80024c08: disconnected-pad mask (bit 0 port 1, bit 1 port 2); callers: main menu OPDEMO 0x800a2bb4 (VERSUS is
   skipped while the mask is not 0), battle pause 0x80029e7c.  First two words replayed by mt_mask. */
#define MT_MASK_AT 0x80024c08
#define MT_MASK_W0 0x27bdffe8           /* addiu sp,sp,-0x18 */
#define MT_MASK_W1 0xafbf0014           /* sw ra,0x14(sp) */
/* raw bits R1 + R2 = the default HP + HK keys (key config 0x0040 / 0x0400, native tag mask 0x440) */
#define MT_TAGMASK 0x000a
/* START 0x0800 and directions 0xf000: mtcore defaults */

/* the side's second character on point (only for a human side, human bits 0x8007bdc9):
   select = picks made (byte 0x8007cfae side 1, 0x8007cfc8 side 2); fight = partner object active (+0), normal
   state (+4 == 2) and not benched (+0x2a3 == 0).  The tag and the KO hand-over set the leaving member's +0x2a3. */
#ifdef MT_VSCPU
/* (vs CPU builds) select: mt_ssec bit s, set by mt_select from MT_SEL_SECOND */
extern uint8_t mt_ssec;
#define MT_SEL_SECOND(s)  (S8(0x8007cfaeu + (s) * 0x1a) > 0)
MT_PSFN int MT_POINT_SECOND(int s, int sc) {
	uint32_t p = s ? 0x8007caf8u : 0x8007c6f0u;
	if (sc != MT_SC_FIGHT) return mt_ssec >> s & 1;
	return U8(p) && U16(p + 4) == 2 && !U8(p + 0x2a3);
}
#else
MT_PSFN int MT_POINT_SECOND(int s, int sc) {
	uint32_t p = s ? 0x8007caf8u : 0x8007c6f0u;
#ifndef MT_VSCPU
	if (!(U8(0x8007bdc9u) >> s & 1)) return 0;
#endif
	if (sc == MT_SC_SELECT) return S8(0x8007cfaeu + s * 0x1a) > 0;
	if (sc != MT_SC_FIGHT) return 0;
	return U8(p) && U16(p + 4) == 2 && !U8(p + 0x2a3);
}
#endif

/* ---- vs CPU (MT_VSCPU, mktag --vscpu) */
#define MT_VERSUS()       (U8(0x8007b740u) == 1)      /* mode: 0 BATTLE, 1 VERSUS, 2 CROSS OVER, 3 TRAINING */
#define MT_PORT1_WORD()   U16(CUR)
#define MT_PORT1_OK()     ((f_int)0x80024b68)()
#define MT_PORT1_OK_FN    0x80024b68
/* seat k (0 P1 first / 1 P2 first / 2 P1 second / 3 P2 second) -> its object's +3: 1 human, 0 the AI drives it */
#define MT_OBJ(k)         ((k) == 0 ? 0x8007be90u : (k) == 1 ? 0x8007c2a0u : (k) == 2 ? 0x8007c6f0u : 0x8007caf8u)
#define MT_SET_HUMAN(k, h) (U8(MT_OBJ(k) + 3) = (uint8_t)(h))
/* select (games/mvc/work/vscpu/select_re.md): SEL01 at 0x8018dcec, select main 0x8018e948 reached through the SEL01
   table word 0x801b017c (patched in the SEL01 copy to vs_selmain); side done bits 0x8007cf84 (bit 0 side 1, bit 1 side 2) */
#define MT_SELMAIN        0x8018e948u
#define MT_SELMAIN_PTR    0x801b017cu
#define MT_SIDE_DONE(s)   (U8(0x8007cf84u) >> (s) & 1)
/* text: 0x80020f10(text, x << 16 | y, advance << 24 | colour << 16 | kind << 13 | layer); screen = (x - 0x40, y - 8);
   kind 0 = 8x8 ASCII font, colour 0x24 light cyan */
#define MT_PRINT(s, x, y) ((void (*)(const char *, uint32_t, uint32_t))0x80020f10u)((s), (uint32_t)((x) + 0x40) << 16 | ((y) + 8), 8u << 24 | 0x24u << 16 | 1)
#define MT_PANEL_X0 8
#define MT_PANEL_X1 176
#define MT_PANEL_Y  14
/* AI strength (0..31, nothing sets it in VERSUS): difficulty option 0x8007b71c x 4, as the stock VS COM option does */
#define MT_AI_LEVEL()     (U8(0x8007be81u) = (uint8_t)(U8(0x8007b71cu) * 4))

