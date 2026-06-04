@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
title PNN Garden
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

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
