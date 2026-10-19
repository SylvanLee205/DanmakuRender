@echo off
rem ASCII ONLY. This is the ACTION of the boot scheduled task.
rem Runs the launcher in foreground so the task stays "Running" while DMR
rem lives, and every decision/exit is logged to logs\autostart.log
rem (session 0 has no console, the log is the only window into it).
chcp 65001 >nul
cd /d "%~dp0"
".\.venv\Scripts\python.exe" tools\autostart_launch.py --foreground
