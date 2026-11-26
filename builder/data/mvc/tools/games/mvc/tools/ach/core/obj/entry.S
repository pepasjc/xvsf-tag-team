	.set noreorder
	.section .text.entry,"ax"
	.globl _start
_start:
	j	ach_frame
	nop
	.space 0x14
	.word	0
