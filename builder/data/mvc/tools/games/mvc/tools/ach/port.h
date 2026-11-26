/* port.h: MvC (SLUS-01059) side of the built-in achievements (tools/ach/ach.c).  Addresses: docs/ACHIEVEMENTS.md */
#pragma once
#include <stdint.h>

/* hooks (tools/ach/mshach.py patches the calls; the runtime makes the replaced call itself) */
#define IDLE_PREV  0x80011864u            /* DrawSync(0): the call at 0x80022a18 in present 0x80022a0c */
#define FRAME_PREV 0x8002097cu            /* frame begin (ClearOTag x3): the call at 0x80022fe8 in the main frame routine 0x80022f3c */
typedef void (*f_v4)(uint32_t, uint32_t, uint32_t, uint32_t);
typedef void (*f_print)(const char*, uint32_t, uint32_t);
typedef void (*f_1)(uint32_t);
#define PRINT_FN   0x80020f10u            /* (text, x << 16 | y, advance << 24 | colour << 16 | 1) */
#define SFX_FN     0x80085a7cu            /* (id): 0 = the menu cursor sound */

#define PORT_FILE "BASLUS-01059ACH"
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
#define PORT_SFX_UNLOCK()  ((f_1)SFX_FN)(0)
#define PORT_SFX_CONFIRM() ((f_1)SFX_FN)(0)
#define PORT_SFX_CURSOR()  ((f_1)SFX_FN)(0)
#define PORT_SFX_CANCEL()  ((f_1)SFX_FN)(0)
/* new presses (the menu's pad test 0x8002518c(4, mask), both pads) */
uint16_t port_pad_new(void);
#define PORT_PAD_NEW() port_pad_new()
#define PORT_B_UP    0x1000
#define PORT_B_RIGHT 0x2000
#define PORT_B_DOWN  0x4000
#define PORT_B_LEFT  0x8000
#define PORT_B_BACK  0x0030               /* triangle, circle */
#define PORT_COL_HEAD 0x24
#define PORT_COL_ON   0x26
#define PORT_COL_OFF  0x27
#define PAGE_X     0x48                   /* the routine x: screen x + 64 */
#define PAGE_Y     0x14
#define PAGE_LINE  10
#define PAGE_ROWS  12
#define PAGE_DESC  4
