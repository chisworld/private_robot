@echo off
cd /d "%~dp0"
if not exist "%~dp0launch\start_garden.bat" (
  echo [ERROR] missing launch\start_garden.bat
  pause
  exit /b 1
)
call "%~dp0launch\start_garden.bat"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
