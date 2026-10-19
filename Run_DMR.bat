@echo off
rem ASCII ONLY. Used by the boot scheduled task.
rem Guard first: never start a second instance (state DB is a singleton).
chcp 65001 >nul
cd /d "%~dp0"
".\.venv\Scripts\python.exe" tools\autostart_guard.py
if errorlevel 2 call "%~dp0Start_Render.bat"
