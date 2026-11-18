SECTIONS {
  .chunke 0x80015604 : { *(.chunke) }              e_end = .;      /* 156 bytes */
  .chunkf 0x8001667c : { *(.chunkf) *(.chunkf_data) }  f_end = .;      /* 156 bytes */
  .chunkd 0x800168a4 : { *(.chunkd) }              d_end = .;
  .chunkc 0x80016bcc : { *(.chunkc) }              c_end = .;      /* 284 bytes */
  .chunka 0x800171c8 : { *(.chunka_head) *(.chunka) *(.text) *(.text.*) *(.data*) }  a_end = .;
  .dbg    0x80017350 : { *(.dbg) }
  .chunkb 0x800173b8 : { *(.chunkb) }              b_end = .;
  .chunkg 0x8008f4d0 : { *(.chunkg) }              g_end = .;      /* 136 bytes, break-tested free range */
  /* directory sectors are read to 0x801fe004: 616 bytes of tables, then code; magic+checksum at +2040.
     .ram = policy code of the main directory, .ramb = code of the boss directory (same address) */
  OVERLAY 0x801fe26c : {
    .ram  { *(.ram0) *(.ram) *(.rodata*) ram_end = .; }      /* plan() first */
    .ramb { *(.ramb0) *(.ramb) ramb_end = .; }               /* bplan() first: same address as plan() */
  }
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) *(.eh_frame) *(.bss) }
}
