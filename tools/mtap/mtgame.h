/* mtgame.h: XvSF (SLUS-00627, tag hack 1.4) addresses for common/mtap/mtcore.c (evidence: work/mtap/xvsf_padmap.md)

   Pads: BIOS pad driver (libapi InitPAD(0x80060aa0, 12, 0x80060ac8, 12) + StartPAD at 0x80054e40 / 0x80054e48), not
   libpad: the kernel routine sends 01 42 00 (3rd byte 00, kernel RAM 0x800046ec).  Its buffers are turned into the raw
   words once per frame by 0x8002c72c, called from 0x8002c968 inside 0x8002c960 (key-config mapping right after it),
   which the present routine calls after VSync (0x80028bac stock, 0x80028ba0 in 1.4). */
#define MT_SCENE_V()  S16(0x80042774u)   /* 0 boot / title / menus, 4 select (versus / arcade grid), 8 battle */
#define MT_SC_MENU    0
#define MT_SC_SELECT  4
#define MT_SC_FIGHT   8
#define CUR           0x80043984u     /* raw words, current (P1, P2) = ~(byte2 << 8 | byte3), 0 when not a digital pad */
#define PADW          0x8004c2b0u     /* P1, P2, or, and (0x8002c8e0(n) reads PADW[n]); +8 = disconnected mask */
/* hook: 0x8002c968 `jal 0x8002c72c` (0x0c00b1cb, delay slot nop) -> jal mt_tick; stock in x14_c1 */
#define MT_HOOK_AT    0x8002c968
#define MT_HOOK_WORD  0x0c00b1cb
#define MT_STOCK_UPDATE() ((f_void)0x8002c72c)()
#define MT_PORT2_WORD()   U16(CUR + 2)
#define MT_PORT2_OK()     (!(U16(PADW + 8) & 2))   /* mask bit 1: port 2 status != 0 or type != 4 (fresh: set by the update) */
/* previous-frame words (0x8004c578/a, 0x800420d0..d6) are built by the stock update from CUR: not written here */
#define MT_WRITE(a, b) do { U16(CUR) = (a); U16(CUR + 2) = (b); U16(PADW) = (a); U16(PADW + 2) = (b); \
                            U16(PADW + 4) = (a) | (b); U16(PADW + 6) = (a) & (b); } while (0)
/* 0x8002c70c(n) = 0x8002c8e0(n) = PADW[n]; all 5 callers pass n = 4 = the disconnected mask 0x8004c2b8 (bit 0 port 1,
   bit 1 port 2): main menu VERSUS skip (OPDEMO 0x8009889c / 0x80098908 / 0x80098974) and the fight's unplugged-pad
   pause (0x8002a440 / 0x8002a4a0).  First two words (addiu sp,sp,-0x18; sw ra,0x10(sp)) are replayed by mt_mask. */
#define MT_MASK_AT 0x8002c70c
#define MT_MASK_W0 0x27bdffe8
#define MT_MASK_W1 0xafbf0010
/* raw bits R2 (0x02) + R1 (0x08) = HK + HP in the 1.4 default key table 0x8003d8f8 (padpatch: R1 = HP, R2 = HK) = tag */
#define MT_TAGMASK 0x000a
/* MT_START 0x0800 / MT_DIRS 0xf000: same raw layout as MSHvSF (core defaults) */

/* the side's second character on point: select = side state 0x800438d4 + s * 0x24 (1 first pick, 2 its confirm
   animation, 3 second pick, 4 its confirm, 5 done; Beetle trace work/mtap/xvdbg.py); fight = the point object (P1 0x80042a10 / P2 0x80042d58, always the active one) holds the second pick:
   +0x230 is exchanged by the swap with the char id, so it is 1 after a tag and after a KO hand-over */
#define MT_MAIN(s)  ((s) ? 0x80042d58u : 0x80042a10u)
#define MT_PART(s)  ((s) ? 0x800434b8u : 0x80043178u)
#ifdef MT_VSCPU
extern uint8_t mt_ssec;
/* select: side state 0x800438d4 + s * 0x24 (1 first cursor, 2 its confirm, 3 second cursor, 4 its confirm, 5 option
   row, 6, 7 done); mt_ssec bit s set by mt_select */
#define MT_SEL_SECOND(s)  (U8(0x800438d4u + (s) * 0x24) >= 3)
MT_PSFN int MT_POINT_SECOND(int s, int sc) {
	if (sc != MT_SC_FIGHT) return mt_ssec >> s & 1;
	return U8(MT_MAIN(s) + 0x230) != 0;
}
#else
static inline int MT_POINT_SECOND(int s, int sc) {
	if (sc == MT_SC_SELECT) return U8(0x800438d4u + s * 0x24) >= 3;
	if (sc != MT_SC_FIGHT) return 0;
	return U8((s ? 0x80042d58u : 0x80042a10u) + 0x230) != 0;
}
#endif

/* ---- vs CPU (MT_VSCPU, mktagdisc --vscpu; research work/vscpu_xvmsh.md) */
#define MT_VERSUS()       (U8(0x8004218cu) == 2)      /* mode: 1 arcade, 2 versus, 3 training, 4 survival */
#define MT_PORT1_WORD()   U16(CUR)
#define MT_MASK_V()       (U16(PADW + 8) & 1)
#define MT_MASK_RAW()     U16(PADW + 8)               /* (--vsmenu: the stock mask = PADW[4], all callers pass 4) */         /* (no port-1 test function in XvSF: the builder's mask bit 0) */
/* seat k's object: the swap keeps the point character in the MAIN object (exchanges char / +0x230, never +3), so seat k
   is in the main object while it is on point: main +3 = human(seat on point), partner +3 = human(the other seat) */
#define MT_OBJ(k)  ((((k) >= 2) == (U8(MT_MAIN((k) & 1) + 0x230) != 0)) ? MT_MAIN((k) & 1) : MT_PART((k) & 1))
/* select (SELECT.BIN at 0x80098000): `jal 0x8009e4a8` at 0x8009c260 runs every select frame after the frame begin ->
   jal vs_selmain (in the SELECT.BIN copy) */
#define MT_SELMAIN        0x8009e4a8u
#define MT_SIDE_DONE(s)   (U8(0x800438c6u) >> (s) & 1)
/* text 0x8002d79c(text, x, y, advance, colour, 1): x = picture x + 76, y = picture y + 9; <= 66 sprites a frame */
#define MT_PRINT(s, x, y) ((void (*)(const char *, int, int, int, int, int))0x8002d79cu)((s), (x) + 76, (y) + 9, 8, 0x33, 1)
#define MT_PANEL_X0 8
#define MT_PANEL_X1 176
#define MT_PANEL_Y  12
/* AI rank: s16 0x80042a02 (0..31, the CPU brain reads it; VERSUS never sets it) = difficulty option 0x800421a4 x 4 */
#define MT_AI_LEVEL()     (U16(0x80042a02u) = (uint16_t)(U8(0x800421a4u) * 4))
