@echo off
rem pfs - part 3/3: receiver (lists files then downloads selected paths)
rem Usage: 3_receiver.bat ["invite code"] [dest folder]
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "INVITE=%~1"
if "%INVITE%"=="" set /p "INVITE=Paste invite code: "
if "%INVITE%"=="" (
  echo [pfs] No invite code given.
  pause
  exit /b 1
)

set "DEST=%~2"
if "%DEST%"=="" set /p "DEST=Destination folder [.]: "
if "%DEST%"=="" set "DEST=."

echo [pfs] Fetching file listing...
"%PY%" -m pfs.cli.main list "%INVITE%"
if errorlevel 1 (
  echo [pfs] Could not connect. Check the signaling server and invite code.
  pause
  exit /b 1
)

echo.
set /p "PATHS=Paths to download (space separated, e.g. docs report.pdf): "
if "%PATHS%"=="" (
  echo [pfs] Nothing selected.
  pause
  exit /b 1
)

"%PY%" -m pfs.cli.main get "%INVITE%" %PATHS% --dest "%DEST%"

echo [pfs] Done.
pause
exit /b 0
