@echo off
rem ============================================================
rem  DanmakuRender launcher / crash-restart guard
rem  ASCII ONLY - DO NOT add non-ASCII characters!
rem
rem  Why ASCII only:
rem    cmd.exe parses this file with the SYSTEM code page (936/GBK)
rem    BEFORE the chcp below takes effect. UTF-8 Chinese here would
rem    be misread as GBK, break command parsing, and flood the
rem    console with "not recognized as an internal command".
rem    (This actually happened on 2026-10-07.)
rem
rem  Notification is NOT sent from here. DMR itself sends it after a
rem  successful start (see tools/gen_restart_notify.py), so the
rem  message reflects the real state instead of "about to start".
rem ============================================================

rem chcp 65001 keeps console output readable
chcp 65001 >nul

title DanmakuRender_Guard

:loop
cls
echo [%date% %time%] Starting DanmakuRender ...

rem switch to project drive and dir
F:
cd "F:\DanmakuRender_AutoUp"

rem run in venv
rem   --quiet : keep all INFO (so each streamer's load/live state is visible)
rem             but filter out the engine message-dict noise
".\.venv\Scripts\python.exe" main.py --quiet

echo.
echo [%date% %time%] WARNING: program exited (crash or manual close).
echo Restarting in 10 seconds ...
echo.

timeout /t 10
goto loop
