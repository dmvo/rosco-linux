#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
kernel=${ROSCO_LINUX_SOURCE:-"$root/../linux-rosco"}
cross="$root/toolchain/install/bin/m68k-linux-gnu-"
out="$root/out/linux"
jobs=${ROSCO_BUILD_JOBS:-2}
for_split=0
if [[ ${1:-} == --for-split ]]; then
    for_split=1
    shift
fi

if [[ ! -x "${cross}gcc" ]]; then
    echo "Build the Linux toolchain first: bash $root/toolchain/build.sh" >&2
    exit 1
fi
python3 "$root/toolchain/check.py"
export KBUILD_BUILD_USER=rosco
export KBUILD_BUILD_HOST=linux
export KBUILD_BUILD_VERSION=1
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git -C "$kernel" show -s --format=%ct HEAD)
export KBUILD_BUILD_TIMESTAMP
KBUILD_BUILD_TIMESTAMP=$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S UTC')
mkdir -p "$out" "$root/logs"
make -C "$kernel" O="$out" ARCH=m68k CROSS_COMPILE="$cross" \
    KCONFIG_ALLCONFIG=arch/m68k/configs/rosco_m68k_defconfig allnoconfig
make -C "$kernel" -j"$jobs" O="$out" ARCH=m68k CROSS_COMPILE="$cross" \
    vmlinux > "$root/logs/build-linux.log" 2>&1
"${cross}objcopy" -O binary "$out/vmlinux" "$root/out/linux.bin"
"${cross}size" "$out/vmlinux" | tee "$root/out/linux-size.txt"
"${cross}nm" -n "$out/vmlinux" > "$root/out/linux-symbols.txt"
python3 - "$root" "$for_split" <<'PY'
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
symbols = {}
for line in (root / 'out/linux-symbols.txt').read_text().splitlines():
    fields = line.split()
    if len(fields) == 3:
        symbols[fields[2]] = int(fields[0], 16)
assert symbols['_start'] == 0x1000, 'Unexpected kernel entry address'
if sys.argv[2] != '1':
    assert symbols['_end'] < 0x100000, 'RAM image is too large; use build-f020.sh'
    assert (root / 'out/linux.bin').stat().st_size <= 0xef000, 'Image exceeds loader limit'
if sys.argv[2] == '1':
    print(f"Intermediate RAM link ends at {symbols['_end']:#x}; split link required")
else:
    print(f"Static RAM end: {symbols['_end']:#x}; "
          f"space above kernel: {0x100000 - symbols['_end']} bytes")
PY
cp "$out/.config" "$root/out/linux.config"
git -C "$kernel" diff --binary > "$root/out/linux.patch"
sha256sum "$out/vmlinux" "$root/out/linux.bin" "$root/out/linux.config" \
    "$root/out/linux.patch" > "$root/out/linux.sha256"
make -C "$root" CROSS_COMPILE="$cross" loader
if [[ ${1:-} == --boot ]]; then
    if (( for_split )); then
        echo 'Use build-f020.sh --boot to load a split image' >&2
        exit 1
    fi
    shift
    exec python3 "$root/boot.py" "$root/out/linux.bin" "$@"
fi
