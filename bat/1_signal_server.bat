@echo off
rem pfs - part 1/3: signaling server
rem Usage: 1_signal_server.bat [host] [port]      (default 0.0.0.0 8765)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "HOST=%~1"
if "%HOST%"=="" set "HOST=0.0.0.0"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8765"

echo [pfs] Signaling server listening on %HOST%:%PORT%
echo [pfs] Press Ctrl+C to stop.
"%PY%" -m uvicorn server.signal_server:app --host %HOST% --port %PORT%

echo [pfs] Signaling server stopped.
pause
exit /b 0
