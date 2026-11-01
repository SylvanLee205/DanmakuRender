@echo off
rem ASCII ONLY.
rem Remove the "start DMR at boot" scheduled task.
rem Delegates to tools\install_boot_task.py --remove (the same code that
rem created it), so the task name can never drift out of sync between the
rem two scripts - which is exactly what happened before with the XML template.
chcp 65001 <nul >nul
cd /d "%~dp0"
title Remove DMR boot task

net session >nul 2>&1
if errorlevel 1 (
  echo [X] Need administrator: right-click this file - Run as administrator
  pause
  exit /b 1
)

call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found. Run Setup.bat first.
  pause
  exit /b 1
)

"%DMR_PY%" tools\install_boot_task.py --remove
echo.
pause
