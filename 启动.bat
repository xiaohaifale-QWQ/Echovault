@echo off
cd /d "%~dp0"
start "" /b pythonw.exe "%~dp0main.py" gui
exit /b
