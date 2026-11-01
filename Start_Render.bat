@echo off
rem ============================================================
rem  DanmakuRepo launcher / crash-restart guard
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
chcp 65001 <nul >nul

title DMR_Guard

rem Work from wherever this file lives.
rem NOTE 2026-11-02: a bare "F:" used to sit right below. On a machine with
rem no F: drive that line silently fails; if the project moved to another
rem drive it switched the cwd to the WRONG drive first. cd /d handles both.
cd /d "%~dp0"

rem -- resolve the Python interpreter (venv / portable / py launcher / PATH) --
rem    Done ONCE before the restart loop, not inside it.
call "%~dp0_env.bat"
if errorlevel 1 (
  echo [X] No Python 3 found on this machine.
  echo     Run Setup.bat once ^(double-click it^) - it installs everything.
  pause
  exit /b 1
)

:loop
cls
echo [%date% %time%] Starting DanmakuRepo ...

rem run in the resolved interpreter
rem   --quiet : keep all INFO (so each streamer's load/live state is visible)
rem             but filter out the engine message-dict noise
"%DMR_PY%" main.py --quiet

echo.
echo [%date% %time%] WARNING: program exited (crash or manual close).
echo Restarting in 10 seconds ...
echo.

rem NOTE: ping instead of timeout - timeout fails when there is no console
rem       (e.g. when started by a scheduled task in session 0) and the loop
rem       would restart the program with no delay at all.
"%SystemRoot%\System32\ping.exe" -n 11 127.0.0.1 >nul
goto loop
