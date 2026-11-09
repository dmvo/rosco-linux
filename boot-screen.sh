#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
printf -v command '%q ' screen -S rosco-linux -c "$root/screenrc" \
    -L -Logfile "$root/logs/screen-$stamp.log" \
    python3 "$root/boot.py" "$root/out/showcase/ram.bin" \
    --flash-manifest "$root/out/showcase/manifest.json" \
    --protected-backup "$root/out/backups/f020-original-20261022.bin" \
    --terminal --loader-progress "$@"
exec sg dialout -c "$command"
