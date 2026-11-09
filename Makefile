# SPDX-License-Identifier: GPL-2.0-only
CROSS_COMPILE ?= /opt/rosco/bin/m68k-elf-rosco-

.PHONY: all
all: out/probe.bin

.PHONY: loader
loader: out/loader.bin

.PHONY: loader-screen
loader-screen: out/loader-screen.bin

out/loader-screen.o: loader.S | out
	$(CROSS_COMPILE)gcc -m68010 -ffreestanding -DROSCO_WAIT_FOR_CONSOLE -c -o $@ $<

out/loader-screen.elf: out/loader-screen.o loader.ld probe.ld
	$(CROSS_COMPILE)ld -T loader.ld -Map out/loader-screen.map -o $@ $<

out/loader-screen.bin: out/loader-screen.elf
	$(CROSS_COMPILE)objcopy -O binary $< $@
	$(CROSS_COMPILE)objdump -d -m m68k:68010 $< > out/loader-screen.dis

out/loader.o: loader.S | out
	$(CROSS_COMPILE)gcc -m68010 -ffreestanding -c -o $@ $<

out/loader.elf: out/loader.o loader.ld probe.ld
	$(CROSS_COMPILE)ld -T loader.ld -Map out/loader.map -o $@ $<

out/loader.bin: out/loader.elf
	$(CROSS_COMPILE)objcopy -O binary $< $@
	$(CROSS_COMPILE)objdump -d -m m68k:68010 $< > out/loader.dis

.PHONY: ramboot
ramboot: out/ramboot.bin

out:
	mkdir -p $@

out/probe.o: probe.S | out
	$(CROSS_COMPILE)gcc -m68010 -ffreestanding -c -o $@ $<

out/probe.elf: out/probe.o probe.ld
	$(CROSS_COMPILE)ld -T probe.ld -Map out/probe.map -o $@ $<

out/probe.bin: out/probe.elf
	$(CROSS_COMPILE)objcopy -O binary $< $@
	$(CROSS_COMPILE)objdump -d -m m68k:68010 $< > out/probe.dis

out/kernel.bin: out/kernel/vmlinux
	$(CROSS_COMPILE)objcopy -O binary $< $@

out/ramboot.o: ramboot.S out/kernel.bin
	$(CROSS_COMPILE)gcc -m68010 -ffreestanding -c -o $@ $<

out/ramboot.elf: out/ramboot.o probe.ld
	$(CROSS_COMPILE)ld -T probe.ld -Map out/ramboot.map -o $@ $<

out/ramboot.bin: out/ramboot.elf
	$(CROSS_COMPILE)objcopy -O binary $< $@
	$(CROSS_COMPILE)size $<
