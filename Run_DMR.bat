@echo off
rem ASCII ONLY. This is the ACTION of the boot scheduled task.
rem
rem --boot-fallback 180 behaviour (supervise mode, stays resident):
rem   * someone is logged in  -> do nothing; the logon autostart (Startup
rem     folder entry + DanmakuRender_SessionWatch task) starts DMR inside the
rem     user session, so the console window is VISIBLE on the desktop
rem     (the familiar behaviour).
rem   * nobody logged in       -> after the 180s grace period, start DMR here
rem     in session 0 so recording never stops, then keep watching: if DMR
rem     dies while nobody is logged in, start it again.
rem   * logged in but DMR dead -> wait 10 minutes (the logon autostart retries
rem     itself), then session 0 fallback as a last resort (recording first).
rem This mode NEVER kills or migrates processes - migration is done by the
rem logon autostart only, so the two never fight.
rem Every decision is logged to logs\autostart.log (session 0 has no console).
chcp 65001 >nul
cd /d "%~dp0"
".\.venv\Scripts\python.exe" tools\autostart_launch.py --boot-fallback 180
