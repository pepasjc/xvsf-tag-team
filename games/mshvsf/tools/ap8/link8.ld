/* same layout as tools/tagload/link.ld; the blob entry is ap8_main (entry8.S) instead of tl_main; .dir8 = the 8 MB
 * content directory (mkap8.py); PAD (--defsym, mkap8.py) keeps room for the strong decoder in the blob's sectors */
SECTIONS {
  .glue 0x80013580 : { glue.o(.glue) }  glue_end = .;
  .heapcap 0x80010df8 : { glue.o(.heapcap) }  heapcap_end = .;
  .blob 0x80087e10 : { entry8.o(.entry8) *(.text) *(.text.*) *(.rodata*) *(.data*) *(.sdata*) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); *(.sdir) . = ALIGN(4); *(.dir8) . = ALIGN(4); . = . + PAD; *(.dir) . = ALIGN(4); }  blob_end = .;
  tl_strong = blob_end;
  /DISCARD/ : { glue.o(.entry) *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }
}
