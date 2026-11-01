"""上传重新渲染成功的产物 + 处理失败渲染队列。

1. 上传 2 个成功的弹幕版
2. 从 .temp/failed_renders.json 移除本次已解决的条目（和之前失败的陈旧条目）
3. 保留损坏文件对应的条目（标记为不可用），由用户决定是否删除源文件
"""
import json
import os
import shutil
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT
os.chdir(UP)
sys.path.insert(0, UP)

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
QUEUE = os.path.join(UP, '.temp', 'failed_renders.json')

UPLOADS = [
    (r'直播回放\vvu（弹幕版）\vvu-2026年10月15日19点30分（弹幕版）.mp4', 'vvu'),
    (r'直播回放\小鱼大王（弹幕版）\小鱼大王-2026年10月15日21点21分（弹幕版）.mp4',
     '小鱼大王'),
]

print('=' * 78)
print('1. 上传重新渲染成功的产物')
print('=' * 78)
for rel, task in UPLOADS:
    p = os.path.join(UP, rel)
    if not os.path.exists(p):
        print(f'  ❌ 不存在: {rel}')
        continue
    sz = os.path.getsize(p)
    print(f'  → [{task}] {os.path.basename(p)}  ({sz/1024/1024:.1f} MB)')
    r = subprocess.run([RCLONE, 'copyto', p,
                        f'cd2:百度网盘/DMR录播/{task}/{os.path.basename(p)}',
                        '--retries', '3', '--low-level-retries', '10',
                        '--transfers', '1'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=3600)
    print(f'     exit={r.returncode}'
          + (f'  {(r.stderr or "").strip()[:120]}' if r.returncode else ''))

print()
print('=' * 78)
print('2. 等 CD2 传完并核对')
print('=' * 78)


def cloud_names(task):
    tmp = os.path.join(os.environ['TEMP'], 'upd_chk')
    os.makedirs(tmp, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(SVC, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(tmp, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    import sqlite3
    q = os.path.join(tmp, 'dir_cache.sqlite')
    try:
        con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute('SELECT id FROM cached_item WHERE path LIKE ?',
                    (f'%/DMR录播/{task}',))
        out = set()
        for (did,) in cur.fetchall():
            cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
            out |= {r[0] for r in cur.fetchall()}
        con.close()
        return out
    except Exception:
        return set()


for rel, task in UPLOADS:
    name = os.path.basename(rel)
    got = False
    for i in range(20):
        time.sleep(30)
        names = cloud_names(task)
        if name in names:
            print(f'  ✅ [{task}] 已到云端: {name}')
            got = True
            break
        if i % 3 == 0:
            print(f'     +{(i+1)*30}s 等待中...')
    if not got:
        print(f'  ⚠️ [{task}] 30 分钟内未确认: {name}')

print()
print('=' * 78)
print('3. 处理失败渲染队列')
print('=' * 78)
q = json.load(open(QUEUE, encoding='utf-8'))
print(f'  当前 {len(q)} 条')

# 已解决的输出路径（本次重渲染成功的）
SOLVED = {
    os.path.normpath(os.path.join(UP, UPLOADS[0][0])),
    os.path.normpath(os.path.join(UP, UPLOADS[1][0])),
}

remove, keep = [], []
for uid, task in list(q.items()):
    out = os.path.normpath(str(task.get('output') or ''))
    title = os.path.basename(out)
    if out in SOLVED:
        # 已成功渲染并上传
        remove.append((uid, title, '已重新渲染并上传'))
        continue
    # 源文件已不存在的陈旧条目
    vid = task.get('video') or {}
    vpath = vid.get('path') if isinstance(vid, dict) else None
    if vpath and not os.path.exists(str(vpath)):
        remove.append((uid, title, '源文件已不存在（陈旧）'))
        continue
    keep.append((uid, title))

print(f'  可移除 {len(remove)} 条:')
for uid, t, why in remove:
    print(f'    - {t[:70]}')
    print(f'        {why}')
print(f'  保留 {len(keep)} 条:')
for uid, t in keep[:15]:
    print(f'    · {t[:80]}')
if len(keep) > 15:
    print(f'    ... 还有 {len(keep)-15} 条')

if remove and '--apply' in sys.argv:
    shutil.copy2(QUEUE, QUEUE + f'.bak-{time.strftime("%Y%m%d-%H%M%S")}')
    for uid, _, _ in remove:
        q.pop(uid, None)
    with open(QUEUE, 'w', encoding='utf-8') as f:
        json.dump(q, f, ensure_ascii=False, indent=4)
    print(f'\n  ✅ 已移除 {len(remove)} 条，队列剩 {len(q)} 条')
    print(f'      （已备份原文件）')
else:
    print('\n  （未加 --apply，队列未改动）')
