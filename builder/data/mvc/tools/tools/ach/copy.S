/* copy.S: boot copy of the achievements blob (tools/ach).  Linked into a zero area of the game's EXE image
   (both images follow it there); the EXE header's pc0 points at ach_copy.  It copies image A to ACH_BASE and
   clears its BSS, copies image B to ACH_BASEB, flushes the I-cache and goes on to the previous pc0.
   sp / gp / a0 / a1 are kept. */
	.set noreorder
	.section .text
	.globl ach_copy
ach_copy:
	move	$s7, $a0
	move	$s6, $a1
	la	$t0, blob
	li	$t1, ACH_BASE
	li	$t2, ACH_BASE + BLOB_LEN
1:	lw	$t3, 0($t0)
	addiu	$t0, $t0, 4
	sw	$t3, 0($t1)
	addiu	$t1, $t1, 4
	bne	$t1, $t2, 1b
	nop
	li	$t2, ACH_BASE + BLOB_LEN + BSS_LEN
	beq	$t1, $t2, 3f
	nop
2:	sw	$zero, 0($t1)
	addiu	$t1, $t1, 4
	bne	$t1, $t2, 2b
	nop
3:	la	$t0, blobb
	li	$t1, ACH_BASEB
	li	$t2, ACH_BASEB + BLOBB_LEN
4:	lw	$t3, 0($t0)
	addiu	$t0, $t0, 4
	sw	$t3, 0($t1)
	addiu	$t1, $t1, 4
	bne	$t1, $t2, 4b
	nop
#if BLOBC_LEN
	la	$t0, blobc		/* region C (only when the game uses it) */
	li	$t1, ACH_BASEC
	li	$t2, ACH_BASEC + BLOBC_LEN
5:	lw	$t3, 0($t0)
	addiu	$t0, $t0, 4
	sw	$t3, 0($t1)
	addiu	$t1, $t1, 4
	bne	$t1, $t2, 5b
	nop
#endif
	addiu	$t2, $zero, 0xA0	/* FlushCache */
	jalr	$t2
	addiu	$t1, $zero, 0x44
	move	$a0, $s7
	move	$a1, $s6
	move	$s6, $zero
	move	$s7, $zero
	li	$t0, PREV_PC0
	jr	$t0
	nop
	.align	2
blob:
	.incbin	BLOB_FILE
	.align	2
blobb:
	.incbin	BLOBB_FILE
#if BLOBC_LEN
	.align	2
blobc:
	.incbin	BLOBC_FILE
#endif
