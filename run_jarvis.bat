@echo off
REM Launch JARVIS AI from repository root
cd /d "%~dp0JarvisAI"
call run_jarvis.bat %*
exit /b %errorlevel%
