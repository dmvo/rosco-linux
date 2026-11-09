#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Display a compact, unmodified selection of a real Linux UART log."""

import argparse
from pathlib import Path
import re
import sys


class ConsoleView:
    # Omit routine allocation diagnostics, never warnings, errors or panics.
    noise = (
        "Zone ranges:", "  DMA      [mem ", "  Normal   empty",
        "Movable zone start for each node", "Early memory node ranges",
        "  node   0: [mem ", "Initmem setup node ",
        "Dentry cache hash table entries:", "Inode-cache hash table entries:",
        "Mount-cache hash table entries:", "Mountpoint-cache hash table entries:",
        "Built 1 zonelists,", "mem auto-init:", "SLUB:",
        "printk: log buffer data + meta data:", "workingset:",
        "bringup:", "[tick pc/jiffies/pid/free/isr]",
        "  with arguments:", "    /init", "  with environment:",
        "    HOME=/", "    TERM=linux",
    )

    def __init__(self, emit, clear=False):
        self.emit = emit
        self.clear = clear
        self.started = False
        self.pending = b""
        self.previous = None

    def feed(self, data):
        self.pending += data
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            self.line(line)

    def line(self, data):
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "",
                      data.decode("utf-8", errors="replace").replace("\r", ""))
        if line.startswith("Linux version "):
            self.started = True
            if self.clear:
                self.emit("\x1b[2J\x1b[H")
        if not self.started or not line or line.startswith(self.noise):
            return
        if line == self.previous and line.startswith("printk: legacy "):
            return
        self.previous = line
        self.emit(line + "\n")

    def flush(self):
        if self.pending:
            self.line(self.pending)
            self.pending = b""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    view = ConsoleView(sys.stdout.write)
    view.feed(args.log.read_bytes())
    view.flush()


if __name__ == "__main__":
    main()
