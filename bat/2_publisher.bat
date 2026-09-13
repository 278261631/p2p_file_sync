@echo off
rem pfs - part 2/3: publisher (login, share a folder)
rem Usage: 2_publisher.bat ["folder"] [server] [port] [account]
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

set "SERVER=%~2"
if "%SERVER%"=="" set /p "SERVER=Server host [127.0.0.1]: "
if "%SERVER%"=="" set "SERVER=127.0.0.1"
set "PORT=%~3"
if "%PORT%"=="" set /p "PORT=Server port [8765]: "
if "%PORT%"=="" set "PORT=8765"
set "USER=%~4"
if "%USER%"=="" set /p "USER=Account: "
set /p "PASS=Password: "

echo [pfs] Publishing "%ROOT%" as %USER% via %SERVER%:%PORT%
"%PY%" -m pfs.cli.main serve --root "%ROOT%" --server %SERVER% --port %PORT% --user %USER% --password "%PASS%"

echo [pfs] Publisher stopped.
pause
exit /b 0
