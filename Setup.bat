@echo off
rem ============================================================
rem  DanmakuRepo one-click setup.  ASCII ONLY.
rem
rem  Double-click this file on a brand new machine:
rem    1. finds any Python 3 (venv / portable / py launcher / PATH)
rem    2. creates .venv inside the project
rem    3. installs requirements.txt
rem    4. locates or downloads ffmpeg / ffprobe / rclone
rem    5. creates configs\global.yml if it is missing
rem    6. optionally creates desktop shortcuts + boot task
rem
rem  It is safe to run again at any time - every step is idempotent.
rem ============================================================
chcp 65001 <nul >nul
cd /d "%~dp0"
title DanmakuRepo Setup

echo.
echo  ==============================================================
echo    DanmakuRepo - setup / repair
echo  ==============================================================

call "%~dp0_env.bat"
if errorlevel 1 goto :no_python

echo.
echo  Using Python: %DMR_PY%
echo.
"%DMR_PY%" tools\bootstrap.py %*

set RC=%errorlevel%
echo.
if not "%RC%"=="0" (
  echo  [X] Setup finished with errors ^(code %RC%^).
  echo      Read the messages above - they say exactly what is missing.
) else (
  echo  [OK] Setup finished.
)
echo.
pause
exit /b %RC%

:no_python
echo.
echo  ==============================================================
echo   Python 3 was NOT found on this machine.
echo  ==============================================================
echo.
echo   Install it once, then double-click this file again:
echo.
echo     https://www.python.org/downloads/
echo.
echo   IMPORTANT: tick "Add python.exe to PATH" in the installer.
echo.
echo   Alternatives that also work without installing anything:
echo     * put a portable python at  %~dp0python\python.exe
echo     * install Python from the Microsoft Store
echo.
echo   Opening the download page for you ...
start "" "https://www.python.org/downloads/"
echo.
pause
exit /b 1
