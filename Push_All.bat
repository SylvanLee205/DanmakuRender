@echo off
rem ASCII ONLY - do not add non-ASCII characters.
rem cmd.exe parses this file with the SYSTEM code page (GBK) BEFORE chcp takes
rem effect, so any Chinese here would break command parsing.
rem
rem Push BOTH repositories in one go:
rem   1) public  DanmakuRepo       branch main  (scrubbed, no configs/)
rem   2) private DanmakuRepo-Full  branch main       (full copy, runnable as-is)
rem
rem It refuses to run when master has uncommitted changes.
chcp 65001 <nul >nul
cd /d "%~dp0"
title Push both repos

".\.venv\Scripts\python.exe" tools\push_all.py --apply
if errorlevel 1 goto failed

echo.
echo [OK] Both repos are up to date.
echo      public  https://github.com/SylvanLee205/DanmakuRepo
echo      private https://github.com/SylvanLee205/DanmakuRepo-Full
pause
exit /b 0

:failed
echo.
echo [X] Push failed - see the message above.
echo     If it is an authentication problem, run this once:
echo        git credential reject
echo     ...then start this script again and sign in to GitHub.
pause
exit /b 1
