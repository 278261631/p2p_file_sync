#!/usr/bin/env bash
# pfs - part 3/3: receiver (login, browse shares, download)
# Usage: 3_receiver.sh [server] [port] [account] [dest folder]
set -euo pipefail
cd "$(dirname "$0")/.."

. "sh/_lib.sh"
pfs_setup_python

SERVER="${1:-}"
if [ -z "$SERVER" ]; then read -r -p "Server host [127.0.0.1]: " SERVER; fi
SERVER="${SERVER:-127.0.0.1}"

PORT="${2:-}"
if [ -z "$PORT" ]; then read -r -p "Server port [18765]: " PORT; fi
PORT="${PORT:-18765}"

ACCOUNT="${3:-}"
if [ -z "$ACCOUNT" ]; then read -r -p "Account: " ACCOUNT; fi

read -rs -p "Password: " PASS
echo

DEST="${4:-}"
if [ -z "$DEST" ]; then read -r -p "Destination folder [.]: " DEST; fi
DEST="${DEST:-.}"

export PFS_LOG_DIR=logs

echo "[pfs] Shares available:"
if ! "$PY" -m pfs.cli.main list --server "$SERVER" --port "$PORT" --user "$ACCOUNT" --password "$PASS"; then
  echo "[pfs] Login/list failed. Check server, account and password."
  exit 1
fi

echo
read -r -p "Share name to download: " SHARE
read -r -p "Paths within the share (space separated): " -a PATHS
if [ -z "$SHARE" ]; then
  echo "[pfs] No share selected."
  exit 1
fi

"$PY" -m pfs.cli.main get "$SHARE" ${PATHS[@]+"${PATHS[@]}"} --dest "$DEST" --server "$SERVER" --port "$PORT" --user "$ACCOUNT" --password "$PASS"

echo "[pfs] Done."
