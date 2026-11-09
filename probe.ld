/* SPDX-License-Identifier: GPL-2.0-only */
OUTPUT_ARCH(m68k)
ENTRY(_start)
SECTIONS {
	. = 0x40000;
	.text : { *(.text.start) *(.text*) *(.rodata*) }
	.data : { *(.data*) }
	.bss : { *(.bss*) *(COMMON) }
}
