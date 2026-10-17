@echo off
cd /d "%~dp0"
if exist "%~dp0start_desktop.vbs" (
    start "" wscript "%~dp0start_desktop.vbs"
    exit
)
start "" pythonw "%~dp0desktop.py"
exit
