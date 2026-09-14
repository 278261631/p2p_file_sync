#!/usr/bin/env bash
# pfs - public relay: signaling server + coturn (TURN) via Docker
# Edit deploy/turnserver.conf (external-ip, realm, user) before first run.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "[pfs] Docker not found in PATH."
  exit 1
fi

echo "[pfs] Starting signaling server + coturn relay (detached)..."
if ! docker compose -f deploy/docker-compose.yml up -d --build; then
  echo "[pfs] Failed to start. Check Docker and deploy/turnserver.conf."
  exit 1
fi

echo
docker compose -f deploy/docker-compose.yml ps
echo
echo "[pfs] Relay is up. Stop it with: docker compose -f deploy/docker-compose.yml down"
