#!/usr/bin/env bash
# pfs - publisher desktop app (share a folder, show invite code)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python3
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

export PFS_LOG_DIR=logs

echo "[pfs] Starting publisher GUI..."
if ! "$PY" -m pfs.gui.app publish; then
  echo "[pfs] GUI exited with an error. Did you run 0_install.sh?"
fi
