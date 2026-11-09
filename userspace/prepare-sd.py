#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write the ROMFS image to one named card, then verify it by reading back.

The card is named on the command line by its /dev/disk/by-id path, the
reader's serial number and the exact capacity in bytes; all three must
match before anything is written. The image is out/userspace/rootfs.romfs
as built by build-rootfs.py, checked against its rootfs.sha256.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import struct

import dbus


ROOT = Path(__file__).resolve().parent.parent
SERVICE = "org.freedesktop.UDisks2"
BLOCK = SERVICE + ".Block"
PROPERTIES = "org.freedesktop.DBus.Properties"
OPTIONS = dbus.Dictionary({"auth.no_user_interaction": dbus.Boolean(True)},
                          signature="sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, type=Path,
                        help="the card as /dev/disk/by-id/usb-...-0:0")
    parser.add_argument("--serial", required=True,
                        help="the reader's serial number as UDisks2 reports it")
    parser.add_argument("--capacity", required=True, type=int,
                        help="the card's exact size in bytes")
    parser.add_argument("--write", action="store_true",
                        help="overwrite the named card; otherwise inspect only")
    args = parser.parse_args()
    if not str(args.device).startswith("/dev/disk/by-id/usb-"):
        raise SystemExit("--device must be a /dev/disk/by-id/usb-... path")
    DEVICE, SERIAL, CAPACITY = args.device, args.serial, args.capacity
    data = (ROOT / "out/userspace/rootfs.romfs").read_bytes()
    expected = (ROOT / "out/userspace/rootfs.sha256").read_text().split()[0]
    if (hashlib.sha256(data).hexdigest() != expected or
            data[:8] != b"-rom1fs-" or len(data) > 1024 * 1024):
        raise SystemExit("ROMFS image does not match rootfs.sha256 from build-rootfs.py")
    device = DEVICE.resolve(strict=True)
    bus = dbus.SystemBus()
    obj = bus.get_object(SERVICE, "/org/freedesktop/UDisks2/block_devices/" + device.name)
    props = dbus.Interface(obj, PROPERTIES)

    def check_identity():
        block = props.GetAll(BLOCK)
        drive = dbus.Interface(bus.get_object(SERVICE, block["Drive"]),
                               PROPERTIES).GetAll(SERVICE + ".Drive")
        st = DEVICE.stat()
        if not (stat.S_ISBLK(st.st_mode) and st.st_rdev == block["DeviceNumber"] and
                DEVICE.resolve(strict=True) == device and
                bytes(block["Device"]).rstrip(b"\0").decode() == str(device) and
                block["Size"] == CAPACITY and not block["HintSystem"] and
                not block["ReadOnly"] and drive["Serial"] == SERIAL and
                drive["ConnectionBus"] == "usb" and drive["Removable"]):
            raise SystemExit("Card identity/safety check failed; nothing written")
        return st.st_rdev

    devnum = check_identity()
    print(f"Card: {device}, reader serial {SERIAL}, {CAPACITY} bytes", flush=True)
    print(f"ROMFS: {len(data)} bytes, SHA256 {expected}", flush=True)
    if not args.write:
        print("Inspection only; pass --write to replace the card contents")
        return

    # Use the desktop disk service's normal authorization path. No password is
    # read by this script. Root can instead open the same checked device.
    manager = dbus.Interface(bus.get_object(SERVICE, "/org/freedesktop/UDisks2"),
                             "org.freedesktop.DBus.ObjectManager")
    for path, interfaces in manager.GetManagedObjects().items():
        partition = interfaces.get(SERVICE + ".Partition", {})
        fs = interfaces.get(SERVICE + ".Filesystem", {})
        if partition.get("Table") == obj.object_path and fs.get("MountPoints"):
            dbus.Interface(bus.get_object(SERVICE, path),
                           SERVICE + ".Filesystem").Unmount(OPTIONS)
            print(f"Unmounted {path}", flush=True)
    check_identity()
    try:
        if os.geteuid() == 0:
            fd = os.open(device, os.O_RDWR | os.O_EXCL | os.O_CLOEXEC)
        else:
            handle = dbus.Interface(obj, BLOCK).OpenForRestore(OPTIONS)
            fd = handle.take()
    except (dbus.DBusException, PermissionError) as error:
        raise SystemExit(f"Administrator authorization required; no data written: {error}")
    try:
        size = struct.unpack("=Q", fcntl.ioctl(fd, 0x80081272, bytes(8)))[0]
        if os.fstat(fd).st_rdev != devnum or size != CAPACITY:
            raise SystemExit("Opened device identity differs; nothing written")
        check_identity()
        # Replace the old MBR with a whole-device ROMFS. Clear only the first
        # MiB to prevent residual header signatures; this is not secure erasure.
        payload = data.ljust(1024 * 1024, b"\0")
        previous = os.pread(fd, len(payload), 0)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        evidence = ROOT / "out/userspace" / f"sd-write-{stamp}"
        with evidence.with_suffix(".previous-head.bin").open("xb") as output:
            output.write(previous)
        offset = 0
        while offset < len(payload):
            written = os.pwrite(fd, payload[offset:], offset)
            if not written:
                raise OSError("Short SD write")
            offset += written
        os.fsync(fd)
        if os.geteuid() == 0:
            fcntl.ioctl(fd, 0x1261)  # BLKFLSBUF: discard cached block contents.
        actual = os.pread(fd, len(payload), 0)
        if actual != payload:
            raise SystemExit("SD readback differs; do not use this card image")
        record = {"state": "verified", "device": str(device), "capacity": size,
                  "reader_serial": SERIAL, "rootfs_bytes": len(data),
                  "rootfs_sha256": hashlib.sha256(actual[:len(data)]).hexdigest(),
                  "written_and_checked_bytes": len(payload), "utc": stamp}
        evidence.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record, indent=2), flush=True)
    finally:
        os.close(fd)
    dbus.Interface(obj, BLOCK).Rescan(OPTIONS)
    print("Card written, flushed and read back successfully", flush=True)


if __name__ == "__main__":
    main()
