"""用服务版口径摸清云端真实状态，然后补传真正缺失的文件。

教训（2026-10-06）：应用版的 dir_cache 里也会有**幻影条目** ——
它的 files 表条目不代表百度真的收到了。用户网页确认：
苏苏没烦恼 目录实际只有 9 个文件，应用版缓存却说 13 个。
所以**唯一可信的验证 = 用户网页看**；次可信 = 服务版缓存（与 rclone 一致）。

这个脚本：
  1. 用服务版缓存列出每个任务的云端真实文件
  2. 和本地对照，找出真正缺失的（09-30 之后）
  3. 补传
  4. 用服务版缓存复查
"""
import os
import re
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
UP = r'F:\DanmakuRender_AutoUp'
REPLAY = os.path.join(UP, '直播回放')
TMP = os.environ['TEMP']


def svc_cache_all():
    """读服务版缓存，返回 {任务: {文件名: 大小}}。"""
    dst = os.path.join(TMP, 'svcall')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(SVC_ROOT, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    out = {}
    q = os.path.join(dst, 'dir_cache.sqlite')
    if not os.path.exists(q):
        return out
    try:
        con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute("SELECT id, path FROM cached_item WHERE path LIKE ?", ('%/DMR录播/%',))
        for did, path in cur.fetchall():
            task = path.rstrip('/').split('/')[-1]
            if task.startswith('__'):
                continue
            cur.execute('SELECT name, size FROM files WHERE parent_id=?', (did,))
            for nm, sz in cur.fetchall():
                out.setdefault(task, {})[nm] = sz
        con.close()
    except Exception:
        pass
    return out


print('=' * 78)
print('1. 服务版看到的云端真实内容')
print('=' * 78)
cloud = svc_cache_all()
print(f'  {len(cloud)} 个任务目录')
for t in sorted(cloud):
    print(f'    {t}: {len(cloud[t])} 个文件')

print()
print('=' * 78)
print('2. 本地 vs 云端（只看 09-30 之后）')
print('=' * 78)
to_upload = []
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
    cf = cloud.get(task, {})
    cloud_sizes = set(str(v) for v in cf.values())
    miss = {f: s for f, s in loc.items()
            if f not in cf and str(s) not in cloud_sizes}
    if loc:
        mark = f'  ⚠ 缺 {len(miss)}' if miss else '  ✅'
        print(f'  {task:16} 本地 {len(loc):>3}  云端 {len(cf):>3}{mark}')
    for f, s in sorted(miss.items()):
        to_upload.append((task, f, s, os.path.join(d, f)))

print()
print('=' * 78)
print(f'3. 真正需要补传的: {len(to_upload)} 个')
print('=' * 78)
total_mb = sum(s for _, _, s, _ in to_upload) / 1024 / 1024
for task, f, s, p in to_upload:
    print(f'  [{task}] {s/1024/1024:>8.1f} MB  {f}')
print(f'\n  合计 {total_mb:.1f} MB，按 4.4 MB/s 约需 {total_mb/4.4:.0f} 秒')

if not to_upload:
    print('\n  ✅ 没有缺失文件')
    raise SystemExit(0)

print()
print('=' * 78)
print('4. 逐个上传')
print('=' * 78)
sent = []
for task, f, s, p in to_upload:
    dest = f'cd2:百度网盘/DMR录播/{task}/{f}'
    print(f'\n  → [{task}] {f}')
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
print(f'5. 等 CD2 异步上传（{len(sent)} 个）')
print('=' * 78)
waited = 0
while waited < 3000 and sent:
    time.sleep(60)
    waited += 60
    cloud = svc_cache_all()
    done = 0
    for task, f, s in sent:
        cf = cloud.get(task, {})
        if f in cf and str(cf[f]) == str(s):
            done += 1
    print(f'    +{waited:>4}s  服务版确认 {done}/{len(sent)}')
    if done == len(sent):
        break

print()
print('=' * 78)
print('6. 结果（服务版口径）')
print('=' * 78)
cloud = svc_cache_all()
ok = 0
for task, f, s in sent:
    cf = cloud.get(task, {})
    got = cf.get(f)
    if got and str(got) == str(s):
        print(f'  ✅ {f}')
        ok += 1
    else:
        print(f'  ❌ {f}  服务版云端={got}  本地={s}')
print(f'\n  {ok}/{len(sent)} 确认到达云端')

print()
print('=' * 78)
print('7. 复查所有任务')
print('=' * 78)
still = []
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
        if m and f'{m.group(1)}-{m.group(2)}-{m.group(3)}' >= '2026-09-30':
            loc[f] = os.path.getsize(os.path.join(d, f))
    cf = cloud.get(task, {})
    cloud_sizes = set(str(v) for v in cf.values())
    miss = {f: s for f, s in loc.items()
            if f not in cf and str(s) not in cloud_sizes}
    if miss:
        still.append((task, miss))
        print(f'  ⚠ {task}: 仍缺 {len(miss)}')
        for f, s in sorted(miss.items()):
            print(f'      {s/1024/1024:>8.1f} MB  {f}')
if not still:
    print('  ✅ 所有任务在服务版口径下都完整')
print()
print('  ⚠️ 提醒：服务版缓存与 rclone 一致，但**最终确认请在百度网盘网页看**。')
