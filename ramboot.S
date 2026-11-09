/* SPDX-License-Identifier: GPL-2.0-only */
/* Move a kernel from the stock firmware's load address to low RAM. */
	.section .text.start,"ax"
	.globl _start
_start:
	move.w #0x2700,%sr
	lea 0x100000,%sp
	lea copy_stub,%a0
	lea 0x800,%a1
	move.w #copy_stub_end-copy_stub-1,%d0
1:
	move.b (%a0)+,(%a1)+
	dbra %d0,1b
	lea kernel_image,%a0
	lea 0x1000,%a1
	move.l #kernel_end-kernel_image,%d0
	jmp 0x800

copy_stub:
	moveq #0,%d1
	movec %d1,%vbr
	move.l #0x800+early_fault-copy_stub,8
	move.l #0x800+early_fault-copy_stub,12
	move.l #0x800+early_fault-copy_stub,16
	move.l #0x800+early_fault-copy_stub,32
	lea copying(%pc),%a2
	bsr puts
2:
	move.b (%a0)+,(%a1)+
	subq.l #1,%d0
	bne 2b
	lea entering(%pc),%a2
	bsr puts
	jmp 0x1000

early_fault:
	move.w #0x2700,%sr
	move.l %sp,%a3
	lea fault_pc(%pc),%a2
	bsr puts
	move.l 2(%a3),%d2
	bsr hex32
	lea fault_format(%pc),%a2
	bsr puts
	moveq #0,%d2
	move.w 6(%a3),%d2
	bsr hex32
	lea newline(%pc),%a2
	bsr puts
3:
	stop #0x2700
	bra 3b

puts:
	move.b (%a2)+,%d1
	beq 4f
	bsr putchar
	bra puts
4:
	rts

putchar:
	btst #2,0xf00003
	beq putchar
	move.b %d1,0xf00007
	rts

hex32:
	moveq #7,%d3
5:
	rol.l #4,%d2
	move.b %d2,%d1
	and.b #15,%d1
	add.b #'0',%d1
	cmp.b #'9',%d1
	bls 6f
	add.b #7,%d1
6:
	bsr putchar
	dbra %d3,5b
	rts

copying: .asciz "\r\nRAM loader: relocating kernel\r\n"
entering: .asciz "RAM loader: entering Linux\r\n"
fault_pc: .asciz "Early fault: PC="
fault_format: .asciz " format/vector="
newline: .asciz "\r\n"
	.balign 2
copy_stub_end:
	.balign 4
kernel_image:
	.incbin "out/kernel.bin"
kernel_end:
