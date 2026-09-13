@echo off
rem pfs - desktop GUI (publisher + receiver in one window)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo [pfs] Starting desktop GUI...
"%PY%" -m pfs.gui.app
if errorlevel 1 (
  echo [pfs] GUI exited with an error. Did you run 0_install.bat?
  pause
)
exit /b 0
