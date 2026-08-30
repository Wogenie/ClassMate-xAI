@echo off
setlocal
cd /d "%~dp0..\frontend"

echo Frontend: http://localhost:5173  (API proxied to :8000)
call npm run dev