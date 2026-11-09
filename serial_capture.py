#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Capture the rosco console without flushing its existing input buffer."""

import argparse
import fcntl
import os
from pathlib import Path
import select
import subprocess
import sys
import termios
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--bell", action="store_true")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, termios.TIOCEXCL)
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        print(f"Capturing {args.port} at 115200 8N1 to {args.log}", flush=True)
        if args.bell:
            print("\a", end="", flush=True)
            subprocess.Popen(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        deadline = time.monotonic() + args.seconds
        with args.log.open("xb", buffering=0) as log:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([fd], [], [], 0.5)
                if ready:
                    data = os.read(fd, 4096)
                    if data:
                        log.write(data)
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
