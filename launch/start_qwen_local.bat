@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
title Qwen Local (llama-server)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo.
echo ========================================
echo   Local Qwen llama-server + .env patch
echo ========================================
echo.

set "PY="
if exist ".venv\Scripts\python.exe" (
  set "PY=%CD%\.venv\Scripts\python.exe"
) else if exist "%USERPROFILE%\anaconda3\envs\AI\python.exe" (
  set "PY=%USERPROFILE%\anaconda3\envs\AI\python.exe"
) else if exist "%USERPROFILE%\miniconda3\envs\AI\python.exe" (
  set "PY=%USERPROFILE%\miniconda3\envs\AI\python.exe"
) else (
  set "PY=python"
)

if not exist "scripts\qwen_local_launch.py" (
  echo [ERROR] scripts\qwen_local_launch.py missing
  pause
  exit /b 1
)

if not exist "models\Qwen3.6-35B-A3B-Uncensored\llama-server.exe" (
  echo [ERROR] models\Qwen3.6-35B-A3B-Uncensored\llama-server.exe not found
  echo         Place the Qwen llama.cpp bundle under models\
  pause
  exit /b 1
)

REM 默认：本地文字对话 + DashScope 云端识图（推荐）
REM 可选：--ngl 40  显存不足时减少 GPU 层
REM 可选：--port 8081
REM 不推荐：--vision-local  本地 mmproj 识图极慢且会阻塞对话
"%PY%" scripts\qwen_local_launch.py %*

set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo [FAILED] exit code %EC%
  echo   - Reduce GPU layers: launch\start_qwen_local.bat --ngl 30
  echo   - Port busy: use --port 8081 and update DEEPSEEK_BASE_URL in .env
  pause
  exit /b %EC%
)

echo.
echo [DONE] llama-server stopped.
pause
exit /b 0
