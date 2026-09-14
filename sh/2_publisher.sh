#!/usr/bin/env bash
# pfs - part 2/3: publisher (login, share a folder)
# Usage: 2_publisher.sh ["folder"] [server] [port] [account]
set -euo pipefail
cd "$(dirname "$0")/.."

. "sh/_lib.sh"
pfs_setup_python

ROOT="${1:-}"
if [ -z "$ROOT" ]; then read -r -p "Folder to share: " ROOT; fi
if [ ! -d "$ROOT" ]; then
  echo "[pfs] Folder not found: \"$ROOT\""
  exit 1
fi

SERVER="${2:-}"
if [ -z "$SERVER" ]; then read -r -p "Server host [127.0.0.1]: " SERVER; fi
SERVER="${SERVER:-127.0.0.1}"

PORT="${3:-}"
if [ -z "$PORT" ]; then read -r -p "Server port [18765]: " PORT; fi
PORT="${PORT:-18765}"

ACCOUNT="${4:-}"
if [ -z "$ACCOUNT" ]; then read -r -p "Account: " ACCOUNT; fi

read -rs -p "Password: " PASS
echo

export PFS_LOG_DIR=logs

echo "[pfs] Publishing \"$ROOT\" as $ACCOUNT via ${SERVER}:${PORT}"
exec "$PY" -m pfs.cli.main serve --root "$ROOT" --server "$SERVER" --port "$PORT" --user "$ACCOUNT" --password "$PASS"
