@echo off
rem ASCII ONLY - do not add non-ASCII characters.
rem Why: cmd.exe parses this file with the SYSTEM code page (936/GBK)
rem   BEFORE the chcp below takes effect. UTF-8 Chinese here would be
rem   misread as GBK, break command parsing, and flood the console with
rem   "not recognized as an internal command". (Happened on 2026-10-07,
rem   and again on 2026-10-23 when Chinese comments were added here.)
rem
rem Add a Douyin live room as a recording task.
rem
rem How to use:
rem   1. Copy the live room link (any Douyin share text works, or just the
rem      room id).
rem   2. Double-click this file. It reads the clipboard, asks Douyin for the
rem      streamer name, and writes configs\DMR-<name>.yml.
rem   3. DMR picks the new file up automatically - no restart needed.
rem
rem One link or several at once are both fine.
rem
rem 2026-10-23: pause only appears when the script exits non-zero.
rem   It used to be an unconditional pause, and add_room.py once died from
rem   a clipboard-access segfault without printing anything - the user just
rem   saw a lone "press any key to continue" with no clue what happened.
rem   Now: on success the script itself waits for one Enter; on failure the
rem   exit code is printed explicitly before pausing.
chcp 65001 <nul >nul
cd /d "%~dp0"
title DMR Add Room
rem -- resolve the Python interpreter (venv / portable / py launcher / PATH) --
call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found on this machine.
  echo     Run Setup.bat once ^(double-click it^) - it installs everything.
  pause
  exit /b 1
)
"%DMR_PY%" tools\add_room.py
set RC=%errorlevel%
if not "%RC%"=="0" (
  echo.
  echo [X] add_room.py exited with code %RC%.
  echo     If nothing was printed above, the script crashed before any output.
  echo     Just try again - or paste the link manually when it asks.
  pause
)
