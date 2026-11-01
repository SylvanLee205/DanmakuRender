@echo off
setlocal
chcp 65001 <nul >nul
title Remove DMR boot task
net session >nul 2>&1
if errorlevel 1 (
  echo [X] Need administrator: right-click this file - Run as administrator
  pause
  exit /b 1
)
set "TASK=DMR_Boot"
schtasks /query /tn "%TASK%" >nul 2>&1
if errorlevel 1 (
  echo Task "%TASK%" not found - nothing to remove.
  pause
  exit /b 0
)
schtasks /delete /tn "%TASK%" /f
echo Done. DMR will no longer start at boot.
pause
