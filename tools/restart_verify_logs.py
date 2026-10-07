"""重启 DMR 使日志改动生效，并验证输出效果 + 挂载盘状态。"""
import glob
import os
import re
import shutil
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or ''))


def dmr_pids():
    out = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*main.py*' } | "
             "ForEach-Object { $_.ProcessId }")
    return [int(x) for x in out.split() if x.strip().isdigit()]


print('=' * 78)
print('1. 挂载盘状态（用户说 H: 挂载效果不错）')
print('=' * 78)
print(ps("Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name -eq 'H' } | "
         "ForEach-Object { '  H: 已用 ' + [math]::Round($_.Used/1GB,1) + ' GB / 可用 ' + "
         "[math]::Round($_.Free/1GB,1) + ' GB' }") or '  H: 不存在')
try:
    items = os.listdir('H:\\')
    print(f'  H:\\ 可访问，根目录 {len(items)} 项')
    for x in items[:8]:
        print(f'    {x}')
except Exception as e:
    print(f'  H:\\ 访问失败: {type(e).__name__}: {e}')

print()
print('=' * 78)
print('2. 停止 DMR')
print('=' * 78)
pids = dmr_pids()
print(f'  当前: {pids}')
ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
   "Where-Object { $_.CommandLine -like '*main.py*' } | "
   "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
time.sleep(5)
print(f'  停止后: {dmr_pids() or "✅ 已停"}')

# 记录旧日志位置
old_logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
                  key=os.path.getmtime, reverse=True)

print()
print('=' * 78)
print('3. 重启 DMR')
print('=' * 78)
subprocess.Popen([os.path.join(UP, '.venv', 'Scripts', 'python.exe'),
                  'main.py', '--quiet'],
                 cwd=UP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
for i in range(15):
    time.sleep(5)
    p = dmr_pids()
    if p:
        print(f'  ✅ 已启动（{(i+1)*5} 秒）: {p}')
        break
else:
    print('  ⚠ 没起来')

print()
print('=' * 78)
print('4. 验证新日志格式（等 60 秒看有没有新消息）')
print('=' * 78)
time.sleep(60)
new_logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
                  key=os.path.getmtime, reverse=True)
if new_logs:
    lg = new_logs[0]
    print(f'  日志: {os.path.basename(lg)}  ({os.path.getsize(lg)} 字节)')
    txt = open(lg, encoding='utf-8', errors='replace').read()
    lines = [l for l in txt.split('\n') if l.strip()]
    print(f'  共 {len(lines)} 行，尾部 15 行:')
    for l in lines[-15:]:
        print(f'    {l[:165]}')
    # 检查关键格式
    print()
    print('  格式检查:')
    checks = {
        '含长路径 [\'./直播回放/': '❌ 还有长路径（应该已消除）',
        'upload success': '❌ 还有 upload success（应该已消除）',
        'GOP:': '⚠ GOP 出现在控制台级别（应为 debug）',
    }
    for pat, bad in checks.items():
        n = txt.count(pat)
        print(f'    {pat!r}: {n} 次  {bad if n else "✅"}')

print()
print('=' * 78)
print('5. 最终状态')
print('=' * 78)
print(f'  DMR 进程: {dmr_pids()}')
print('  ' + ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -like '*main.py*' } | "
                "ForEach-Object { 'PID ' + $_.ProcessId + '  ' + $_.CommandLine }").strip().replace('\n', '\n  '))
print(f'  CD2 服务版: {ps("(Get-Service CloudDrive2).Status.ToString()")}')
print(f'  19798: {ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}  '
      f'19799: {ps("(Get-NetTCPConnection -LocalPort 19799 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')
