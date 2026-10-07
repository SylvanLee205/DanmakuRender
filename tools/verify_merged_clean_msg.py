"""验证合并后的清理消息格式 + CD2 状态。"""
import os
import subprocess
import sys

sys.path.insert(0, r'F:\DanmakuRender_AutoUp')


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 合并后的清理消息格式预览')
print('=' * 78)
from os.path import basename

base = '苏苏没烦恼-2026年10月07日05点32分'
scenarios = [
    ('有弹幕文件（正常情况）', base + '.mkv', base + '.ass'),
    ('没有弹幕文件', base + '.mkv', None),
]
for label, src, dm in scenarios:
    has_dm = bool(dm)
    if has_dm:
        msg = f'正在清理原文件: {basename(src)}（含弹幕文件）'
    else:
        msg = f'正在清理原文件: {basename(src)}'
    print(f'  {label}:')
    print(f'    [PROGRESS] {msg}')
print()
print('  ❌ 改前（两行，还带 method 和路径）:')
print('    [info] 正在清理文件: delete ./直播回放/苏苏没烦恼\\苏苏没烦恼-...05点32分.mkv.')
print('    [info] 正在清理弹幕文件: delete ./直播回放/苏苏没烦恼\\苏苏没烦恼-...05点32分.ass.')
print()
print('  ✅ 改后（一行，只留文件名）:')
print('    [PROGRESS] 正在清理原文件: 苏苏没烦恼-...05点32分.mkv（含弹幕文件）')

print()
print('=' * 78)
print('2. 验证 cleaner 模块能正常导入（确认 _has_dm 变量没问题）')
print('=' * 78)
import importlib
for m in ('DMR.Cleaner', 'DMR.Task.liveevents', 'DMR.Uploader', 'DMR.Render'):
    try:
        importlib.import_module(m)
        print(f'  ✅ {m}')
    except Exception as e:
        print(f'  ❌ {m}: {type(e).__name__}: {e}')

print()
print('=' * 78)
print('3. 确认 PROGRESS 级别注册')
print('=' * 78)
import logging
try:
    from DMR.Task.liveevents import PROGRESS
    print(f'  PROGRESS 常量 = {PROGRESS}')
except Exception as e:
    print(f'  导入失败: {e}')
    PROGRESS = 25
print(f'  logging 里的名字: {logging.getLevelName(PROGRESS)}')

print()
print('=' * 78)
print('4. 组件状态')
print('=' * 78)
print('  CD2 服务版: ' + ps("(Get-Service CloudDrive2).Status.ToString() + ' / ' + "
                       "(Get-Service CloudDrive2).StartType.ToString()"))
print(f'  19798: {ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}  '
      f'19799: {ps("(Get-NetTCPConnection -LocalPort 19799 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}（应为 0）')
print('  DMR: ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { 'PID ' + $_.ProcessId }").replace('\n', ' ') or '未运行'))
print('  HTTPS 配置: ' + ps("Select-String -Path 'C:\\Windows\\System32\\config\\systemprofile\\Waytech\\CloudDrive2\\config.toml' "
                       "-Pattern 'enable_https' | ForEach-Object { $_.Line.Trim() }"))
