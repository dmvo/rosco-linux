# Notes for coding agents

Read `README.md` first for the overview. This file has the facts and rules
that are easy to get wrong.

## Two repositories

- **Kernel**: https://github.com/dmvo/linux, branch `rosco-m68k-r2-poc`, based on upstream
  `7be4bc52fd9e`. The scripts expect it checked out at `../linux-rosco`,
  or set `ROSCO_LINUX_SOURCE=/path`. The rosco work is 5 commits on top of
  the base. Read them with `git log --stat 7be4bc52fd9e..`. Two of them
  are marked `HACK:`. Treat those as measurements of what 1 MiB needs,
  not as finished code.
- **This repository**: host tools, the loader, userspace and evidence.

## Hard rules (real hardware)

- **Never** ask anyone to remove the SST39SF0x0 flash chips from their
  sockets. All flash programming is done in place over UART.
- Do not open the serial port or start a boot unless the board owner says
  the board is connected and they are ready to press Reset. Only one
  process can hold `/dev/ttyUSB0`, and GNU screen keeps it even when
  detached.
- Never write the flash below 0xe0c000, which holds the stock firmware.
  `boot.py` enforces this using `--protected-backup` and refuses to run if
  the backup does not match. Do not weaken those checks.
- Do not weaken `userspace/prepare-sd.py`. It writes only the card the
  board owner names by by-id path, reader serial and capacity. Never guess
  those values; ask the owner. Writing the wrong block device destroys data.
- "It compiles", "it prints `Linux version`" and "it works in an emulator"
  are not proof that it boots on the board. Only a UART log from real
  hardware counts. Keep such logs in `logs/`.

## Build facts

- Toolchain: `toolchain/build.sh` builds binutils 2.42 + GCC 15.2.0 for
  `m68k-linux-gnu`. It needs the patch in `toolchain/` because stock
  `config/m68k/linux.h` turns off strict alignment and makes odd-address
  word/long accesses, which fault on a 68010. `toolchain/check.py`
  checks this, and `build.sh` runs it on every build.
- `build.sh` runs `allnoconfig` with `KCONFIG_ALLCONFIG=rosco_m68k_defconfig`,
  so the defconfig is the full configuration. `SOURCE_DATE_EPOCH` and
  `KBUILD_BUILD_*` are pinned so that builds are reproducible.
- `build-f020.sh` = `build.sh --for-split` + `split_xip.py`. Its output
  is `out/split-f020/{ram.bin,flash.bin,manifest.json}`. The manifest is
  what `boot.py --flash-manifest` uses, and the SHA-256 sums in it must
  match the images.
- The plain RAM-only image (`build.sh` without the split) no longer fits
  in 1 MiB with the SD/MMC stack enabled. It is still asserted by
  `build.sh`, but it is not used.
- Memory is the limit everywhere. After any config or code change, report
  `text/data/bss`, the static RAM end (`_end`) and the flash text size. If
  you can boot, also report free memory, as `STATUS.txt` does. The OOM
  history in `STATUS.txt` (attempts 03–10) shows which allocations hit
  the limit first.

## Tests that run without hardware

```sh
python3 test_flash_protocol.py     # flash protocol over a PTY: CRC retry, refusals, readback
python3 test_sections.py           # kernel text range classification for the split
python3 toolchain/check.py         # strict-alignment code generation check
```

## Evidence and history

- `STATUS.txt` is the full engineering log in chronological order. Later
  sections replace earlier "next" notes.
- `logs/linux-20261022-NN.*` are the attempts in order. The `.timed.log`
  files have host timestamps, `.flash.json` is the flash journal and
  `.console.json` is the userspace echo test result.
- The verified image is attempt 13: `out/attempt-13/manifest.json`,
  `SHA256SUMS`, `kernel.config`, `source.patch`. `source.patch` is the
  same as the kernel branch minus its README commit.

## Reasonable next steps (not started)

1. Clean up the sccnxp XR68C681 commit and the MC68010 trap/signal commit,
   and prepare them for upstream review. They are the most self-contained.
2. Replace the `HACK:` memory commits with something maintainers could
   accept, or keep them out of tree.
3. Test 68010 user faults (format 8) and signals on hardware.
4. Add a shell (BusyBox, FLAT), possibly on a board with SST39SF040 chips,
   which have more flash.

For kernel submissions, follow `Documentation/process/coding-assistants.rst`
in the kernel tree. Agents must not add `Signed-off-by:`, and the human
submitter must review and sign off.
