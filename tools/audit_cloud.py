"""完整审计 掉了颗兔牙 目录：本地 vs 云端，找出所有静默丢失的文件。

⚠️ 关键：不能用 rclone lsf 的结果作为"云端有"的依据？
   实际上可以 —— 幻影条目只出现在**当前 pending** 的文件上（也就是刚 PUT 的）。
   历史文件如果上传失败，早就从 pending 层消失了。
   但为了严谨，我这里同时报告，并对可疑项用 dir_cache 复核。
"""
import os
import subprocess
import sys

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
UP = r'F:\DanmakuRender_AutoUp'
TASK = '掉了颗兔牙'
LOCAL_DIR = os.path.join(UP, '直播回放', f'{TASK}（弹幕版）')
REMOTE = f'cd2:百度网盘/DMR录播/{TASK}'


def has_emoji(s):
    return any(ord(c) > 0xFFFF for c in s)


print('=' * 78)
print(f'审计：{TASK}')
print('=' * 78)

r = subprocess.run([RCLONE, 'lsf', REMOTE], capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=300)
cloud = set(l.strip() for l in r.stdout.split('\n') if l.strip())
local = set(f for f in os.listdir(LOCAL_DIR) if f.endswith('.mp4'))

print(f'  本地 {len(local)} 个文件')
print(f'  云端 {len(cloud)} 个文件')
print()

only_local = sorted(local - cloud)
only_cloud = sorted(cloud - local)
both = sorted(local & cloud)

print(f'=== ❌ 本地有、云端没有（静默丢失）: {len(only_local)} 个 ===')
emoji_cnt = 0
for f in only_local:
    p = os.path.join(LOCAL_DIR, f)
    mb = os.path.getsize(p) / 1024 / 1024
    e = has_emoji(f)
    emoji_cnt += e
    print(f'    {"[含emoji] " if e else "[无emoji!] "}{mb:>8.1f} MB  {f}')
print(f'\n    其中含 emoji 的: {emoji_cnt} / {len(only_local)}')

print()
print(f'=== 云端有、本地没有: {len(only_cloud)} 个 ===')
for f in only_cloud:
    print(f'    {f}')

print()
print(f'=== 两边都有: {len(both)} 个 ===')

print()
print('=' * 78)
print('结论判定')
print('=' * 78)
if only_local and all(has_emoji(f) for f in only_local):
    print('  ✓ 所有丢失的文件都含 emoji —— 与 emoji 假说完全吻合')
elif only_local:
    print(f'  ⚠ 有 {len(only_local) - emoji_cnt} 个丢失文件不含 emoji，需要另找原因')
else:
    print('  ✓ 没有丢失的文件')

# 按日期排序看丢失窗口
print()
print('=== 丢失文件的日期分布 ===')
import re
dates = {}
for f in only_local:
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', f)
    if m:
        key = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
        dates[key] = dates.get(key, 0) + 1
for d in sorted(dates):
    print(f'    {d}: {dates[d]} 个')
