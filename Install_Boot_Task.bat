@echo off
setlocal
chcp 65001 >nul
title Install DMR boot task
rem ASCII ONLY.
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo [X] Need administrator: right-click this file - Run as administrator
  echo.
  pause
  exit /b 1
)
set "TASK=DanmakuRender_Boot"
set "ACTION=F:\DanmakuRender_AutoUp\Run_DMR.bat"
if not exist "%ACTION%" (
  echo [X] missing %ACTION%
  pause
  exit /b 1
)
echo Creating scheduled task "%TASK%"
echo   trigger : at system startup (runs BEFORE anyone logs on)
echo   account : Administrator - password asked now; Windows stores it as an
echo             LSA secret (same mechanism Autologon used)
echo   action  : %ACTION%
echo.
schtasks /create /tn "%TASK%" /tr "%ACTION%" /sc onstart /ru "Administrator" /rp * /rl highest /f
if errorlevel 1 (
  echo.
  echo [X] Create failed - nothing was changed.
  pause
  exit /b 1
)
echo.
echo Applying settings: no execution time limit, start if missed ...
powershell -NoProfile -Command "$n='%TASK%'; $s=Get-ScheduledTask -TaskName $n -ErrorAction Stop; $s.Settings.ExecutionTimeLimit='PT0S'; $s.Settings.StartWhenAvailable=$true; $s.Settings.DisallowStartIfOnBatteries=$false; $s.Settings.StopIfGoingOnBatteries=$false; $s.Settings.MultipleInstances='IgnoreNew'; Set-ScheduledTask -TaskName $n -Settings $s.Settings | Out-Null"
echo.
powershell -NoProfile -Command "Get-ScheduledTask -TaskName '%TASK%' | Format-List TaskName,State"
echo.
echo [OK] Installed. DMR will start at the next boot WITHOUT anyone logging in.
echo      The logon entry stays as a fallback (it skips when DMR already runs).
echo      Rollback: double-click Remove_Boot_Task.bat
pause
