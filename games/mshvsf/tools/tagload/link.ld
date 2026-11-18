SECTIONS {
  .glue 0x80013580 : { glue.o(.glue) }  glue_end = .;
  .heapcap 0x80010df8 : { glue.o(.heapcap) }  heapcap_end = .;
  .blob 0x80087e10 : { glue.o(.entry) *(.text) *(.text.*) *(.rodata*) *(.data*) *(.sdata*) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); *(.sdir) . = ALIGN(4); *(.dir) . = ALIGN(4); }  blob_end = .;
  tl_strong = blob_end;
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }
}
