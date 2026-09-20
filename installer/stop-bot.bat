@echo off
REM Kill switch: create the STOP file so the engine opens no new positions.
REM This does NOT close open trades and does NOT kill the process - open
REM positions keep their SL/TP on the broker's server.
setlocal
cd /d "%~dp0.."

echo stopped by stop-bot.bat on %DATE% %TIME% > "STOP"
if exist "STOP" (
  echo.
  echo STOP created - the bot will not open any NEW position.
  echo.
  echo Still open:
  echo   - existing positions, protected by their SL/TP on the broker side
  echo   - the bot process itself, which keeps managing them
  echo     ^(breakeven and the force-close at the configured hour^)
  echo.
  echo To close positions right now, do it in MT5 by hand.
  echo To fully stop the process, close its window or press Ctrl+C there.
  echo To resume trading, delete the STOP file or use start-bot.bat.
) else (
  echo Could not create the STOP file in "%CD%" - check permissions.
  pause & exit /b 1
)
pause
