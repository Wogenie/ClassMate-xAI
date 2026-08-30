@echo off
setlocal
cd /d "%~dp0..\backend"

if not exist .venv (
    echo No .venv found. Run scripts\install_backend.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

if not exist .env (
    copy .env.example .env >nul
)

echo Start backend: http://localhost:8000  (docs at /docs)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload