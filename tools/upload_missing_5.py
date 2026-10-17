"""CD2 已恢复，补传那 5 个缺失文件。"""
import os
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
UP = r'F:\DanmakuRender_AutoUp'
TMP = os.environ['TEMP']

MISSING = [
    ('掉了颗兔牙', '掉了颗兔牙-2026年10月05日21点15分（弹幕版）.mp4'),
    ('掉了颗兔牙', '掉了颗兔牙-2026年10月05日22点15分（弹幕版）.mp4'),
    ('vvu', 'vvu-2026年10月06日15点59分（弹幕版）.mp4'),
    ('vvu', 'vvu-2026年10月06日16点26分（弹幕版）.mp4'),
    ('vvu', 'vvu-2026年10月06日17点26分（弹幕版）.mp4'),
]


def cloud_list(task):
    dst = os.path.join(TMP, 'cd2up5')
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
print('1. 逐个上传（用 copyto 控制目标名，避免嵌套目录）')
print('=' * 78)
sent = []
for task, name in MISSING:
    p = os.path.join(UP, '直播回放', f'{task}（弹幕版）', name)
    if not os.path.exists(p):
        print(f'  ❌ 本地不存在: {name}')
        continue
    size = os.path.getsize(p)
    print(f'\n  --- [{task}] {name}')
    print(f'      {size} 字节 ({size/1024/1024:.1f} MB)')
    dest = f'cd2:百度网盘/DMR录播/{task}/{name}'
    r = subprocess.run([RCLONE, 'copyto', p, dest, '--retries', '2',
                        '--transfers', '1'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=3600)
    print(f'      rclone exit={r.returncode}')
    if r.returncode != 0:
        print(f'      {(r.stderr or "")[:300]}')
        continue
    sent.append((task, name, size))

print()
print('=' * 78)
print('2. 等 CD2 异步上传（按文件大小给足时间）')
print('=' * 78)
# 总共约 1GB，按 4MB/s 约需 250 秒，给 300 秒
for i in range(10):
    time.sleep(30)
    done = 0
    for task, name, size in sent:
        cf = cloud_list(task)
        if cf.get(name) and int(cf[name]) == size:
            done += 1
    print(f'    +{(i+1)*30:>3}s  已确认 {done}/{len(sent)} 个')
    if done == len(sent):
        break

print()
print('=' * 78)
print('3. 最终验证')
print('=' * 78)
ok = 0
for task, name, size in sent:
    cf = cloud_list(task)
    got = cf.get(name)
    if got and int(got) == size:
        print(f'  ✅ {name}  字节一致 ({size})')
        ok += 1
    elif got:
        print(f'  ⚠ {name}  云端 {got} vs 本地 {size}')
    else:
        print(f'  ❌ {name}  云端还没有')

print()
print(f'  结果: {ok}/{len(sent)} 成功')

print()
print('=' * 78)
print('4. 全量审计')
print('=' * 78)
r = subprocess.run([os.path.join(UP, '.venv', 'Scripts', 'python.exe'),
                    os.path.join(UP, 'tools', 'audit_cloud.py')],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=900, cwd=UP)
for l in r.stdout.split('\n'):
    if '合计' in l or '丢失' in l or '清单来源' in l:
        print(f'  {l.strip()}')
