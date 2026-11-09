#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a ROMFS SD image without root privileges or access to block devices."""

from pathlib import Path
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parent
root = source.parent
commit = "2bdc5f933f5aa1451252d36f10bd376992affe24"
archive = root / "toolchain/genromfs-0.5.7.tar.gz"
expected = "431be8c59b93f077617d09619808b7b324fa44f63c844df21913d1416cadbc8f"
if not archive.exists():
    subprocess.run(["curl", "-L", "--fail", "-o", str(archive),
                    f"https://codeload.github.com/chexum/genromfs/tar.gz/{commit}"],
                   check=True)
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit("genromfs source archive checksum mismatch")
gen_source = root / "toolchain" / f"genromfs-{commit}"
if not gen_source.exists():
    subprocess.run(["tar", "-xzf", str(archive), "-C", str(root / "toolchain")],
                   check=True)
if "Stable directory order makes ROMFS images reproducible" not in (
        gen_source / "genromfs.c").read_text():
    subprocess.run(["patch", "-p1", "--input", str(source / "genromfs-sorted.patch")],
                   cwd=gen_source, check=True)
subprocess.run(["make", "-C", str(gen_source)], check=True)
subprocess.run([sys.executable, str(source / "build-init.py")], check=True)
out = root / "out/userspace"
image = out / "rootfs.romfs"
with tempfile.TemporaryDirectory(prefix="rootfs-", dir=out) as staging:
    tree = Path(staging)
    (tree / "dev").mkdir()
    # genromfs interprets these empty files as device-node specifications.
    (tree / "dev/@console,c,5,1").touch()
    (tree / "dev/@ttySC0,c,204,205").touch()
    shutil.copy2(out / "init", tree / "init")
    subprocess.run([str(gen_source / "genromfs"), "-d", str(tree),
                    "-V", "rosco-linux", "-f", str(image)], check=True)
data = image.read_bytes()
assert data[:8] == b"-rom1fs-"
assert len(data) % 1024 == 0
assert sum(struct.unpack(">128I", data[:512])) % (1 << 32) == 0
digest = hashlib.sha256(data).hexdigest()
(out / "rootfs.sha256").write_text(f"{digest}  rootfs.romfs\n")
print(f"ROMFS: {len(data)} bytes; SHA256 {digest}; no device was written")
