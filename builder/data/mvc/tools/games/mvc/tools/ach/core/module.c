/* module.c: MvC achievements menu module (freeze worker, rc4 line 2026-11-20).  The ACHIEVEMENTS page and the memory
   card of the shared runtime (tools/ach/ach.c, included unchanged: ach_page, card_tick and what they use), linked at
   MOD_AT and read from the disc by the resident core (core.c) at the main menu.  The core owns the unlock bits
   (c_done) and the evaluation; this module only shows them and keeps the card in step:
     +0x00 'ACHM', +0x04 size, +0x08 sum of the words from +0x10 to the end, +0x10 j mod_page, +0x18 j mod_card. */
#define ACH_NOWD 1
#define ACH_NOCOST 1
#include "ach.c"

/* the core's state (corebuild.py symbols) */
#define CORE_DONE  ((uint8_t*)C_DONE)
#define CORE_DIRTY (*(volatile uint8_t*)C_DIRTY)
#define CORE_PAGE  (*(volatile uint8_t*)C_PAGE)
#define CORE_NB    ((NACH_CORE + 7) / 8)
#define MENU ((volatile uint8_t*)0x8007b6e8u)
#define C_STATE (MOD_AT + 0x28)
void mod_menu(void);

static void sync(void) {
	uint32_t i;
	for (i = 0; i < CORE_NB; i++) { bits[i] |= CORE_DONE[i]; CORE_DONE[i] |= bits[i]; }
	if (CORE_DIRTY) { ach_dbg.pending = 1; CORE_DIRTY = 0; }
}
int mod_page(void) {
	int r;
	sync();
	r = ach_page();
	CORE_PAGE = (uint8_t)r;
	return r;
}
void mod_card(void) {
	sync();
	card_tick();
	sync();
}

/* the main menu (OPDEMO.ARC as menus.py left it on the disc) -> ours: 7 lines from the core's table, ACHIEVEMENTS =
   state 5 = the core's c_state (mvcach.menu_patch words, mvcore.py); the core calls this once the overlay is up */
extern const uint16_t m_ovl_at[];       /* word index from OPDEMO's base 0x8009dfe4 */
extern const uint32_t m_ovl_w[];
extern const uint32_t m_ovl_n;
void bios_flushcache(void);
void mod_patch(void) {
	uint32_t i;
	for (i = 0; i < m_ovl_n; i++) ((volatile uint32_t*)0x8009dfe4u)[m_ovl_at[i]] = m_ovl_w[i];
	bios_flushcache();
}

/* ---- MvC port part the page and the card use (port.c, the menu test against the core's state handler) ---- */
static int slen(const char* s) { int n = 0; while (s[n]) n++; return n; }
void port_text(const char* s, int x, int y, int col) {
	(void)slen;
	((f_print)PRINT_FN)(s, (uint32_t)x << 16 | (uint32_t)y, 8u << 24 | (uint32_t)col << 16 | 1);
}
uint16_t port_pad_new(void) {
	static const uint16_t m[] = { PORT_B_UP, PORT_B_DOWN, PORT_B_LEFT, PORT_B_RIGHT, 0x0010, 0x0020 };
	uint32_t k, n = 0;
	for (k = 0; k < sizeof(m) / sizeof(m[0]); k++) if (((uint32_t (*)(uint32_t, uint32_t))0x8002518cu)(4, m[k])) n |= m[k];
	return (uint16_t)n;
}
#define MENU_LOADED (*(const uint32_t*)(0x800b5bf8u + 4 * 5) == (uint32_t)C_STATE)
int port_card_safe(void) { return !((MENU[0] == 6 || MENU[0] == 8) && MENU_LOADED); }
int port_card_idle(void) { return MENU[0] == 0 && MENU[1] && MENU_LOADED; }
/* (never called here: the popup and the evaluation are the core's) */
void port_popup(const char* head, const char* line, int first) { (void)head; (void)line; (void)first; }
void port_derive(void) {}
const uint8_t ach_file_title[64] = {
	0x82,0x6c, 0x82,0x96, 0x82,0x62, 0x81,0x40,
	0x82,0x60, 0x82,0x62, 0x82,0x67, 0x82,0x68, 0x82,0x64, 0x82,0x75, 0x82,0x64, 0x82,0x6c, 0x82,0x64, 0x82,0x6d,
	0x82,0x73, 0x82,0x72, 0 };

__asm__(".set push\n.set noreorder\n.section .text.entry,\"ax\"\n.globl _mstart\n_mstart:\n"
        ".word 0x4d484341\n.word 0\n.word 0\n.word 0\nj mod_page\nnop\nj mod_card\nnop\nj mod_patch\nnop\n"
        "jal mod_menu\nnop\nj 0x800a2df8\nnop\n.set pop\n");      /* +0x28: OPDEMO state 5 (ACHIEVEMENTS) */
/* +0x28 calls this once a frame while the page is open; 0 from the page = back to the main menu */
void mod_menu(void) {
	if (!mod_page()) { MENU[0] = 0; MENU[1] = 0; MENU[2] = 0; MENU[3] = 0; CORE_PAGE = 0; }
}
/* the main menu's 7 strings (13-byte stride; mvcore.py writes the last line; mod_patch points OPDEMO's table here) */
#ifdef VSMENU       /* (rc4.15) VERSUS CPU below VERSUS (mvcach.menu_patch: 8 lines) */
char m_menutab[8][13] __attribute__((section(".keep.menutab"))) = { "BATTLE", "VERSUS", "VERSUS CPU", "TRAINING", "GALLERY", "ACHIEVEMENTS", "OPTION", "" };
#else
char m_menutab[7][13] __attribute__((section(".keep.menutab"))) = { "BATTLE", "VERSUS", "TRAINING", "GALLERY", "ACHIEVEMENTS", "OPTION", "" };
#endif

/* BIOS B-table calls (as tools/ach/start.S) */
__asm__(".set push\n.set noreorder\n.section .text.bios,\"ax\"\n"
        ".globl bios_open, bios_read, bios_write, bios_close, bios_lseek, bios_firstfile, bios_card_write\n"
        "bios_open: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x32\n"
        "bios_lseek: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x33\n"
        "bios_read: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x34\n"
        "bios_write: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x35\n"
        "bios_close: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x36\n"
        "bios_firstfile: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x42\n"
        "bios_card_write: addiu $t2, $zero, 0xB0\n jr $t2\n addiu $t1, $zero, 0x4E\n"
        ".globl bios_flushcache\nbios_flushcache: addiu $t2, $zero, 0xA0\n jr $t2\n addiu $t1, $zero, 0x44\n"
        ".set pop\n");
uint32_t ra_eval_frame(uint8_t* o) { (void)o; return 0; }
void ra_eval_reset(void) {}
