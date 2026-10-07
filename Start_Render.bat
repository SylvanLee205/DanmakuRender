@echo off
rem ============================================================
rem  DanmakuRender launcher (ASCII only - DO NOT add non-ASCII!)
rem
rem  Why ASCII only:
rem    cmd.exe parses this file using the SYSTEM code page (936/GBK)
rem    BEFORE the chcp below takes effect. Any UTF-8 Chinese here
rem    would be misread as GBK and break command parsing, causing
rem    an endless flood of "not recognized as an internal command".
rem    Chinese notification text lives in notify_content.txt instead.
rem ============================================================

rem chcp 65001 so curl sends the UTF-8 notify text correctly
chcp 65001 >nul

title DanmakuRender_Guard

rem --- config ---
set "API_URL=https://17530.push.ft07.com/send/sctp17530thl3urer2dsbnw3rnqyxzep.send"
set "NOTIFY_FILE=F:\DanmakuRender_AutoUp\notify_content.txt"
rem ---------------

:loop
cls
echo [%date% %time%] Starting DanmakuRender ...

rem Send restart notification.
rem   -m 15      : timeout, otherwise a stuck network blocks startup forever
rem   --data-urlencode "desp@file" : read body from UTF-8 file
curl -s -m 15 --data-urlencode "title=DanmakuRender" --data-urlencode "desp@%NOTIFY_FILE%" "%API_URL%" >nul 2>&1

rem switch to project drive and dir
F:
cd "F:\DanmakuRender_AutoUp"

rem run in venv (quiet: only key progress + warnings)
".\.venv\Scripts\python.exe" main.py --quiet

echo.
echo [%date% %time%] WARNING: program exited (crash or manual close).
echo Restarting in 10 seconds ...
echo.

timeout /t 10
goto loop
