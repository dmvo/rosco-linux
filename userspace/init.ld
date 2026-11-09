/* SPDX-License-Identifier: GPL-2.0-only */
OUTPUT_ARCH(m68k)
ENTRY(_start)
PHDRS { text PT_LOAD FLAGS(5); }
SECTIONS {
	. = 0;
	.text : { *(.text.start) *(.text*) *(.rodata*) } :text
	.data : { *(.data*) }
	.bss : { *(.bss*) *(COMMON) }
	ASSERT(SIZEOF(.data) == 0, "PIC init must not use a data segment")
	ASSERT(SIZEOF(.bss) == 0, "PIC init must not use a BSS segment")
	/DISCARD/ : { *(.comment) *(.note*) }
}
