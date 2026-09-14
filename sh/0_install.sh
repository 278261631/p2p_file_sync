#!/usr/bin/env bash
# pfs - install dependencies (run once)
set -euo pipefail
cd "$(dirname "$0")/.."

. "sh/_lib.sh"
pfs_setup_python

echo "[pfs] Installing dependencies with \"$PY\" ..."
"$PY" -m pip install -e ".[gui,server,dev]"

echo "[pfs] Done. Use the other .sh scripts to start each part."
