@echo off
cd /d "%~dp0"
title Antigravity Token Desktop

:: 如果传入了 --show-console 或 --debug，保留控制台窗口便于查看日志
echo %* | findstr /i "\-\-show\-console \-\-debug" >nul
if %errorlevel% equ 0 (
    python desktop.py %*
    if %errorlevel% neq 0 pause
    exit /b
)

:: 优先使用 pythonw 纯静默启动桌面客户端（完全无黑框）
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw desktop.py %*
    exit
)

:: 兜底使用 python 启动（desktop.py 内置调用 Windows API 毫秒级自动隐藏黑框）
where python >nul 2>nul
if %errorlevel% equ 0 (
    start "" python desktop.py %*
    exit
)

echo [!] 未检测到 Python 环境，请检查是否已正确安装 Python 并加入系统 PATH。
pause
