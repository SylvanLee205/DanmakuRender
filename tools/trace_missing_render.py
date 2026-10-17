"""查清 苏苏没烦恼 10月04日00点24分 的弹幕版到底在哪。

背景：
    之前我补传过 苏苏没烦恼-2026年10月04日00点24分（弹幕版）.mp4 到云端，
    也验证过字节一致。但现在本地弹幕版目录里没有它，源 .mkv 还在。
    需要搞清：是本地被清了？还是从来没生成本地文件？
"""
import os
import shutil
import sqlite3
import subprocess

UP = r'F:\DanmakuRender_AutoUp'
REPLAY = os.path.join(UP, '直播回放')
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
TMP = os.environ['TEMP']
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'

TARGETS = [
    ('苏苏没烦恼', '苏苏没烦恼-2026年10月04日00点24分'),
    ('小鱼大王', '小鱼大王-2026年10月01日01点19分'),
]

print('=' * 78)
print('1. 本地源目录 vs 弹幕版目录（完整对照）')
print('=' * 78)
for task, stem in TARGETS:
    src = os.path.join(REPLAY, task)
    dm = os.path.join(REPLAY, f'{task}（弹幕版）')
    print(f'\n  【{task}】源文件里含 "{stem.split("-")[-1]}":')
    for d, label in ((src, '源'), (dm, '弹幕版')):
        if not os.path.isdir(d):
            print(f'    {label}目录不存在: {d}')
            continue
        hits = [f for f in os.listdir(d) if stem.split('-')[-1][:6] in f]
        print(f'    {label}目录匹配 {len(hits)} 个:')
        for f in sorted(hits):
            p = os.path.join(d, f)
            print(f'      {os.path.getsize(p)/1024/1024:>9.2f} MB  {f}')

print()
print('=' * 78)
print('2. 云端有没有这个弹幕版')
print('=' * 78)


def cloud_list(task):
    dst = os.path.join(TMP, 'chk_cloud')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(SVC, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    out = {}
    q = os.path.join(dst, 'dir_cache.sqlite')
    if os.path.exists(q):
        try:
            con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
            cur = con.cursor()
            cur.execute("SELECT id FROM cached_item WHERE path LIKE ?",
                        (f'%/DMR录播/{task}',))
            for (did,) in cur.fetchall():
                cur.execute('SELECT name, size FROM files WHERE parent_id=?', (did,))
                for nm, sz in cur.fetchall():
                    out[nm] = sz
            con.close()
        except Exception as e:
            return {'(err)': str(e)}
    return out


for task, stem in TARGETS:
    cf = cloud_list(task)
    hits = {k: v for k, v in cf.items() if stem.split('-')[-1][:6] in k}
    print(f'\n  【{task}】云端匹配 {len(hits)} 个:')
    for k, v in sorted(hits.items()):
        print(f'    {int(v)/1024/1024 if str(v).isdigit() else 0:>9.2f} MB  {k}')
    if not hits:
        print('    （云端也没有）')

print()
print('=' * 78)
print('3. 用 rclone 直接问云端（含幻影）')
print('=' * 78)
for task, stem in TARGETS:
    r = subprocess.run([RCLONE, 'lsf', f'cd2:百度网盘/DMR录播/{task}', '--format', 'sp'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    hits = [x.strip() for x in r.stdout.split('\n')
            if x.strip() and stem.split('-')[-1][:6] in x]
    print(f'  【{task}】rclone 匹配 {len(hits)} 个:')
    for h in hits:
        print(f'    {h}')

print()
print('=' * 78)
print('4. 结论')
print('=' * 78)
print('''  判断方法：
    - 本地弹幕版有 + 云端有   -> 正常，源文件可以安全清理
    - 本地弹幕版无 + 云端有   -> 本地已清理，源文件也**可清理**
                                  （内容已在云端，重渲染没意义）
    - 本地弹幕版无 + 云端无   -> ⚠️ 不要清理源文件！
                                  否则永远无法渲染/上传
''')
