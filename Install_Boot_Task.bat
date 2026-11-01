@echo off
rem ASCII ONLY.
rem Create the "start DMR at boot" scheduled task.
rem
rem 2026-11-02: this used to build the task with a long schtasks command line
rem inside the .bat. It now delegates to tools\install_boot_task.py, which
rem generates everything at run time (no hard-coded paths, no UTF-16 XML
rem template) and reads the account password from the registry when
rem autologon is configured.
rem
rem Requires administrator - the python script asks for UAC itself, but we
rem also check here so the message is obvious.
chcp 65001 <nul >nul
cd /d "%~dp0"
title Install DMR boot task

net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights ... click "Yes" on the UAC prompt.
  rem %SystemRoot% is expanded here on purpose: this line runs before _env.bat.
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found. Run Setup.bat first.
  pause
  exit /b 1
)

echo ============================================================
echo  Create scheduled task: DMR_Boot
echo ============================================================
echo  trigger : at system startup (runs BEFORE anyone logs on)
echo  action  : %~dp0Run_DMR.bat
echo  account : the same one Windows uses for auto-logon; the password
echo            is read from the registry and stored by Windows as an
echo            LSA secret (never written into the task in clear text)
echo.
echo  NOTE: the task runs in session 0, so it has NO console window.
echo        Everything it does is logged to %~dp0logs\autostart.log
echo.
"%DMR_PY%" tools\install_boot_task.py %*
set RC=%errorlevel%
echo.
pause
exit /b %RC%
