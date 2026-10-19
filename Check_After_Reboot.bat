@echo off
rem ASCII ONLY. Post-reboot self check - read only.
chcp 65001 >nul
cd /d "%~dp0"
title DMR Post-Boot Check
".\.venv\Scripts\python.exe" tools\post_boot_check.py
echo.
pause
