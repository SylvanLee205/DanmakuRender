"""统计启动时各类消息的数量，决定控制台该显示什么。"""
import glob
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 找一份"完整启动过程"的日志（重启后 60 秒内的内容）')
print('=' * 78)
# 取最新日志里第二次启动之后的段（跳过前面旧内容）
lg = logs[0]
txt = open(lg, encoding='utf-8', errors='replace').read()
lines = [l for l in txt.split('\n') if l.strip()]
print(f'  文件: {os.path.basename(lg)}  共 {len(lines)} 行')

# 找最后一次 "DanmakuRender" 启动标志，或最后一个 engine info 密集段
start_idx = 0
for i, l in enumerate(lines):
    if 'Plugin' in l and 'started' in l:
        start_idx = i
seg = lines[start_idx:]
print(f'  取最后一段（从 index {start_idx}）共 {len(seg)} 行')

print()
print('=' * 78)
print('2. 各类型消息的条数（决定控制台负担）')
print('=' * 78)
patterns = [
    ('engine][info]: 下载任务', '任务启动（你熟悉的）'),
    ('engine][debug]: {', '引擎消息字典（大段 JSON）'),
    ('liveevents][info]: .*: 直播已结束', '"直播已结束"'),
    ('liveevents][info]: .*: 直播开始', '"直播开始"'),
    ('engine][info]: 直播任务', '直播任务状态'),
    ('ERROR', 'ERROR'),
    ('WARNING', 'WARNING'),
    ('解析', '含"解析"'),
    ('失败', '含"失败"'),
    ('错误', '含"错误"'),
]
for pat, label in patterns:
    n = len(re.findall(pat, txt))
    print(f'  {label:28} {n:>4} 条')

print()
print('=' * 78)
print('3. ★ 关键：有没有"解析直播间失败"这类噪音')
print('=' * 78)
for pat in ('GetRoomInfo', '解析抖音房间号', '解析', '失败', 'Error:', '错误'):
    hits = [l for l in lines if pat in l]
    if hits:
        print(f'\n  含 "{pat}" 的 {len(hits)} 条（样例）:')
        for l in hits[-4:]:
            print(f'    {l[:160]}')
    else:
        print(f'  含 "{pat}": 0 条')

print()
print('=' * 78)
print('4. 模拟：如果控制台设成 INFO 级别，启动时会看到多少行')
print('=' * 78)
# INFO 级别 = 显示 INFO/WARNING/ERROR/PROGRESS
info_like = [l for l in lines
             if re.search(r'\[(info|warning|error|critical|PROGRESS)\]', l, re.I)
             and 'engine][debug]' not in l]
print(f'  INFO 级别会显示约 {len(info_like)} 行')
print('  样例（前 15 行）:')
for l in info_like[:15]:
    print(f'    {l[:150]}')

print()
print('=' * 78)
print('5. 对比：各候选级别的显示量')
print('=' * 78)
cands = [
    ('PROGRESS（当前）', r'\[PROGRESS\]|\[(warning|error|critical)\]'),
    ('INFO（你熟悉的）', r'\[(info|warning|error|critical|PROGRESS)\]'),
    ('DEBUG（全部）', r'\[(debug|info|warning|error|critical|PROGRESS)\]'),
]
for label, pat in cands:
    n = len([l for l in lines if re.search(pat, l, re.I)])
    print(f'  {label:20} ~{n:>5} 行')
print()
print('  ⚠️ 注意：DEBUG 会把 engine 消息字典也显示出来（大段 JSON），')
print('     这就是你之前觉得"乱"的主要来源。')
