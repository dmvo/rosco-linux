#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise host flash sequencing over a PTY before using real flash."""

import contextlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import tty
import zlib

import boot


def exercise(corrupt_protected=False, *, start=0x20000, existing_kernel=False,
             full_window=False):
    master, slave = os.openpty()
    tty.setraw(slave)
    capacity = 0x80000 - start
    command_write = b"WFX1" if start == 0x20000 else b"WFX2"
    original = bytes(range(256)) * (start // 256) + b"\xff" * capacity
    flash = bytearray(original)
    if existing_kernel:
        flash[0x20000:] = b"\x5a" * 0x60000
    if corrupt_protected:
        flash[start - 1] ^= 1
    before = bytes(flash)
    payload = (bytes(range(256)) * (capacity // 256) if full_window else
               bytes(range(251)) * 40)
    padded = payload + b"\xff" * (-len(payload) % 8192)
    commands = []
    errors = []
    rejected = []

    def exact(n):
        data = b""
        while len(data) < n:
            part = os.read(master, n - len(data))
            if not part:
                raise RuntimeError("Unexpected EOF")
            data += part
        return data

    def target():
        try:
            while True:
                command = exact(4)
                commands.append(command)
                if command == b"RDB1":
                    boot.write_all(master, b"B")
                    for offset in range(0, len(flash), 1024):
                        block = flash[offset:offset + 1024]
                        boot.write_all(master, block + struct.pack(">I", zlib.crc32(block)))
                        assert exact(1) == b"A"
                    if corrupt_protected or commands.count(b"RDB1") == 3:
                        return
                elif command == command_write:
                    length = struct.unpack(">I", exact(4))[0]
                    assert 0 < length <= capacity and length % 8192 == 0
                    boot.write_all(master, b"F")
                    for offset in range(0, length, 8192):
                        while True:
                            block = exact(8192)
                            crc = struct.unpack(">I", exact(4))[0]
                            if crc != zlib.crc32(block):
                                rejected.append(offset)
                                boot.write_all(master, b"N")
                                continue
                            flash[start + offset:start + offset + 8192] = block
                            boot.write_all(master, b"A")
                            break
                else:
                    raise AssertionError(command)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "flash.json"
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    boot.update_flash(slave, payload, original, journal,
                                      flash_start=0xe00000 + start)
            except RuntimeError:
                if not corrupt_protected:
                    raise
            else:
                assert not corrupt_protected, "Protected mismatch was accepted"
            record = json.loads(journal.read_text())
            assert record["state"] == ("failed" if corrupt_protected else "verified")
        thread.join(timeout=5)
        assert not thread.is_alive(), "Target did not finish"
        assert not errors, errors
        if corrupt_protected:
            assert commands == [b"RDB1"], "A write was attempted after protected mismatch"
        else:
            assert commands == [b"RDB1", command_write, b"RDB1", command_write, b"RDB1"]
            assert rejected == [0], "Deliberately bad CRC was not retried"
            assert flash[:start] == original[:start]
            assert flash[start:start + len(padded)] == padded
            assert flash[start + len(padded):] == before[start + len(padded):]
    finally:
        os.close(slave)
        os.close(master)


exercise()
exercise(corrupt_protected=True)
exercise(start=0xc000, existing_kernel=True)
exercise(start=0xc000, corrupt_protected=True)
exercise(start=0xc000, full_window=True)
with tempfile.TemporaryDirectory() as tmp:
    for payload, backup, start in (
        (b"x", bytes(0xc001) + b"\xff" * (0x80000 - 0xc001), 0xe0c000),
        (b"x" * (0x74000 + 1), b"\xff" * 0x80000, 0xe0c000),
        (b"x", b"\xff" * 0x80000, 0xe0a000),
    ):
        try:
            boot.update_flash(-1, payload, backup, Path(tmp) / "unused.json",
                              flash_start=start)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid firmware/layout accepted")
print("PASS: both bounded layouts, first-sector CRC retry, full-window readback, "
      "existing-kernel preservation, protected boundary and oversized-image refusal")
