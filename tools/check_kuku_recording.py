"""查明 哭哭不嘻嘻 的 .part 到底怎么了。"""
import glob
import os
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


def snap():
    out = []
    if os.path.isdir(D):
        for f in sorted(os.listdir(D)):
            p = os.path.join(D, f)
            try:
                out.append((f, os.path.getsize(p),
                            time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(p)))))
            except Exception:
                pass
    return out


print('=' * 78)
print('1. 目录快照（第一次）')
print('=' * 78)
for f, sz, mt in snap():
    print(f'  {sz/1024/1024:>10.2f} MB  {mt}  {f}')

print()
print('  等 30 秒再看...')
time.sleep(30)
print()
print('=' * 78)
print('2. 目录快照（30 秒后）')
print('=' * 78)
for f, sz, mt in snap():
    print(f'  {sz/1024/1024:>10.2f} MB  {mt}  {f}')

print()
print('=' * 78)
print('3. 录制进程状态')
print('=' * 78)
procs = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
           "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }")
for line in procs.split('\n'):
    if '哭哭' in line:
        pid = line.split('|')[0]
        print(f'  ✅ 录制进程 PID {pid} 存活')
        # 看进程运行多久
        info = ps(f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | "
                  f"ForEach-Object {{ '启动 ' + $_.StartTime.ToString('HH:mm:ss') + '  CPU ' + [math]::Round($_.CPU,1) }}")
        print(f'      {info}')
if not any('哭哭' in l for l in procs.split('\n')):
    print('  ❌ 没有哭哭不嘻嘻的录制进程')

print()
print('=' * 78)
print('4. 是否有 ffmpeg 在转封装（说明分段刚录完）')
print('=' * 78)
ff = ps("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
        "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }")
if ff.strip():
    for l in ff.split('\n')[:5]:
        print(f'  {l[:170]}')
else:
    print('  （没有 ffmpeg 在跑）')

print()
print('=' * 78)
print('5. DMR 日志：哭哭不嘻嘻 最近 20 条（关键）')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
shown = 0
for lg in logs[:2]:
    try:
        lines = open(lg, encoding='utf-8', errors='replace').read().split('\n')
    except Exception:
        continue
    hits = [l.strip() for l in lines
            if '哭哭不嘻嘻' in l and not l.strip().startswith('"')]
    for l in hits[-20:]:
        print(f'  {l[:175]}')
        shown += 1
    if shown:
        break
if not shown:
    print('  （无）')

print()
print('=' * 78)
print('6. 有没有 ERROR / 录制中断迹象')
print('=' * 78)
errs = []
for lg in logs[:2]:
    try:
        for l in open(lg, encoding='utf-8', errors='replace').read().split('\n'):
            if ('哭哭不嘻嘻' in l or 'streamgears' in l) and \
               any(k in l for k in ('ERROR', 'error', '中断', '失败', '停止', 'Stopped', 'stop')):
                errs.append(l.strip())
    except Exception:
        continue
for l in errs[-15:]:
    print(f'  {l[:175]}')
if not errs:
    print('  （无错误）')
