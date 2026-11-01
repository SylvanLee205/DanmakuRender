"""修正状态库里的脏状态。

两类修正：
  A. 云端**确实有**，但状态卡在 uploading/recorded（上传成功但状态没回写）
     → 标成 uploaded
  B. 命中「跳过上传」规则（横屏/高码率/高帧率），本就不该上传
     → 标成 skipped（配合新加的 _STATUS_TO_STATE 映射，重启后不再重跑）

默认 dry-run，加 --apply 才写库。写库前自动备份 dmr_state.db。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

PROD = _PROJECT_ROOT
DB = os.path.join(PROD, 'logs', 'dmr_state.db')
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'

apply = '--apply' in sys.argv

# ── 云端文件名集合 ──
print('=' * 78)
print(f'状态修正 {"（实际写库）" if apply else "（DRY-RUN）"}')
print('=' * 78)
print('  读取云端文件列表...')
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播',
                    '--max-depth', '2', '--files-only'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
if r.returncode != 0:
    print(f'  ❌ rclone 失败: {(r.stderr or "")[:200]}')
    sys.exit(1)
cloud = set()
for line in (r.stdout or '').split('\n'):
    line = line.strip()
    if line:
        cloud.add(os.path.basename(line))
print(f'  云端文件名 {len(cloud)} 个')

conn = sqlite3.connect(DB, timeout=60)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT * FROM artifacts')
arts = [dict(r) for r in cur.fetchall()]

# ── A. 云端有、但状态不是 uploaded ──
print()
print('─' * 78)
print('A. 云端已有但状态未回写 → 标成 uploaded')
print('─' * 78)
fix_uploaded = []
for a in arts:
    if a['state'] == 'uploaded':
        continue
    d = json.loads(a['data'] or '{}')
    base = os.path.basename(str(d.get('path') or ''))
    if base and base in cloud:
        fix_uploaded.append((a, base, d.get('attempts')))
if fix_uploaded:
    for a, base, att in fix_uploaded:
        print(f'  {a["state"]:10} -> uploaded  attempts={att}  {base[:60]}')
else:
    print('  （无）')

# ── B. 命中跳过规则但状态还停在 rendered/recorded ──
print()
print('─' * 78)
print('B. 命中跳过上传规则 → 标成 skipped')
print('─' * 78)
sys.path.insert(0, PROD)
os.chdir(PROD)
import logging
logging.basicConfig(level=logging.CRITICAL)
import types
import yaml
from DMR.utils import evaluate_upload_skip_rule


cfg = yaml.safe_load(open(os.path.join(PROD, 'configs', 'global.yml'),
                          encoding='utf-8'))
rule = (((cfg.get('render_args') or {}).get('dmrender') or {})
        .get('skip_upload_rule') or {})

fix_skipped = []
for a in arts:
    if a['state'] in ('uploaded', 'skipped', 'cleaned', 'missing'):
        continue
    d = json.loads(a['data'] or '{}')
    p = d.get('path')
    if not p:
        continue
    ab = os.path.normpath(os.path.join(PROD, str(p).replace('/', os.sep)))
    if not os.path.exists(ab):
        continue
    base = os.path.basename(ab)
    if base in cloud:
        continue        # A 类已处理
    # ⚠️ evaluate_upload_skip_rule 用 getattr(video, 'path') 取路径，
    #    直接传字符串会取不到（→ 分辨率缺失 → fail-open 不跳过）。
    #    这里包一个带 path 的简单对象，让它能走 FFprobe 探测分支。
    probe_obj = types.SimpleNamespace(path=ab, resolution=None,
                                      bitrate=None, fps=None)
    try:
        skip, detail = evaluate_upload_skip_rule(probe_obj, rule)
    except Exception as e:
        print(f'  ⚠️ 判断失败 {base[:50]}: {e}')
        continue
    if skip:
        fix_skipped.append((a, base, detail))
if fix_skipped:
    for a, base, detail in fix_skipped:
        print(f'  {a["state"]:10} -> skipped   {base[:56]}')
        print(f'       命中: {detail}')
else:
    print('  （无）')

print()
print('─' * 78)
print(f'合计：A 类 {len(fix_uploaded)} 条，B 类 {len(fix_skipped)} 条')
print('─' * 78)

if not apply:
    print()
    print('  DRY-RUN 结束。确认无误后加 --apply 执行。')
    conn.close()
    sys.exit(0)

# ── 备份 ──
bak = f'{DB}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
for suffix in ('', '-wal', '-shm'):
    src = DB + suffix
    if os.path.exists(src):
        shutil.copy2(src, bak + suffix)
print()
print(f'  已备份: {bak}(.db/-wal/-shm)')

now = int(time.time())
n1 = n2 = 0
for a, base, _ in fix_uploaded:
    d = json.loads(a['data'] or '{}')
    d['last_error'] = None
    cur.execute('UPDATE artifacts SET state=?, data=?, updated_at=? WHERE artifact_id=?',
                ('uploaded', json.dumps(d, ensure_ascii=False), now, a['artifact_id']))
    n1 += 1
for a, base, detail in fix_skipped:
    d = json.loads(a['data'] or '{}')
    d['skip_detail'] = detail
    cur.execute('UPDATE artifacts SET state=?, data=?, updated_at=? WHERE artifact_id=?',
                ('skipped', json.dumps(d, ensure_ascii=False), now, a['artifact_id']))
    n2 += 1
conn.commit()

# 校验
cur.execute('SELECT kind, state, COUNT(*) FROM artifacts GROUP BY kind, state ORDER BY kind, state')
print()
print('  修正后状态分布:')
for row in cur.fetchall():
    print(f'    {row[0]:10} {row[1]:12} {row[2]}')
conn.close()
print()
print(f'  ✅ 已写入：uploaded +{n1}，skipped +{n2}')
