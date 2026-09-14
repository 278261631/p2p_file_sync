@echo off
rem pfs - receiver desktop app (paste invite, pick files, download)
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

rem pythonw.exe is a GUI-subsystem executable, so no console window appears.
set "PYW=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"

set "PFS_LOG_DIR=logs"

start "" "%PYW%" -m pfs.gui.app receive
exit /b 0
