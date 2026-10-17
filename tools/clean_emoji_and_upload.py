"""清掉 emoji 死任务 + 补传所有真正缺失的文件。

emoji 文件名的限制是已知的（Baidu errno -7）。这些文件：
  - 本地名: 相扑猫💦-2026年10月01日13点13分（弹幕版）.mp4
  - 云端名: 相扑猫-2026年10月01日13点13分（弹幕版）.mp4  ← emoji 已清洗
  - 字节数完全一致 → **已经上传成功了**，队列里的是重复任务的残骸

这些残骸永远不会成功，会无限重试占死 CD2 的单线程上传 → 必须清掉。
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'
UP = r'F:\DanmakuRender_AutoUp'
TMP = os.environ['TEMP']
BK = os.path.join(r'F:\_CD2配置备份_20261005', 'before_emoji_clean_' + time.strftime('%H%M%S'))


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or ''))


def queue():
    dst = os.path.join(TMP, 'cd2qz')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(NEW, 'clouddrive_data.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'clouddrive_data.sqlite' + s))
            except Exception:
                pass
    try:
        con = sqlite3.connect(f'file:{os.path.join(dst, "clouddrive_data.sqlite")}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute('SELECT dest_path, filename, size FROM transfer_tasks')
        r = cur.fetchall()
        con.close()
        return r
    except Exception:
        return []


def cloud_list(task):
    dst = os.path.join(TMP, 'cd2cl')
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
print('1. 清掉 emoji 死任务（它们已在云端，只是本地名带 emoji）')
print('=' * 78)
q = queue()
print(f'  队列 {len(q)} 条:')
for dest, fn, sz in q:
    print(f'    {fn}')

# emoji 判断
def has_emoji(s):
    return any(ord(c) > 0x2190 for c in s if not ('\u4e00' <= c <= '\u9fff'
                                                   or '\u3000' <= c <= '\u303f'
                                                   or '\uff00' <= c <= '\uffef'
                                                   or c.isascii()))

stale = [(d, f, s) for d, f, s in q if has_emoji(f)]
print(f'\n  其中带 emoji 的: {len(stale)} 个')

if stale:
    os.makedirs(BK, exist_ok=True)
    for f in ('clouddrive_data.sqlite', 'clouddrive_data.sqlite-wal',
              'clouddrive_data.sqlite-shm'):
        src = os.path.join(NEW, f)
        if os.path.exists(src):
            try:
                shutil.copy2(src, BK)
            except Exception:
                pass
    print(f'  已备份到 {BK}')
    ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")
    time.sleep(8)
    try:
        con = sqlite3.connect(os.path.join(NEW, 'clouddrive_data.sqlite'), timeout=30)
        cur = con.cursor()
        n = 0
        for dest, fn, sz in stale:
            cur.execute('DELETE FROM transfer_tasks WHERE dest_path=? AND filename=?',
                        (dest, fn))
            n += cur.rowcount
            print(f'    ✓ 删除: {fn}')
        con.commit()
        con.close()
        print(f'  共删 {n} 条')
    except Exception as e:
        print(f'  ❌ {type(e).__name__}: {e}')
    subprocess.Popen([APP, '--autostart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(12):
        time.sleep(5)
        if ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen "
              "-ErrorAction SilentlyContinue | Measure-Object).Count").strip() not in ('', '0'):
            print(f'  ✅ CD2 就绪（{(i+1)*5} 秒）')
            break

print()
print(f'  剩余队列: {len(queue())} 条')
for dest, fn, sz in queue():
    print(f'    {fn}')

print()
print('=' * 78)
print('2. 找出所有真正缺失的文件（09-30 之后）')
print('=' * 78)
REPLAY = os.path.join(UP, '直播回放')
to_upload = []
for t in sorted(os.listdir(REPLAY)):
    if not t.endswith('（弹幕版）'):
        continue
    task = t[:-len('（弹幕版）')]
    d = os.path.join(REPLAY, t)
    if not os.path.isdir(d):
        continue
    loc = {f: os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)
           if f.endswith('.mp4')}
    if not loc:
        continue
    cf = cloud_list(task)
    # 云端文件名可能经过 emoji 清洗，用 size 匹配更可靠
    cloud_sizes = set(str(v) for v in cf.values())
    for f, s in sorted(loc.items()):
        m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', f)
        if not m:
            continue
        key = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
        if key < '2026-09-30':
            continue
        # 名字直接匹配，或大小匹配（emoji 改名的情况）
        if f in cf or str(s) in cloud_sizes:
            continue
        to_upload.append((task, f, s, os.path.join(d, f)))

if not to_upload:
    print('  ✅ 没有缺失文件')
else:
    print(f'  缺 {len(to_upload)} 个:')
    for task, f, s, p in to_upload:
        print(f'    [{task}] {s/1024/1024:>8.1f} MB  {f}')

print()
if to_upload:
    print('=' * 78)
    print('3. 逐个上传')
    print('=' * 78)
    sent = []
    for task, f, s, p in to_upload:
        dest = f'cd2:百度网盘/DMR录播/{task}/{f}'
        print(f'\n  → [{task}] {f} ({s/1024/1024:.1f} MB)')
        r = subprocess.run([RCLONE, 'copyto', p, dest, '--retries', '2'],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=3600)
        print(f'     rclone exit={r.returncode}')
        if r.returncode != 0:
            print(f'     {(r.stderr or "")[:250]}')
        else:
            sent.append((task, f, s))

    print()
    print('=' * 78)
    print(f'4. 等 CD2 异步上传（{len(sent)} 个，共 '
          f'{sum(s for _,_,s in sent)/1024/1024:.0f} MB）')
    print('=' * 78)
    total = sum(s for _, _, s in sent) / 1024 / 1024
    print(f'  按 4.4 MB/s 约需 {total/4.4:.0f} 秒')
    waited = 0
    while waited < 2400 and sent:
        time.sleep(60)
        waited += 60
        done = 0
        for task, f, s in sent:
            cf = cloud_list(task)
            if f in cf and str(cf[f]) == str(s):
                done += 1
        print(f'    +{waited:>4}s  已确认 {done}/{len(sent)}')
        if done == len(sent):
            break

    print()
    print('=' * 78)
    print('5. 结果')
    print('=' * 78)
    ok = 0
    for task, f, s in sent:
        cf = cloud_list(task)
        if f in cf and str(cf[f]) == str(s):
            print(f'  ✅ {f}')
            ok += 1
        else:
            print(f'  ❌ {f}  云端={cf.get(f)} 本地={s}')
    print(f'\n  {ok}/{len(sent)} 成功')

print()
print('=' * 78)
print('6. 全量审计')
print('=' * 78)
r = subprocess.run([os.path.join(UP, '.venv', 'Scripts', 'python.exe'),
                    os.path.join(UP, 'tools', 'audit_cloud.py')],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=900, cwd=UP)
for l in r.stdout.split('\n'):
    if any(k in l for k in ('合计', '丢失', '清单来源')):
        print(f'  {l.strip()}')
