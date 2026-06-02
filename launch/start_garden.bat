@echo off
cd /d "%~dp0.."
title PNN Garden

echo.
echo ========================================
echo   PNN Garden (API + Web)
echo ========================================
echo.

set "PY="
if exist "%USERPROFILE%\anaconda3\envs\AI\python.exe" (
  set "PY=%USERPROFILE%\anaconda3\envs\AI\python.exe"
) else if exist "%USERPROFILE%\miniconda3\envs\AI\python.exe" (
  set "PY=%USERPROFILE%\miniconda3\envs\AI\python.exe"
) else (
  set "PY=python"
)

"%PY%" scripts\launcher.py
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" pause
exit /b %EC%

