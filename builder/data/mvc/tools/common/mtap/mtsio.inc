/* mtsio.inc (included by mtcore.c): mt_read, hand-scheduled MIPS I (noreorder: every delay / load slot is explicit).
   Registers: t7 = return address, t8 = 0x1f800000 (I/O), t9 = saved SR; xfer uses t0-t2, a1, a2, v0. */
__asm__(".section .text.mt_read,\"ax\"\n.set noreorder\n.globl mt_read\nmt_read:\n"
	"	mfc0 $t9, $12\n"
	"	addiu $t0, $0, -2\n"                 /* (mfc0 load slot) */
	"	and $t0, $t9, $t0\n"
	"	mtc0 $t0, $12\n"                     /* interrupts off */
	"	move $t7, $ra\n"
	"	lui $t8, 0x1f80\n"
	"	lui $a1, %hi(mt_req)\n"
	"	addiu $a1, $a1, %lo(mt_req)\n"
	"	bal 9f\n"
	"	addiu $a2, $0, 3\n"                  /* request access 01 42 01 */
	"	addiu $t0, $0, " STR(GAP_DELAY) "\n"
	"1:	bnez $t0, 1b\n"
	"	addiu $t0, $t0, -1\n"
	"	lui $a1, %hi(mt_req + 3)\n"
	"	addiu $a1, $a1, %lo(mt_req + 3)\n"
	"	bal 9f\n"
	"	move $a2, $a0\n"                     /* long access, n bytes */
	"	addiu $t0, $0, 60\n"
	"1:	bnez $t0, 1b\n"
	"	addiu $t0, $t0, -1\n"
	"	addiu $t0, $0, -129\n"
	"	sw $t0, 0x1070($t8)\n"               /* I_STAT = ~0x80: our ACK interrupts are not libpad's */
	"	mtc0 $t9, $12\n"
	"	move $ra, $t7\n"
	"	bne $v0, $a0, 2f\n"
	"	lui $t1, %hi(mt_rx)\n"
	"	lbu $v0, %lo(mt_rx + 1)($t1)\n"
	"	nop\n"
	"	xori $v0, $v0, 0x80\n"
	"	jr $ra\n"
	"	sltiu $v0, $v0, 1\n"                 /* 1 = all n bytes, ID 0x80 */
	"2:	jr $ra\n"
	"	move $v0, $0\n"
	/* xfer: send a2 bytes from a1 on port 1 -> v0 = bytes received (stored at mt_rx) */
	"9:	sh $0, 0x104a($t8)\n"
	"	addiu $t0, $0, 0x0d\n"
	"	sh $t0, 0x1048($t8)\n"               /* JOY_MODE */
	"	addiu $t0, $0, 0x88\n"
	"	sh $t0, 0x104e($t8)\n"               /* JOY_BAUD */
	"	addiu $t0, $0, 0x1003\n"
	"	sh $t0, 0x104a($t8)\n"               /* JOY_CTRL: TX enable, /JOY1, ACK interrupt enable */
	"	addiu $t0, $0, " STR(SEL_DELAY) "\n"
	"1:	bnez $t0, 1b\n"
	"	addiu $t0, $t0, -1\n"
	"1:	lw $t0, 0x1044($t8)\n"               /* drain a stale RX byte (no SIO reset) */
	"	nop\n"
	"	andi $t0, $t0, 2\n"
	"	beqz $t0, 1f\n"
	"	nop\n"
	"	b 1b\n"
	"	lbu $t0, 0x1040($t8)\n"
	"1:	lui $t1, %hi(mt_rx)\n"
	"	addiu $t1, $t1, %lo(mt_rx)\n"
	"	move $v0, $0\n"
	"3:	lbu $t0, 0($a1)\n"
	"	addiu $t2, $0, " STR(RX_WAIT) "\n"
	"	sb $t0, 0x1040($t8)\n"               /* TX */
	"4:	lw $t0, 0x1044($t8)\n"
	"	addiu $t2, $t2, -1\n"
	"	andi $t0, $t0, 2\n"
	"	bnez $t0, 5f\n"
	"	nop\n"
	"	bnez $t2, 4b\n"
	"	nop\n"
	"	b 8f\n"
	"	nop\n"
	"5:	lbu $t0, 0x1040($t8)\n"              /* RX */
	"	addiu $a1, $a1, 1\n"
	"	addiu $v0, $v0, 1\n"
	"	sb $t0, 0($t1)\n"
	"	beq $v0, $a2, 8f\n"
	"	addiu $t1, $t1, 1\n"
	"	addiu $t2, $0, " STR(ACK_WAIT) "\n"
	"6:	lw $t0, 0x1044($t8)\n"               /* /ACK latch (JOY_STAT bit 9): the device wants more */
	"	addiu $t2, $t2, -1\n"
	"	andi $t0, $t0, 0x200\n"
	"	bnez $t0, 7f\n"
	"	nop\n"
	"	bnez $t2, 6b\n"
	"	nop\n"
	"	b 8f\n"
	"	nop\n"
	"7:	addiu $t0, $0, 0x1013\n"
	"	b 3b\n"
	"	sh $t0, 0x104a($t8)\n"               /* acknowledge */
	"8:	jr $ra\n"
	"	sh $0, 0x104a($t8)\n"
	".set reorder\n.previous\n");
