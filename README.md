# rosco-linux: Linux bring-up on rosco_m68k R2

These are the host tools, bare-metal loader, minimal userspace and evidence
from booting modern upstream Linux on a
[rosco_m68k](https://github.com/rosco-m68k/rosco_m68k) revision 2 board:
an MC68010 at 8 MHz with 1 MiB of RAM and no MMU.

The kernel changes are on branch [`rosco-m68k-r2-poc`](https://github.com/dmvo/linux/tree/rosco-m68k-r2-poc)
of a Linux fork. See `README.rosco_m68k.md` on that branch.

**Status (2026-10-22): proof of concept, verified on real hardware.**
Linux detects the SDHC card, mounts a read-only ROMFS root from it and runs
a FLAT `/init` as PID 1, which does `getpid()` and echoes UART input. There
is no shell yet.

```
rosco_m68k R2: MC68010, 1 MiB RAM, split RAM/flash kernel
xr68c681: ttySC0 MMIO:0x00f00001 (irq = 5, base_baud = 230400) is a XR68C681
mmc0: new SDHC card on SPI
mmcblk0: mmc0:0000 TSBBH 3.69 GiB
VFS: Mounted root (romfs filesystem) readonly on device 179:0.
Run /init as init process
ROSCO Linux userspace from SD; getpid=0x00000001
userspace read: enter a line
Hello, 68010!
userspace received: Hello, 68010!
```

The full session, from the stock firmware banner to the reply, is in
[`logs/screen-20261022T204440Z.log`](logs/screen-20261022T204440Z.log).

## How it fits in 1 MiB

| | |
| --- | --- |
| Board RAM | 1 MiB, 0x000000–0x0fffff, kernel linked at 0x1000 |
| Board flash | 2 × SST39SF020A, 512 KiB, 0xe00000–0xe7ffff |
| Stock firmware | rosco Classic 2.42. It uses the first 43858 bytes; 0xe00000–0xe0bfff (48 KiB) is kept untouched |
| Kernel text in flash | 472044 bytes, run in place from 0xe0c000 |
| Kernel image in RAM | 587236 bytes, static end 0x96158 |
| Console | XR68C681 DUART at 0xf00001, channel A, 115200 8N1, `ttySC0` |
| SD card | SPI bit-banged on DUART pins: OP2=CS, OP4=SCK, OP6=MOSI, IP2=MISO |
| Root filesystem | 1 KiB ROMFS written to the whole card (no partition table) |
| `/init` | 356-byte FLAT binary, written in assembly |

The kernel is linked normally and then split by `split_xip.py`. Ordinary
function sections go to the free part of flash. Entry code, init code,
the scheduler, data and BSS stay in RAM.

## Boot flow

1. Press Reset. With no bootable media, the stock firmware waits for a
   Kermit upload.
2. `run.py` sends the 1064-byte `loader.bin` through C-Kermit. The loader
   moves its receiver to 0x800.
3. `boot.py` reads the whole flash back and compares it with the
   expected image. Only if it differs does it program the kernel window
   with the `WFX2` command: 8 KiB sector pairs, each CRC-checked and
   verified word by word. A one-sector trial runs first, and the full
   array is read back afterwards. The firmware area is never written.
4. `boot.py` uploads the RAM image to 0x1000 in 1 KiB CRC32 blocks (about
   55 s at 115200) and the loader jumps to the kernel.
5. The terminal stays attached to the UART for the Linux console.

The flash chips are programmed in their sockets and are never removed.

## Layout

```
boot.py, run.py           host loader: Kermit stage, flash check/program, RAM upload, terminal
loader.S, loader.ld       bare-metal RAM receiver and flash programmer (68010 assembly)
build.sh                  build the kernel from ../linux-rosco (RAM-only link)
build-f020.sh             build + split into RAM/flash images for the F020 pair
split_xip.py              host relink of kernel text into flash
boot-screen.sh            the demo: GNU screen + boot.py, firmware banner through to Linux
boot-terminal.sh          the same without GNU screen
console_view.py           optional shortened view of a log (keeps all warnings and errors)
serial_capture.py         plain UART capture
test_flash_protocol.py    PTY tests of the flash protocol (bad CRC, refusals, readback)
test_sections.py          tests of kernel text range classification for the split
probe.S, ramboot.S, alignment.c, probe.ksc
                          early hardware probe and toolchain alignment checks
toolchain/                GCC 15.2 + binutils 2.42 m68k-linux-gnu build with strict-alignment patch
userspace/                /init, ROMFS builder (pinned genromfs), SD writer
logs/                     real UART logs from every board attempt
out/attempt-13/           manifest, hashes and config of the verified image
STATUS.txt                detailed engineering log of the bring-up, attempt by attempt
```

## Reproducing

You need a rosco_m68k R2 with an MC68010, a USB-TTL adapter on DUART
channel A, the flash-write jumper JP3 fitted, and a microSD card. On the
host (Ubuntu) you need: a build environment for GCC (GMP/MPFR/MPC
headers), `curl`, `ripgrep`, `python3`, C-Kermit (`kermit`) and GNU
`screen`. Your user must be in the `dialout` group.

```sh
git clone -b rosco-m68k-r2-poc https://github.com/dmvo/linux.git linux-rosco
git clone https://github.com/dmvo/rosco-linux.git
cd rosco-linux

bash toolchain/build.sh                 # m68k-linux-gnu GCC 15.2 into toolchain/install
bash build-f020.sh                      # -> out/split-f020/{ram.bin,flash.bin,manifest.json}
python3 userspace/build-rootfs.py       # -> out/userspace/rootfs.romfs
```

Write the ROMFS image to the start of the whole SD card (not a partition):
`sudo dd if=out/userspace/rootfs.romfs of=/dev/sdX conv=fsync`.
`userspace/prepare-sd.py` does this with a read-back check. It writes only
the card you name by `/dev/disk/by-id` path, reader serial number and exact
capacity, and refuses if any of them differs. To find them:
`ls -l /dev/disk/by-id/ | grep usb-`, `udisksctl info -b /dev/sdX | grep Serial`
and `lsblk -bdno SIZE /dev/sdX`. Run it once without `--write` to check.

Before the first flash update, save a backup of your original flash (the
flash is read twice and both reads must match):

```sh
python3 boot.py out/split-f020/ram.bin --backup-flash out/backups/f020-original.bin
```

The kernel window is still empty at this point, so the RAM image that is
uploaded after the backup will not boot. Press Reset and continue.
Normal build-and-boot cycle:

```sh
bash build-f020.sh --boot --protected-backup out/backups/f020-original.bin --terminal
```

Press Reset when the host rings the bell. `Ctrl-]` disconnects. Updates
refuse to run if the firmware area of the flash does not match the backup.

The build is reproducible. Repeated builds gave identical `vmlinux`, RAM
image, flash image and config, and the SHA-256 sums of the verified image
are in `out/attempt-13/manifest.json`.

## What is not done

- No shell or C library userspace yet. The next step is BusyBox, with a
  writable filesystem.
- The RAM/flash split is a host-side relink. It is not kernel Kconfig/XIP
  support.
- The memory-reserve changes in the kernel are hacks for 1 MiB. They are
  not upstreamable as they stand.
- 68010 user faults and signals have not been exercised on hardware.
- Upstream submission has not been started.

## License

GPL-2.0-only (see SPDX headers and `COPYING`).
