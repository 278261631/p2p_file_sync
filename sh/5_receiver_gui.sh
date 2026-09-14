#!/usr/bin/env bash
# pfs - receiver desktop app (paste invite, pick files, download)
set -euo pipefail
cd "$(dirname "$0")/.."

. "sh/_lib.sh"
pfs_setup_python

export PFS_LOG_DIR=logs

echo "[pfs] Starting receiver GUI..."
if ! "$PY" -m pfs.gui.app receive; then
  echo "[pfs] GUI exited with an error. Did you run 0_install.sh?"
fi
