@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
title private_robot 首次安装

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo.
echo ========================================
echo   private_robot 首次安装
echo   需要：Python 3.11+、网络（下载依赖）
echo ========================================
echo.

set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 Python 3.11 并勾选 Add to PATH
  echo        https://www.python.org/downloads/
  pause
  exit /b 1
)

"%PY%" scripts\first_run_setup.py
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" pause
exit /b %EC%
