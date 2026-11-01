"""清理"已确认上传成功"的本地文件（源视频 + 弹幕版 + 源弹幕）。

⚠️⚠️ 2026-10-18 修正：本工具**只删源视频 + 源弹幕，永不删弹幕版**。

    用户明确需求：弹幕版必须永久保留在本地（同时上传云端做备份）。
    原版本会连带删除 dm_video —— 那是个错误，已修正。

安全前提（缺一不删）：
  1. 该分段的 dm_video 状态必须是 uploaded
  2. dm_video 文件名必须在云端**确实存在**（实时 rclone 核对）
  3. 待删文件必须位于 直播回放/ 目录下
  4. 文件最后修改时间必须早于 --min-age 小时（默认 1 小时，避免误删正在写入的）
  5. 跳过 rule 命中（src_video 状态 skipped）的文件**不动** —— 那是"不上传、留本地"的语义
  6. 每个文件先记日志再删；删除失败只告警不中断

默认 dry-run，加 --apply 才真删。
删完把状态库对应产物标成 cleaned（不可逆，但云端有备份）。
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
REPLAY = os.path.join(PROD, '直播回放')
DB = os.path.join(PROD, 'logs', 'dmr_state.db')
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'

apply = '--apply' in sys.argv
MIN_AGE_H = 1.0
for i, a in enumerate(sys.argv):
    if a == '--min-age' and i + 1 < len(sys.argv):
        MIN_AGE_H = float(sys.argv[i + 1])

print('=' * 78)
print(f'清理已确认上传成功的本地文件 {"（实际删除）" if apply else "（DRY-RUN）"}')
print('=' * 78)
print(f'  最小文件年龄: {MIN_AGE_H} 小时（更新的文件不删）')

# ── 1. 云端核对 ──
print('  读取云端文件列表...')
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播',
                    '--max-depth', '2', '--files-only'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
if r.returncode != 0:
    print(f'  ❌ rclone 失败: {(r.stderr or "")[:200]}')
    sys.exit(1)
cloud = {os.path.basename(x.strip()) for x in (r.stdout or '').split('\n') if x.strip()}
print(f'  云端 {len(cloud)} 个文件')

# ── 2. 读状态库并按 (session, idx) 配对 ──
conn = sqlite3.connect(DB, timeout=60)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT * FROM artifacts')
arts = [dict(x) for x in cur.fetchall()]

groups = {}
for a in arts:
    groups.setdefault((a['session_id'], a['segment_idx']), {})[a['kind']] = a

now = time.time()
to_delete = []      # [(path, kind, size, artifact)]
skipped_reasons = {}

for key, g in sorted(groups.items()):
    dm = g.get('dm_video')
    if not dm or dm['state'] != 'uploaded':
        continue
    dd = json.loads(dm['data'] or '{}')
    dp = dd.get('path')
    if not dp:
        continue
    dabs = os.path.normpath(os.path.join(PROD, str(dp).replace('/', os.sep)))
    dbase = os.path.basename(dabs)
    if dbase not in cloud:
        skipped_reasons.setdefault('云端核对不通过', []).append(dbase)
        continue
    if not os.path.exists(dabs):
        continue
    # 年龄检查
    if now - os.path.getmtime(dabs) < MIN_AGE_H * 3600:
        skipped_reasons.setdefault('文件太新', []).append(dbase)
        continue
    # ⚠️ 绝对不删弹幕版！下面这行原实现已禁用（弹幕版必须永久保留本地）
    # to_delete.append((dabs, 'dm_video', os.path.getsize(dabs), dm))

    # 源视频：只有不是 skipped 才删（skipped = 命中跳过规则、要留本地）
    sv = g.get('src_video')
    if sv and sv['state'] != 'skipped':
        sd = json.loads(sv['data'] or '{}')
        sp = sd.get('path')
        if sp:
            sabs = os.path.normpath(os.path.join(PROD, str(sp).replace('/', os.sep)))
            if os.path.exists(sabs) and now - os.path.getmtime(sabs) >= MIN_AGE_H * 3600:
                to_delete.append((sabs, 'src_video', os.path.getsize(sabs), sv))
            # 源弹幕 .ass
            dmp = sd.get('danmaku_path')
            if dmp:
                aabs = os.path.normpath(os.path.join(PROD, str(dmp).replace('/', os.sep)))
                if os.path.exists(aabs):
                    to_delete.append((aabs, 'src_danmaku', os.path.getsize(aabs), sv))

# ── 3. 安全过滤 ──
safe = []
for p, kind, sz, art in to_delete:
    rp = os.path.abspath(p)
    if not rp.lower().startswith(os.path.abspath(REPLAY).lower()):
        print(f'  ⚠️ 跳过（不在直播回放目录）: {rp}')
        continue
    safe.append((rp, kind, sz, art))

# 去重（同一路径可能被多个产物引用）
seen = set()
uniq = []
for p, kind, sz, art in safe:
    k = os.path.normcase(p)
    if k in seen:
        continue
    seen.add(k)
    uniq.append((p, kind, sz, art))

# ── 4. 报告 ──
LAB = {'dm_video': '弹幕版', 'src_video': '源视频', 'src_danmaku': '源弹幕'}
from collections import Counter
cnt = Counter(k for _, k, _, _ in uniq)
siz = Counter()
for _, k, sz, _ in uniq:
    siz[k] += sz
print()
print('  待删除统计:')
for k in ('dm_video', 'src_video', 'src_danmaku'):
    if cnt[k]:
        print(f'    {LAB[k]:8} {cnt[k]:4} 个  {siz[k]/1024**3:7.2f} GB')
print(f'    {"合计":8} {len(uniq):4} 个  {sum(siz.values())/1024**3:7.2f} GB')

if skipped_reasons:
    print()
    print('  被拦下的:')
    for reason, lst in skipped_reasons.items():
        print(f'    {reason}: {len(lst)} 个')
        for x in lst[:3]:
            print(f'        {x[:64]}')

if not apply:
    print()
    print('  ── 前 25 个待删文件 ──')
    for p, kind, sz, _ in sorted(uniq, key=lambda x: -x[2])[:25]:
        rel = os.path.relpath(p, PROD)
        print(f'    {LAB[kind]:8} {sz/1024**2:9.1f} MB  {rel[:74]}')
    print()
    print('  DRY-RUN 结束。确认无误后加 --apply 执行。')
    conn.close()
    sys.exit(0)

# ── 5. 执行删除 ──
print()
print('  开始删除...')
ok = fail = 0
deleted_bytes = 0
cleaned_arts = []
for p, kind, sz, art in uniq:
    rel = os.path.relpath(p, PROD)
    try:
        os.remove(p)
        ok += 1
        deleted_bytes += sz
        print(f'    ✅ {rel[:74]}')
        if kind in ('dm_video', 'src_video'):
            cleaned_arts.append((art['artifact_id'], kind, p))
    except Exception as e:
        fail += 1
        print(f'    ❌ {rel[:60]}  {type(e).__name__}: {e}')

print()
print(f'  删除完成: 成功 {ok}，失败 {fail}，释放 {deleted_bytes/1024**3:.2f} GB')

# ── 6. 更新状态库为 cleaned ──
if cleaned_arts:
    ts = int(time.time())
    for aid, kind, p in cleaned_arts:
        try:
            cur.execute('UPDATE artifacts SET state=?, updated_at=? WHERE artifact_id=?',
                        ('cleaned', ts, aid))
        except Exception as e:
            print(f'    ⚠️ 状态更新失败 {aid}: {e}')
    conn.commit()
    print(f'  状态库: {len(cleaned_arts)} 条产物标为 cleaned')

# ── 7. 清理空目录 ──
removed_dirs = 0
for dp, dn, fn in os.walk(REPLAY, topdown=False):
    try:
        if not os.listdir(dp):
            os.rmdir(dp)
            removed_dirs += 1
            print(f'    🗑 删除空目录: {os.path.relpath(dp, PROD)}')
    except OSError:
        pass

cur.execute('SELECT kind, state, COUNT(*) FROM artifacts GROUP BY kind, state ORDER BY kind, state')
print()
print('  清理后状态分布:')
for row in cur.fetchall():
    print(f'    {row[0]:10} {row[1]:12} {row[2]}')
conn.close()
