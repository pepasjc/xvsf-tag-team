/* mtmenu.h (XvSF, included by common/mtap/mtcore.c with MT_VSMENU, mktagdisc --vsmenu): main-menu row VERSUS CPU right
   below VERSUS MODE.  Chosen -> the game's VERSUS (mode 2) with mt_vsmode = the confirming pad + 1 (OPDEMO writes the pad
   index, 0 / 1, to menu +0x0d): mt_select seats that pad's side human, the other side CPU (the human picks both teams).
   Call chain: the menu sites (EXE 0x80028638, OPDEMO 0x8009bf54) -> ex_menuin (EX OPTIONS) -> MT_MENU_J (fixed
   trampoline, first word of the string block) -> mt_vsmenu -> ach_menuin (ACH_VSMENU) or the menu routine 0x800987c0.
   The menu routine sets state = cursor + 1 when a row is chosen; mt_vsmenu maps our rows back to the stock states, so
   EX OPTIONS (state 7 with the achievements runtime, 6 without) and the game see the layout they know.
   The overlay words (table, x per entry, lines, cursor wrap, first y, step, the overlay's menu call) are rewritten here
   once per overlay load (EX's own patch writes a 6 / 7-line menu first; ours follows on the next menu call). */
#define VM_MENU   ((volatile uint8_t*)0x80042180u)          /* +0 state, +0x0d confirming pad, +0x12 cursor */
#define VM_FN     ((void (*)(void))0x800987c0u)
#define VM_JAL(t) (0x0c000000u | ((uint32_t)(t) >> 2 & 0x03ffffffu))
#define VM_W(a)   (*(volatile uint32_t*)(a))
#ifndef MT_MENU_Y8
#define MT_MENU_Y8    0x84
#endif
#ifndef MT_MENU_STEP8
#define MT_MENU_STEP8 0x0d
#endif
static const char vm_tab8[8][16] __attribute__((section(".rodata.vmtab"))) = {
	" BATTLE MODE\0\0\0\xc8", " VERSUS MODE\0\0\0\xc8", "VERSUS CPU\0\0\0\0\0\xd4", "TRAINING MODE\0\0\xc8",
	"SURVIVAL MODE\0\0\xc8", "ACHIEVEMENTS\0\0\0\xcc", " OPTION MODE\0\0\0\xc8", "EX OPTIONS\0\0\0\0\0\xd4" };
static const char vm_tab7[7][16] __attribute__((section(".rodata.vmtab7"))) = {   /* without the achievements runtime */
	" BATTLE MODE\0\0\0\xc8", " VERSUS MODE\0\0\0\xc8", "VERSUS CPU\0\0\0\0\0\xd4", "TRAINING MODE\0\0\xc8",
	"SURVIVAL MODE\0\0\xc8", " OPTION MODE\0\0\0\xc8", "EX OPTIONS\0\0\0\0\0\xd4" };

/* overlay words: lui s1 / addiu s1 (table, at run time), then x per entry, lines, cursor wrap (2), first y, step, the
   overlay's menu call; [0] = with the achievements runtime (8 rows), [1] = without (7) */
static const uint32_t vm_at[9] __attribute__((section(".rodata.vmat"))) = { 0x80098748u, 0x8009874cu,
	0x80098770u, 0x80098794u, 0x80098948u, 0x8009894cu, 0x80098740u, 0x80098788u, 0x8009bf54u };
static const uint32_t vm_w[2][7] __attribute__((section(".rodata.vmw"))) = {
	{ 0x9225000fu, 0x2a020008u, 0x28420008u, 0x34020007u, 0x3c120000u | MT_MENU_Y8, 0x3c020000u | MT_MENU_STEP8, VM_JAL(MT_EXMENUIN) },
	{ 0x9225000fu, 0x2a020007u, 0x28420007u, 0x34020006u, 0x3c120000u | MT_MENU_Y7, 0x3c020000u | MT_MENU_STEP7, VM_JAL(MT_EXMENUIN) } };

void mt_vsmenu(void) {
	void (*ach)(void) = *(void (* volatile *)(void))MT_EXACH;
	const uint32_t *w = vm_w[!ach];
	uint32_t t = ach ? (uint32_t)vm_tab8 : (uint32_t)vm_tab7, s, i;
	if (VM_W(0x80098794u) != w[1]) {
		VM_W(0x80098748u) = 0x3c110000u | ((t + 0x8000u) >> 16 & 0xffffu);  /* lui s1 */
		VM_W(0x8009874cu) = 0x26310000u | (t & 0xffffu);                     /* addiu s1 */
		for (i = 0; i < 7; i++) VM_W(vm_at[i + 2]) = w[i];
		((void (*)(void))MT_FLUSH)();
	}
	s = VM_MENU[0];
	if (!s) mt_vsmode = 0;
	if (ach) ach(); else VM_FN();
	if (s || !(i = VM_MENU[0])) return;
	if (i == 3) { mt_vsmode = (uint8_t)((VM_MENU[0x0d] & 1) + 1); i = 2; }    /* VERSUS CPU -> VERSUS */
	else if (i > 3) i = ach && i >= 7 ? i * 2 - 9 : i - 1;                   /* TRAINING.. -> stock states (ach: 7->5, 8->7) */
	VM_MENU[0] = (uint8_t)i;
}
__asm__(".section .text.mt_menu_j,\"ax\"\n.set noreorder\n.globl mt_menu_j\nmt_menu_j:\n	j mt_vsmenu\n	nop\n.set reorder\n.previous\n");
