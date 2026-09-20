@echo off
REM Preflight check against the running MT5 terminal. Sends no orders.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Not installed yet - run install.bat first.
  pause & exit /b 1
)

".venv\Scripts\python.exe" "scripts\doctor.py" --config "config.yaml" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
