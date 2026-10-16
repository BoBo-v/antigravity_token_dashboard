@echo off
cd /d "%~dp0"
title Antigravity Token Browser Mode
echo ========================================================
echo   Starting Antigravity Token Dashboard (Browser Mode)...
echo ========================================================
start http://127.0.0.1:8765
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
pause
