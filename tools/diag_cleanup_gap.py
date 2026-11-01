"""排查：为什么有些源视频/弹幕没被清理，以及弹幕版是否生成/上传。

分三层看：
  1. 磁盘现状：每个主播目录里有什么（源视频 / 源弹幕 / 弹幕版 / 弹幕版弹幕）
  2. 状态库：这些文件在 dmr_state.db 里是什么状态（是否终态、是否标记 upload_skipped）
  3. 云端：rclone 上有没有对应的弹幕版

输出按"问题类型"归类，直接给出"为什么没删"。
"""
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys

PROD = r'F:\DanmakuRepo'
REPLAY = os.path.join(PROD, '直播回放')
DB = os.path.join(PROD, 'logs', 'dmr_state.db')
RCLONE = None
for c in (r'C:\User Program Files\rclone-v1.75.1\rclone.exe', 'rclone'):
    if c == 'rclone':
        RCLONE = c
    elif os.path.exists(c):
        RCLONE = c
        break

# ── 文件分类 ──
def classify(path, name):
    in_dm = '（弹幕版）' in path or '(弹幕版)' in path
    ext = os.path.splitext(name)[1].lower()
    if ext in ('.mkv', '.flv', '.mp4', '.ts'):
        return 'dm_video' if in_dm else 'src_video'
    if ext in ('.ass', '.xml', '.json'):
        return 'dm_danmaku' if in_dm else 'src_danmaku'
    return 'other'


def scan_disk():
    """返回 {主播: {文件名: (kind, size, mtime)}}。"""
    out = {}
    if not os.path.isdir(REPLAY):
        return out
    for task_dir in sorted(os.listdir(REPLAY)):
        full = os.path.join(REPLAY, task_dir)
        if not os.path.isdir(full):
            continue
        task = task_dir.replace('（弹幕版）', '').replace('(弹幕版)', '')
        for dirpath, dirnames, filenames in os.walk(full):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                d = out.setdefault(task, {})
                d[p] = (classify(p, fn), st.st_size, st.st_mtime)
    return out


def load_state():
    """读状态库：artifacts 表（路径 -> 状态/kind）。"""
    if not os.path.exists(DB):
        return {}, 'state db 不存在'
    try:
        conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 探 schema
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        if 'artifacts' not in tables:
            return {}, f'没有 artifacts 表（有: {sorted(tables)}）'
        cur.execute('PRAGMA table_info(artifacts)')
        cols = [r[1] for r in cur.fetchall()]
        cur.execute('SELECT * FROM artifacts')
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {'rows': rows, 'cols': cols, 'tables': sorted(tables)}, None
    except Exception as e:
        return {}, f'{type(e).__name__}: {e}'


print('=' * 78)
print('一、磁盘现状')
print('=' * 78)
disk = scan_disk()
print(f'  主播目录 {len(disk)} 个')

tot = {}
for task, files in disk.items():
    for p, (kind, sz, mt) in files.items():
        tot.setdefault(kind, [0, 0])
        tot[kind][0] += 1
        tot[kind][1] += sz
print()
print('  按类型统计:')
LABEL = {'src_video': '源视频', 'src_danmaku': '源弹幕',
         'dm_video': '弹幕版视频', 'dm_danmaku': '弹幕版弹幕', 'other': '其他'}
for k, (n, sz) in sorted(tot.items(), key=lambda x: -x[1][1]):
    print(f'    {LABEL.get(k, k):12} {n:4} 个  {sz/1024/1024/1024:8.2f} GB')

# ── 逐个主播看：源视频 vs 弹幕版 ──
print()
print('  每个主播的配对情况（源视频数 / 弹幕版数 / 源弹幕数）:')
print(f'    {"主播":22} {"源视频":>6} {"源弹幕":>6} {"弹幕版":>6} {"弹幕版弹":>8} {"残留源GB":>10}')
residual = []
for task in sorted(disk, key=lambda t: -sum(
        v[1] for v in disk[t].values() if v[0] == 'src_video')):
    f = disk[task]
    n_sv = sum(1 for v in f.values() if v[0] == 'src_video')
    n_sd = sum(1 for v in f.values() if v[0] == 'src_danmaku')
    n_dv = sum(1 for v in f.values() if v[0] == 'dm_video')
    n_dd = sum(1 for v in f.values() if v[0] == 'dm_danmaku')
    gb_sv = sum(v[1] for v in f.values() if v[0] == 'src_video') / 1024**3
    if n_sv == 0 and n_dv == 0:
        continue
    flag = '⚠️' if n_sv > 0 else '  '
    print(f'    {flag}{task[:20]:22} {n_sv:>6} {n_sd:>6} {n_dv:>6} {n_dd:>8} {gb_sv:>9.2f}')
    if n_sv > 0:
        residual.append((task, n_sv, n_sd, n_dv, n_dd, gb_sv))

print()
print(f'  ★ 有源视频残留的主播: {len(residual)} 个，'
      f'合计 {sum(r[5] for r in residual):.2f} GB')

print()
print('=' * 78)
print('二、状态库')
print('=' * 78)
state, err = load_state()
if err:
    print(f'  ⚠️ {err}')
else:
    rows = state['rows']
    print(f'  artifacts 表: {len(rows)} 行   列: {state["cols"]}')
    print(f'  所有表: {state["tables"]}')
    # 状态分布
    for key in ('state', 'status', 'kind', 'upload_state'):
        if key in state['cols']:
            from collections import Counter
            c = Counter(str(r.get(key)) for r in rows)
            print(f'    {key} 分布: {dict(c)}')

print()
print('=' * 78)
print('三、逐个残留文件的详细原因')
print('=' * 78)

# 建 path -> 状态 索引
path_index = {}
if not err:
    for r in state['rows']:
        for k in ('path', 'file_path', 'local_path'):
            if r.get(k):
                path_index[os.path.normcase(
                    os.path.normpath(str(r[k]).replace('/', os.sep)))] = r
                break

for task, n_sv, n_sd, n_dv, n_dd, gb in residual:
    print()
    print(f'  ── {task}  （源视频 {n_sv} 个 / 弹幕版 {n_dv} 个 / {gb:.2f} GB）──')
    files = disk[task]
    srcs = [(p, v) for p, v in files.items() if v[0] in ('src_video', 'src_danmaku')]
    srcs.sort(key=lambda x: -x[1][1])
    for p, (kind, sz, mt) in srcs[:14]:
        fn = os.path.basename(p)
        idx = path_index.get(os.path.normcase(os.path.normpath(p)))
        if idx:
            st = idx.get('state') or idx.get('status') or '?'
            extra = ''
            for k in ('kind', 'upload_state', 'upload_group', 'skipped'):
                if k in idx and idx[k] not in (None, '', 0):
                    extra += f' {k}={idx[k]}'
            note = f'状态库: {st}{extra}'
        else:
            note = '状态库: 无记录'
        import datetime
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(mt)).days
        print(f'      {LABEL.get(kind,kind):8} {sz/1024**2:9.1f} MB {age:3}天前  {fn[:52]}')
        print(f'               {note}')

print()
print('=' * 78)
print('四、云端核对（rclone，只读）')
print('=' * 78)
try:
    r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播',
                        '--max-depth', '2', '--files-only'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=180)
    if r.returncode != 0:
        print(f'  ⚠️ rclone 失败 exit={r.returncode}: {(r.stderr or "")[:200]}')
    else:
        cloud = [x for x in (r.stdout or '').split('\n') if x.strip()]
        print(f'  云端 DMR录播 下 {len(cloud)} 个条目（深度2）')
        # 按任务聚合
        by_task = {}
        for x in cloud:
            parts = x.split('/')
            if len(parts) >= 2:
                by_task.setdefault(parts[0], []).append(parts[-1])
        print(f'  云端任务目录 {len(by_task)} 个')
        # 对每个残留主播核对
        for task, *_ in residual:
            c = by_task.get(task, [])
            local_dv = [os.path.basename(p) for p, v in disk[task].items() if v[0] == 'dm_video']
            missing = [f for f in local_dv if f not in c]
            print(f'    {task[:20]:22} 云端 {len(c):3} 个  本地弹幕版 {len(local_dv):3} 个'
                  f'  {"⚠️ 本地有未上传: " + str(len(missing)) if missing else "✅ 已全部上传"}')
            for m in missing[:3]:
                print(f'        未上传: {m[:60]}')
except Exception as e:
    print(f'  ⚠️ {type(e).__name__}: {e}')

print()
print('=' * 78)
print('五、清理配置（对照用）')
print('=' * 78)
try:
    import yaml
    d = yaml.safe_load(open(os.path.join(PROD, 'configs', 'global.yml'),
                            encoding='utf-8')) or {}
    ca = d.get('clean_args') or {}
    print('  global.yml clean_args:')
    for k, v in ca.items():
        print(f'    {k} = {v!r}')
except Exception as e:
    print(f'  ⚠️ {e}')
