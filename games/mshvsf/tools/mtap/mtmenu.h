/* mtmenu.h (MSHvSF, included by common/mtap/mtcore.c with MT_VSMENU, mktag --vsmenu): main-menu row VERSUS CPU right
   below VERSUS.  Fixed EXE-block addresses (tools/mtap/mtap4.py CFG_M), so the menu overlay patches (gameplay/menus.py,
   on the disc) and the achievements runtime (port.c PORT_MENUTAB) can name them before this code is linked:
     vm_tab9  9-row text table (stride 13) with the achievements runtime: BATTLE VERSUS VERSUS-CPU TRAINING HERO-BATTLE
              ACHIEVEMENTS OPTION GALLERY EX-OPTIONS        vm_tab8  8 rows without it (PS2 / PS3: no ACHIEVEMENTS)
     mt_sel_j the menu's START site (OPDEMO 0x80099e08: `j mt_sel_j; move a0, v1` - v1 = cursor) -> mt_mshsel, then the
              dispatcher's epilogue 0x80099e98
     mt_vsmode 0 none, 1 VERSUS CPU from P1's pad, 2 from P2's (menu +0x6d = the pad that pressed START)
   (vm_tab9 / vm_tab8: kept by name in CFG_M keep.)  States stay the stock ones (state = cursor + 1 in the layout without our row): the row gives the VERSUS state 2. */
#define VM_MENU ((volatile uint8_t*)0x80025040u)        /* +0 state, +0x0c cursor, +0x6d confirming pad */
__attribute__((used)) static const char vm_tab9[9][13] __attribute__((section(".rodata.vmtab9"))) = {
	"BATTLE", "VERSUS", "VERSUS CPU", "TRAINING", "HERO BATTLE", "ACHIEVEMENTS", "OPTION", "GALLERY", "EX OPTIONS" };
__attribute__((used)) static const char vm_tab8[8][13] __attribute__((section(".rodata.vmtab8"))) = {
	"BATTLE", "VERSUS", "VERSUS CPU", "TRAINING", "HERO BATTLE", "OPTION", "GALLERY", "EX OPTIONS" };
void mt_mshsel(uint32_t c) {
	c &= 0xff;
	mt_vsmode = c == 2 ? (uint8_t)((VM_MENU[0x6d] & 1) + 1) : 0;
	VM_MENU[0] = (uint8_t)(c < 2 ? c + 1 : c == 2 ? 2 : c);
}
__asm__(".section .text.mt_sel_j,\"ax\"\n.set noreorder\n.globl mt_sel_j\nmt_sel_j:\n	jal mt_mshsel\n	nop\n	j 0x80099e98\n	nop\n.set reorder\n.previous\n");
