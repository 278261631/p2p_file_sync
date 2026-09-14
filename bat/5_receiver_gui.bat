@echo off
rem pfs - receiver desktop app (paste invite, pick files, download)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "PFS_LOG_DIR=logs"

echo [pfs] Starting receiver GUI...
"%PY%" -m pfs.gui.app receive
if errorlevel 1 (
  echo [pfs] GUI exited with an error. Did you run 0_install.bat?
  pause
)
exit /b 0
