#!/usr/bin/env bash
# pfs - install dependencies (run once)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python3
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

echo "[pfs] Installing dependencies with \"$PY\" ..."
"$PY" -m pip install -e ".[gui,server,dev]"

echo "[pfs] Done. Use the other .sh scripts to start each part."
