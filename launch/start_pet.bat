@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
title Pet-14

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo.
echo ========================================
echo   PNN Garden Pet (API 8765 + Live2D)
echo ========================================
echo.

set "PY="

if exist ".venv\Lib\site-packages\PySide6\__init__.py" (
  if exist ".venv\Lib\site-packages\sounddevice.py" (
    set "PY=%CD%\.venv\Scripts\python.exe"
    echo [OK] project .venv
  ) else (
    echo [WARN] .venv missing sounddevice, using conda AI
  )
)

if not defined PY (
  if exist "%USERPROFILE%\anaconda3\envs\AI\python.exe" (
    set "PY=%USERPROFILE%\anaconda3\envs\AI\python.exe"
    echo [OK] conda env AI
  ) else if exist "%USERPROFILE%\miniconda3\envs\AI\python.exe" (
    set "PY=%USERPROFILE%\miniconda3\envs\AI\python.exe"
    echo [OK] conda env AI
  ) else if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" (
    call "%USERPROFILE%\anaconda3\Scripts\activate.bat" AI 2>nul
    set "PY=python"
    echo [OK] conda activate AI
  ) else (
    set "PY=python"
    echo [WARN] system python - use conda env AI if pet fails to start
  )
)

if not exist "scripts\launcher.py" (
  echo [ERROR] scripts\launcher.py missing
  pause
  exit /b 1
)

if not exist "scripts\run_pet.py" (
  echo [ERROR] scripts\run_pet.py missing
  pause
  exit /b 1
)

echo [TIP] Set DEEPSEEK_API_KEY in .env (see .env.example)
echo.

echo [CHECK] API 8765 ...
"%PY%" scripts\check_api_for_pet.py 2>nul
set "API_UP=%ERRORLEVEL%"

if "%API_UP%"=="0" (
  echo [FAST] API ready, starting pet...
  echo [START] scripts\run_pet.py
  "%PY%" scripts\run_pet.py
) else (
  echo [START] launcher --pet --no-warmup
  "%PY%" scripts\launcher.py --pet --no-warmup
)

set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo [FAILED] exit code %EC%
  echo   - Run launch\kill_api_8765.bat if port 8765 is busy
  echo   - Or: pip install -r requirements.txt
  echo   - Log: data\logs\api_boot.log
  pause
  exit /b %EC%
)

echo.
echo [DONE] Pet closed.
pause
exit /b 0
