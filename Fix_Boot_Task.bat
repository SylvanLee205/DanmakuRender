@echo off
setlocal
chcp 65001 >nul
title Fix DMR boot task settings
rem ASCII ONLY. Removes the default 72-hour execution limit from the boot task.
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights ... click "Yes" on the UAC prompt.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "F:\DanmakuRender_AutoUp\tools\install_boot_task.ps1"
echo.
echo Done. If it printed "OK", the 72-hour limit is gone.
pause
