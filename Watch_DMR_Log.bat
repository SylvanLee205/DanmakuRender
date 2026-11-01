@echo off
rem ASCII ONLY. Live view of DMR's log + periodic status line.
rem Use this when there is no console window to look at (session 0 / RDP closed).
chcp 65001 <nul >nul
cd /d "%~dp0"
title DMR live log
rem -- resolve the Python interpreter (venv / portable / py launcher / PATH) --
call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found on this machine.
  echo     Run Setup.bat once ^(double-click it^) - it installs everything.
  pause
  exit /b 1
)
"%DMR_PY%" tools\watch_log.py
echo.
pause
