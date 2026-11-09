#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual section helpers with RAM, flash and gap addresses."""

import ctypes
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent
kernel = root.parent / "linux-rosco"
bounds = {"_stext": 0x1000, "_etext": 0x2000, "_end": 0x5000,
          "__init_begin": 0x6000, "__init_end": 0x7000}
with tempfile.TemporaryDirectory(prefix="rosco-sections-") as directory:
    tmp = Path(directory)
    (tmp / "linux").mkdir()
    (tmp / "linux/types.h").write_text("#include <stdbool.h>\n#include <stddef.h>\n")
    (tmp / "linux/compiler.h").write_text(
        "#define __weak __attribute__((weak))\n"
        "#define __visible __attribute__((visibility(\"default\")))\n"
        "#define IS_ENABLED(option) 0\n")
    source = tmp / "test.c"
    source.write_text(
        "#include <asm/sections.h>\n"
        "char test_space[0xe80000];\n"
        "unsigned long test_base(void) { return (unsigned long)test_space; }\n"
        "int text_address(unsigned long a) { return __is_kernel_text(a); }\n"
        "int kernel_address(unsigned long a) { return __is_kernel(a); }\n")
    for name, config, flash in (("generic", False, False),
                                ("ram", True, False), ("split", True, True)):
        symbols = dict(bounds)
        if flash:
            symbols.update(__xiptext_start=0xe20000, __xiptext_end=0xe7f000)
        library = tmp / f"{name}.so"
        command = ["cc", "-Wall", "-Werror", "-O2", "-fPIC", "-shared",
                   "-nostdlib", "-Wl,-Bsymbolic", "-I", str(tmp),
                   "-I", str(kernel / "arch/m68k/include"),
                   "-I", str(kernel / "include"), str(source), "-o", str(library)]
        if config:
            command.append("-DCONFIG_ROSCO_M68K=1")
        command.extend(f"-Wl,--defsym,{key}=test_space+{value}"
                       for key, value in symbols.items())
        subprocess.run(command, check=True)
        lib = ctypes.CDLL(str(library))
        lib.test_base.restype = ctypes.c_ulong
        base = lib.test_base()
        for function in (lib.text_address, lib.kernel_address):
            function.argtypes = [ctypes.c_ulong]
            function.restype = ctypes.c_int
        text_cases = {0: False, 0xfff: False, 0x1000: True, 0x1fff: True,
                      0x2000: False, 0xe00000: False, 0xe1ffff: False,
                      0xe20000: flash, 0xe7efff: flash, 0xe7f000: False}
        kernel_cases = dict(text_cases)
        kernel_cases.update({0x2000: True, 0x4fff: True, 0x5000: False,
                             0x5fff: False, 0x6000: True, 0x6fff: True,
                             0x7000: False, 0x800000: False})
        for function, cases in ((lib.text_address, text_cases),
                                (lib.kernel_address, kernel_cases)):
            for address, expected in cases.items():
                actual = bool(function(base + address))
                assert actual == expected, (name, function.__name__, hex(address), actual)
        print(f"PASS: {name} section boundaries, data/init ranges and gaps")
