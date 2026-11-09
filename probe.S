/* SPDX-License-Identifier: GPL-2.0-only */
/* RAM-only inventory probe, loaded by the stock firmware at 0x40000. */

	.section .text.start,"ax"
	.globl _start
_start:
	move.w #0x2700,%sr
	lea 0x100000,%sp
	lea banner,%a0
	bsr puts
	move.l 0x400,%d0
	bsr hex32
	lea memory,%a0
	bsr puts
	move.l 0x414,%d0
	bsr hex32
	lea cpu,%a0
	bsr puts
	move.l 0x41c,%d0
	bsr hex32
	lea uart,%a0
	bsr puts
	move.l 0x418,%d0
	bsr hex32
	lea firmware,%a0
	bsr puts
	move.l 0xe00400,%d0
	bsr hex32
	lea vbr,%a0
	bsr puts
	movec %vbr,%d0
	bsr hex32
	bsr test_faults
	lea ready,%a0
	bsr puts
1:
	btst #0,0xf00003
	beq 1b
	move.b 0xf00007,%d0
	bsr putc
	bra 1b

/* MC68010 format 8 is 58 bytes; recover through a fresh format 0 frame. */
test_faults:
	move.l %sp,%a3
	move.l #fault8,0x0c
	move.l #fault8,0x08
	move.l #address_done,fault_resume
	move.w 1,%d0
address_done:
	lea address_result,%a0
	bsr puts
	bsr print_fault
	cmp.l %sp,%a3
	bne failed
	move.l #bus_done,fault_resume
	move.w 0x800000,%d0
bus_done:
	lea bus_result,%a0
	bsr puts
	bsr print_fault
	cmp.l %sp,%a3
	bne failed
	rts

fault8:
	move.w 6(%sp),fault_format
	move.w 8(%sp),fault_ssw
	move.l 10(%sp),fault_address
	move.l 2(%sp),fault_pc
	move.w (%sp),50(%sp)
	move.l fault_resume,52(%sp)
	clr.w 56(%sp)
	lea 50(%sp),%sp
	rte

print_fault:
	moveq #0,%d0
	move.w fault_format,%d0
	bsr hex32
	lea fault_address_label,%a0
	bsr puts
	move.l fault_address,%d0
	bsr hex32
	lea fault_ssw_label,%a0
	bsr puts
	moveq #0,%d0
	move.w fault_ssw,%d0
	bsr hex32
	lea fault_pc_label,%a0
	bsr puts
	move.l fault_pc,%d0
	bsr hex32
	rts

failed:
	lea failed_message,%a0
	bsr puts
1:
	stop #0x2700
	bra 1b

putc:
	btst #2,0xf00003
	beq putc
	move.b %d0,0xf00007
	rts

puts:
	move.b (%a0)+,%d0
	beq 1f
	bsr putc
	bra puts
1:
	rts

hex32:
	move.l %d0,%d2
	moveq #7,%d1
1:
	rol.l #4,%d2
	move.l %d2,%d0
	and.l #15,%d0
	add.b #'0',%d0
	cmp.b #'9',%d0
	bls 2f
	add.b #7,%d0
2:
	bsr putc
	dbra %d1,1b
	rts

banner: .asciz "\r\nROSCO LINUX inventory probe (RAM only)\r\nSDB magic=0x"
memory: .asciz " RAM bytes=0x"
cpu: .asciz " CPU info=0x"
uart: .asciz "\r\nUART=0x"
firmware: .asciz " ROM version word=0x"
vbr: .asciz " VBR=0x"
address_result: .asciz "\r\nAddress error format/vector=0x"
bus_result: .asciz "\r\nBus error format/vector=0x"
fault_address_label: .asciz " fault=0x"
fault_ssw_label: .asciz " ssw=0x"
fault_pc_label: .asciz " saved_pc=0x"
failed_message: .asciz "\r\nFAIL: exception did not restore SP\r\n"
ready: .asciz "\r\nProbe ready; polling UART echo. Reset to return to firmware.\r\n"

	.data
	.balign 2
fault_resume: .long 0
fault_address: .long 0
fault_pc: .long 0
fault_format: .word 0
fault_ssw: .word 0
