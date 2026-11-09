#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Load a RAM image through the stock rosco firmware, then log its output."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import re
import subprocess
import tempfile


def kermit_path(path):
    value = str(Path(path).resolve())
    if any(c in value for c in "{}\n\r\\"):
        raise ValueError("Path contains Kermit command characters")
    return "{" + value + "}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--ready", action="store_true",
                        help="firmware is already waiting for Kermit")
    parser.add_argument("--quiet", action="store_true",
                        help="hide transfer details while keeping the live firmware banner")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--expect", default="Kernel panic")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"/dev/[A-Za-z0-9_./-]+", args.port):
        parser.error("invalid serial device path")
    if not 0 < args.image.stat().st_size <= 0xb0000:
        parser.error("image must fit in 0x40000..0xeffff below firmware stage 2")
    if any(c in args.expect for c in "{}\n\r\\"):
        parser.error("invalid expectation")
    if not 1 <= args.seconds <= 3600:
        parser.error("seconds must be between 1 and 3600")
    kermit = shutil.which("kermit")
    if not kermit:
        parser.error("C-Kermit is required")
    root = Path(__file__).resolve().parent
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = args.log or root / "logs" / f"boot-{stamp}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        parser.error(f"log already exists: {log}")
    commands = [
        "set exit warning off",
        "set file display none" if args.quiet else "set file display brief",
        "set carrier-watch off",
        f"set line {args.port}",
        "if fail exit 1 Cannot open serial port",
        "set speed 115200",
        "set flow-control none",
        "set file type binary",
        "set transfer mode manual",
        "set send packet-length 90",
        "set window 1",
        "set input echo on",
        "set session-log binary",
        f"log session {kermit_path(log)}",
    ]
    if not args.ready:
        commands += [
            "input 1800 {Ready for Kermit receive}",
            "if fail exit 2 Firmware loader was not seen",
        ]
        if args.quiet:
            # The firmware prompt has no newline; SEND's hidden display
            # no longer separates it from the receiver's next message.
            commands.append("echo")
    commands += [
        f"send {kermit_path(args.image)}",
        "if fail exit 3 Kermit transfer failed",
        f"input {args.seconds} {{{args.expect}}}",
        "if fail exit 4 Expected output was not seen",
        "input 2 {__capture_end_marker__}",
        "close session",
        "exit 0",
    ]
    if not args.quiet:
        print(f"Image: {args.image.resolve()} ({args.image.stat().st_size} bytes)",
              flush=True)
        print(f"UART log: {log}", flush=True)
    if not args.ready:
        print("\a", end="", flush=True)
        if shutil.which("paplay"):
            subprocess.Popen(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ksc") as script:
        script.write("\n".join(commands) + "\n")
        script.flush()
        result = subprocess.run([kermit, "-Y", "-C",
                                 f"take {kermit_path(script.name)}"])
    # C-Kermit can return success after a signal interrupts its INPUT.
    # Do not advance to the binary protocol without the receiver's greeting.
    if result.returncode == 0 and args.expect.encode() not in log.read_bytes():
        print("Expected output is missing from the UART log", flush=True)
        raise SystemExit(4)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
