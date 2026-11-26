/* tools/tagload/link.ld + the 8 MB stub (ap8stub.c, entry8.S) and its directory .dir8 (mkap8.py).  Word 0 of the
 * blob (glue.o .entry: j tl_wrap) is patched to j ap8_ent by mkap8.py; ARENA + 8 stays j tl_restore. */
SECTIONS {
  .g1 0x8002547c : { glue.o(.g1) }
  .g2 0x8001780c : { glue.o(.g2) }
  .res 0x8001b454 : { glue.o(.res) }
  .rh 0x80014774 : { glue.o(.rh) }
  .hg 0x800858b0 : { glue.o(.hg) }
  .post 0x801fd700 : { glue.o(.post) }
  .blob 0x80092c40 : { glue.o(.entry) *(.text) *(.text.*) *(.rodata*) *(.data*) *(.sdata*) *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); *(.dir8) . = ALIGN(4); *(.sdir) . = ALIGN(4); *(.dir) . = ALIGN(4); }  blob_end = .;
  tl_strong = blob_end;
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) }
}
