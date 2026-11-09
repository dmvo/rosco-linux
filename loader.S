/* SPDX-License-Identifier: GPL-2.0-only */
/* Stock Kermit loads this at 0x40000; the receiver runs below the kernel. */
	.section .text.start,"ax"
	.globl _start
_start:
	move.w #0x2700,%sr
	lea 0x100000,%sp
	lea receiver(%pc),%a0
	lea 0x800,%a1
	move.w #receiver_end-receiver-1,%d0
1:
	move.b (%a0)+,(%a1)+
	dbra %d0,1b
	jmp 0x800

receiver:
	moveq #0,%d0
	movec %d0,%vbr
	move.b %d0,0xf0000b
	move.l #0x800+fault-receiver,8
	move.l #0x800+fault-receiver,12
	move.l #0x800+fault-receiver,16
	move.l #0x800+fault-receiver,32
	lea ready(%pc),%a2
	bsr puts
command:
	suba.l %a5,%a5
	bsr read_be32
	cmp.l #0x52444231,%d1	/* RDB1: read the 512 KiB F020 window */
	beq dump_flash
	cmp.l #0x57465831,%d1	/* WFX1: write only 0xe20000..0xe7ffff */
	beq receive_flash
	cmp.l #0x57465832,%d1	/* WFX2: write only 0xe0c000..0xe7ffff */
	beq receive_flash_expanded
	cmp.l #0x524c4d31,%d1
	bne protocol_error
	bsr read_be32
	tst.l %d1
	beq protocol_error
	cmp.l #0xef000,%d1
	bhi protocol_error
	move.l %d1,%d4
	lea 0x1000,%a0
	moveq #'H',%d0
	bsr putchar
next_block:
	move.l #1024,%d7
	move.l %a5,%d0
	beq block_size_ready
	move.l #8192,%d7
block_size_ready:
	cmp.l %d7,%d4
	bcc full_block
	move.l %d4,%d7
full_block:
	move.l %a0,%a4
retry_block:
	move.l %a4,%a0
	move.l %d7,%d5
	moveq #-1,%d6
read_byte:
	bsr getchar
	move.b %d0,(%a0)+
	bsr crc_byte
	subq.l #1,%d5
	bne read_byte
	not.l %d6
	bsr read_be32
	cmp.l %d1,%d6
	beq block_ok
	moveq #'N',%d0
	bsr putchar
	bra retry_block
block_ok:
	move.l %a5,%d0
	beq block_ack
	bsr program_sector
	tst.l %d0
	bne flash_error
	lea 8192(%a5),%a5
	lea 0xf0000,%a0
block_ack:
	moveq #'A',%d0
	bsr putchar
	sub.l %d7,%d4
	bne next_block
	move.l %a5,%d0
	bne command
#ifdef ROSCO_WAIT_FOR_CONSOLE
	lea paused(%pc),%a2
	bsr puts
wait_for_console:
	bsr getchar
	cmp.b #13,%d0
	beq start_linux
	cmp.b #10,%d0
	bne wait_for_console
start_linux:
#endif
	lea entering(%pc),%a2
	bsr puts
	jmp 0x1000

receive_flash:
	lea 0xe20000,%a5
	move.l #0x60000,%d3
	bra receive_flash_length
receive_flash_expanded:
	lea 0xe0c000,%a5
	move.l #0x74000,%d3
receive_flash_length:
	bsr read_be32
	tst.l %d1
	beq flash_error
	cmp.l %d3,%d1
	bhi flash_error
	move.l %d1,%d0
	and.l #8191,%d0
	bne flash_error
	move.l %d1,%d4
	bsr flash_identify
	tst.l %d0
	bne flash_error
	lea 0xf0000,%a0
	moveq #'F',%d0
	bsr putchar
	bra next_block

flash_error:
	move.w #0xf0f0,0xe00000
	moveq #'E',%d0
	bsr putchar
	bra command

/* Each 16-bit command operates on both interleaved x8 chips. */
flash_command:
	move.w #0xaaaa,0xe0aaaa
	move.w #0x5555,0xe05554
	move.w %d0,0xe0aaaa
	rts

flash_identify:
	move.w #0x9090,%d0
	bsr flash_command
	nop
	nop
	move.w 0xe00000,%d1
	move.w 0xe00002,%d2
	move.w #0xf0f0,0xe00000
	moveq #-1,%d0
	cmp.w #0xbfbf,%d1
	bne identify_done
	cmp.w #0xb6b6,%d2
	bne identify_done
	moveq #0,%d0
identify_done:
	rts

/* CRC has already validated the complete sector buffer at 0xf0000.
 * A5 is constrained to the selected bounded window by receive_flash and D4.
 * The lowest 48 KiB are unreachable by either flash-write command.
 * There is deliberately no chip-erase command or arbitrary write address.
 */
program_sector:
	move.w #0x8080,%d0
	bsr flash_command
	move.w #0xaaaa,0xe0aaaa
	move.w #0x5555,0xe05554
	move.w #0x3030,(%a5)
	move.l #100000,%d5
erase_wait:
	cmp.w #-1,(%a5)
	beq erase_done
	subq.l #1,%d5
	bne erase_wait
	bra flash_failed
erase_done:
	nop
	nop
	move.l %a5,%a1
	move.w #4095,%d3
check_erased:
	cmp.w #-1,(%a1)+
	bne flash_failed
	dbra %d3,check_erased
	lea 0xf0000,%a0
	move.l %a5,%a1
	move.w #4095,%d3
program_word:
	move.w (%a0)+,%d6
	cmp.w #-1,%d6
	beq program_next
	move.w #0xa0a0,%d0
	bsr flash_command
	move.w %d6,(%a1)
	move.l #100000,%d5
program_wait:
	cmp.w (%a1),%d6
	bne program_busy
	nop
	nop
	cmp.w (%a1),%d6
	beq program_next
program_busy:
	subq.l #1,%d5
	bne program_wait
	bra flash_failed
program_next:
	addq.l #2,%a1
	dbra %d3,program_word
	lea 0xf0000,%a0
	move.l %a5,%a1
	move.w #4095,%d3
verify_word:
	cmpm.w (%a0)+,(%a1)+
	bne flash_failed
	dbra %d3,verify_word
	moveq #0,%d0
	rts
flash_failed:
	moveq #-1,%d0
	rts

/* Read only: this command never writes to the flash address window. */
dump_flash:
	lea 0xe00000,%a0
	move.l #0x80000,%d4
	moveq #'B',%d0
	bsr putchar
dump_block:
	move.l %a0,%a4
dump_retry:
	move.l %a4,%a0
	move.w #1023,%d5
	moveq #-1,%d6
dump_byte:
	moveq #0,%d0
	move.b (%a0)+,%d0
	bsr putchar
	bsr crc_byte
	dbra %d5,dump_byte
	not.l %d6
	move.l %d6,%d1
	bsr write_be32
	bsr getchar
	cmp.b #'N',%d0
	beq dump_retry
	cmp.b #'A',%d0
	bne protocol_error
	sub.l #1024,%d4
	bne dump_block
	bra command

crc_byte:
	eor.l %d0,%d6
	moveq #7,%d2
crc_bit:
	lsr.l #1,%d6
	bcc crc_next
	eor.l #0xedb88320,%d6
crc_next:
	dbra %d2,crc_bit
	rts

write_be32:
	moveq #3,%d3
write_word_byte:
	rol.l #8,%d1
	move.b %d1,%d0
	bsr putchar
	dbra %d3,write_word_byte
	rts

read_be32:
	moveq #0,%d1
	moveq #3,%d2
read_word_byte:
	bsr getchar
	lsl.l #8,%d1
	or.l %d0,%d1
	dbra %d2,read_word_byte
	rts

getchar:
	btst #0,0xf00003
	beq getchar
	moveq #0,%d0
	move.b 0xf00007,%d0
	rts

putchar:
	btst #2,0xf00003
	beq putchar
	move.b %d0,0xf00007
	rts

puts:
	move.b (%a2)+,%d0
	beq puts_done
	bsr putchar
	bra puts
puts_done:
	rts

protocol_error:
	lea error(%pc),%a2
	bsr puts
halt:
	stop #0x2700
	bra halt

fault:
	move.w #0x2700,%sr
	move.l %sp,%a3
	lea fault_pc(%pc),%a2
	bsr puts
	move.l 2(%a3),%d1
	bsr hex32
	lea fault_format(%pc),%a2
	bsr puts
	moveq #0,%d1
	move.w 6(%a3),%d1
	bsr hex32
	lea newline(%pc),%a2
	bsr puts
	bra halt

hex32:
	moveq #7,%d2
hex_digit:
	rol.l #4,%d1
	move.b %d1,%d0
	and.b #15,%d0
	add.b #'0',%d0
	cmp.b #'9',%d0
	bls hex_emit
	add.b #7,%d0
hex_emit:
	bsr putchar
	dbra %d2,hex_digit
	rts

ready: .asciz "\r\nROSCO-RAM-READY\r\n"
#ifdef ROSCO_WAIT_FOR_CONSOLE
paused: .asciz "\r\nROSCO-LINUX-PAUSED\r\n"
#endif
entering: .asciz "\r\nRAM loader: entering Linux\r\n"
error: .asciz "\r\nRAM loader: invalid header\r\n"
fault_pc: .asciz "Early fault: PC="
fault_format: .asciz " format/vector="
newline: .asciz "\r\n"
	.balign 2
receiver_end:
