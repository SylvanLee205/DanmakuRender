"""全任务审计：找出真正"在上传流水线启用后仍然丢失"的文件。

判定标准：
  - 只统计【文件名日期 >= 上传流水线启用日】的文件（更早的本来就没打算上传）
  - 本地有 / 云端无  → 疑似丢失
"""
import os
import re
import subprocess

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
UP = r'F:\DanmakuRender_AutoUp'
REPLAY = os.path.join(UP, '直播回放')
REMOTE_ROOT = 'cd2:百度网盘/DMR录播'
PIPELINE_START = '2026-09-29'      # 云端最早文件日期


def run(cmd, t=900):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=t)


def date_of(name):
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', name)
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


def has_emoji(s):
    return any(ord(c) > 0xFFFF for c in s)


# 云端全量
r = run([RCLONE, 'lsf', REMOTE_ROOT, '-R'])
cloud = {}
for l in r.stdout.split('\n'):
    l = l.strip()
    if '/' not in l:
        continue
    task, fn = l.split('/', 1)
    cloud.setdefault(task, set()).add(fn)

# 本地（只取 （弹幕版） 目录）
print('=' * 80)
print(f'全任务审计（只统计文件名日期 >= {PIPELINE_START} 的，即上传流水线启用后）')
print('=' * 80)

total_lost = 0
total_lost_bytes = 0
report = []

for d in sorted(os.listdir(REPLAY)):
    full = os.path.join(REPLAY, d)
    if not os.path.isdir(full) or not d.endswith('（弹幕版）'):
        continue
    task = d[:-len('（弹幕版）')]
    if task not in cloud:
        # 云端根本没这个目录 —— 要么没开上传，要么全丢
        pass
    cloud_files = cloud.get(task, set())
    local_files = [f for f in os.listdir(full) if f.endswith('.mp4')]

    lost = []
    for f in local_files:
        dt = date_of(f)
        if not dt or dt < PIPELINE_START:
            continue                    # 流水线启用前的，不算丢失
        if f not in cloud_files:
            lost.append(f)

    if lost:
        sizes = [os.path.getsize(os.path.join(full, f)) for f in lost]
        lost_bytes = sum(sizes)
        total_lost += len(lost)
        total_lost_bytes += lost_bytes
        report.append((task, lost, lost_bytes))

print()
if not report:
    print('  ✓ 没有发现上传期内丢失的文件')
else:
    for task, lost, lb in sorted(report, key=lambda x: -x[2]):
        ne = sum(1 for f in lost if has_emoji(f))
        print(f'\n  【{task}】丢失 {len(lost)} 个, {lb/1024/1024/1024:.2f} GB'
              f'（含 emoji 的 {ne} 个）')
        for f in sorted(lost):
            p = os.path.join(REPLAY, f'{task}（弹幕版）', f)
            mb = os.path.getsize(p) / 1024 / 1024
            tag = '[emoji]' if has_emoji(f) else '[干净 ]'
            print(f'      {tag} {mb:>8.1f} MB  {f}')

print()
print('=' * 80)
print(f'合计：真正丢失 {total_lost} 个文件, {total_lost_bytes/1024/1024/1024:.2f} GB')
print('=' * 80)

print()
print('=== 对照：各任务的本地/云端文件数（只算流水线启用后）===')
for d in sorted(os.listdir(REPLAY)):
    full = os.path.join(REPLAY, d)
    if not os.path.isdir(full) or not d.endswith('（弹幕版）'):
        continue
    task = d[:-len('（弹幕版）')]
    cf = cloud.get(task, set())
    lf = [f for f in os.listdir(full) if f.endswith('.mp4') and (date_of(f) or '') >= PIPELINE_START]
    if lf or cf:
        flag = ' ← 有缺口' if len(lf) != len(cf) else ''
        print(f'  {task:16} 本地 {len(lf):>3}   云端 {len(cf):>3}{flag}')
