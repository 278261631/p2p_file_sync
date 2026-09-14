@echo off
rem pfs - part 3/3: receiver (login, browse shares, download)
rem Usage: 3_receiver.bat [server] [port] [account] [dest folder]
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "SERVER=%~1"
if "%SERVER%"=="" set /p "SERVER=Server host [127.0.0.1]: "
if "%SERVER%"=="" set "SERVER=127.0.0.1"
set "PORT=%~2"
if "%PORT%"=="" set /p "PORT=Server port [18765]: "
if "%PORT%"=="" set "PORT=18765"
set "USER=%~3"
if "%USER%"=="" set /p "USER=Account: "
set /p "PASS=Password: "

set "DEST=%~4"
if "%DEST%"=="" set /p "DEST=Destination folder [.]: "
if "%DEST%"=="" set "DEST=."

set "PFS_LOG_DIR=logs"

echo [pfs] Shares available:
"%PY%" -m pfs.cli.main list --server %SERVER% --port %PORT% --user %USER% --password "%PASS%"
if errorlevel 1 (
  echo [pfs] Login/list failed. Check server, account and password.
  pause
  exit /b 1
)

echo.
set /p "SHARE=Share name to download: "
set /p "PATHS=Paths within the share (space separated): "
if "%SHARE%"=="" (
  echo [pfs] No share selected.
  pause
  exit /b 1
)

"%PY%" -m pfs.cli.main get "%SHARE%" %PATHS% --dest "%DEST%" --server %SERVER% --port %PORT% --user %USER% --password "%PASS%"

echo [pfs] Done.
pause
exit /b 0
