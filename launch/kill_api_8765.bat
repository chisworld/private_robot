@echo off

chcp 65001 >nul 2>&1

cd /d "%~dp0.."

echo Killing processes on port 8765 ...

if exist "%USERPROFILE%\anaconda3\envs\AI\python.exe" (

  set "PY=%USERPROFILE%\anaconda3\envs\AI\python.exe"

) else if exist "%USERPROFILE%\miniconda3\envs\AI\python.exe" (

  set "PY=%USERPROFILE%\miniconda3\envs\AI\python.exe"

) else (

  set "PY=python"

)

"%PY%" -c "import sys;sys.path.insert(0,'.');from pnn.core.api_health import kill_api_on_port,_pids_on_port;kill_api_on_port();print('remaining:',_pids_on_port(8765) or 'none')"

pause

