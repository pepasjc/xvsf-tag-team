/* start.S: entry table of the built-in achievements blob (tools/ach), linked at ACH_BASE.
   The game's patched code calls (jal) or jumps (j) to these slots; tools/ach/achbuild.py has the offsets. */
	.set noreorder
	.section .text.entry,"ax"
	.globl _start
_start:
	j	ach_frame		/* +0x00 once per frame, in place of a call (the call is made first) */
	nop
	j	ach_page		/* +0x08 the ACHIEVEMENTS page, once per frame while it is open */
	nop
	j	ach_idle		/* +0x10 evaluation, in place of a call where the game waits (the call is made after) */
	nop
	.word	ach_dbg			/* +0x18 debug block */
	.word	0			/* +0x1c the sum of our read-only words (achbuild build_spans; the watchdog's reference) */

	.section .text
/* BIOS calls (B table) */
	.globl	bios_open, bios_read, bios_write, bios_close, bios_lseek, bios_firstfile, bios_card_write
	.globl	bios_flushcache
bios_open:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x32
bios_lseek:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x33
bios_read:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x34
bios_write:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x35
bios_close:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x36
bios_firstfile:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x42
bios_card_write:			/* _card_write(port, sector, buf): queued, returns at once */
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x4E
bios_flushcache:
	addiu	$t2, $zero, 0xA0
	jr	$t2
	addiu	$t1, $zero, 0x44

/* boot copy: the game's EXE carries the blob in a zero area that it overwrites later; the EXE header's
   pc0 points here (ACH_COPY, linked into the EXE image, not into the blob - see copy.S) */
