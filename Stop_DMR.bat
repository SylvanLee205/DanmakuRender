@echo off
rem ASCII ONLY - do not add non-ASCII characters.
rem Stop watchdog + DMR + recording children (streamgears / ffmpeg).
chcp 65001 <nul >nul
cd /d "%~dp0"
title DMR Stop
".\.venv\Scripts\python.exe" tools\stop_dmr.py
echo.
pause
