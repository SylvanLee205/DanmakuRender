"""重写 Start_Render.bat 为**纯 ASCII**，彻底避免编码问题。

背景（2026-10-07 事故）：
    原 bat 是 UTF-8 + 中文。虽然开头有 `chcp 65001`，但 cmd.exe
    **在解析到 chcp 之前就已经按系统代码页(936/GBK)解读了文件**，
    所以中文变乱码 → 命令破碎 → 无限刷屏：
        '_URL" >nul' 不是内部或外部命令...
        '彲鑳芥槸宕╂簝鎴栨墜鍔ㄥ叧闂級銆?echo' 不是内部或外部命令...

    更糟的是我用 Python 改文件时没显式指定编码，某些路径下按 GBK 写入，
    导致文件编码更乱。

解决方案：**bat 里一个中文都不放，全部用 ASCII。**
    - title 用英文
    - echo 用英文
    - 通知的中文文案放到 notify_content.txt（UTF-8），bat 只读文件
    - 这样 bat 无论按 GBK 还是 UTF-8 解析都完全一样

新 bat 结构：
    chcp 65001        -> 让 curl 的参数按 UTF-8 编码（保证中文不乱码）
    curl ... @notify_content.txt
    python main.py --quiet
"""
import os
import shutil
import time

UP = r'F:\DanmakuRender_AutoUp'
BAT = os.path.join(UP, 'Start_Render.bat')
NOTIFY = os.path.join(UP, 'notify_content.txt')

# ── 纯 ASCII 的批处理内容 ──
# 注意：不要在这里放任何非 ASCII 字符！
BAT_ASCII = r'''@echo off
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
'''

print('=' * 78)
print('1. 备份当前（坏的）bat')
print('=' * 78)
bk = BAT + '.bak-enc-' + time.strftime('%Y%m%d-%H%M%S')
if os.path.exists(BAT):
    shutil.copy2(BAT, bk)
    print(f'  已备份到 {os.path.basename(bk)}')

print()
print('=' * 78)
print('2. 写通知文案文件（UTF-8，中文放这里）')
print('=' * 78)
notify_text = 'DanmakuRender已成功复活。'
with open(NOTIFY, 'w', encoding='utf-8', newline='\n') as f:
    f.write(notify_text)
print(f'  {NOTIFY}')
print(f'  内容: {notify_text}')
print(f'  编码: UTF-8  大小 {os.path.getsize(NOTIFY)} 字节')

print()
print('=' * 78)
print('3. 写纯 ASCII 的 bat')
print('=' * 78)
# ⚠️ 关键：显式 encoding='ascii' 写 —— 如果有非 ASCII 字符会立刻报错，
#    这样能保证以后不会再犯同样的错
try:
    with open(BAT, 'w', encoding='ascii', newline='\r\n') as f:
        f.write(BAT_ASCII)
    print('  ✅ 写成功（已强制 ASCII 校验，没有非 ASCII 字符）')
except UnicodeEncodeError as e:
    print(f'  ❌ 内容里有非 ASCII 字符，必须去掉: {e}')
    raise SystemExit(1)

raw = open(BAT, 'rb').read()
non_ascii = [b for b in raw if b > 127]
crlf = b'\r\n' in raw
print(f'  大小: {len(raw)} 字节')
print(f'  非 ASCII 字节数: {len(non_ascii)}  {"✅ 纯 ASCII" if not non_ascii else "❌ 还有"}')
print(f'  行尾: {"CRLF" if crlf else "LF"}')
print(f'  含 --quiet: {b"--quiet" in raw}')
print(f'  含 -m 15:   {b"-m 15" in raw}')
print(f'  含 @%NOTIFY_FILE%: {b"@%NOTIFY_FILE%" in raw}')

print()
print('=' * 78)
print('4. 内容预览')
print('=' * 78)
for i, l in enumerate(raw.decode('ascii').split('\r\n'), 1):
    if l.strip():
        print(f'  {i:2}| {l}')
