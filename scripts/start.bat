@echo off
cd /d "%~dp0.."
python scripts\launcher.py --page chat
if errorlevel 1 pause
exit /b %errorlevel%
