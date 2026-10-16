@echo off
cd /d "%~dp0"
title Antigravity Token Desktop
echo ========================================================
echo   Starting Antigravity Token Native Desktop App...
echo ========================================================
python desktop.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Desktop app exited or encountered error.
    pause
)
