/* SPDX-License-Identifier: GPL-2.0-only */
INCLUDE probe.ld
ASSERT(SIZEOF(.text) <= 0x800, "Receiver overlaps kernel destination")
