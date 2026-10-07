"""从 Start_Render.bat 移除通知逻辑（改由 DMR 在启动成功后发）。

理由：
    1. 避免重复通知（bat 发一次 + DMR 发一次）
    2. bat 在启动前发，只能说"我要启动了"；
       DMR 在启动成功后发，能说"已经起来了、加载了 N 个主播"，
       而且 DMR 根本没起来时不会误报成功。
    3. bat 越简单越不容易出错（它出过错：编码导致无限刷屏）

bat 仍然保持纯 ASCII。
"""
import os
import shutil
import time

UP = r'F:\DanmakuRender_AutoUp'
BAT = os.path.join(UP, 'Start_Render.bat')

BAT_ASCII = r'''@echo off
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
'''

print('=' * 78)
print('1. 备份')
print('=' * 78)
bk = BAT + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
if os.path.exists(BAT):
    shutil.copy2(BAT, bk)
    print(f'  已备份 {os.path.basename(bk)}')

print()
print('=' * 78)
print('2. 写新 bat')
print('=' * 78)
try:
    with open(BAT, 'w', encoding='ascii', newline='\r\n') as f:
        f.write(BAT_ASCII)
    print('  ✅ 写入成功')
except UnicodeEncodeError as e:
    print(f'  ❌ 非 ASCII: {e}')
    raise SystemExit(1)

raw = open(BAT, 'rb').read()
na = len([b for b in raw if b > 127])
print(f'  非 ASCII 字节: {na}  {"✅" if na == 0 else "❌"}')
print(f'  含 curl:        {b"curl" in raw}  （应为 False，通知已交给 DMR）')
print(f'  含 --quiet:     {b"--quiet" in raw}')
print(f'  含 main.py:     {b"main.py" in raw}')

print()
print('=' * 78)
print('3. 生效内容')
print('=' * 78)
for i, l in enumerate(raw.decode('ascii').split('\r\n'), 1):
    if l.strip() and not l.strip().startswith('rem'):
        print(f'  {i:2}| {l}')
