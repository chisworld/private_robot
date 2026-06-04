@echo off
cd /d "%~dp0.."
title PNN Garden

rem 强制 Python 输出 UTF-8，与 chcp 65001 对齐，避免终端中文乱码
chcp 65001 >nul 2>&1
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

