@echo off
setlocal
chcp 65001 <nul >nul
title Install DMR boot task
rem ASCII ONLY.
rem Self-elevate: without admin the task cannot be created.
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights ... please click "Yes" on the UAC prompt.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

set "TASK=DMR_Boot"
set "ACTION=F:\DanmakuRepo\Run_DMR.bat"
if not exist "%ACTION%" (
  echo [X] missing %ACTION%
  pause
  exit /b 1
)

echo ============================================================
echo  Create scheduled task: %TASK%
echo ============================================================
echo  trigger : at system startup (runs BEFORE anyone logs on)
echo  account : Administrator - password asked now; Windows stores it
echo            as an LSA secret (same mechanism Autologon used)
echo  action  : %ACTION%
echo.
echo  NOTE: the task runs in session 0, so it has NO console window.
echo        Everything it does is logged to:
echo          F:\DanmakuRepo\logs\autostart.log
echo        and DMR's own log: logs\DMR-YYYYMMDD*.log
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
echo Testing the task once now (safe: DMR may already be running, the guard
echo refuses to start a second instance) ...
schtasks /run /tn "%TASK%" >nul 2>&1
"%SystemRoot%\System32\ping.exe" -n 8 127.0.0.1 >nul
powershell -NoProfile -Command "$i=Get-ScheduledTaskInfo -TaskName '%TASK%'; '  LastRun : {0}' -f $i.LastRunTime; '  Result  : {0}   (0 = success, 267009 = still running)' -f $i.LastTaskResult"

echo.
echo ============================================================
echo  [OK] Installed.
echo ============================================================
echo  It now starts DMR at every boot, WITHOUT anyone logging in.
echo  The logon entry stays as a fallback (it skips if DMR already runs).
echo.
echo  How to check it is working later:
echo    1) double-click DMR post-boot check on the desktop
echo       -^> section 7 shows task state / last run / result
echo    2) open logs\autostart.log  -^> boot-task lines
echo    3) DMR's own log starts with: code version / 33 tasks / 0 ERROR
echo.
echo  Rollback: double-click Remove_Boot_Task.bat
echo.
pause
