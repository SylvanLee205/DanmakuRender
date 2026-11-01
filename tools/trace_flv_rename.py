"""查清为什么三个 .flv 没被改名处理。

已知：
  - 正常流程：streamgears 分段结束 -> stream_downloader 把 [正在录制]xxx.flv
    改名为 "哭哭不嘻嘻-YYYY年MM月DD日HH点MM分.mkv" -> 发 livesegment 事件
  - 日志里 00:20:39 有一次成功的改名（232039 -> 23点20分.mkv）
  - 但 223036 / 233035 / 003037 三个从没被改名

要查：
  1. 完整看 stream_downloader 的改名逻辑（触发条件）
  2. 日志里这几个时间戳附近发生了什么
  3. 是否有 liveerror / 异常退出
"""
import glob
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRepo'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 日志里所有 "Rename" 记录（改名是分段落地的标志）')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
allrename = []
for lg in logs[:6]:
    for line in open(lg, encoding='utf-8', errors='replace'):
        if 'Rename video file' in line:
            allrename.append((os.path.basename(lg), line.strip()))
print(f'  共 {len(allrename)} 条 Rename 记录，全部列出:')
for f, l in allrename:
    print(f'    {l[:175]}')

print()
print('=' * 78)
print('2. 哭哭不嘻嘻 相关的 stream_downloader 日志（含改名/分段）')
print('=' * 78)
hits = []
for lg in logs[:6]:
    for line in open(lg, encoding='utf-8', errors='replace'):
        s = line.strip()
        if 'stream_downloader' in s and '哭哭' in s:
            hits.append(s)
for l in hits:
    print(f'  {l[:175]}')
if not hits:
    print('  （无）')

print()
print('=' * 78)
print('3. 23:30 / 00:30 / 00:38 前后发生了什么')
print('=' * 78)
for target in ('23:29:', '23:30:', '00:29:', '00:30:', '00:38:', '00:39:',
               '02:40:'):
    print(f'\n  --- 含 "{target}" 的日志 ---')
    found = []
    for lg in logs[:4]:
        for line in open(lg, encoding='utf-8', errors='replace'):
            s = line.strip()
            if target in s and not s.startswith('"'):
                found.append(s)
    # 只看关键行
    key = [l for l in found
           if any(k in l for k in ('Rename', 'livesegment', 'livestart',
                                   'liveend', 'liveerror', 'streamgears',
                                   'stream_downloader', 'ERROR', 'error',
                                   '哭哭', '分段'))]
    for l in key[-8:]:
        print(f'    {l[:170]}')
    if not key:
        print('    （无关键日志）')

print()
print('=' * 78)
print('4. 有没有 liveerror / 异常退出')
print('=' * 78)
errs = []
for lg in logs[:6]:
    for line in open(lg, encoding='utf-8', errors='replace'):
        s = line.strip()
        if s.startswith('"'):
            continue
        if any(k in s for k in ('liveerror', '异常退出', 'download error',
                                'Stream-gears 异常', '录制过程出错')):
            errs.append(s)
for l in errs[-25:]:
    print(f'  {l[:175]}')
if not errs:
    print('  （无）')

print()
print('=' * 78)
print('5. 这三个 .flv 能否被 ffprobe 读取（判断是否完整/可播放）')
print('=' * 78)
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')
for f in sorted(os.listdir(D)):
    if not f.endswith('.flv'):
        continue
    p = os.path.join(D, f)
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration,size,format_name',
                        '-of', 'default=nw=1', p],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    print(f'  {f}')
    for l in (r.stdout or '').strip().split('\n'):
        print(f'      {l}')
    if r.returncode != 0:
        print(f'      ⚠️ ffprobe 失败: {(r.stderr or "")[:150]}')

print()
print('=' * 78)
print('6. 现在还在录吗（streamgears 进程）')
print('=' * 78)
out = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
         "ForEach-Object { $_.ProcessId }")
print(f'  所有 streamgears 进程 PID: {out.split() if out.strip() else "无"}')
print()
print('  全部正在录制的任务:')
det = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
         "ForEach-Object { $_.CommandLine }")
for l in det.split('\n'):
    m = re.search(r'-o\s+\./直播回放/(\S+)', l)
    if m:
        print(f'    {m.group(1)}')
if '哭哭' not in det:
    print('    （哭哭不嘻嘻已下播，无录制进程）')
