@echo off
rem ASCII ONLY - do not add non-ASCII characters.
rem Start DMR if (and only if) no instance is already running.
rem NOTE: use ping (not timeout) for the short delay - timeout.exe fails when
rem       stdin is redirected, and a GNU timeout from Git Bash rejects /t.
chcp 65001 <nul >nul
cd /d "%~dp0"
title DMR Start
".\.venv\Scripts\python.exe" tools\autostart_guard.py
if errorlevel 2 (
    echo Starting DanmakuRepo ...
    explorer.exe "%~dp0Start_Render.bat"
) else (
    echo DanmakuRepo is already running - nothing to do.
)
"%SystemRoot%\System32\ping.exe" -n 6 127.0.0.1 >nul 2>nul
