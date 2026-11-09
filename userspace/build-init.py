#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble the PIC smoke test and add the Linux version-4 FLAT header."""

from pathlib import Path
import hashlib
import struct
import subprocess

source = Path(__file__).resolve().parent
root = source.parent
out = root / "out/userspace"
out.mkdir(parents=True, exist_ok=True)
cross = str(root / "toolchain/install/bin/m68k-linux-gnu-")
subprocess.run([cross + "gcc", "-m68010", "-ffreestanding", "-c",
                "-o", str(out / "init.o"), str(source / "init.S")], check=True)
# Retain relocations so the position-independent requirement is verifiable.
subprocess.run([cross + "ld", "--emit-relocs", "-T", str(source / "init.ld"),
                "-o", str(out / "init.elf"), str(out / "init.o")], check=True)
relocs = subprocess.check_output([cross + "readelf", "-rW", str(out / "init.elf")],
                                 text=True)
for line in relocs.splitlines():
    if "R_68K_" in line and "R_68K_PC" not in line:
        raise SystemExit(f"init is not relocation-free: {line}")
(out / "init.relocs").write_text(relocs)
disasm = subprocess.check_output([cross + "objdump", "-dr", "-m", "m68k:68010",
                                  str(out / "init.elf")], text=True)
(out / "init.dis").write_text(disasm)
subprocess.run([cross + "objcopy", "-O", "binary", str(out / "init.elf"),
                str(out / "init.bin")], check=True)
payload = (out / "init.bin").read_bytes()
end = 64 + len(payload)
# entry, data start/end, BSS end, stack, reloc start/count, RAM flag, build date.
header = struct.pack(">4s15I", b"bFLT", 4, 64, end, end, end, 2048, end, 0,
                     1, 0, 0, 0, 0, 0, 0)
image = header + payload
(out / "init").write_bytes(image)
(out / "init").chmod(0o755)
print(f"FLAT init: {len(image)} bytes; SHA256 {hashlib.sha256(image).hexdigest()}")
