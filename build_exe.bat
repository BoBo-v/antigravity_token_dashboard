@echo off
cd /d "%~dp0"
echo ========================================================
echo   Building Antigravity Token Dashboard EXE...
echo ========================================================

python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo [!] Failed to install PyInstaller.
    pause
    exit /b 1
)

python -m PyInstaller AntigravityDashboard.spec --clean --noconfirm
if %errorlevel% equ 0 (
    echo ========================================================
    echo   Build Success!
    echo   Output: dist\AntigravityDashboard.exe
    echo ========================================================
) else (
    echo [!] Build failed. Please check error message above.
)
pause
