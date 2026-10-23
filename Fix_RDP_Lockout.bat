@echo off
setlocal
chcp 65001 <nul >nul
title Fix RDP lockout
rem ASCII ONLY.
rem Use this ONLY if you cannot connect over RDP again.
rem It turns auto-logon OFF so the console session is free, and offers to
rem log off the current console session (which is what actually blocks
rem /admin style RDP connections).
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo [X] Need administrator: right-click this file - Run as administrator
  echo.
  pause
  exit /b 1
)

echo Turning OFF auto-logon so the console session will not be occupied ...
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 0 /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v ForceAutoLogon /t REG_SZ /d 0 /f >nul
echo   done.
echo.

echo Current sessions:
query session
echo.
echo Next reboot will stop at the logon screen, so RDP always works.
echo.
echo If you need to free the console session RIGHT NOW, run:
echo     logoff 1
echo   (check the session id above first - only log off the CONSOLE one)
echo.
echo DMR is independent of sessions when the boot task is installed.
echo If it is not installed yet, start it after logging in: the desktop icon (Start_DMR.bat)
echo.
pause
