@echo off
rem ASCII ONLY - do not add non-ASCII characters.
rem One-click health check. Run this FIRST whenever something looks wrong.
rem
rem   Doctor.bat              full report
rem   Doctor.bat --brief      only show problems
rem   Doctor.bat --export     also pack a diagnostic zip into .temp\ (send it to AI)
chcp 65001 <nul >nul
cd /d "%~dp0"
title DMR Doctor

call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found on this machine.
  echo     Run Setup.bat once ^(double-click it^) - it installs everything.
  pause
  exit /b 1
)
"%DMR_PY%" tools\doctor.py %*
echo.
pause
