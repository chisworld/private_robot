@echo off

chcp 65001 >nul 2>&1

cd /d "%~dp0.."

title Pet-14

rem 强制 Python 输出 UTF-8，与 chcp 65001 对齐，避免终端中文乱码
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo.
echo ========================================
echo   14酱 桌宠 (API 8765 + Live2D)
echo ========================================
echo.

set "PY="

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
  echo [OK] system python
)

if not exist "scripts\launcher.py" (
  echo [ERROR] scripts\launcher.py missing
  pause
  exit /b 1
)

echo [TIP] Set DEEPSEEK_API_KEY in .env (copy from .env.example)
echo.

curl -s -o nul --connect-timeout 1 http://127.0.0.1:8765/api/health 2>nul

if %errorlevel%==0 (
  echo [FAST] API ready, starting pet UI...
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
  echo   - Port 8765/9880 busy: kill old python.exe in Task Manager
  echo   - Missing deps: pip install -r requirements.txt
  pause
  exit /b %EC%
)

echo.
echo [DONE] Pet closed.
pause
exit /b 0
