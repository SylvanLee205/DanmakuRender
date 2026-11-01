@echo off
setlocal
chcp 65001 <nul >nul
title Fix DMR boot task
rem ASCII ONLY.
rem Re-imports the boot task from tools\boot_task.xml, which has
rem ExecutionTimeLimit = PT0S (unlimited). schtasks is the supported path;
rem Register-ScheduledTask via the CIM provider rejects this account's
rem credentials (0x8007052e) even though schtasks accepts them.
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights ... click "Yes" on the UAC prompt.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

set "TASK=DMR_Boot"
set "XML=F:\DanmakuRender_AutoUp\tools\boot_task.xml"
if not exist "%XML%" (
  echo [X] missing %XML%
  pause
  exit /b 1
)

echo Re-importing task "%TASK%" from XML.
echo The 72-hour runtime limit will be removed (PT0S = unlimited).
echo Please enter the Administrator password once when asked.
echo.
schtasks /create /tn "%TASK%" /xml "%XML%" /ru "Administrator" /rp * /f
if errorlevel 1 (
  echo.
  echo [X] Import failed. The existing task was NOT changed, so nothing is broken.
  echo     DMR still starts at boot via autologon. Send the text above to the assistant.
  pause
  exit /b 1
)

echo.
for /f "delims=" %%L in ('powershell -NoProfile -Command "(Get-ScheduledTask -TaskName '%TASK%').Settings.ExecutionTimeLimit"') do set "LIM=%%L"
for /f "delims=" %%S in ('powershell -NoProfile -Command "(Get-ScheduledTask -TaskName '%TASK%').State"') do set "ST=%%S"
echo   State              : %ST%
echo   ExecutionTimeLimit : %LIM%
echo.
if /i "%LIM%"=="PT0S" (
  echo [OK] 72-hour limit removed. Task is now unlimited.
) else (
  echo [WARN] Limit is still %LIM%. Send this screen to the assistant.
)
echo.
echo Verify later: double-click the post-boot check on the desktop,
echo section 7 should show "unlimited".
pause
