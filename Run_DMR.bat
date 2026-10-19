@echo off
rem ASCII ONLY. This is the ACTION of the boot scheduled task.
rem
rem --boot-fallback 180 behaviour:
rem   * waits up to 180s for someone to log in. If a desktop appears, it exits
rem     and lets the logon autostart run DMR inside the user session, so the
rem     console window is VISIBLE on the desktop (the familiar behaviour).
rem   * if nobody logs in within 180s (autologon broken / nobody RDPs in),
rem     it starts DMR here in session 0 so recording never stops.
rem Every decision is logged to logs\autostart.log (session 0 has no console).
chcp 65001 >nul
cd /d "%~dp0"
".\.venv\Scripts\python.exe" tools\autostart_launch.py --boot-fallback 180
