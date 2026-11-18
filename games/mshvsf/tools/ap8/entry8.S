/* blob entry of the 8 MB build: the glue calls ARENA+0 (tools/tagload/glue.S) */
        .set noreorder
        .section .entry8, "ax"
        j       ap8_main
        nop
