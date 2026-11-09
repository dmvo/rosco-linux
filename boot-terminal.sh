#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
image="$root/out/showcase"
if [[ ! -f "$image/manifest.json" ]]; then
    echo 'No verified showcase image has been selected yet.' >&2
    exit 1
fi
printf -v command '%q ' python3 "$root/boot.py" "$image/ram.bin" \
    --flash-manifest "$image/manifest.json" \
    --protected-backup "$root/out/backups/f020-original-20261022.bin" \
    --terminal --compact "$@"
exec sg dialout -c "$command"
