@echo off
rem pfs - publisher desktop app (share a folder, show invite code)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

rem pythonw.exe is a GUI-subsystem executable, so no console window appears.
set "PYW=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"

set "PFS_LOG_DIR=logs"

start "" "%PYW%" -m pfs.gui.app publish
exit /b 0
