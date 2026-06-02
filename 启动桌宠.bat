@echo off
cd /d "%~dp0"
if not exist "%~dp0launch\start_pet.bat" (
  echo [ERROR] missing launch\start_pet.bat
  pause
  exit /b 1
)
call "%~dp0launch\start_pet.bat"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
