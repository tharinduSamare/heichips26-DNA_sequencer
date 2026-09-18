ENTRY(_start)

MEMORY
{
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 4K
}

SECTIONS
{
    .text : ALIGN(4)
    {
        *(.text.init)
        *(.text*)
    } > RAM

    .rodata : ALIGN(4)
    {
        *(.rodata*)
    } > RAM

    .data : ALIGN(4)
    {
        *(.data*)
    } > RAM

    .bss : ALIGN(4)
    {
        *(.bss*)
        *(COMMON)
    } > RAM

    /*
     * Stack starts at the top of RAM
     * and grows downward.
     */
    _stack_top = ORIGIN(RAM) + LENGTH(RAM);
}