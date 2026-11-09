#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
jobs=${ROSCO_BUILD_JOBS:-2}
mkdir -p "$root/src" "$root/build-binutils-official" "$root/build-gcc" "$root/../logs"
cd "$root/src"
if [[ ! -f binutils-2.42.tar.xz ]]; then
    curl -L --fail --silent --show-error \
        https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz -o binutils-2.42.tar.xz
fi
if [[ ! -f gcc-15.2.0.tar.xz ]]; then
    curl -L --fail --silent --show-error \
        https://ftp.gnu.org/gnu/gcc/gcc-15.2.0/gcc-15.2.0.tar.xz -o gcc-15.2.0.tar.xz
fi
sha256sum -c <<'SUMS'
f6e4d41fd5fc778b06b7891457b3620da5ecea1006c6a4a41ae998109f85a800  binutils-2.42.tar.xz
438fd996826b0c82485a29da03a72d71d6e3541a83ec702df4271f6fe025d24e  gcc-15.2.0.tar.xz
SUMS
[[ -d binutils-2.42 ]] || tar -xf binutils-2.42.tar.xz
[[ -d gcc-15.2.0 ]] || tar -xf gcc-15.2.0.tar.xz
if ! rg -q '^#define STRICT_ALIGNMENT \(TARGET_STRICT_ALIGNMENT && !TARGET_68020\)' \
        gcc-15.2.0/gcc/config/m68k/linux.h; then
    patch -d gcc-15.2.0 -p1 < "$root/gcc-15.2.0-m68k-linux-alignment.patch"
fi
cd "$root/build-binutils-official"
if [[ ! -f Makefile ]]; then
    ../src/binutils-2.42/configure --target=m68k-linux-gnu --prefix="$root/install" \
        --disable-nls --disable-gdb --disable-gprofng --disable-werror \
        > "$root/../logs/binutils-official-config.log" 2>&1
fi
make -j"$jobs" all-binutils all-gas all-ld > "$root/../logs/binutils-official-build.log" 2>&1
make install-binutils install-gas install-ld > "$root/../logs/binutils-official-install.log" 2>&1
if [[ ${1:-} == --binutils-only ]]; then
    exit 0
fi
cd "$root/build-gcc"
if [[ ! -f Makefile ]]; then
    ../src/gcc-15.2.0/configure --target=m68k-linux-gnu --prefix="$root/install" \
        --with-as="$root/install/bin/m68k-linux-gnu-as" \
        --with-ld="$root/install/bin/m68k-linux-gnu-ld" \
        --enable-languages=c --disable-bootstrap --disable-multilib --disable-nls \
        --disable-shared --disable-threads --disable-libsanitizer --disable-libssp \
        --disable-libquadmath --disable-libgomp --without-headers \
        --enable-checking=release CFLAGS=-O1 CXXFLAGS=-O1 \
        > "$root/../logs/gcc-config.log" 2>&1
fi
make -j"$jobs" all-gcc > "$root/../logs/gcc-build.log" 2>&1
make install-gcc > "$root/../logs/gcc-install.log" 2>&1
"$root/install/bin/m68k-linux-gnu-gcc" --version
