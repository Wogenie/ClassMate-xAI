@echo off
setlocal
cd /d "%~dp0..\frontend"

echo Installing frontend dependencies...
call npm install
if errorlevel 1 goto :fail

echo.
echo Frontend installed. Now run:  scripts\run_frontend.bat
goto :eof

:fail
echo Install failed. Make sure Node.js 18+ is installed.
exit /b 1