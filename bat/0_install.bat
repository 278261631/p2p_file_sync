@echo off
rem pfs - install dependencies (run once)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo [pfs] Installing dependencies with "%PY%" ...
"%PY%" -m pip install -e ".[gui,server,dev]"
if errorlevel 1 (
  echo [pfs] Install failed.
  pause
  exit /b 1
)

echo [pfs] Done. Use the other .bat files to start each part.
pause
exit /b 0
