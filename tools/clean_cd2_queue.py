"""清掉 CD2 队列里无限重试的堵塞任务，让正常的 .tmpupload 能上传。

⚠️ 直接改 CD2 的数据库需要先停服务。做之前必备份。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import time

NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'
BK = os.path.join(r'F:\_CD2配置备份_20261005',
                  'before_queue_clean_' + time.strftime('%H%M%S'))

# 要删掉的堵塞任务（云端已有 → 重复上传 → 永远 PermissionDenied）
REMOVE = [
    ('/百度网盘/DMR录播/掉了颗兔牙', '掉了颗兔牙-2026年10月05日21点15分（弹幕版）.mp4'),
    ('/百度网盘/DMR录播/掉了颗兔牙', '掉了颗兔牙-2026年10月05日22点15分（弹幕版）.mp4'),
    ('/百度网盘/DMR录播/苏苏没烦恼', '苏苏没烦恼-2026年09月30日20点46分（弹幕版）.mp4'),
    ('/百度网盘/DMR录播/苏苏没烦恼', '苏苏没烦恼-2026年09月30日21点46分（弹幕版）.mp4'),
    ('/百度网盘/DMR录播/苏苏没烦恼', '苏苏没烦恼-2026年09月30日22点46分（弹幕版）.mp4'),
    ('/百度网盘/DMR录播/苏苏没烦恼', '苏苏没烦恼-2026年10月04日00点24分（弹幕版）.mp4'),
]


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 备份 + 停止 CD2（改数据库必须停）')
print('=' * 78)
os.makedirs(BK, exist_ok=True)
for f in ('clouddrive_data.sqlite', 'clouddrive_data.sqlite-wal',
          'clouddrive_data.sqlite-shm'):
    src = os.path.join(NEW, f)
    if os.path.exists(src):
        shutil.copy2(src, BK)
        print(f'  ✓ {f}')
ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")
time.sleep(8)
print(f'  CD2 已停: {ps("(Get-Process CloudDrive -ErrorAction SilentlyContinue | Measure-Object).Count")} 个进程')

print()
print('=' * 78)
print('2. 改数据库：删掉堵塞任务')
print('=' * 78)
db = os.path.join(NEW, 'clouddrive_data.sqlite')
try:
    con = sqlite3.connect(db, timeout=30)
    cur = con.cursor()
    cur.execute('PRAGMA table_info(transfer_tasks)')
    cols = [r[1] for r in cur.fetchall()]
    print(f'  表结构: {cols}')
    print()
    print('  删前全部任务:')
    cur.execute('SELECT dest_path, filename, size FROM transfer_tasks')
    for r in cur.fetchall():
        print(f'    {r[1]}  ({r[2]} 字节)')

    removed = 0
    for dest, fn in REMOVE:
        cur.execute('DELETE FROM transfer_tasks WHERE dest_path=? AND filename=?',
                    (dest, fn))
        if cur.rowcount:
            removed += cur.rowcount
            print(f'  ✓ 删除: {fn}')
    con.commit()

    print()
    print('  删后剩余任务:')
    cur.execute('SELECT dest_path, filename, size FROM transfer_tasks')
    left = cur.fetchall()
    for r in left:
        print(f'    {r[1]}  ({r[2]} 字节)')
    con.close()
    print(f'\n  共删除 {removed} 条，剩余 {len(left)} 条')
except Exception as e:
    print(f'  ❌ 失败: {type(e).__name__}: {e}')

print()
print('=' * 78)
print('3. 重启 CD2')
print('=' * 78)
subprocess.Popen([APP, '--autostart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for i in range(12):
    time.sleep(5)
    n = ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count").strip()
    if n and n != '0':
        print(f'  ✅ CD2 就绪（{(i+1)*5} 秒）')
        break
else:
    print('  ⚠ 未就绪')

print()
print('=' * 78)
print('4. 等 180 秒，看 .tmpupload 有没有传上去')
print('=' * 78)
TMP = os.environ['TEMP']
for i in range(6):
    time.sleep(30)
    dst = os.path.join(TMP, 'cd2w')
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
        cur.execute("SELECT id FROM cached_item WHERE path LIKE ?", ('%/DMR录播/掉了颗兔牙',))
        found = []
        for (did,) in cur.fetchall():
            cur.execute('SELECT name FROM files WHERE parent_id=? AND name LIKE ?',
                        (did, '%tmpupload%'))
            found += [r[0] for r in cur.fetchall()]
        con.close()
    except Exception as e:
        found = [f'(err {e})']
    print(f'    +{(i+1)*30:>3}s  tmpupload 在云端: {len([f for f in found if "err" not in f])} 个')
    if len([f for f in found if 'err' not in f]) >= 2:
        break

print()
print('=' * 78)
print('5. CD2 日志尾部')
print('=' * 78)
ld = os.path.join(NEW, 'log')
today = time.strftime('%Y-%m-%d') + '.log'
fp = os.path.join(ld, today)
if os.path.exists(fp):
    lines = open(fp, encoding='utf-8', errors='replace').read().split('\n')
    for l in lines[-15:]:
        if l.strip():
            print(f'    {l[:175]}')
