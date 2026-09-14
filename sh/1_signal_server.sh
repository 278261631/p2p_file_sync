#!/usr/bin/env bash
# pfs - part 1/3: signaling + directory server
# Usage: 1_signal_server.sh [host] [port]      (default 0.0.0.0 18765)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python3
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

if [ ! -f "server/accounts.json" ]; then
  if [ -f "server/accounts.example.json" ]; then
    cp "server/accounts.example.json" "server/accounts.json"
    echo "[pfs] Created server/accounts.json from the example. Edit it to set your accounts."
  else
    echo "[pfs] Warning: server/accounts.json not found; no account can log in."
  fi
fi

HOST="${1:-0.0.0.0}"
PORT="${2:-18765}"

# Local/LAN development uses plaintext ws://; the clients (scripts 2-5) connect
# without TLS. For internet use, front this server with a TLS proxy and drop
# PFS_ALLOW_INSECURE (see deploy/Dockerfile).
export PFS_ALLOW_INSECURE=1

# Rolling logs: logs/signal.log, rotated daily, 7 files kept.
export PFS_LOG_DIR=logs

echo "[pfs] Server listening on ${HOST}:${PORT} (plaintext, dev only)"
echo "[pfs] Accounts file: server/accounts.json"
echo "[pfs] Logs: logs/signal.log"
echo "[pfs] Press Ctrl+C to stop."
exec "$PY" -m uvicorn server.signal_server:app --host "$HOST" --port "$PORT"
