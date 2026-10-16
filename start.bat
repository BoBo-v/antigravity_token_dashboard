@echo off
cd /d "%~dp0"
title Antigravity Token Dashboard
echo ========================================================
echo   Starting Antigravity Token Dashboard...
echo ========================================================
python run.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Start failed. Please check Python environment.
    pause
)