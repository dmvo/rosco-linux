#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an experimental F020 split image from a completed RAM kernel build.

This only links files on the host. It does not access or program the board.
The flash window must be checked against the board backup before use.
The m68k section helpers include both RAM and flash text ranges.
"""

from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess


root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--build", type=Path, default=root / "out/linux")
parser.add_argument("--out", type=Path, default=root / "out/split-f020")
args = parser.parse_args()
build = args.build.resolve()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
cross = str(root / "toolchain/install/bin/m68k-linux-gnu-")
flash_start = 0xe0c000
flash_limit = 0xe80000
budget = flash_limit - flash_start


def output(tool, *args):
    return subprocess.check_output([cross + tool, *map(str, args)], text=True,
                                   cwd=build)


config = (build / ".config").read_text()
for unsupported in ("CONFIG_KALLSYMS=y", "CONFIG_LTO_CLANG=y",
                    "CONFIG_MODULES=y", "CONFIG_BUILDTIME_TABLE_SORT=y"):
    if unsupported in config:
        raise SystemExit(f"This experiment does not yet support {unsupported}")

functions = set()
for line in output("nm", "--defined-only", build / "vmlinux").splitlines():
    fields = line.split()
    if len(fields) == 3 and fields[1] in "TtWw":
        functions.add(fields[2])

sections = []
for line in output("objdump", "-h", build / "vmlinux.o").splitlines():
    fields = line.split()
    if len(fields) >= 7 and fields[0].isdigit():
        name = fields[1]
        # entry.S uses a 16-bit BSR to this function; retain its RAM location.
        if (name.startswith(".text.") and name[6:] in functions
                and name != ".text.do_notify_resume"):
            size = int(fields[2], 16)
            align = 1 << int(fields[6].split("**")[1])
            if re.fullmatch(r"[.A-Za-z0-9_$]+", name):
                sections.append((size, align, name))

# Largest first, with an explicit tie breaker: deterministic packing. Keep
# special entry/init/scheduler sections in their normal RAM locations.
selected = []
used = 0
for size, align, name in sorted(sections, key=lambda s: (-s[0], s[2])):
    aligned = (used + align - 1) & -align
    if aligned + size <= budget:
        selected.append(name)
        used = aligned + size

script = (build / "arch/m68k/kernel/vmlinux.lds").read_text()
region = f"""
 .xiptext {flash_start:#x} : {{
  __xiptext_start = .;
""" + "".join(f"  *({name})\n" for name in selected) + f"""
  __xiptext_end = .;
 }}
 ASSERT(SIZEOF(.xiptext) <= {budget:#x}, "F020 flash text overflow")
"""
assert script.count("SECTIONS {") == 1
script = script.replace("SECTIONS {", "SECTIONS {" + region)
linker = out / "vmlinux.lds"
linker.write_text(script)
subprocess.run([
    cross + "ld", "-m", "m68kelf", "-z", "noexecstack",
    "--no-warn-rwx-segments", "--gc-sections", "--build-id=sha1",
    "-T", str(linker), "-Map", str(out / "vmlinux.map"),
    "-o", str(out / "vmlinux"), "--whole-archive", "vmlinux.a",
    ".vmlinux.export.o", "init/version-timestamp.o", "--no-whole-archive",
    "--start-group", "--end-group",
], cwd=build, check=True)
subprocess.run([cross + "objcopy", "-O", "binary", "-R", ".xiptext",
                str(out / "vmlinux"), str(out / "ram.bin")], check=True)
subprocess.run([cross + "objcopy", "-O", "binary", "-j", ".xiptext",
                str(out / "vmlinux"), str(out / "flash.bin")], check=True)
symbols = {}
for line in output("nm", "-n", out / "vmlinux").splitlines():
    fields = line.split()
    if len(fields) == 3:
        symbols[fields[2]] = int(fields[0], 16)
assert symbols["_start"] == 0x1000
assert symbols["_end"] < 0x100000
assert symbols["__xiptext_start"] == flash_start
assert symbols["__xiptext_end"] <= flash_limit
manifest = {
    "experimental": True,
    "ram_start": symbols["_start"],
    "ram_end": symbols["_end"],
    "ram_bytes": (out / "ram.bin").stat().st_size,
    "flash_start": flash_start,
    "flash_end": symbols["__xiptext_end"],
    "flash_bytes": (out / "flash.bin").stat().st_size,
    "flash_preserve_below": flash_start,
    "flash_protocol": "WFX2",
    "selected_sections": len(selected),
    "sha256": {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
               for name in ("vmlinux", "ram.bin", "flash.bin", "vmlinux.lds")},
}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
(out / "sections.txt").write_text(output("objdump", "-h", out / "vmlinux"))
print(json.dumps(manifest, indent=2))
