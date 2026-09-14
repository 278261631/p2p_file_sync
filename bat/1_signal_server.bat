@echo off
rem pfs - part 1/3: signaling + directory server
rem Usage: 1_signal_server.bat [host] [port]      (default 0.0.0.0 18765)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not exist "server\accounts.json" (
  if exist "server\accounts.example.json" (
    copy /y "server\accounts.example.json" "server\accounts.json" >nul
    echo [pfs] Created server\accounts.json from the example. Edit it to set your accounts.
  ) else (
    echo [pfs] Warning: server\accounts.json not found; no account can log in.
  )
)

set "HOST=%~1"
if "%HOST%"=="" set "HOST=0.0.0.0"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=18765"

rem Local/LAN development uses plaintext ws://; the clients (bats 2-5) connect
rem without TLS. For internet use, front this server with a TLS proxy and drop
rem PFS_ALLOW_INSECURE (see deploy\Dockerfile).
set "PFS_ALLOW_INSECURE=1"

echo [pfs] Server listening on %HOST%:%PORT% (plaintext, dev only)
echo [pfs] Accounts file: server\accounts.json
echo [pfs] Press Ctrl+C to stop.
"%PY%" -m uvicorn server.signal_server:app --host %HOST% --port %PORT%

echo [pfs] Server stopped.
pause
exit /b 0
