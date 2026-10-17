"""测试看门狗的拉起逻辑（真的把 CD2 停掉，看它能不能拉起来）。

这是必要的验证：如果看门狗只会在正常时静默退出、真出事时拉不起来，
那它就没用。CD2 是用户态应用，我停掉后能自己拉起来（父进程是 explorer）。
"""
import os
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
PY = os.path.join(UP, '.venv', 'Scripts', 'python.exe')
WD = os.path.join(UP, 'tools', 'cd2_watchdog.py')
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 测试前状态')
print('=' * 78)
print('  进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id }") or '无'))
print('  29798: ' + ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count.ToString()") + ' 个监听')

print()
print('=' * 78)
print('2. 【模拟故障】停掉 CD2')
print('=' * 78)
ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")
time.sleep(6)
print('  进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id }") or '✅ 已停止（模拟故障）'))
print('  29798: ' + ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count.ToString()") + ' 个监听')

print()
print('=' * 78)
print('3. 运行看门狗（应该检测到故障并拉起）')
print('=' * 78)
t0 = time.time()
r = subprocess.run([PY, WD], capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=180, cwd=UP)
el = time.time() - t0
print(f'  退出码: {r.returncode}  (1=做了拉起动作)')
print(f'  耗时  : {el:.1f}s')
print('  输出:')
for l in (r.stdout or '').split('\n'):
    if l.strip():
        print(f'    {l}')

print()
print('=' * 78)
print('4. 拉起后状态')
print('=' * 78)
print('  进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id + ' 启动 ' + $_.StartTime.ToString('HH:mm:ss') }") or '❌ 仍未启动'))
print('  29798: ' + ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count.ToString()") + ' 个监听')
try:
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen('http://127.0.0.1:29798/dav', timeout=10)
    except urllib.error.HTTPError as e:
        print(f'  WebDAV: HTTP {e.code} {"(401=正常)" if e.code == 401 else ""}')
except Exception as e:
    print(f'  WebDAV: {e}')

print()
print('=' * 78)
print('5. 再跑一次看门狗（现在应该静默退出 exit 0）')
print('=' * 78)
r2 = subprocess.run([PY, WD], capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=120, cwd=UP)
print(f'  退出码: {r2.returncode}  (0=正常无需处理)')
print(f'  输出  : {(r2.stdout or "").strip() or "(静默)"}')

print()
print('=' * 78)
print('6. 看门狗日志')
print('=' * 78)
lg = os.path.join(UP, 'logs', 'cd2_watchdog.log')
if os.path.exists(lg):
    for l in open(lg, encoding='utf-8', errors='replace').read().split('\n')[-12:]:
        if l.strip():
            print(f'    {l}')

print()
print('=' * 78)
print('结论')
print('=' * 78)
print(f'  看门狗能检测故障并拉起: {"✅ 是" if r.returncode == 1 and "CloudDrive" in ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }") else "⚠ 需检查"}')
print(f'  正常时静默退出        : {"✅ 是" if r2.returncode == 0 else "⚠ 否"}')
