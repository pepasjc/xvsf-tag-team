/* header of the per-battle predictor area at 0x801fe804 (read with the directory sector, tools/speed/decode/ahead_sector.py)
 *   +0  magic 0x50410000 (checked by the resident stub before it jumps to +0x14)
 *   +4  vc_lookup, +8 vc_prefetch (upload worker's cache; 0 = predictions discarded)
 *   +12 checksum of the area (words, without itself and the state word), +16 state (0 unchecked, 1 good, 2 bad)
 *   +20 entry: ahook(deadline, late) */
        .set    noreorder
        .section .text.head, "ax"
        .globl  ah_vc, ah_sum, ah_state, ah_start, ah_entry
ah_start:
        .word   0x50410000
ah_vc:  .word   0, 0
ah_sum: .word   0
ah_state: .word 0
ah_entry:
        j       ahook
        nop
