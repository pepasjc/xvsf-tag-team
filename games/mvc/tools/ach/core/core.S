/* core.S: MvC built-in achievements, resident core in MIPS assembly (freeze worker, rc4 line 2026-11-20).
   Same behaviour as core.c (the reference: host/core_diff vs rcheevos 12.5, host/derive_diff vs port.c); this file is
   what runs: corebuild.py packs its sections into the kernel spans.  host/asmdiff.py runs it in Unicorn against the C
   reference frame by frame; dlib.hazards checks the load delays.

   Once per main-loop frame, from the frame routine's `jal 0x8002097c` (ClearOTag x3) at 0x80022fe8:
     the call itself, derive (the set's derived bytes), eval (74 template achievements + 112518), popup (title + points;
     drawn only while the EX OPTIONS byte ACHIEVEMENT POPUP 0x8001175d is 0), then the main menu: the menu module that
     OPDEMO.ARC carries at MOD_AT patches the menu (when the state table is still menus.py's) and keeps the memory card
     (main menu idle).  Data block cdat (s6): see the offsets below.  s7 = 0x80078000 (game bytes, signed 16-bit offsets). */
	.include "core_set.inc"
	.set noreorder
	.set noat

	.equ V_SIDE, 0
	.equ V_MAIN, 1
	.equ V_ACT, 2
	.equ V_COMBO, 3
	.equ V_FULL, 4
	.equ V_CLEAR, 5
	.equ V_CLEAR8, 6
	.equ V_GATE, 7
	.equ V_FIN, 8
	.equ V_GROUP, 9
	.equ V_MGROUP, 10
	.equ V_SGATE, 11
	.equ V_CGATE, 12
	.equ V_RYU, 13
	.equ V_NODOWN, 14
	.equ V_MVL, 15
	.equ D_DONE, 0x10
	.equ D_WAIT, 0x1a
	.equ D_DIRTY, 0x24
	.equ D_DPREV, 0x25
	.equ D_DVAL, 0x26
	.equ D_ANY, 0x27
	.equ D_HIT, 0x28
	.equ D_HH, 0x29
	.equ D_PREVB, 0x2a
	.equ D_PAGE, 0x2b
	.equ D_POP, 0x2c
	.equ D_NQ, 0x2d
	.equ D_OLIFE, 0x2e
	.equ D_QUEUE, 0x32
	.equ D_LINE, 0x3a
	.equ D_END, 0x78
	.equ POP_FRAMES, 210
	.equ PRINT_FN, 0x80020f10
	.equ SFX_FN, 0x80085a7c
	.equ POPUP_OFF, 0x8001175d
	.equ MENU, 0x8007b6e8
	.equ STATE5, 0x800b5c0c

/* ---- the data block (initialised: copied at boot) ------------------------------------------------------------- */
	.section .data.cdat,"aw"
	.align 2
	.globl c_vars, c_done, c_wait, c_dirty, c_page, c_pop, c_nq, c_queue, c_line, cdat
cdat:
c_vars:	.space 16
c_done:	.space 10
c_wait:	.byte 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff
c_dirty: .byte 0
	.byte 0, 0, 0, 0, 0, 0                  /* dprev dval any hit hh prevb */
c_page:	.byte 0
c_pop:	.byte 0
c_nq:	.byte 0
	.half 0, 0                              /* olife[2] */
c_queue: .space 8
c_line:	.space D_END - D_LINE

	.section .rodata.c_unl,"a"
	.align 2
str_unl: .asciz "ACHIEVEMENT UNLOCKED"

/* ---- ach_frame ----------------------------------------------------------------------------------------------- */
	.section .text.ach_frame,"ax"
	.align 2
	.globl ach_frame
ach_frame:
	addiu	$sp, $sp, -40
	sw	$ra, 36($sp)
	sw	$s0, 0($sp)
	sw	$s1, 4($sp)
	sw	$s2, 8($sp)
	sw	$s3, 12($sp)
	sw	$s4, 16($sp)
	sw	$s5, 20($sp)
	sw	$s6, 24($sp)
	jal	0x8002097c                      /* the replaced call (a0-a3 as we got them) */
	sw	$s7, 28($sp)
	lui	$s7, 0x8007
	ori	$s7, $s7, 0x8000
	lui	$s6, %hi(cdat)
	jal	derive
	addiu	$s6, $s6, %lo(cdat)
#ifdef INFB
	/* (infinite meter) EX row INFINITE SUPER METER ON: in battle, every fighter's meter = the game's maximum (level
	   +0x298 = 3, gauge +0x296 = 0: a gain at level 3 clamps there; partners mirror their main) on both teams, human
	   and CPU; and it is a cheat: nothing is evaluated (no unlock) */
	lui	$t0, %hi(INFB)
	lbu	$t0, %lo(INFB)($t0)
	lbu	$t2, 0x3dcc($s7)                /* scene 0x8007bdcc: 8 = battle */
	beqz	$t0, 8f
	xori	$t2, $t2, 8
	bnez	$t2, 9f
	li	$t1, 3
	sb	$t1, 0x4128($s7)                /* P1 main 0x8007be90 */
	sh	$zero, 0x4126($s7)
	sb	$t1, 0x4538($s7)                /* P2 main 0x8007c2a0 */
	sh	$zero, 0x4536($s7)
	sb	$t1, 0x4988($s7)                /* P1 partner 0x8007c6f0 */
	sh	$zero, 0x4986($s7)
	sb	$t1, 0x4d90($s7)                /* P2 partner 0x8007caf8 */
	b	9f
	sh	$zero, 0x4d8e($s7)
8:
#endif
	jal	eval
	nop
#ifdef INFB
9:
#endif
	jal	popup
	nop
	jal	menu
	nop
	lw	$ra, 36($sp)
	lw	$s0, 0($sp)
	lw	$s1, 4($sp)
	lw	$s2, 8($sp)
	lw	$s3, 12($sp)
	lw	$s4, 16($sp)
	lw	$s5, 20($sp)
	lw	$s6, 24($sp)
	lw	$s7, 28($sp)
	jr	$ra
	addiu	$sp, $sp, 40

/* ---- derive: s6 cdat, s7 game base; t / a / v / s0-s5 free; returns with jr ra (ra = ach_frame's call) -------- */
	.section .text.derive,"ax"
	.align 2
derive:
	move	$s5, $ra
	lbu	$t0, 0x3dc9($s7)                /* hum */
	nop
	xori	$t1, $t0, 2
	sltiu	$t1, $t1, 1                     /* p2 */
	sltu	$t0, $zero, $t0
	addu	$s0, $t0, $t1                   /* side = (hum != 0) + p2 */
	sb	$s0, V_SIDE($s6)
	subu	$t2, $zero, $t1
	andi	$t2, $t2, 0x410
	addu	$s1, $s7, $t2                   /* mo: fields at +0x3e90 (P1 0x7be90 / P2 0x7c2a0) */
	sll	$t3, $t1, 3
	subu	$s2, $s1, $t3                   /* po: fields at +0x46f0 (P1 0x7c6f0 / P2 0x7caf8) */
	lhu	$s3, 0x4124($s1)                /* lm */
	lhu	$s4, 0x4984($s2)                /* lp */
	lbu	$t4, 0x3fc8($s1)                /* combo of mo */
	lbu	$t5, 0x4828($s2)                /* combo of po */
	sltu	$t6, $zero, $s0                 /* sideb */
	sltu	$t7, $t4, $t5
	beqz	$t7, 1f
	subu	$t8, $zero, $t6                 /* side mask */
	move	$t4, $t5
1:	and	$t4, $t4, $t8
	sb	$t4, V_COMBO($s6)
	xori	$t4, $s3, 144
	xori	$t5, $s4, 144
	or	$t4, $t4, $t5
	sltiu	$t4, $t4, 1
	and	$t4, $t4, $t6
	sb	$t4, V_FULL($s6)
	sll	$t5, $t1, 2
	addu	$t5, $s7, $t5                   /* TEAM + 4 p2: fields at +0x38aa */
	lbu	$t7, 0x3e90($s1)                /* mo active */
	lbu	$t9, 0x46f0($s2)                /* po active */
	lhu	$t0, 0x38aa($t5)                /* main */
	sltiu	$t7, $t7, 1
	sltu	$t9, $zero, $t9
	and	$t7, $t7, $t9
	sll	$t7, $t7, 1
	addu	$t5, $t5, $t7
	lhu	$t1, 0x38aa($t5)                /* act */
	bnez	$s0, 2f
	andi	$t0, $t0, 0xff
	li	$t0, 0xff
	li	$t1, 0xff
2:	andi	$t1, $t1, 0xff
	sb	$t0, V_MAIN($s6)
	sb	$t1, V_ACT($s6)
	jal	group
	move	$a0, $t1
	sb	$v0, V_GROUP($s6)
	jal	group
	move	$a0, $t0
	sb	$v0, V_MGROUP($s6)
	lbu	$t0, 0x3740($s7)                /* mode */
	lbu	$t1, 0x371c($s7)                /* diff */
	lbu	$t2, 0x3df2($s7)                /* stage */
	lbu	$t3, 0x3dc8($s7)                /* bdc8 */
	lbu	$t4, 0x416d($s7)                /* beg */
	lbu	$t5, 0x4f10($s7)                /* cf10 */
	xori	$a1, $t0, 3
	sltiu	$a1, $a1, 1                     /* mode == 3 */
	sltiu	$t0, $t0, 1                     /* battle */
	sltiu	$t4, $t4, 2                     /* nbeg */
	or	$a1, $a1, $t0
	and	$a1, $a1, $t4
	sb	$a1, V_CGATE($s6)
	xori	$t5, $t5, 2
	sltiu	$t5, $t5, 1                     /* cf10 == 2 */
	sltiu	$a2, $t2, 7
	xori	$a2, $a2, 1                     /* stage >= 7 */
	and	$a2, $a2, $t5
	and	$a2, $a2, $t0
	and	$a2, $a2, $t4                   /* t */
	sltu	$a3, $zero, $t1                 /* d1 */
	and	$v0, $a2, $a3
	sb	$v0, V_CLEAR($s6)
	xori	$v0, $t1, 7
	sltiu	$v0, $v0, 1
	and	$v0, $v0, $a2
	sb	$v0, V_CLEAR8($s6)
	sltu	$v0, $zero, $t3
	and	$v0, $v0, $t0
	and	$v0, $v0, $t4
	and	$v0, $v0, $a3                   /* sgate */
	sb	$v0, V_SGATE($s6)
	lbu	$v1, 0x4afb($s7)
	lbu	$a0, 0x4534($s7)
	nop
	or	$v1, $v1, $a0
	sltiu	$v1, $v1, 1
	and	$v0, $v0, $v1
	sb	$v0, V_GATE($s6)
	lbu	$v0, 0x382a($s7)
	lbu	$v1, 0x3770($s7)
	lbu	$a0, 0x3772($s7)
	xori	$a1, $v0, 1
	beqz	$a1, 4f                         /* 1: 0x7b770 */
	xori	$a1, $v0, 2
	beqz	$a1, 4f                         /* 2: 0x7b772 (the delay slot's move) */
	move	$v1, $a0
	move	$v1, $zero
4:	sb	$v1, V_FIN($s6)
	lbu	$v1, 0x38e4($s7)
	xori	$v0, $t3, 1
	sltiu	$v0, $v0, 1
	and	$v0, $v0, $t0
	subu	$v0, $zero, $v0
	and	$v1, $v1, $v0
	sb	$v1, V_RYU($s6)
	/* nodown */
	and	$v0, $t0, $t6                   /* battle && side */
	beqz	$v0, 7f
	move	$v1, $zero
	lbu	$v1, V_NODOWN($s6)
	lbu	$a0, 0x382b($s7)
	lbu	$a1, V_FULL($s6)
	or	$a0, $a0, $t2                   /* stage == 0 && b82b == 0 */
	bnez	$a0, 6f
	nop
	beqz	$a1, 6f
	nop
	li	$v1, 1
6:	lhu	$a0, D_OLIFE($s6)
	lhu	$a1, D_OLIFE + 2($s6)
	sltiu	$a2, $s3, 1
	sltu	$a0, $zero, $a0
	and	$a0, $a0, $a2                   /* olife0 && !lm */
	sltiu	$a2, $s4, 1
	sltu	$a1, $zero, $a1
	and	$a1, $a1, $a2
	or	$a0, $a0, $a1
	beqz	$a0, 7f
	nop
	move	$v1, $zero
7:	sb	$v1, V_NODOWN($s6)
	and	$s3, $s3, $t8                   /* olife = side ? life : 0 */
	and	$s4, $s4, $t8
	sh	$s3, D_OLIFE($s6)
#ifdef ACHFIX
	sh	$s4, D_OLIFE + 2($s6)
	/* (ach audit, --achfix) the human's side (core.c): SGATE = gate ? 1 + score tier : 0, GATE (+ own round win),
	   FIN, RYU (on-point object's form byte), MVL (latched move number, 0x80 on an assist KO).  Live here: s0 side,
	   s1 / s2 mo / po (s7-relative), t0 battle, t3 bdc8, t4 nbeg, a3 d1, t6 side != 0, t8 = -(side != 0). */
	xori	$t5, $s0, 2
	sltiu	$t5, $t5, 1                     /* p2 */
	sll	$t7, $t5, 3                     /* 8 p2 */
	addu	$t9, $s7, $t5
	lbu	$t9, 0x382a($t9)                /* w = rounds won by the human side (0x7b82a / 0x7b82b) */
	xori	$v0, $t5, 1                     /* !p2 */
	subu	$v1, $zero, $v0
	andi	$v1, $v1, 0x410
	addu	$v1, $s7, $v1                   /* oppm: fields at +0x3e90 (P2 0x7c2a0 / P1 0x7be90) */
	sll	$a0, $v0, 3
	subu	$a0, $v1, $a0                   /* oppp: fields at +0x46f0 (P2 0x7caf8 / P1 0x7c6f0) */
	sltu	$a1, $zero, $t3
	and	$a1, $a1, $t0
	and	$a1, $a1, $t4
	and	$a1, $a1, $a3
	and	$a1, $a1, $t6                   /* sg */
	lw	$a2, 0x4168($s1)                /* score: mo +0x2d8 */
	nop
	lui	$v0, 0x9
	ori	$v0, $v0, 0x27c0                /* 600000 */
	sltu	$s3, $a2, $v0
	xori	$s3, $s3, 1
	lui	$v0, 0xc
	ori	$v0, $v0, 0x3500                /* 800000 */
	sltu	$s4, $a2, $v0
	xori	$s4, $s4, 1
	addu	$s3, $s3, $s4
	lui	$v0, 0xf
	ori	$v0, $v0, 0x4240                /* 1000000 */
	sltu	$s4, $a2, $v0
	xori	$s4, $s4, 1
	addu	$s3, $s3, $s4
	addiu	$s3, $s3, 1
	subu	$s4, $zero, $a1
	and	$s3, $s3, $s4
	sb	$s3, V_SGATE($s6)
	lbu	$a2, 0x46f3($a0)                /* oppp +3 (human) */
	lbu	$s3, 0x4124($v1)                /* oppm life (low byte) */
	sltu	$s4, $zero, $t9                 /* w != 0 */
	or	$a2, $a2, $s3
	sltiu	$a2, $a2, 1
	and	$a2, $a2, $s4
	and	$a2, $a2, $a1
	sb	$a2, V_GATE($s6)
	addu	$a2, $s7, $t7
	lbu	$s3, 0x3770($a2)                /* finish code, 1st round win (0x7b770 / 0x7b778) */
	lbu	$s4, 0x3772($a2)                /* 2nd */
	xori	$a2, $t9, 1
	beqz	$a2, 1f
	xori	$a2, $t9, 2
	beqz	$a2, 1f
	move	$s3, $s4                        /* (delay) */
	move	$s3, $zero
1:	sb	$s3, V_FIN($s6)
	lbu	$a2, 0x3e90($s1)                /* mo active */
	lbu	$s3, 0x46f0($s2)                /* po active */
	sltiu	$a2, $a2, 1
	sltu	$s3, $zero, $s3
	and	$a2, $a2, $s3                   /* onp: the partner is on point */
	sll	$s3, $a2, 1
	addu	$s3, $s3, $t5
	addu	$s3, $s3, $s7
	lbu	$s3, 0x38e4($s3)                /* form byte 0x7b8e4 + p2 + 2 onp */
	xori	$s4, $t3, 1
	sltiu	$s4, $s4, 1
	and	$s4, $s4, $t0
	and	$s4, $s4, $t6
	subu	$s4, $zero, $s4
	and	$s3, $s3, $s4
	sb	$s3, V_RYU($s6)
	and	$s4, $t9, $t8                   /* w (0 without a human) */
	beqz	$s4, 2f
	move	$s3, $zero                      /* (delay) MVL = 0 */
	lbu	$s3, V_MVL($s6)
	lbu	$s4, 0x46f0($a0)                /* oppp active */
	bnez	$s3, 3f                         /* latched */
	nop
	lw	$s3, 0x3f30($v1)                /* oppm +0xa0: what hit it */
	beqz	$s4, 5f
	nop
	lw	$s3, 0x4790($a0)                /* oppp +0xa0 */
	nop
5:	lui	$s4, 0x8008
	addiu	$s4, $s4, -0x4470               /* 0x8007bb90: P1 / P2 assist objects (0x118 each) */
	subu	$s3, $s3, $s4
	sltiu	$s3, $s3, 0x230
	bnez	$s3, 2f
	addiu	$s3, $zero, 0x80                /* (delay) assist KO: no move */
	lbu	$s3, 0x3f28($s1)                /* mo +0x98 */
	beqz	$a2, 7f
	nop
	lbu	$s3, 0x4788($s2)                /* po +0x98 */
	nop
7:	ori	$s3, $s3, 0x80
2:	sb	$s3, V_MVL($s6)
3:	jr	$s5
	nop
#else
	jr	$s5
	sh	$s4, D_OLIFE + 2($s6)
#endif

/* group of a character id * 2 (a0): 0 none (0xff, Onslaught 34), 1 Marvel (2..14, 36, 38, 40), 2 Capcom; t9 */
group:
	addiu	$t9, $a0, -34
	beqz	$t9, 1f
	addiu	$t9, $a0, -255
	beqz	$t9, 1f
	addiu	$t9, $a0, -2
	sltiu	$t9, $t9, 13                    /* 2..14 */
	addiu	$v0, $a0, -36
	sltiu	$v0, $v0, 5
	andi	$v1, $a0, 1
	xori	$v1, $v1, 1
	and	$v0, $v0, $v1                   /* 36, 38, 40 */
	or	$v0, $v0, $t9
	xori	$v0, $v0, 1
	jr	$ra
	addiu	$v0, $v0, 1
1:	jr	$ra
	move	$v0, $zero

/* ---- eval: s0 i, s1 record, s2 mask, s3 done byte address, s4 template, s5 b (0x7b82b) ------------------------- */
	.section .text.eval,"ax"
	.align 2
eval:
	move	$a3, $ra
	lbu	$s5, 0x382b($s7)
	lbu	$t0, D_DPREV($s6)
	lbu	$t1, DELTA_VAR($s6)
	sb	$t0, D_DVAL($s6)
	sb	$t1, D_DPREV($s6)
	move	$s0, $zero
	lui	$s1, %hi(c_rec)
	addiu	$s1, $s1, %lo(c_rec)
Eloop:
	srl	$t0, $s0, 3
	addu	$s3, $s6, $t0
	lbu	$t2, D_DONE($s3)
	andi	$t3, $s0, 7
	li	$t4, 1
	sllv	$s2, $t4, $t3
	and	$t5, $t2, $s2
	bnez	$t5, Enext
	li	$t6, SPECIAL_IDX
	beq	$s0, $t6, Espec
	lbu	$t0, 0($s1)                     /* (delay) template | points << 4 */
	lui	$t1, %hi(c_toff)
	andi	$t0, $t0, 15
	addu	$t1, $t1, $t0
	lbu	$t1, %lo(c_toff)($t1)
	lui	$s4, %hi(c_tpl)
	addiu	$s4, $s4, %lo(c_tpl)
	addu	$s4, $s4, $t1
Ploop:
	lbu	$t0, 0($s4)                     /* reference */
	lbu	$t1, 1($s4)                     /* mask | mode << 3 */
	li	$at, 0xff
	beq	$t0, $at, Ptrue
	srl	$t2, $t1, 3                     /* mode */
	andi	$t3, $t2, 1
	bnez	$t3, 1f
	lbu	$t4, 1($s1)                     /* p = param 0 (odd modes) */
	lbu	$t4, 2($s1)                     /* or param 1 */
1:	beqz	$t2, Pconst
	sltiu	$t3, $t2, 3
	bnez	$t3, Pval                       /* 1 / 2: p */
	sltiu	$t3, $t2, 5
	bnez	$t3, Pci                        /* 3 / 4: c_const[p] */
	nop
	b	Pval                            /* 5 / 6: p - 1 */
	addiu	$t4, $t4, -1
Pconst:	lbu	$t4, 2($s4)
	nop
Pci:	sll	$t4, $t4, 2
	lui	$t5, %hi(c_const)
	addu	$t5, $t5, $t4
	lw	$t4, %lo(c_const)($t5)
Pval:	sll	$t0, $t0, 1
	lui	$t5, %hi(c_ref)
	addu	$t5, $t5, $t0
	lhu	$t0, %lo(c_ref)($t5)            /* w */
	nop
	andi	$t5, $t0, 0x8000
	beqz	$t5, Pgame
	andi	$t5, $t0, 0x4000
	bnez	$t5, Pa
	lbu	$t6, D_DVAL($s6)                /* delta */
	andi	$t5, $t0, 15
	addu	$t5, $s6, $t5
	b	Pa
	lbu	$t6, 0($t5)                     /* derived byte */
Pgame:	andi	$t5, $t0, 0x1fff
	addu	$t5, $s7, $t5
	andi	$t0, $t0, 0x2000
	beqz	$t0, Pa
	lbu	$t6, 0x3000($t5)                /* byte (0x7b000 + offset) */
	lw	$t6, 0x3000($t5)                /* 32-bit (aligned) */
Pa:	nop                                     /* (a load just before, in every path) */
	sltu	$t5, $t6, $t4
	bnez	$t5, 2f
	li	$t7, 4
	beq	$t6, $t4, 2f
	li	$t7, 2
	li	$t7, 1
2:	and	$t7, $t7, $t1
	bnez	$t7, Ploop
	addiu	$s4, $s4, 3
	/* false: rcheevos WAITING -> ACTIVE */
	lbu	$t0, D_WAIT($s3)
	nor	$t1, $s2, $zero
	and	$t0, $t0, $t1
	b	Enext
	sb	$t0, D_WAIT($s3)
Ptrue:	lbu	$t0, D_WAIT($s3)
	nop
	and	$t0, $t0, $s2
	bnez	$t0, Enext                      /* still WAITING: true at activation */
	nop
Etrig:	lbu	$t0, D_DONE($s3)
	li	$t1, 1
	or	$t0, $t0, $s2
	sb	$t0, D_DONE($s3)
	sb	$t1, D_DIRTY($s6)
	lbu	$t0, D_NQ($s6)
	nop
	sltiu	$t1, $t0, 8
	beqz	$t1, Enext
	addu	$t1, $s6, $t0
	sb	$s0, D_QUEUE($t1)
	addiu	$t0, $t0, 1
	sb	$t0, D_NQ($s6)
Enext:	addiu	$s0, $s0, 1
	sltiu	$t0, $s0, NACH
	bnez	$t0, Eloop
	addiu	$s1, $s1, 3
	jr	$a3
	sb	$s5, D_PREVB($s6)

/* 112518 (core.c special): t0-t9, v0 v1 a0 a1; s5 = b; exits to Etrig / Enext */
Espec:
	lbu	$t0, 0x3df2($s7)                /* st */
	lbu	$t1, D_PREVB($s6)               /* db */
	lbu	$t2, 0x3740($s7)
	lbu	$v1, D_ANY($s6)                 /* s_any (kept in v1) */
	sltu	$t2, $zero, $t2                 /* R: mode != 0 */
	or	$v1, $v1, $t2
	move	$v0, $t2                        /* reset */
	xori	$t3, $s5, 2
	sltiu	$t3, $t3, 1                     /* N: b == 2 */
	or	$v1, $v1, $t3
	xori	$t4, $t1, 1
	sltiu	$t4, $t4, 1
	and	$t3, $t3, $t4                   /* R: and d == 1 */
	or	$v1, $v1, $t3
	or	$v0, $v0, $t3
	xori	$t3, $s5, 1
	sltiu	$t3, $t3, 1                     /* N: b == 1 */
	or	$v1, $v1, $t3
	sltiu	$t4, $t1, 1
	and	$t3, $t3, $t4                   /* N: and d == 0 */
	or	$v1, $v1, $t3
	xori	$t4, $t0, 7
	sltiu	$t4, $t4, 1
	and	$t3, $t3, $t4                   /* R: and st == 7 */
	or	$v1, $v1, $t3
	or	$v0, $v0, $t3
	beqz	$v0, 1f
	lbu	$t5, D_HH($s6)
	/* reset: hits cleared; with has_hits the state stays, else WAITING -> ACTIVE */
	sb	$zero, D_ANY($s6)
	sb	$zero, D_HIT($s6)
	bnez	$t5, Ehh
	sb	$zero, D_HH($s6)
	b	Eact
	nop
Ehh:	b	Enext
	nop
1:	sltiu	$t3, $t0, 1                     /* N: st == 0 */
	or	$v1, $v1, $t3
	sltiu	$t4, $s5, 1
	and	$t3, $t3, $t4                   /* .1.: and b == 0 */
	or	$v1, $v1, $t3
	lbu	$t4, D_HIT($s6)
	nop
	or	$t4, $t4, $t3
	sb	$t4, D_HIT($s6)                 /* t = hit */
	lbu	$t5, 0x416d($s7)
	lbu	$t6, 0x371c($s7)
	sltiu	$t5, $t5, 2                     /* beg <= 1 */
	or	$v1, $v1, $t5
	and	$t4, $t4, $t5
	sltu	$t6, $zero, $t6                 /* diff >= 1 */
	or	$v1, $v1, $t6
	and	$t4, $t4, $t6
	sltiu	$t5, $t0, 7
	xori	$t5, $t5, 1                     /* T: st >= 7 */
	or	$v1, $v1, $t5
	and	$t4, $t4, $t5
	lbu	$t6, 0x4f10($s7)
	nop
	xori	$t6, $t6, 2
	sltiu	$t6, $t6, 1                     /* T: cf10 == 2 */
	or	$v1, $v1, $t6
	and	$t4, $t4, $t6
	beqz	$t4, 2f
	sb	$v1, D_ANY($s6)
	/* true: WAITING -> hits cleared, stay; else trigger */
	lbu	$t0, D_WAIT($s3)
	nop
	and	$t0, $t0, $s2
	beqz	$t0, Etrig
	nop
	sb	$zero, D_ANY($s6)
	sb	$zero, D_HIT($s6)
	b	Enext
	sb	$zero, D_HH($s6)
2:	sb	$v1, D_HH($s6)                  /* has_hits = any count != 0 */
Eact:	lbu	$t0, D_WAIT($s3)
	nor	$t1, $s2, $zero
	and	$t0, $t0, $t1
	b	Enext
	sb	$t0, D_WAIT($s3)

/* ---- popup ---------------------------------------------------------------------------------------------------- */
	.section .text.popup,"ax"
	.align 2
popup:
	move	$s5, $ra
	lbu	$t0, D_POP($s6)
	lbu	$t1, D_PAGE($s6)
	beqz	$t0, Pstart
	addiu	$t0, $t0, -1
	bnez	$t1, Pclr
	sb	$t0, D_POP($s6)
	lui	$t2, %hi(POPUP_OFF)
	lbu	$t2, %lo(POPUP_OFF)($t2)
	lui	$a0, %hi(str_unl)
	bnez	$t2, Pret
	addiu	$a0, $a0, %lo(str_unl)
	li	$a1, 0x4a
	jal	text
	li	$a2, 0x26
	addiu	$a0, $s6, D_LINE
	li	$a1, 0x56
	jal	text
	li	$a2, 0x24
Pret:	jr	$s5
	nop
Pclr:	jr	$s5
	sb	$zero, D_POP($s6)
Pstart:	lbu	$t0, D_NQ($s6)
	bnez	$t1, Pret
	nop
	beqz	$t0, Pret
	lbu	$s0, D_QUEUE($s6)               /* (delay) i */
	/* title i -> line (corec.py: titles one after another; phrase symbol 1; Huffman, byte nodes, LSB first) */
	lui	$t0, %hi(c_hdat)
	addiu	$t0, $t0, %lo(c_hdat)
	lui	$t1, %hi(c_hnode)
	addiu	$t1, $t1, %lo(c_hnode)
	move	$t2, $zero                      /* bit */
	addiu	$t3, $s6, D_LINE                /* p */
	move	$t4, $s0                        /* titles to skip */
Tnext:	move	$t5, $zero
Tbit:	srl	$t6, $t2, 3
	addu	$t6, $t0, $t6
	lbu	$t6, 0($t6)
	andi	$t7, $t2, 7
	srlv	$t6, $t6, $t7
	andi	$t6, $t6, 1
	sll	$t5, $t5, 1
	addu	$t5, $t5, $t6
	addu	$t5, $t1, $t5
	lbu	$t5, 0($t5)
	addiu	$t2, $t2, 1
	andi	$t6, $t5, 0x80
	beqz	$t6, Tbit
	andi	$t5, $t5, 0x7f
	bnez	$t5, Tsym
	nop
	beqz	$t4, Tend
	addiu	$t4, $t4, -1
	b	Tnext
	addiu	$t3, $s6, D_LINE
Tsym:	addiu	$t6, $t5, -1
	bnez	$t6, Tch
	lui	$t7, %hi(c_phrase)
	addiu	$t7, $t7, %lo(c_phrase)
Tph:	lbu	$t8, 0($t7)
	addiu	$t7, $t7, 1
	beqz	$t8, Tnext
	nop
	sb	$t8, 0($t3)
	b	Tph
	addiu	$t3, $t3, 1
Tch:	addiu	$t5, $t5, 30                    /* symbol - 2 + ' ' */
	sb	$t5, 0($t3)
	b	Tnext
	addiu	$t3, $t3, 1
Tend:	/* " (points)" */
	li	$t5, 0x20                       /* ' (' */
	sb	$t5, 0($t3)
	li	$t5, 0x28
	sb	$t5, 1($t3)
	addiu	$t3, $t3, 2
	sll	$t5, $s0, 1
	addu	$t5, $t5, $s0
	lui	$t6, %hi(c_rec)
	addu	$t6, $t6, $t5
	lbu	$t5, %lo(c_rec)($t6)
	lui	$t6, %hi(c_ptab)
	srl	$t5, $t5, 4
	addu	$t6, $t6, $t5
	lbu	$t5, %lo(c_ptab)($t6)           /* points (< 100) */
	li	$t6, 0
	sltiu	$t7, $t5, 10
3:	bnez	$t7, 4f
	nop
	addiu	$t5, $t5, -10
	addiu	$t6, $t6, 1
	b	3b
	sltiu	$t7, $t5, 10
4:	beqz	$t6, 5f
	addiu	$t6, $t6, 0x30
	sb	$t6, 0($t3)
	addiu	$t3, $t3, 1
5:	addiu	$t5, $t5, 0x30
	sb	$t5, 0($t3)
	li	$t5, 0x29                       /* ')' */
	sb	$t5, 1($t3)
	sb	$zero, 2($t3)
	/* queue: drop the head */
	lbu	$t0, D_NQ($s6)
	addiu	$t1, $s6, D_QUEUE
	addiu	$t0, $t0, -1
	sb	$t0, D_NQ($s6)
6:	beqz	$t0, 7f
	lbu	$t2, 1($t1)
	addiu	$t0, $t0, -1
	sb	$t2, 0($t1)
	b	6b
	addiu	$t1, $t1, 1
7:	li	$t0, POP_FRAMES
	sb	$t0, D_POP($s6)
	lui	$t2, %hi(POPUP_OFF)
	lbu	$t2, %lo(POPUP_OFF)($t2)
	nop
	bnez	$t2, Pret
	lui	$t9, %hi(SFX_FN)
	addiu	$t9, $t9, %lo(SFX_FN)
	jalr	$t9                             /* unlock sound (the menu cursor sound) */
	move	$a0, $zero
	jr	$s5
	nop

/* text a0 centred at y a1, colour a2 (the game's text routine; tail call, returns to our caller) */
text:	move	$t0, $a0
1:	lbu	$t1, 0($t0)
	nop
	bnez	$t1, 1b
	addiu	$t0, $t0, 1
	subu	$t0, $t0, $a0
	addiu	$t0, $t0, -1                    /* length */
	sll	$t0, $t0, 2
	li	$t1, 256
	subu	$t0, $t1, $t0
	sll	$t0, $t0, 16
	or	$a1, $a1, $t0
	sll	$a2, $a2, 16
	lui	$t1, 0x0800
	ori	$t1, $t1, 1
	or	$a2, $a2, $t1
	lui	$t9, %hi(PRINT_FN)
	addiu	$t9, $t9, %lo(PRINT_FN)
	jr	$t9
	nop

/* ---- the main menu: the module (OPDEMO.ARC tail at MOD_AT) ------------------------------------------------------ */
	.section .text.menu,"ax"
	.align 2
menu:
	move	$s5, $ra
#ifdef MENUGATE
	/* --titlefix (rc4.8 tester, 2026-11-21): on a real CD the main menu takes input before OPDEMO.ARC's tail (the
	   slack with the EX OPTIONS screen code + this module) is in RAM -> EX OPTIONS jumped into an unloaded sector
	   (MiSTer freeze).  The confirm calls the new state's handler in the same frame, so the state-table entry itself
	   is parked: the module is read last; while it is not whole, entry [6] (menus.py + --exopt: EX OPTIONS -> exst in
	   the slack) is the stock no-op handler and a state >= 6 goes back to 0 (the press is ignored); once whole, exst
	   is put back before the module's own menu patch below reads the table. */
	/* (keyed on the main-menu table itself, not on "menu up": that byte is 0 outside state 0) */
	lui	$t0, %hi(GATE_ST6)
	lw	$t1, %lo(GATE_ST6 - 24)($t0)    /* table [0] = the main menu's case: OPDEMO's menu is in RAM */
	li	$t2, GATE_ST0
	bne	$t1, $t2, 3f
	nop
	lw	$t1, %lo(GATE_ST6)($t0)
	li	$t2, GATE_EXST
	li	$t3, GATE_NOOP
	beq	$t1, $t2, 4f
	nop
#ifdef MODRELOAD2
	bne	$t1, $t3, 7f                    /* [6] neither: patched by the module (or not ours) -> module still whole? */
#else
	bne	$t1, $t3, 3f                    /* [6] neither: patched by the module (or not ours) */
#endif
	nop
4:	jal	modok
	nop
	lui	$t0, %hi(GATE_ST6)
	lw	$t1, %lo(GATE_ST6)($t0)
	li	$t2, GATE_EXST
	li	$t3, GATE_NOOP
	beqz	$v0, 1f
	nop
	bne	$t1, $t3, 3f                    /* whole: exst back if we parked it */
	nop
	b	3f
	sw	$t2, %lo(GATE_ST6)($t0)
1:	bne	$t1, $t2, 2f                    /* not whole: park EX OPTIONS */
	nop
	sw	$t3, %lo(GATE_ST6)($t0)
2:
#ifdef MODRELOAD
	/* --modreload (2026-11-24): the attract intro animation uses OPDEMO's upper RAM (0x80102e14-0x8010d614) as its buffer
	   and a START from it (or from the title after it) enters the main menu WITHOUT reading OPDEMO.ARC again: slack
	   (EX OPTIONS screen) + module gone for good -> 6-row menu, no VERSUS CPU / ACHIEVEMENTS, EX OPTIONS parked.
	   Menu up, module not whole, no async read pending (= OPDEMO is not still loading on a real CD) -> read the copy's
	   tail sectors again (sync).  The reload pass returns at once; the next pass is the normal "module whole" path. */
	jal	mreload
	nop
	bnez	$v0, Mret
	nop
#endif
	lui	$t0, %hi(MENU)
	lbu	$t2, %lo(MENU)($t0)             /* state 6 = EX OPTIONS (pre-patch): back to the menu */
	li	$t4, 6
	bne	$t2, $t4, 3f
	nop
	sb	$zero, %lo(MENU)($t0)
#ifdef MODRELOAD2
	b	3f
	nop
	/* --modreload2 (2026-11-25, real PS1 / MiSTer / DuckStation: boot -> menu -> idle -> the attract intro plays AGAIN ->
	   START -> empty or scrambled main menu).  After the first menu visit the module has patched state-table [6]
	   (0x800a2de0), so the gate above took the "[6] neither: patched by the module" exit and never re-checked the module;
	   the second intro's buffer (0x80102e14-0x8010d5a0) wipes slack + module but not the table -> mreload never ran and
	   the menu kept calling into the wiped module.  Now: [6] patched but the module not whole -> park [6] (as the
	   not-whole path does) and re-read the tail; the next passes are the first-intro sequence (whole -> exst -> patch). */
7:	jal	modok
	nop
	bnez	$v0, 3f
	nop
	lui	$t0, %hi(GATE_ST6)
	li	$t3, GATE_NOOP
	sw	$t3, %lo(GATE_ST6)($t0)
	jal	mreload
	nop
	bnez	$v0, Mret
	nop
#endif
3:
#endif
#ifdef MENUFONT
	jal	mfont
	nop
#endif
#ifdef DIAGMENU
	jal	diagm
	nop
#endif
	lui	$t0, %hi(MENU)
	lbu	$t1, %lo(MENU + 1)($t0)         /* menu up */
	lbu	$t2, %lo(MENU)($t0)             /* state */
	beqz	$t1, Mret
	lui	$t3, %hi(STATE5)
	lw	$t3, %lo(STATE5)($t3)
	li	$t4, MENUS5
	bne	$t3, $t4, Mcard
	nop
	jal	modok                           /* menus.py's state table: the module patches the overlay */
	nop
	beqz	$v0, Mret
	nop
	li	$t9, MOD_AT + 0x20
	jalr	$t9
	nop
Mret:	jr	$s5
	nop
Mcard:	li	$t4, MOD_AT + 0x28              /* ours: the module's state-5 stub */
	bnez	$t2, Mret
	nop
	bne	$t3, $t4, Mret
	nop
	jal	modok
	nop
	beqz	$v0, Mret
	nop
	li	$t9, MOD_AT + 0x18              /* main menu idle: the card */
	jalr	$t9
	nop
	jr	$s5
	nop

#ifdef MODRELOAD
	/* -> v0 = 1 when the tail was read again (state 6 = parked EX OPTIONS press -> 0, as the gate does) */
	.section .text.mreload,"ax"
	.align 2
mreload:
	lui	$t0, %hi(MENU)
	lbu	$t1, %lo(MENU + 1)($t0)         /* menu up */
	lh	$t2, %lo(MENU + 0x30)($t0)      /* 0x8007b718: async file read pending (the file loader's flag) */
	lui	$t3, 0x8002
	lw	$t3, -0x1848($t3)               /* 0x8001e7b8: libcd CdRead sectors still to come (0 = no read in flight) */
	beqz	$t1, 9f
	move	$v0, $zero
	bnez	$t2, 9f
	nop
	bnez	$t3, 9f
	nop
	addiu	$sp, $sp, -24
	sw	$ra, 20($sp)
	li	$a0, RL_INDEX                   /* private file-table entry {msf, size} in the EXE (mktag.py) */
	li	$a1, RL_DEST                    /* the copy's tail sector in RAM */
	jal	0x80024800                      /* RD(index, dest): sync while the flag is 0 */
	nop
	lui	$t0, %hi(MENU)
	lbu	$t2, %lo(MENU)($t0)
	li	$t4, 6
	bne	$t2, $t4, 8f
	nop
	sb	$zero, %lo(MENU)($t0)
8:	lw	$ra, 20($sp)
	li	$v0, 1
	jr	$ra
	addiu	$sp, $sp, 24
9:	jr	$ra
	nop
	.section .text.menu,"ax"
#endif

#ifdef MENUFONT
	/* --menufont (2026-11-25, real PS1 + MiSTer: main menu text drawn as sprite tiles after attract battles): the menu font is
	   part of BATTLE.TEX's VRAM area (x896-1023 y0-255, glyphs at rows 32-63) and only battle loads upload it; on real CD
	   timing an attract-battle upload can carry stale buffer data, and the menu never uploads it again.  Once per main-menu
	   entry (latch MF_LATCH, cleared on any frame without the menu), CD idle (as mreload): RD the 8 KB of BATTLE.TEX rows
	   32-63 (private file-table entry MF_INDEX) into the battle arena (idle at the main menu), LoadImage (896,32,128,32),
	   DrawSync.  Busy CD -> retried next frame. */
	.section .text.mfont,"ax"
	.align 2
#ifdef MENUFONT2
	/* --menufont2 (2026-11-25, .24: VERSUS -> pause QUIT -> main menu still scrambled with --menufont: the latch-once reload
	   ran in a CD gap of the menu's own entry load; a later upload re-garbled the page).  No latch: every 32 main loops on the
	   main menu with the CD idle, StoreImage a 8x32 sample of the font page (920,32), DrawSync, word sum; != MF_SUM (the
	   BATTLE.TEX bytes) -> RD the 8 KB + LoadImage (896,32,128,32) + DrawSync.  Repairs whatever path / order garbles it. */
mfont:
	lui	$t0, %hi(MENU)
	lbu	$t1, %lo(MENU + 1)($t0)         /* menu up */
	lui	$t3, 0x8008
	beqz	$t1, 9f
	lw	$t3, -0x48b4($t3)               /* 0x8007b74c main loops */
	nop
	andi	$t3, $t3, 31
	bnez	$t3, 9f
	lh	$t2, %lo(MENU + 0x30)($t0)      /* async file read pending */
	lui	$t3, 0x8002
	lw	$t3, -0x1848($t3)               /* libcd sectors still to come */
	bnez	$t2, 9f
	nop
	bnez	$t3, 9f
	nop
	addiu	$sp, $sp, -560
	sw	$ra, 556($sp)
	li	$t0, 0x00200398                 /* RECT x 920, y 32 */
	sw	$t0, 16($sp)
	li	$t0, 0x00200008                 /* w 8, h 32 */
	sw	$t0, 20($sp)
	addiu	$a0, $sp, 16
	jal	0x80011b70                      /* StoreImage */
	addiu	$a1, $sp, 32
	jal	0x80011864                      /* DrawSync(0) */
	move	$a0, $zero
	addiu	$t1, $sp, 32
	addiu	$t2, $sp, 544
	move	$t3, $zero
1:	lw	$t4, 0($t1)
	addiu	$t1, $t1, 4
	bne	$t1, $t2, 1b
	addu	$t3, $t3, $t4
#ifdef DIAGMENU
	lui	$t4, 0x8001
	sw	$t3, -0x24($t4)                 /* diag: last sample sum -> 0x8000FFDC */
#endif
	li	$t4, MF_SUM
	beq	$t3, $t4, 8f
	nop
#ifdef DIAGMENU
	lui	$t4, 0x8001
	lw	$t5, -0xa4($t4)                 /* diag: repair count 0x8000FF5C */
	nop
	addiu	$t5, $t5, 1
	sw	$t5, -0xa4($t4)
#endif
	li	$a0, MF_INDEX
	li	$a1, MF_BUF
	jal	0x80024800                      /* RD(index, dest) */
	nop
	li	$t0, 0x00200380                 /* RECT x 896, y 32 */
	sw	$t0, 16($sp)
	li	$t0, 0x00200080                 /* w 128, h 32 */
	sw	$t0, 20($sp)
	addiu	$a0, $sp, 16
	li	$a1, MF_BUF
	jal	0x80011b10                      /* LoadImage */
	nop
	jal	0x80011864                      /* DrawSync(0) */
	move	$a0, $zero
8:	lw	$ra, 556($sp)
	nop
	jr	$ra
	addiu	$sp, $sp, 560
9:	jr	$ra
	nop
#else
mfont:
	lui	$t0, %hi(MENU)
	lbu	$t1, %lo(MENU + 1)($t0)         /* menu up */
	lui	$t5, %hi(MF_LATCH)
	bnez	$t1, 1f
	lw	$t6, %lo(MF_LATCH)($t5)
	jr	$ra
	sw	$zero, %lo(MF_LATCH)($t5)
1:	lh	$t2, %lo(MENU + 0x30)($t0)      /* async file read pending */
	bnez	$t6, 9f
	lui	$t3, 0x8002
	lw	$t3, -0x1848($t3)               /* libcd sectors still to come */
	bnez	$t2, 9f
	nop
	bnez	$t3, 9f
	nop
	addiu	$sp, $sp, -32
	sw	$ra, 28($sp)
	li	$t6, 1
	sw	$t6, %lo(MF_LATCH)($t5)
	li	$a0, MF_INDEX
	li	$a1, MF_BUF
	jal	0x80024800                      /* RD(index, dest) */
	nop
	li	$t0, 0x00200380                 /* RECT x 896, y 32 */
	sw	$t0, 16($sp)
	li	$t0, 0x00200080                 /* w 128, h 32 */
	sw	$t0, 20($sp)
	addiu	$a0, $sp, 16
	li	$a1, MF_BUF
	jal	0x80011b10                      /* LoadImage */
	nop
	jal	0x80011864                      /* DrawSync(0) */
	move	$a0, $zero
	lw	$ra, 28($sp)
	nop
	jr	$ra
	addiu	$sp, $sp, 32
9:	jr	$ra
	nop
#endif
	.section .text.menu,"ax"
#endif

#ifdef DIAGMENU
	/* TEST DISCS ONLY (env DIAG_MENU=1, 2026-11-25 menu-garbage probe on the real PS1): main menu + L1+R1+SELECT held (pad word
	   0x800204f2 == 0xf3fe) -> DrawSync; MoveImage the font page (896,0,128,256) to (0,0)/(0,256), the CLUT block (0,448,256,64)
	   to (128,0)/(128,256); 8 words as bit-blocks (4x8 px per bit, MSB left, white = 1) LoadImaged to (128,80)/(128,336):
	   w0 mfont2 last sum (0x8000FFDC)  w1 repair count (0x8000FF5C)  w2 *0x8007b6e8 (menu state)  w3 *0x800a2c68 (rows)
	   w4 sum 0x8009dfe4..0x80102e14 (OPDEMO stock part)  w5 sum 0x80102e14..0x8010d614 (tail + slack + module)
	   w6 *0x800b5c10 (state table [6])  w7 *MOD_AT ('ACHM')    then holds the picture ~8 s. */
	.section .text.diagm,"ax"
	.align 2
diagm:
	lui	$t0, %hi(MENU)
	lbu	$t1, %lo(MENU + 1)($t0)
	lui	$t0, 0x8002
	beqz	$t1, 9f
	lhu	$t1, 0x04f2($t0)
	li	$t2, 0xf3fe
	bne	$t1, $t2, 9f
	nop
	addiu	$sp, $sp, -88
	sw	$ra, 84($sp)
	sw	$s0, 80($sp)
	sw	$s1, 76($sp)
	sw	$s2, 72($sp)
	jal	0x80011864                      /* DrawSync(0) */
	move	$a0, $zero
	lui	$t0, 0x8001
	lw	$t1, -0x24($t0)
	lw	$t2, -0xa4($t0)
	sw	$t1, 16($sp)
	sw	$t2, 20($sp)
	lui	$t0, 0x8008
	lw	$t1, -0x4918($t0)               /* 0x8007b6e8 */
	nop
	sw	$t1, 24($sp)
	lui	$t0, 0x800a
	lw	$t1, 0x2c68($t0)                /* 0x800a2c68 */
	nop
	sw	$t1, 28($sp)
	li	$a0, 0x8009dfe4
	li	$a1, 0x80102e14
	bal	dsum
	nop
	sw	$v0, 32($sp)
	li	$a0, 0x80102e14
	li	$a1, 0x8010d614
	bal	dsum
	nop
	sw	$v0, 36($sp)
	lui	$t0, 0x800b
	lw	$t1, 0x5c10($t0)                /* 0x800b5c10 */
	nop
	sw	$t1, 40($sp)
	li	$t0, MOD_AT
	lw	$t1, 0($t0)
	nop
	sw	$t1, 44($sp)
	/* bitmap 128 x 64 halfwords at 0x80094c40: word w -> rows 8w..8w+7, bit b (MSB first) -> x 4b..4b+2, x 4b+3 = gap */
	li	$s0, 0x80094c40
	move	$t4, $zero                      /* w */
1:	sll	$t0, $t4, 2
	addu	$t0, $t0, $sp
	lw	$t7, 16($t0)                    /* value */
	move	$t6, $zero                      /* row r */
2:	move	$t5, $zero                      /* bit b */
3:	li	$t0, 31
	subu	$t0, $t0, $t5
	srlv	$t1, $t7, $t0
	andi	$t1, $t1, 1
	li	$t2, 0x0842                     /* 0: dark grey */
	beqz	$t1, 4f
	nop
	li	$t2, 0x7fff                     /* 1: white */
4:	sll	$t0, $t4, 3                     /* pixel index = ((8w + r) * 128 + 4b) halfwords */
	addu	$t0, $t0, $t6
	sll	$t0, $t0, 7
	sll	$t1, $t5, 2
	addu	$t0, $t0, $t1
	sll	$t0, $t0, 1
	addu	$t0, $t0, $s0
	sh	$t2, 0($t0)
	sh	$t2, 2($t0)
	sh	$t2, 4($t0)
	sh	$zero, 6($t0)
	addiu	$t5, $t5, 1
	slti	$t0, $t5, 32
	bnez	$t0, 3b
	nop
	addiu	$t6, $t6, 1
	slti	$t0, $t6, 8
	bnez	$t0, 2b
	nop
	addiu	$t4, $t4, 1
	slti	$t0, $t4, 8
	bnez	$t0, 1b
	nop
	li	$t0, 0x00500080                 /* RECT x 128, y 80 */
	sw	$t0, 48($sp)
	li	$t0, 0x00400080                 /* w 128, h 64 */
	sw	$t0, 52($sp)
	addiu	$a0, $sp, 48
	jal	0x80011b10                      /* LoadImage */
	move	$a1, $s0
	li	$t0, 0x01500080                 /* x 128, y 336 */
	sw	$t0, 48($sp)
	addiu	$a0, $sp, 48
	jal	0x80011b10
	move	$a1, $s0
	li	$t0, 0x00000380                 /* font page x 896, y 0 */
	sw	$t0, 56($sp)
	li	$t0, 0x01000080                 /* w 128, h 256 */
	sw	$t0, 60($sp)
	addiu	$a0, $sp, 56
	move	$a1, $zero
	jal	0x80011bd0                      /* MoveImage(rect, 0, 0) */
	move	$a2, $zero
	addiu	$a0, $sp, 56
	move	$a1, $zero
	jal	0x80011bd0                      /* -> (0, 256) */
	li	$a2, 256
	li	$t0, 0x01c00000                 /* CLUT block x 0, y 448 */
	sw	$t0, 64($sp)
	li	$t0, 0x00400100                 /* w 256, h 64 */
	sw	$t0, 68($sp)
	addiu	$a0, $sp, 64
	li	$a1, 128
	jal	0x80011bd0                      /* -> (128, 0) */
	move	$a2, $zero
	addiu	$a0, $sp, 64
	li	$a1, 128
	jal	0x80011bd0                      /* -> (128, 256) */
	li	$a2, 256
	jal	0x80011864                      /* DrawSync(0) */
	move	$a0, $zero
	li	$t0, 0x04000000                 /* hold ~8 s */
5:	addiu	$t0, $t0, -1
	bnez	$t0, 5b
	nop
	lw	$ra, 84($sp)
	lw	$s0, 80($sp)
	lw	$s1, 76($sp)
	lw	$s2, 72($sp)
	jr	$ra
	addiu	$sp, $sp, 88
9:	jr	$ra
	nop
dsum:	move	$v0, $zero
6:	lw	$t0, 0($a0)
	addiu	$a0, $a0, 4
	bne	$a0, $a1, 6b
	addu	$v0, $v0, $t0
	jr	$ra
	nop
	.section .text.menu,"ax"
#endif

#ifdef CORE_SPLIT
	/* (rc4.12) --titlefix + --achfix: the menu section no longer fits a span whole; corebuild retries with modok in its
	   own section (exact packing).  Builds that fit first-fit never set CORE_SPLIT (bytes unchanged). */
	.section .text.modok,"ax"
	.align 2
#endif
/* the module is there and whole: 'ACHM', sum of its code + rodata words (+0x10 .. +[0xc]) = [8] */
modok:
	li	$t0, MOD_AT
	lw	$t1, 0($t0)
	li	$t2, 0x4d484341
	bne	$t1, $t2, 2f
	lw	$t3, 12($t0)                    /* ro end */
	nop
	sltiu	$t4, $t3, MOD_MAX
	beqz	$t4, 2f
	sltiu	$t4, $t3, 0x20
	bnez	$t4, 2f
	addu	$t3, $t0, $t3
	addiu	$t5, $t0, 16
	move	$t6, $zero
1:	lw	$t7, 0($t5)
	addiu	$t5, $t5, 4
	bne	$t5, $t3, 1b
	addu	$t6, $t6, $t7
	lw	$t7, 8($t0)
	nop
	xor	$v0, $t6, $t7
	jr	$ra
	sltiu	$v0, $v0, 1
2:	jr	$ra
	move	$v0, $zero
