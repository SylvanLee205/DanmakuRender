"""最终完整性核查：本地 vs 云端，逐个任务对照（按大小匹配，兼容 emoji 改名）。"""
import os
import re
import shutil
import sqlite3
import subprocess

NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
TMP = os.environ['TEMP']
UP = r'F:\DanmakuRender_AutoUp'
REPLAY = os.path.join(UP, '直播回放')


def cloud_list(task):
    dst = os.path.join(TMP, 'cd2final')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(NEW, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    try:
        con = sqlite3.connect(f'file:{os.path.join(dst, "dir_cache.sqlite")}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute("SELECT id FROM cached_item WHERE path LIKE ?", (f'%/DMR录播/{task}',))
        out = {}
        for (did,) in cur.fetchall():
            cur.execute('SELECT name, size FROM files WHERE parent_id=?', (did,))
            for nm, sz in cur.fetchall():
                out[nm] = sz
        con.close()
        return out
    except Exception:
        return {}


print('=' * 78)
print('最终完整性核查（只看 09-30 之后，上传流水线启用时间）')
print('=' * 78)
print(f'  {"任务":16} {"本地(09-30后)":>12} {"云端":>6} {"缺失":>6}')
print('  ' + '-' * 60)
total_local, total_missing, total_mb = 0, 0, 0.0
missing_detail = []
for t in sorted(os.listdir(REPLAY)):
    if not t.endswith('（弹幕版）'):
        continue
    task = t[:-len('（弹幕版）')]
    d = os.path.join(REPLAY, t)
    if not os.path.isdir(d):
        continue
    loc = {}
    for f in os.listdir(d):
        if not f.endswith('.mp4'):
            continue
        m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', f)
        if not m:
            continue
        if f'{m.group(1)}-{m.group(2)}-{m.group(3)}' >= '2026-09-30':
            loc[f] = os.path.getsize(os.path.join(d, f))
    cf = cloud_list(task)
    cloud_sizes = set(str(v) for v in cf.values())
    miss = {f: s for f, s in loc.items()
            if f not in cf and str(s) not in cloud_sizes}
    total_local += len(loc)
    total_missing += len(miss)
    total_mb += sum(miss.values()) / 1024 / 1024
    flag = '' if not miss else f'  ← {len(miss)}'
    print(f'  {task:16} {len(loc):>12} {len(cf):>6} {len(miss):>6}{flag}')
    for f, s in sorted(miss.items()):
        missing_detail.append((task, f, s))

print()
print('=' * 78)
if total_missing == 0:
    print(f'  ✅ 完整！{total_local} 个文件全部在云端')
else:
    print(f'  ⚠ {total_local} 个文件中，{total_missing} 个缺失 ({total_mb:.1f} MB)')
    for task, f, s in missing_detail:
        print(f'      [{task}] {s/1024/1024:>8.1f} MB  {f}')
print('=' * 78)

print()
print('  组件状态:')
def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()
print('    CD2: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                   "ForEach-Object { 'PID ' + $_.Id }") or '未运行'))
print('    DMR: ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { 'PID ' + $_.ProcessId }") or '未运行'))
try:
    con = sqlite3.connect(f'file:{os.path.join(NEW, "clouddrive_data.sqlite")}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM transfer_tasks')
    print(f'    CD2 队列: {cur.fetchone()[0]} 条')
    con.close()
except Exception as e:
    print(f'    CD2 队列: {e}')
