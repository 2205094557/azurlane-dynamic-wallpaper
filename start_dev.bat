@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto missing_venv

".venv\Scripts\python.exe" scripts\start_dev.py %*

echo.
echo [dev] Dev stack exited.
pause
exit /b 0

:missing_venv
echo [dev] .venv not found. Please create the virtual environment first.
pause
exit /b 1
