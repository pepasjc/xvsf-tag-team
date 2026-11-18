# Region 0x80018db4-0x80018f20: libgpu's queue timeout check (called by DrawSync and by _addque's queue-full
# wait) rewritten compactly - same memory effects (the timeout path's two TTY printf()s dropped), normal path
# leaving v0 = 0, v1 = old poll count, at = 0x80020000 as stock - and kchk: _exeque, GPU busy, called by _addque
# (flag EBV+36) -> return with the entry queued instead of spinning.  (A root-counter-0 kick that started the queue
# from an IRQ was tried and dropped: slower than letting the next libgpu call start it, see REPORT round 5.)
# Symbols from other regions (passed with .set): exq3, exq5, EBV.

tchk:
    addiu $sp, $sp, -0x20
    sw    $ra, 0x18($sp)
    jal   0x80011960                    # VSync(-1)
    addiu $a0, $zero, -1
    lui   $at, 0x8002
    lw    $v1, 0x263c($at)              # deadline (vblank count)
    nop
    slt   $v1, $v1, $v0
    bnez  $v1, terr
    lw    $v1, 0x2640($at)              # poll count
    nop
    addiu $v0, $v1, 1
    sw    $v0, 0x2640($at)
    lui   $v0, 0xf
    slt   $v0, $v0, $v1
    bnez  $v0, terr
    nop
tret:
    lw    $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
    jr    $ra
    nop
terr:                                   # GPU timeout (4 s without progress): reset the queue as stock (stock also
    jal   0x80011cc0                    # printf()s two TTY diagnostics first; dropped for space)  SetIntrMask(0)
    move  $a0, $zero
    lui   $at, 0x8002
    sw    $zero, 0x262c($at)
    sw    $v0, 0x2638($at)
    sw    $zero, 0x2628($at)
    lw    $v1, 0x2604($at)
    lw    $t0, 0x2614($at)
    ori   $v0, $zero, 0x401
    sw    $v0, 0($v1)                   # DMA2 CHCR = 0x401
    lw    $v0, 0($t0)
    lw    $v1, 0x25f8($at)
    ori   $v0, $v0, 0x800
    sw    $v0, 0($t0)                   # DPCR |= 0x800
    lui   $v0, 0x0200
    sw    $v0, 0($v1)                   # GP1(02)
    lui   $v0, 0x0100
    sw    $v0, 0($v1)                   # GP1(01)
    lw    $a0, 0x2638($at)
    jal   0x80011cc0                    # SetIntrMask(saved)
    nop
    b     tret
    addiu $v0, $zero, -1

kchk:                                   # from _exeque, GPU busy: non-blocking caller (EBV+36 set by _addque)?
    lui   $v0, %hi(EBV)
    lw    $v0, %lo(EBV)+36($v0)
    nop
    bnez  $v0, 1f
    nop
    j     exq3                          # no: wait for the GPU as stock
    nop
1:  j     exq5                          # yes: leave the entry queued; the next libgpu call, the DMA-completion
    nop                                 # callback or DrawSync starts it (at = 0x80020000 for exq5)
gpuq3_end:
# A0 stubs (frame.py patches()): bcopy/bzero/memcpy/memset of >= MEM_BIOS_MIN bytes go to the BIOS as stock
# (t1 = function number is already set; t2 = 0xa0 as the stock stub leaves it)
a0bios:
    ori   $t2, $zero, 0xa0
    jr    $t2
    nop
