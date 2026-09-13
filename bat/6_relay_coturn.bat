@echo off
rem pfs - public relay: signaling server + coturn (TURN) via Docker
rem Edit deploy\turnserver.conf (external-ip, realm, user) before first run.
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

where docker >nul 2>nul
if errorlevel 1 (
  echo [pfs] Docker not found in PATH.
  pause
  exit /b 1
)

echo [pfs] Starting signaling server + coturn relay (detached)...
docker compose -f deploy\docker-compose.yml up -d --build
if errorlevel 1 (
  echo [pfs] Failed to start. Check Docker and deploy\turnserver.conf.
  pause
  exit /b 1
)

echo.
docker compose -f deploy\docker-compose.yml ps
echo.
echo [pfs] Relay is up. Stop it with: docker compose -f deploy\docker-compose.yml down
pause
exit /b 0
