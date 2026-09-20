@echo off
REM Start the live engine. Reads config.yaml; with dry_run: true it only logs signals.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Not installed yet - run install.bat first.
  pause & exit /b 1
)
if not exist "config.yaml" (
  echo config.yaml is missing - run install.bat first.
  pause & exit /b 1
)

if exist "STOP" (
  echo.
  echo The STOP kill switch is active, so the bot would open no new trades.
  choice /c YN /m "Remove STOP and trade normally"
  if errorlevel 2 (
    echo Leaving STOP in place - the bot will only manage existing positions.
  ) else (
    del "STOP"
    echo STOP removed.
  )
)

echo.
echo Starting the bot. Close this window or press Ctrl+C to stop it.
echo Open MT5 and log in first, with Algo Trading enabled.
echo.
".venv\Scripts\python.exe" "scripts\run_live.py" --config "config.yaml"
set "RC=%ERRORLEVEL%"
echo.
echo Bot exited with code %RC%. See logs\bot.log for details.
pause
exit /b %RC%
