SECTIONS {
  .mod 0x80200000 : { ap8m.o(.text.start) *(.text) *(.text.*) *(.rodata*) *(.data*) *(.sdata*) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); *(.dir8m) . = ALIGN(4); m_sdir = .; *(.sdir) . = ALIGN(4); *(.dir) . = ALIGN(4); m_end = .; }
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }
}
