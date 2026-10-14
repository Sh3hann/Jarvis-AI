@echo off
REM Launch JARVIS AI using the project's Python 3.13 virtual environment.
cd /d "%~dp0"

REM If a previous hung Jarvis instance is running, close only that instance (never touches other apps)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { (`$_.Name -like 'python*' -or `$_.Name -like 'pythonw*') -and `$_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id `$_.ProcessId -Force }" >nul 2>&1

REM If the user explicitly wants live terminal output, run: run_jarvis.bat --debug
if /i "%~1"=="--debug" goto :DEBUG_MODE
if /i "%~1"=="debug" goto :DEBUG_MODE

REM Normal Mode: Launch JARVIS detached with pythonw.exe so the terminal window closes immediately
start "" ".venv\Scripts\pythonw.exe" main.py %*
exit /b 0

:DEBUG_MODE
REM Debug Mode: Run with console attached for live logs
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
