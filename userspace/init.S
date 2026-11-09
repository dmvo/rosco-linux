/* SPDX-License-Identifier: GPL-2.0-only */
/* Relocation-free FLAT smoke test: Linux m68k syscalls, no libc. */
	.section .text.start,"ax"
	.globl _start
_start:
	lea -192(%sp),%sp
	move.l %sp,%a5
	moveq #5,%d0		/* open("/dev/console", O_RDWR, 0) */
	lea console(%pc),%a0
	move.l %a0,%d1
	moveq #2,%d2
	moveq #0,%d3
	trap #0
	tst.l %d0
	bmi failed
	move.l %d0,%d6
	lea banner(%pc),%a0
	move.l #banner_end-banner,%d3
	bsr write_message
	moveq #20,%d0		/* getpid() */
	trap #0
	move.l %d0,%d4
	lea hex_digits(%pc),%a0
	move.l %a5,%a1
	moveq #7,%d5
pid_digit:
	rol.l #4,%d4
	move.l %d4,%d1
	and.w #15,%d1
	move.b (%a0,%d1.w),(%a1)+
	dbra %d5,pid_digit
	move.b #'\n',(%a1)
	move.l %a5,%a0
	moveq #9,%d3
	bsr write_message
again:
	lea prompt(%pc),%a0
	move.l #prompt_end-prompt,%d3
	bsr write_message
	moveq #3,%d0		/* read(fd, buffer, 128) */
	move.l %d6,%d1
	move.l %a5,%d2
	move.l #128,%d3
	trap #0
	tst.l %d0
	ble failed
	move.l %d0,%d7
	lea received(%pc),%a0
	moveq #received_end-received,%d3
	bsr write_message
	move.l %a5,%a0
	move.l %d7,%d3
	bsr write_message
	bra again

/* A0/count D3 -> write all, preserving D6 (fd), D7 (read length), A5. */
write_message:
	move.l %a0,%d2
write_more:
	moveq #4,%d0
	move.l %d6,%d1
	trap #0
	tst.l %d0
	ble failed
	add.l %d0,%d2
	sub.l %d0,%d3
	bne write_more
	rts
failed:
	moveq #29,%d0		/* Keep PID 1 alive if a syscall failed. */
	trap #0			/* pause() */
	bra failed

console:
	.asciz "/dev/console"
banner:
	.ascii "ROSCO Linux userspace from SD; getpid=0x"
banner_end:
prompt:
	.ascii "userspace read: enter a line\n"
prompt_end:
received:
	.ascii "userspace received: "
received_end:
hex_digits:
	.ascii "0123456789abcdef"
	.balign 4
