@echo off
rem ============================================================
rem  Resolve a Python interpreter for this project.  ASCII ONLY.
rem
rem  Usage (from another .bat in the project root):
rem      call "%~dp0_env.bat"
rem      if errorlevel 1 goto no_python
rem      "%DMR_PY%" tools\something.py
rem
rem  Why this file exists:
rem    Every launcher used to hard-code  .venv\Scripts\python.exe .
rem    On a freshly cloned copy there is no .venv, so every single
rem    button was dead. Now the interpreter is looked up in order:
rem
rem      1) <project>\.venv\Scripts\python.exe   (normal case)
rem      2) <project>\python\python.exe          (portable python)
rem      3) py -3 <any>                          (official launcher)
rem      4) python.exe in PATH                   (system install)
rem
rem    Step 1 and 2 make the project self-contained: unzip anywhere,
rem    run Setup.bat once, and the venv is created next to the code.
rem    Step 3/4 mean a machine that already has Python works without
rem    running Setup.bat at all.
rem
rem  ASCII only: cmd.exe parses this file with the system code page
rem  (936/GBK) BEFORE any chcp takes effect.
rem ============================================================

setlocal EnableExtensions
set "DMR_PY="
set "HERE=%~dp0"

rem ---- 0) make core Windows tools reachable --------------------------
rem Why: venv python started from a scheduled task (session 0) often gets a
rem PATH without System32. Then every subprocess.run(['powershell', ...])
rem or ['schtasks', ...] dies with FileNotFoundError, while the exact same
rem code works fine when the user runs it by hand. Prepending these two
rem directories fixes every such call at once, for this process and all
rem children it spawns.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

rem ---- 1) project virtualenv -------------------------------------------
if exist "%HERE%.venv\Scripts\python.exe" (
    set "DMR_PY=%HERE%.venv\Scripts\python.exe"
    goto :have_py
)

rem ---- 2) portable python inside the project ---------------------------
if exist "%HERE%python\python.exe" (
    set "DMR_PY=%HERE%python\python.exe"
    goto :have_py
)
if exist "%HERE%runtime\python.exe" (
    set "DMR_PY=%HERE%runtime\python.exe"
    goto :have_py
)

rem ---- 3) py launcher ---------------------------------------------------
for /f "usebackq delims=" %%P in (`py -3 -c "import sys;print(sys.executable)" 2^>nul`) do (
    set "DMR_PY=%%P"
    goto :have_py
)

rem ---- 4) python in PATH ------------------------------------------------
for /f "usebackq delims=" %%P in (`python -c "import sys;print(sys.executable)" 2^>nul`) do (
    set "DMR_PY=%%P"
    goto :have_py
)

:have_py
rem Publish DMR_PY to the caller's scope (endlocal does not affect
rem the value that is expanded on this very line).
endlocal & set "DMR_PY=%DMR_PY%"

rem Guard: the py/python probes above can occasionally print a warning
rem line instead of a path. Trust nothing that does not exist on disk.
if defined DMR_PY if not exist "%DMR_PY%" set "DMR_PY="

if not defined DMR_PY exit /b 1
exit /b 0
