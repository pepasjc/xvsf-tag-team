SECTIONS {
  . = 0x80010440;
  .text : { *(.text*) *(.rodata*) *(.data*) }
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }
}
