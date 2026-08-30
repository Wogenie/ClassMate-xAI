@echo off
setlocal
cd /d "%~dp0..\backend"

echo [1/4] Creating Python virtual environment...
python -m venv .venv
if errorlevel 1 goto :fail

echo [2/4] Activating venv...
call .venv\Scripts\activate.bat
if errorlevel 1 goto :fail

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip

echo [4/4] Installing requirements...
pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist .env (
    copy .env.example .env >nul
    echo Created .env from .env.example
)

echo.
echo Backend installed. Now run:  scripts\run_backend.bat
goto :eof

:fail
echo.
echo Install failed. Make sure Python 3.10+ is on PATH.
exit /b 1