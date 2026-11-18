/* port.h: MSHvSF (SLUS-00793) side of the built-in achievements (tools/ach/ach.c).  Addresses: docs/ACHIEVEMENTS.md */
#pragma once
#include <stdint.h>

/* hooks (tools/ach/mshach.py patches the calls; the runtime makes the replaced call itself) */
#define IDLE_PREV  0x80010be4u            /* DrawSync(0): the call at 0x800208d4 in present 0x800208c8 */
#define FRAME_PREV 0x80022864u            /* frame begin (ClearOTag x3): the call at 0x80020c64 in the main frame routine */
typedef void (*f_v4)(uint32_t, uint32_t, uint32_t, uint32_t);
typedef void (*f_print)(const char*, uint32_t, uint32_t);
typedef void (*f_1)(uint32_t);
#define PRINT_FN   0x80022e20u            /* (text, x << 16 | y, advance << 24 | colour << 16 | 1) */
#define SFX_FN     0x8007b2ccu            /* (id): 0x84 cursor, 0x91 confirm, 0x82 cancel */

#define PORT_FILE "BASLUS-00793ACH"
void port_derive(void);
void port_text(const char* s, int x, int y, int col);
void port_popup(const char* head, const char* line, int first);
int port_card_safe(void);
int port_card_idle(void);
#define ACH_FRAME_ARGS uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3
#define ACH_IDLE_ARGS  uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3
#define PORT_FRAME_PREV()  ((f_v4)FRAME_PREV)(a0, a1, a2, a3)
#define PORT_IDLE_PREV()   ((f_v4)IDLE_PREV)(a0, a1, a2, a3)
#define PORT_TEXT(s, x, y, c) port_text((s), (x), (y), (c))
#define PORT_POPUP(h, l, f) port_popup((h), (l), (f))
#define PORT_POPUP_OK()    1
#define PORT_CARD_SAFE()   port_card_safe()
#define PORT_CARD_IDLE()   port_card_idle()
#define PORT_SFX_UNLOCK()  ((f_1)SFX_FN)(0x91)
#define PORT_SFX_CONFIRM() ((f_1)SFX_FN)(0x91)
#define PORT_SFX_CURSOR()  ((f_1)SFX_FN)(0x84)
#define PORT_SFX_CANCEL()  ((f_1)SFX_FN)(0x82)
/* pad 1: new presses (now & ~before); bit layout of the game's pad words */
#define PORT_PAD_NEW() ((uint16_t)(*(volatile uint16_t*)0x80027d60u & ~*(volatile uint16_t*)0x80027db8u))
#define PORT_B_UP    0x1000
#define PORT_B_RIGHT 0x2000
#define PORT_B_DOWN  0x4000
#define PORT_B_LEFT  0x8000
#define PORT_B_BACK  0x0030               /* triangle, circle */
#define PORT_COL_HEAD 0x23               /* the main menu's colours: 0x20 cursor line, 0x23 other lines, 0x22 dim */
#define PORT_COL_ON   0x23
#define PORT_COL_OFF  0x22
#define PORT_COL_SEL  0x20
#define PAGE_INFO_TITLE
#define PAGE_COLS  43                     /* 344 pixels: >= 16 inside the 384-pixel picture on each side */
#define PAGE_X     0x50                   /* the routine's x: picture x + 47 (picture x 33 = 25 in a 400-wide capture) */
#define PAGE_Y     0x24                   /* >= 12 lines below the picture top (measured: the routine y = capture y + 13) */
#define PAGE_LINE  9
#define PAGE_ROWS  12
#define PAGE_DESC  4
void port_ovl(void);
#define PORT_FRAME_EXTRA() port_ovl()
#define PORT_NOTICE_OK() (*(volatile int16_t*)0x80070a94u != 0)     /* card notice: not on scene 0 (title, legal, attract, menu share it): the first scene after the menu */
