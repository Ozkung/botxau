@echo off
REM Double-click this file to install the bot on Windows.
REM It only sets things up - it never starts trading by itself.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo Setup did not finish cleanly - read the messages above.
pause
exit /b %RC%
