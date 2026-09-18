.section .text.init
.globl _start

_start:
    /*
     * Initialize stack pointer.
     */
    la sp, _stack_top

    /*
     * Call C main().
     */
    call main

1:
    j 1b