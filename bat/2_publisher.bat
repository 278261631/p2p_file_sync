@echo off
rem pfs - part 2/3: publisher (shares a folder, prints an invite code)
rem Usage: 2_publisher.bat ["folder"] [signal_host] [signal_port]
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "ROOT=%~1"
if "%ROOT%"=="" set /p "ROOT=Folder to share: "
if not exist "%ROOT%" (
  echo [pfs] Folder not found: "%ROOT%"
  pause
  exit /b 1
)

set "SIGNAL_HOST=%~2"
if "%SIGNAL_HOST%"=="" set "SIGNAL_HOST=127.0.0.1"
set "SIGNAL_PORT=%~3"
if "%SIGNAL_PORT%"=="" set "SIGNAL_PORT=8765"

echo [pfs] Publishing "%ROOT%" via signaling %SIGNAL_HOST%:%SIGNAL_PORT%
"%PY%" -m pfs.cli.main serve --root "%ROOT%" --signal-host %SIGNAL_HOST% --signal-port %SIGNAL_PORT% --host %SIGNAL_HOST% --port %SIGNAL_PORT%

echo [pfs] Publisher stopped.
pause
exit /b 0
