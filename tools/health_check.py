"""近期问题排查：错误、清理、上传、云端完整性。"""
import glob
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRepo'
REPLAY = os.path.join(UP, '直播回放')
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 组件状态')
print('=' * 78)
print('  现在: ' + ps("(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')"))
cmd = ps("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
         "ForEach-Object { $_.ProcessId }").split()
py = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*main.py*' } | "
        "ForEach-Object { $_.ProcessId }").split()
print(f'  守护 cmd: {cmd or "❌ 无"}')
print(f'  DMR py  : {py or "❌ 无"}')
print(f'  CD2     : {ps("(Get-Service CloudDrive2).Status.ToString()")}  '
      f'19798={ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')
_sg_q = ("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*streamgears*' } | Measure-Object).Count")
print(f'  录制进程: {ps(_sg_q)} 个')

# 队列
import shutil
import sqlite3
dst = os.path.join(os.environ['TEMP'], 'hc_q')
os.makedirs(dst, exist_ok=True)
for s in ('', '-wal', '-shm'):
    src = os.path.join(SVC, 'clouddrive_data.sqlite' + s)
    if os.path.exists(src):
        try:
            shutil.copy2(src, os.path.join(dst, 'clouddrive_data.sqlite' + s))
        except Exception:
            pass
try:
    con = sqlite3.connect(f'file:{os.path.join(dst, "clouddrive_data.sqlite")}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute('SELECT filename, size FROM transfer_tasks')
    rows = cur.fetchall()
    print(f'  CD2 队列: {len(rows)} 条')
    for f, s in rows[:10]:
        print(f'      {f}  ({int(s)/1024/1024:.1f} MB)')
    con.close()
except Exception as e:
    print(f'  队列查询失败: {e}')

logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)

print()
print('=' * 78)
print('2. 错误与警告统计（最近 3 个日志）')
print('=' * 78)
errs = []
warns = []
for lg in logs[:3]:
    try:
        for line in open(lg, encoding='utf-8', errors='replace'):
            s = line.strip()
            if s.startswith('"'):
                continue
            if '[error]' in s or 'ERROR' in s or 'Traceback' in s or 'NameError' in s:
                errs.append(s)
            elif '[warning]' in s or 'WARNING' in s:
                warns.append(s)
    except Exception:
        continue
print(f'  ERROR 类: {len(errs)} 条')
for l in errs[-12:]:
    print(f'    {l[:170]}')
print()
print(f'  WARNING 类: {len(warns)} 条，尾部 10 条:')
for l in warns[-10:]:
    print(f'    {l[:170]}')

print()
print('=' * 78)
print('3. 清理是否恢复正常')
print('=' * 78)
clean = []
for lg in logs[:3]:
    try:
        for line in open(lg, encoding='utf-8', errors='replace'):
            s = line.strip()
            if '正在清理原文件' in s or '清理完成' in s or '清理错误' in s:
                clean.append(s)
    except Exception:
        continue
print(f'  清理相关日志 {len(clean)} 条，尾部 12 条:')
for l in clean[-12:]:
    print(f'    {l[:170]}')
if not clean:
    print('    （这段时间没有清理活动）')
bad = [l for l in clean if '错误' in l or 'not defined' in l]
print(f'\n  清理错误: {len(bad)} 条  {"✅ 无" if not bad else "❌ 还有"}')

print()
print('=' * 78)
print('4. 滞留源文件检查')
print('=' * 78)
stale = []
for d in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, d)
    if not os.path.isdir(sub) or d.endswith('（弹幕版）'):
        continue
    for f in os.listdir(sub):
        if f.endswith(('.mkv', '.flv', '.ass')):
            p = os.path.join(sub, f)
            age_h = (time.time() - os.path.getmtime(p)) / 3600
            stale.append((age_h, os.path.getsize(p) / 1024 / 1024, d, f))
stale.sort(reverse=True)
print(f'  源目录文件共 {len(stale)} 个（含正常的历史/进行中）')
print('  超过 3 小时且未被清理的（可能是问题）:')
n = 0
for age_h, mb, d, f in stale:
    if age_h > 3:
        n += 1
        if n <= 15:
            print(f'    {age_h:>6.1f}h  {mb:>8.1f} MB  [{d}] {f[:55]}')
if n == 0:
    print('    ✅ 无（清理正常）')
elif n > 15:
    print(f'    ... 还有 {n-15} 个')

print()
print('=' * 78)
print('5. 未处理完的分段（有源无弹幕版）')
print('=' * 78)
issue = []
for d in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, d)
    if not os.path.isdir(sub) or d.endswith('（弹幕版）'):
        continue
    dm = os.path.join(REPLAY, d + '（弹幕版）')
    mps = set(os.listdir(dm)) if os.path.isdir(dm) else set()
    for f in os.listdir(sub):
        if not f.endswith('.mkv'):
            continue
        if f.startswith('[正在录制]') or f.startswith('[正在'):
            continue
        stem = os.path.splitext(f)[0]
        if stem + '（弹幕版）.mp4' not in mps:
            age_h = (time.time() - os.path.getmtime(os.path.join(sub, f))) / 3600
            issue.append((age_h, d, f, os.path.getsize(os.path.join(sub, f)) / 1024 / 1024))
issue.sort(reverse=True)
print(f'  有源 .mkv 但没有（弹幕版）.mp4 的: {len(issue)} 个')
for age_h, d, f, mb in issue[:12]:
    print(f'    {age_h:>6.1f}h  {mb:>8.1f} MB  [{d}] {f[:55]}')

print()
print('=' * 78)
print('6. 日志文件活跃度')
print('=' * 78)
for lg in logs[:3]:
    age = time.time() - os.path.getmtime(lg)
    print(f'  {os.path.basename(lg)}  {os.path.getsize(lg):>9} 字节  '
          f'{int(age)}s 前  {"✅" if age < 600 else "⚠"}')
