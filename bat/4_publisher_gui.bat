@echo off
rem pfs - publisher desktop app (share a folder, show invite code)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo [pfs] Starting publisher GUI...
"%PY%" -m pfs.gui.app publish
if errorlevel 1 (
  echo [pfs] GUI exited with an error. Did you run 0_install.bat?
  pause
)
exit /b 0
