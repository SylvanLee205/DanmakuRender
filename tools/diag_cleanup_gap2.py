"""排查 v2：正确解析状态库里的 data JSON，回答三个问题。

  1. 为什么这 74 个源视频/弹幕没被删？
  2. 弹幕版是否生成了？
  3. 弹幕版是否上传了？
"""
import datetime
import glob
import json
import os
import sqlite3
import subprocess
from collections import Counter, defaultdict

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


PROD = _PROJECT_ROOT
REPLAY = os.path.join(PROD, '直播回放')
DB = os.path.join(PROD, 'logs', 'dmr_state.db')
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'


def norm(rel):
    """把 './直播回放/vvu\\x.mkv' 归一成绝对小写路径用于匹配。"""
    if not rel:
        return None
    p = str(rel).replace('/', os.sep)
    if not os.path.isabs(p):
        p = os.path.join(PROD, p)
    return os.path.normcase(os.path.abspath(os.path.normpath(p)))


# ── 读状态库 ──
conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT * FROM artifacts')
arts = []
for r in cur.fetchall():
    d = dict(r)
    try:
        data = json.loads(d.get('data') or '{}')
    except Exception:
        data = {}
    d['_d'] = data
    d['_path'] = norm(data.get('path'))
    d['_dmpath'] = norm(data.get('danmaku_path'))
    arts.append(d)
cur.execute('SELECT * FROM sessions')
sessions = [dict(r) for r in cur.fetchall()]
conn.close()

by_path = {}
for a in arts:
    if a['_path']:
        by_path[a['_path']] = a
    if a['_dmpath']:
        by_path.setdefault(a['_dmpath'], a)

# ── 扫磁盘 ──
def classify(p, name):
    in_dm = '（弹幕版）' in p
    ext = os.path.splitext(name)[1].lower()
    if ext in ('.mkv', '.flv', '.mp4', '.ts'):
        return 'dm_video' if in_dm else 'src_video'
    if ext in ('.ass', '.xml'):
        return 'dm_danmaku' if in_dm else 'src_danmaku'
    return 'other'


disk = {}
for dp, dn, fns in os.walk(REPLAY):
    for fn in fns:
        p = os.path.join(dp, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        task = os.path.basename(dp)
        if task.endswith('（弹幕版）'):
            task = task[:-5]
        disk[p] = {'kind': classify(p, fn), 'size': st.st_size,
                   'mtime': st.st_mtime, 'task': task, 'name': fn}

print('=' * 78)
print('状态库总览')
print('=' * 78)
print(f'  artifacts {len(arts)} 条   sessions {len(sessions)} 条')
print('  state 分布:', dict(Counter(a['state'] for a in arts)))
print('  kind  分布:', dict(Counter(a['kind'] for a in arts)))
print()
# 状态 × kind 交叉
print('  状态 × 类型:')
cross = defaultdict(Counter)
for a in arts:
    cross[a['state']][a['kind']] += 1
for st in sorted(cross):
    print(f'    {st:12} {dict(cross[st])}')

print()
print('=' * 78)
print('一、残留源视频的原因归类')
print('=' * 78)
srcs = [(p, v) for p, v in disk.items() if v['kind'] == 'src_video']
print(f'  磁盘上源视频 {len(srcs)} 个')
cats = defaultdict(list)
for p, v in srcs:
    a = by_path.get(os.path.normcase(os.path.abspath(p)))
    if a is None:
        cats['① 状态库无记录'].append((p, v, None))
    else:
        cats[f'② 状态={a["state"]}'].append((p, v, a))

for cat in sorted(cats):
    lst = cats[cat]
    gb = sum(v['size'] for _, v, _ in lst) / 1024**3
    print()
    print(f'  {cat}  —— {len(lst)} 个 / {gb:.2f} GB')
    for p, v, a in sorted(lst, key=lambda x: -x[1]['mtime'])[:6]:
        d = datetime.datetime.fromtimestamp(v['mtime']).strftime('%m-%d %H:%M')
        extra = ''
        if a:
            dd = a['_d']
            extra = f" attempts={dd.get('attempts')}"
            if dd.get('last_error'):
                extra += f" err={str(dd['last_error'])[:60]}"
        print(f'      {d}  {v["size"]/1024**2:8.1f} MB  {v["name"][:46]}{extra}')

print()
print('=' * 78)
print('二、弹幕版生成情况')
print('=' * 78)
dmv = [(p, v) for p, v in disk.items() if v['kind'] == 'dm_video']
print(f'  磁盘上弹幕版 {len(dmv)} 个 / {sum(v["size"] for _, v in dmv)/1024**3:.2f} GB')
dm_cats = defaultdict(int)
for p, v in dmv:
    a = by_path.get(os.path.normcase(os.path.abspath(p)))
    dm_cats['有状态记录' if a else '无状态记录(旧文件)'] += 1
print('  ', dict(dm_cats))

# 源视频有配对弹幕版吗
print()
print('  源视频 → 弹幕版 配对情况:')
paired = unpaired = 0
unpaired_list = []
for p, v in srcs:
    base = os.path.splitext(v['name'])[0]
    task = v['task']
    dm_dir = os.path.join(REPLAY, task + '（弹幕版）')
    expect = os.path.join(dm_dir, base + '（弹幕版）.mp4')
    if os.path.exists(expect):
        paired += 1
    else:
        # 模糊匹配
        cand = glob.glob(os.path.join(dm_dir, base + '*'))
        if cand:
            paired += 1
        else:
            unpaired += 1
            unpaired_list.append((task, v['name']))
print(f'    已配对（弹幕版存在）: {paired}')
print(f'    未配对（弹幕版缺失）: {unpaired}')
for t, n in unpaired_list[:10]:
    print(f'      [{t}] {n[:60]}')

print()
print('=' * 78)
print('三、上传情况（状态库 + 云端核对）')
print('=' * 78)
up = Counter(a['state'] for a in arts if a['kind'] == 'dm_video')
print('  弹幕版状态分布:', dict(up))
stuck = [a for a in arts if a['kind'] == 'dm_video'
         and a['state'] not in ('uploaded', 'skipped')]
print(f'  未到达终态的弹幕版: {len(stuck)} 条')
for a in sorted(stuck, key=lambda x: -int(x['updated_at'] or 0))[:12]:
    d = a['_d']
    ts = datetime.datetime.fromtimestamp(int(a['updated_at'] or 0)).strftime('%m-%d %H:%M')
    print(f'    {a["state"]:10} attempts={d.get("attempts")}  {ts}  {os.path.basename(str(d.get("path")))[:52]}')
    if d.get('last_error'):
        print(f'        err: {str(d["last_error"])[:110]}')

# 上传组
conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
try:
    cur.execute('SELECT * FROM upload_groups')
    ugs = [dict(r) for r in cur.fetchall()]
    print()
    print(f'  upload_groups: {len(ugs)} 条')
    st = Counter(str(u.get('state')) for u in ugs)
    print('    状态分布:', dict(st))
    for u in ugs[:6]:
        print(f'      {u.get("state")}  {str(u.get("remote_path") or u.get("path") or "")[:70]}')
except Exception as e:
    print(f'  upload_groups 读取失败: {e}')
conn.close()

print()
print('=' * 78)
print('四、云端实际文件（rclone 只读）')
print('=' * 78)
try:
    r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '2',
                        '--files-only'], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=240)
    if r.returncode != 0:
        print(f'  ⚠️ exit={r.returncode}: {(r.stderr or "")[:180]}')
        cloud = []
    else:
        cloud = [x for x in (r.stdout or '').split('\n') if x.strip()]
    print(f'  云端共 {len(cloud)} 个文件')
    by_task = defaultdict(list)
    for x in cloud:
        parts = x.split('/')
        if len(parts) >= 2:
            by_task[parts[0]].append(parts[-1])
    print(f'  云端任务目录 {len(by_task)} 个')
    for t in sorted(by_task)[:30]:
        print(f'    {t[:24]:26} {len(by_task[t]):4} 个文件')
    print()
    # 本地弹幕版是否都上了云
    print('  本地弹幕版 vs 云端（抽查有源视频残留的 10 个主播）:')
    tasks_with_src = {v['task'] for p, v in srcs}
    for t in sorted(tasks_with_src):
        local = [v['name'] for p, v in dmv if v['task'] == t]
        cset = set(by_task.get(t, []))
        miss = [n for n in local if n not in cset]
        print(f'    {t[:20]:22} 本地 {len(local):3}  云端 {len(cset):3}  未上传 {len(miss):3}'
              f'  {"⚠️" if miss else "✅"}')
except Exception as e:
    print(f'  ⚠️ {type(e).__name__}: {e}')
