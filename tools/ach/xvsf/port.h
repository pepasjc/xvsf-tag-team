/* port.h: XvSF (SLUS-00627) side of the built-in achievements (tools/ach/ach.c).  docs: tools/ach/xvsf/README, docs/ACHIEVEMENTS.md */
#pragma once
#include <stdint.h>

#ifndef IDLE_PREV
#define IDLE_PREV  0x80016454u            /* DrawSync(0): the call in present (tools/speed/frame present.S; xvach.py finds it) */
#endif
#define FRAME_PREV 0x8002d1e8u            /* the first call of the frame routine 0x800285d4 (at 0x800285e0) */
#define MENU_FN    0x800987c0u            /* main-menu input/state routine (OPDEMO), called at 0x80028638 */
typedef void (*f_v4)(uint32_t, uint32_t, uint32_t, uint32_t);
typedef void (*f_text)(const char*, int, int, int, int, int);
typedef void (*f_1)(uint32_t);
typedef uint32_t (*f_pad)(uint32_t);
#define TEXT_FN    0x8002d79cu            /* (text, x, y, advance, colour, 1) */
#define SFX_FN     0x8004d544u            /* (id): 0x84 / 0x85 cursor, 0x82 back, 0x91 confirm */
#define PAD_NOW    0x8002c8e0u            /* (port) -> buttons held */
#define PAD_OLD    0x8002c8f8u            /* (port) -> buttons held a frame earlier */

#define PORT_FILE "BASLUS-00627ACH"
void port_derive(void);
void port_text(const char* s, int x, int y, int col);
void port_popup(const char* head, const char* line, int first);
int port_card_safe(void);
int port_card_idle(void);
uint16_t port_pad_new(void);
#define ACH_FRAME_ARGS uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3
#define ACH_IDLE_ARGS  uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3
#define PORT_FRAME_PREV()  ((f_v4)FRAME_PREV)(a0, a1, a2, a3)
#define PORT_IDLE_PREV()   ((f_v4)IDLE_PREV)(a0, a1, a2, a3)
#define PORT_TEXT(s, x, y, c) port_text((s), (x), (y), (c))
#define PORT_POPUP(h, l, f) port_popup((h), (l), (f))
#ifdef EX_POP                     /* 1.4 EX OPTIONS: ACHIEVEMENT POPUP byte (0 ON, 1 OFF: unlocks still recorded, queue dropped) */
#define PORT_POPUP_OK()    (*(volatile uint8_t*)(EX_POP) == 0)
#define PORT_POPUP_DROP
#else
#define PORT_POPUP_OK()    1
#endif
#define PORT_CARD_SAFE()   port_card_safe()
#define PORT_CARD_IDLE()   port_card_idle()
#define PORT_SFX_UNLOCK()  ((f_1)SFX_FN)(0x91)
#define PORT_SFX_CONFIRM() ((f_1)SFX_FN)(0x91)
#define PORT_SFX_CURSOR()  ((f_1)SFX_FN)(0x84)
#define PORT_SFX_CANCEL()  ((f_1)SFX_FN)(0x82)
#define PORT_PAD_NEW()     port_pad_new()
uint16_t port_pad_held(void);
#define PORT_PAD_HELD()    port_pad_held()
#define PORT_VCOUNT()      (*(volatile uint16_t*)0x800220c8u)   /* the library's vblank counter (+1 per vblank) */
// #define PAGE_CACHE (dropped 2026-11-17: room)                        /* ach.c: lines composed on change, pad read every call, held directions repeat */
#define PAGE_REP_FIRST 15                 /* vblanks before a held direction repeats */
#define PAGE_REP_NEXT  5                  /* then one step per 5 vblanks (12/s at 60 Hz; the menu runs at 30 fps: 10/s) */
#define PORT_B_UP    0x1000
#define PORT_B_RIGHT 0x2000
#define PORT_B_DOWN  0x4000
#define PORT_B_LEFT  0x8000
#define PORT_B_BACK  0x0030               /* triangle, circle */
#define PORT_COL_HEAD 0x33
#define PORT_COL_ON   0x33
#define PORT_COL_OFF  0x33
#define PORT_COL_SEL  0x30               /* the selected row: the menu's cursor colour */
#define PAGE_INFO_TITLE
#define PAGE_COLS  36                     /* 288 pixels: 16 inside the 320-pixel picture on each side */
#define PAGE_X     0x5c                   /* the routine x: picture x + 76 -> 16 */
#define PAGE_Y     0x1d                   /* the routine y: picture y + 9 -> 20 */
#define PAGE_LINE  9
#define PAGE_ROWS  12
#define PAGE_DESC  4
/* the page is drawn where the game draws its one-shot screens (OPTION): present, before DrawSync, with the text
   routine in its direct mode (0x8003d918 = 1: each character goes to the GPU at once, no 66-sprite list limit) */
void port_page_idle(void);
#define PORT_IDLE_EXTRA() port_page_idle()
void port_ovl(void);
#define PORT_FRAME_EXTRA() port_ovl()
uint32_t ach_dbg_frames(void);
extern uint32_t port_menu_frame;                 /* ach_menuin: the main menu ran this frame */
#define PORT_NOTICE_OK() (ach_dbg_frames() - port_menu_frame < 3u && ach_dbg_frames() > 60u)   /* on the main menu */
#define PORT_NOTICE_ONE_LINE
