@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist "%~dp0launch\start_garden.bat" (
  echo [ERROR] missing launch\start_garden.bat
  pause
  exit /b 1
)
call "%~dp0launch\start_garden.bat"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" pause
exit /b %EC%
