"""查清 哭哭不嘻嘻 那三个 .flv 到底怎么回事。

现象：
  三个 [正在录制]xxx.flv（已完成的分段，不是 .part）
  名字都带 [正在录制] 前缀，但它们是**录完的**分段
  没有对应的（弹幕版）.mp4

要查：
  1. 当前时间 / 现在是哪个分段在录
  2. 这三个 .flv 有没有被渲染（有没有 mp4）
  3. DMR 日志里 哭哭不嘻嘻 最近发生了什么
  4. .flv 是不是"待渲染"状态，还是渲染失败了
"""
import glob
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')
DM = os.path.join(UP, '直播回放', '哭哭不嘻嘻（弹幕版）')


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 时间与进程')
print('=' * 78)
print('  现在: ' + ps("(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')"))
print(f'  源目录文件数: {len(os.listdir(D)) if os.path.isdir(D) else 0}')
print(f'  弹幕版目录:   {len(os.listdir(DM)) if os.path.isdir(DM) else "不存在"}')

print()
print('  源目录内容:')
for f in sorted(os.listdir(D)):
    p = os.path.join(D, f)
    st = os.stat(p)
    print(f'    {st.st_size/1024/1024:>10.2f} MB  '
          f'{time.strftime("%m-%d %H:%M:%S", time.localtime(st.st_mtime))}  {f}')

print()
print('  弹幕版目录内容:')
if os.path.isdir(DM):
    for f in sorted(os.listdir(DM)):
        p = os.path.join(DM, f)
        st = os.stat(p)
        print(f'    {st.st_size/1024/1024:>10.2f} MB  '
              f'{time.strftime("%m-%d %H:%M:%S", time.localtime(st.st_mtime))}  {f}')

print()
print('  录制进程:')
out = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
         "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }")
cnt = 0
for line in out.split('\n'):
    if '哭哭' in line:
        cnt += 1
        pid = line.split('|')[0]
        m = re.search(r'-o\s+(\S+)', line)
        info = ps(f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | "
                  f"ForEach-Object {{ '启动 ' + $_.StartTime.ToString('MM-dd HH:mm:ss') }}")
        print(f'    ✅ PID {pid}  {info}  模板={m.group(1) if m else "?"}')
if not cnt:
    print('    ❌ 没有哭哭不嘻嘻的录制进程 —— 可能已下播')

print()
print('=' * 78)
print('2. 这三个 .flv 有没有被渲染（对应 mp4 存在吗）')
print('=' * 78)
flvs = [f for f in os.listdir(D) if f.endswith('.flv')]
mp4s = set(os.listdir(DM)) if os.path.isdir(DM) else set()
for f in sorted(flvs):
    # 提取时间戳 20261007223036
    m = re.search(r'-(\d{14})-', f)
    ts = m.group(1) if m else '?'
    # 找对应 mp4：名字里的时间会转成 2026年10月07日22点30分
    if len(ts) == 14:
        expect_part = f'{ts[:4]}年{ts[4:6]}月{ts[6:8]}日{ts[8:10]}点{ts[10:12]}分'
    else:
        expect_part = '?'
    hits = [x for x in mp4s if expect_part in x]
    print(f'  {f}')
    print(f'      时间戳 {ts} -> 期望 mp4 含 "{expect_part}"')
    print(f'      {"✅ 有渲染产物: " + hits[0] if hits else "❌ 没有渲染产物"}')

print()
print('=' * 78)
print('3. DMR 日志：哭哭不嘻嘻 最近的完整轨迹（30 条）')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
print(f'  日志文件: {[os.path.basename(x) for x in logs[:3]]}')
rows = []
for lg in logs[:2]:
    for line in open(lg, encoding='utf-8', errors='replace'):
        s = line.strip()
        if '哭哭不嘻嘻' in s and not s.startswith('"'):
            rows.append(s)
print(f'  共 {len(rows)} 条，尾部 30 条:')
for l in rows[-30:]:
    print(f'    {l[:170]}')

print()
print('=' * 78)
print('4. 有没有渲染错误 / flv 相关事件')
print('=' * 78)
errs = []
for lg in logs[:2]:
    for line in open(lg, encoding='utf-8', errors='replace'):
        s = line.strip()
        if s.startswith('"'):
            continue
        if any(k in s for k in ('.flv', 'livesegment', 'render', '渲染')) and \
           ('哭哭' in s or 'error' in s.lower() or 'ERROR' in s):
            errs.append(s)
for l in errs[-20:]:
    print(f'  {l[:170]}')
if not errs:
    print('  （无）')

print()
print('=' * 78)
print('5. 云端有没有 哭哭不嘻嘻 的新文件')
print('=' * 78)
import shutil
import sqlite3
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
dst = os.path.join(os.environ['TEMP'], 'kuku_cloud')
os.makedirs(dst, exist_ok=True)
for s in ('', '-wal', '-shm'):
    src = os.path.join(SVC, 'dir_cache.sqlite' + s)
    if os.path.exists(src):
        try:
            shutil.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + s))
        except Exception:
            pass
try:
    con = sqlite3.connect(f'file:{os.path.join(dst, "dir_cache.sqlite")}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute("SELECT id FROM cached_item WHERE path LIKE ?", ('%/DMR录播/哭哭不嘻嘻',))
    total = 0
    for (did,) in cur.fetchall():
        cur.execute('SELECT name, size FROM files WHERE parent_id=? ORDER BY name', (did,))
        for nm, sz in cur.fetchall():
            total += 1
            print(f'    {int(sz)/1024/1024 if str(sz).isdigit() else 0:>10.2f} MB  {nm}')
    if not total:
        print('    （云端无文件）')
    con.close()
except Exception as e:
    print(f'    查询失败: {e}')
