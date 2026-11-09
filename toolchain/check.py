#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the compiler properties required by the MC68010 Linux port."""

from pathlib import Path
import re
import subprocess


root = Path(__file__).resolve().parent.parent
cc = root / "toolchain/install/bin/m68k-linux-gnu-gcc"
out = root / "out/toolchain-check"
out.mkdir(parents=True, exist_ok=True)
outputs = {}
for name, options in (
    ("default", ["-m68010"]),
    ("strict", ["-m68010", "-mstrict-align"]),
    ("relaxed", ["-m68010", "-mno-strict-align"]),
    ("68020", ["-m68020"]),
):
    path = out / f"check-{name}.s"
    subprocess.run([str(cc), *options, "-Os", "-ffreestanding", "-fno-pic",
                    "-S", str(root / "alignment.c"), "-o", str(path)], check=True)
    outputs[name] = path.read_text()

# The test record's long is at offset 1. In strict mode its accesses, and
# the four consecutive byte stores, must remain byte-sized. Relaxed mode
# is the negative control that demonstrates the original failure.
odd_wide = re.compile(r"\b(?:move|or|and)\.[wl]\s+[^\n]*\b[13]\(%a[0-6]\)")
for name in ("default", "strict"):
    if odd_wide.search(outputs[name]):
        raise SystemExit(f"FAIL: {name} generated an odd word/long access")
    if outputs[name].count("move.b") < 11:
        raise SystemExit(f"FAIL: inspect unexpected {name} byte-access sequence")
for name in ("relaxed", "68020"):
    if not odd_wide.search(outputs[name]):
        raise SystemExit(f"FAIL: {name} negative control did not reproduce the access")

abi = out / "check-abi.c"
abi.write_text('''\
_Static_assert(__builtin_types_compatible_p(__SIZE_TYPE__, unsigned int),
               "Linux size_t must be unsigned int");
void *return_pointer(void *p) { return p; }
struct small { unsigned long value; };
struct small return_small(unsigned long value) { return (struct small){value}; }
''')
subprocess.run([str(cc), "-m68010", "-Os", "-ffreestanding", "-fno-pic",
                "-S", str(abi), "-o", str(out / "check-abi.s")], check=True)
print("PASS: MC68010 strict alignment, relaxed/68020 negative controls, Linux size_t")
print(f"ABI return sequences saved for inspection: {out / 'check-abi.s'}")
