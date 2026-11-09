#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Load the RAM receiver with Kermit, upload a kernel, and capture its console."""

import argparse
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
import zlib

from console_view import ConsoleView


class LoaderProgress:
    """Keep detailed progress in a file and redraw one terminal line."""

    def __init__(self, log, terminal):
        self.log = log
        self.terminal = terminal
        self.pending = ""

    def write(self, data):
        self.log.write(data)
        self.pending += data
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.startswith("Read flash: "):
                label, counts = "Checking flash", line.split()[2]
            elif line.startswith("Uploaded "):
                label, counts = "Uploading", line.split()[1]
            else:
                continue
            done, total = map(int, counts.split("/"))
            filled = 24 * done // total
            bar = "=" * filled + "." * (24 - filled)
            self.terminal.write(f"\r{label:<14} [{bar}] {100 * done // total:3d}%\x1b[K")
            self.terminal.flush()
        return len(data)

    def flush(self):
        self.log.flush()
        self.terminal.flush()

    def clear(self):
        self.terminal.write("\r\x1b[K")
        self.terminal.flush()


def write_all(fd, data, timeout=5):
    deadline = time.monotonic() + timeout
    data = memoryview(data)
    while data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
            raise TimeoutError("UART write timed out")
        try:
            data = data[os.write(fd, data):]
        except BlockingIOError:
            continue


def response(fd):
    if not select.select([fd], [], [], 5)[0]:
        raise TimeoutError("RAM receiver did not acknowledge the block")
    value = os.read(fd, 1)
    if not value:
        raise OSError("UART disconnected")
    return value


def read_exact(fd, count, timeout=5):
    deadline = time.monotonic() + timeout
    data = bytearray()
    while len(data) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError("Flash backup read timed out")
        chunk = os.read(fd, count - len(data))
        if not chunk:
            raise OSError("UART disconnected")
        data.extend(chunk)
    return bytes(data)


def read_flash(fd):
    write_all(fd, b"RDB1")
    if response(fd) != b"B":
        raise RuntimeError("Receiver does not support flash backup")
    image = bytearray()
    for offset in range(0, 0x80000, 1024):
        for attempt in range(3):
            data = read_exact(fd, 1028)
            block, expected = data[:1024], struct.unpack(">I", data[1024:])[0]
            good = zlib.crc32(block) == expected
            write_all(fd, b"A" if good else b"N")
            if good:
                image.extend(block)
                break
        else:
            raise RuntimeError(f"Flash backup CRC failure at {offset:#x}")
        if offset % 65536 == 0:
            print(f"Read flash: {offset + 1024}/524288 bytes", flush=True)
    return bytes(image)


def backup_flash(fd, path):
    print("Reading the F020 flash window twice (no flash writes)", flush=True)
    first = read_flash(fd)
    second = read_flash(fd)
    if first != second:
        raise RuntimeError("The two flash reads differ; no backup saved")
    with path.open("xb") as output:
        output.write(first)
    digest = hashlib.sha256(first).hexdigest()
    print(f"Flash backup: {path}; SHA256 {digest}", flush=True)


def transfer(fd, image, test_retry=False, *, header=b"RLM1", ack=b"H",
             block_size=1024):
    write_all(fd, header + struct.pack(">I", len(image)))
    if response(fd) != ack:
        raise RuntimeError("Receiver rejected the header (for flash, check the "
                           "write jumper and two SST39SF020A device IDs)")
    start = time.monotonic()
    retries = 0
    for offset in range(0, len(image), block_size):
        block = image[offset:offset + block_size]
        crc = zlib.crc32(block)
        for attempt in range(3):
            inject = test_retry and offset == 0 and attempt == 0
            write_all(fd, block + struct.pack(">I", crc ^ int(inject)))
            reply = response(fd)
            if inject and reply != b"N":
                raise RuntimeError("Receiver accepted a deliberately bad CRC")
            if reply == b"A":
                break
            if reply != b"N":
                raise RuntimeError(f"Unexpected receiver reply: {reply!r}")
            retries += 1
        else:
            raise RuntimeError(f"Repeated CRC failure at offset {offset:#x}")
        if offset % 65536 == 0:
            print(f"Uploaded {offset + len(block)}/{len(image)} bytes", flush=True)
    print(f"Upload complete: {len(image)} bytes, {retries} retries, "
          f"{time.monotonic() - start:.1f} s", flush=True)
    return retries


def update_flash(fd, payload, protected_backup, journal, *, flash_start=0xe20000):
    """Preserve the stock firmware, program the upper window, verify all flash."""
    profiles = {0xe20000: b"WFX1", 0xe0c000: b"WFX2"}
    if flash_start not in profiles:
        raise ValueError("Unsupported protected F020 flash layout")
    command = profiles[flash_start]
    start = flash_start - 0xe00000
    capacity = 0x80000 - start
    payload += b"\xff" * (-len(payload) % 8192)
    if not payload or len(payload) > capacity or len(protected_backup) != 0x80000:
        raise ValueError("Invalid F020 image or protected backup size")
    if protected_backup[start:] != b"\xff" * capacity:
        raise ValueError("Original firmware backup contains data in the proposed kernel window")
    state = {"state": "checking", "start": flash_start, "bytes": len(payload),
             "protocol": command.decode(),
             "payload_sha256": hashlib.sha256(payload).hexdigest()}

    def record(status):
        state["state"] = status
        journal.write_text(json.dumps(state, indent=2) + "\n")

    try:
        current = read_flash(fd)
        state["before_sha256"] = hashlib.sha256(current).hexdigest()
        if current[:start] != protected_backup[:start]:
            raise RuntimeError("Protected firmware differs from its backup; "
                               "refusing to program flash")
        expected = current[:start] + payload + current[start + len(payload):]
        if current == expected:
            record("already verified")
            print("Flash already matches; no programming needed", flush=True)
            return

        # On the first use, prove sector programming and preservation of the
        # rest of the array before proceeding with the full kernel text.
        if current[start:start + 8192] == b"\xff" * 8192:
            record("testing first sector")
            print("Programming and checking the first 8 KiB sector pair", flush=True)
            transfer(fd, payload[:8192], test_retry=True,
                     header=command, ack=b"F", block_size=8192)
            first = read_flash(fd)
            trial = current[:start] + payload[:8192] + current[start + 8192:]
            if first != trial:
                raise RuntimeError("First-sector readback differs; stopped before "
                                   "programming the rest of flash")

        record("programming")
        print(f"Programming {len(payload)} bytes at {flash_start:#x}", flush=True)
        transfer(fd, payload, header=command, ack=b"F", block_size=8192)
        record("verifying")
        result = read_flash(fd)
        state["after_sha256"] = hashlib.sha256(result).hexdigest()
        if result != expected:
            raise RuntimeError("Full flash readback differs; Linux was not started")
        record("verified")
        print("Flash verified; the protected firmware and other sectors match", flush=True)
    except BaseException as error:
        state["error"] = str(error)
        record("failed")
        raise


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--ready", action="store_true")
    parser.add_argument("--receiver-ready", action="store_true",
                        help="RAM receiver is already running and waiting for a command")
    parser.add_argument("--test-retry", action="store_true",
                        help="verify rejection and retry of a bad first CRC")
    parser.add_argument("--backup-flash", type=Path,
                        help="save two matching CRC-checked reads of the F020 flash")
    parser.add_argument("--flash-manifest", type=Path,
                        help="update a paired split RAM/flash image before booting")
    parser.add_argument("--protected-backup", type=Path,
                        help="original 512 KiB flash backup required for updates")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--console-test", action="store_true",
                        help="send a paced line after /init starts and verify its reply")
    parser.add_argument("--terminal", action="store_true",
                        help="forward terminal input; Ctrl-] disconnects without reset")
    parser.add_argument("--compact", action="store_true",
                        help="show a compact boot log; the saved UART log stays complete")
    parser.add_argument("--quiet-loader", action="store_true",
                        help="save transfer progress to a file instead of displaying it")
    parser.add_argument("--loader-progress", action="store_true",
                        help="show loader progress on one updating terminal line")
    parser.add_argument("--screen", action="store_true",
                        help="load, pause, then hand the real serial port to GNU screen")
    parser.add_argument("--test-paused-loader", action="store_true",
                        help="verify the screen loader waits, then send Enter and capture")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    if not 0 < len(image) <= 0xef000:
        parser.error("kernel image must fit in 0x1000..0xeffff")
    if not 1 <= args.seconds <= 3600:
        parser.error("seconds must be between 1 and 3600")
    if args.backup_flash and args.backup_flash.exists():
        parser.error(f"flash backup already exists: {args.backup_flash}")
    flash = protected = None
    if args.flash_manifest:
        if not args.protected_backup:
            parser.error("--flash-manifest requires --protected-backup")
        manifest = json.loads(args.flash_manifest.read_text())
        flash = (args.flash_manifest.parent / "flash.bin").read_bytes()
        protected = args.protected_backup.read_bytes()
        flash_start = manifest["flash_start"]
        profiles = {0xe20000: "WFX1", 0xe0c000: "WFX2"}
        if (flash_start not in profiles or
                manifest.get("flash_protocol", "WFX1") != profiles[flash_start] or
                manifest["flash_end"] != flash_start + len(flash) or
                manifest["flash_preserve_below"] != flash_start or
                not 0 < len(flash) <= 0xe80000 - flash_start or
                len(protected) != 0x80000):
            parser.error("manifest or backup does not describe the F020 layout")
        if protected[flash_start - 0xe00000:] != b"\xff" * (0xe80000 - flash_start):
            parser.error("original firmware extends into the proposed kernel window")
        for name, data in (("ram.bin", image), ("flash.bin", flash)):
            if hashlib.sha256(data).hexdigest() != manifest["sha256"][name]:
                parser.error(f"{name} does not match the paired image manifest")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = args.log or root / "logs" / f"linux-{stamp}.log"
    timed_log = log.with_suffix(".timed.log")
    flash_journal = log.with_suffix(".flash.json")
    console_journal = log.with_suffix(".console.json")
    if timed_log.exists():
        parser.error(f"timed log already exists: {timed_log}")
    if flash_journal.exists():
        parser.error(f"flash journal already exists: {flash_journal}")
    if args.console_test and console_journal.exists():
        parser.error(f"console journal already exists: {console_journal}")
    if args.terminal and (args.console_test or not sys.stdin.isatty()):
        parser.error("--terminal needs a real terminal and cannot use --console-test")
    if args.screen and (args.terminal or args.compact or args.console_test
                        or args.test_paused_loader
                        or not sys.stdin.isatty()):
        parser.error("--screen needs a terminal and excludes --terminal/--compact/--console-test")
    if args.screen and not shutil.which("screen"):
        parser.error("GNU screen is required")
    paused_loader = args.screen or args.test_paused_loader
    loader = root / "out" / ("loader-screen.bin" if paused_loader else "loader.bin")
    if not loader.is_file():
        parser.error(f"loader is missing: {loader}")
    command = [sys.executable, str(root / "run.py"), str(loader),
               "--port", args.port, "--expect", "ROSCO-RAM-READY", "--seconds",
               "30", "--log", str(log)]
    if args.ready:
        command.append("--ready")
    if args.quiet_loader or args.loader_progress:
        command.append("--quiet")
    if not args.receiver_ready:
        subprocess.run(command, check=True)
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    stdin_attrs = None
    view = ConsoleView(sys.stdout.write, clear=args.terminal) if args.compact else None
    try:
        fcntl.ioctl(fd, termios.TIOCEXCL)
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        progress_log = (log.with_suffix(".loader.log").open("a")
                        if args.quiet_loader or args.loader_progress else nullcontext())
        with progress_log as progress:
            bar = LoaderProgress(progress, sys.stdout) if args.loader_progress else None
            output = bar or progress
            try:
                with redirect_stdout(output) if output is not None else nullcontext():
                    if args.backup_flash:
                        backup_flash(fd, args.backup_flash)
                    if flash is not None:
                        update_flash(fd, flash, protected, flash_journal, flash_start=flash_start)
                    retries = transfer(fd, image, args.test_retry)
            finally:
                if bar:
                    bar.clear()
            if bar:
                print(f"Upload complete: {len(image)} bytes, CRC OK.", flush=True)
        if paused_loader:
            marker = b"ROSCO-LINUX-PAUSED\r\n"
            pending = bytearray()
            while not pending.endswith(marker):
                pending.extend(read_exact(fd, 1))
                if len(pending) > 1024:
                    raise RuntimeError("The loader did not pause before Linux")
            with log.open("ab") as output:
                output.write(pending)
            if args.screen:
                print("RAM image uploaded; opening GNU screen. Press ENTER there to boot Linux.",
                      flush=True)
                fcntl.ioctl(fd, termios.TIOCNXCL)
                os.close(fd)
                fd = None
                subprocess.run(["screen", "-S", "rosco-linux", "-c",
                                str(root / "screenrc"), "-fn", "-L", "-Logfile",
                                str(log.with_suffix(".screen.log")),
                                args.port, "115200,cs8,-ixon,-ixoff,-istrip"], check=True)
                return
            write_all(fd, b"x")
            if select.select([fd], [], [], 1.0)[0]:
                raise RuntimeError("The screen loader did not wait for Enter")
            print("[host: screen loader is paused; sending Enter]", flush=True)
            write_all(fd, b"\r")
        if args.terminal:
            stdin_attrs = termios.tcgetattr(sys.stdin.fileno())
            terminal_attrs = termios.tcgetattr(sys.stdin.fileno())
            terminal_attrs[3] &= ~(termios.ECHO | termios.ICANON)
            terminal_attrs[6][termios.VMIN] = 1
            terminal_attrs[6][termios.VTIME] = 0
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, terminal_attrs)
        with log.open("ab", buffering=0) as output, timed_log.open("xb") as timed:
            output.write(f"\r\n[host: CRC-checked {len(image)} bytes; "
                         f"{retries} retries]\r\n".encode())
            start = time.monotonic()
            deadline = start + args.seconds
            partial = b""
            recent = b""
            token = b"rosco-userspace-uart-syscall-check"
            sent = None
            console_result = {"state": "waiting for init", "byte_interval_ms": 10,
                              "token": token.decode()}
            if args.console_test:
                console_journal.write_text(json.dumps(console_result, indent=2) + "\n")
            while args.terminal or time.monotonic() < deadline:
                readers = [fd, sys.stdin.fileno()] if args.terminal else [fd]
                ready = select.select(readers, [], [], 0.5)[0]
                if args.terminal and sys.stdin.fileno() in ready:
                    entered = os.read(sys.stdin.fileno(), 1024)
                    if not entered or b"\x1d" in entered:
                        break
                    for char in entered:
                        write_all(fd, bytes([char]))
                        time.sleep(0.010)
                if fd in ready:
                    data = os.read(fd, 4096)
                    if not data:
                        raise OSError("UART disconnected")
                    output.write(data)
                    if view:
                        view.feed(data)
                    else:
                        sys.stdout.buffer.write(data)
                    sys.stdout.flush()
                    partial += data
                    while b"\n" in partial:
                        line, partial = partial.split(b"\n", 1)
                        timed.write(f"{time.monotonic() - start:9.3f} ".encode()
                                    + line + b"\n")
                    timed.flush()
                    if args.console_test:
                        recent = (recent + data)[-8192:]
                        if sent is None and b"userspace read: enter a line" in recent:
                            sent = time.monotonic()
                            for char in token + b"\n":
                                write_all(fd, bytes([char]))
                                time.sleep(0.010)
                            console_result["state"] = "sent"
                        if (sent is not None and console_result["state"] == "sent"
                                and b"userspace received: " + token in recent):
                            console_result["state"] = "passed"
                            console_result["round_trip_seconds"] = time.monotonic() - sent
                            print("\n[host: paced userspace UART read/write test passed]",
                                  flush=True)
                        console_journal.write_text(json.dumps(console_result, indent=2) + "\n")
                        if console_result["state"] == "passed":
                            reply_end = recent.find(b"userspace received: " + token) + len(
                                b"userspace received: " + token)
                            if (b"userspace read: enter a line" in recent[reply_end:]
                                    and recent.endswith(b"\n")):
                                break
            if args.console_test and console_result["state"] != "passed":
                raise RuntimeError("Userspace UART test did not complete; see console journal")
    finally:
        if view:
            view.flush()
        if stdin_attrs is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, stdin_attrs)
        if fd is not None:
            os.close(fd)


if __name__ == "__main__":
    main()
