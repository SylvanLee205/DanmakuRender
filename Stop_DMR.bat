@echo off
rem ASCII ONLY - do not add non-ASCII characters.
rem Stop watchdog + DMR + recording children (streamgears / ffmpeg).
chcp 65001 <nul >nul
cd /d "%~dp0"
title DMR Stop
rem -- resolve the Python interpreter (venv / portable / py launcher / PATH) --
call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found on this machine.
  echo     Run Setup.bat once ^(double-click it^) - it installs everything.
  pause
  exit /b 1
)
"%DMR_PY%" tools\stop_dmr.py
echo.
pause
