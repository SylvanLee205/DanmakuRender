@echo off
rem ASCII ONLY. Live view of DMR's log + periodic status line.
rem Use this when there is no console window to look at (session 0 / RDP closed).
chcp 65001 >nul
cd /d "%~dp0"
title DMR live log
".\.venv\Scripts\python.exe" tools\watch_log.py
echo.
pause
