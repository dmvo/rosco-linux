#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
bash "$root/build.sh" --for-split
python3 "$root/split_xip.py"
if [[ ${1:-} == --boot ]]; then
    shift
    exec python3 "$root/boot.py" "$root/out/split-f020/ram.bin" \
        --flash-manifest "$root/out/split-f020/manifest.json" "$@"
fi
