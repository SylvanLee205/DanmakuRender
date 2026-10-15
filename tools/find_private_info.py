"""隐私打码：定位所有需要处理的个人敏感信息。

打码原则：
  · Tailscale IP / 域名  → 这些**确实是你的**，会暴露内网入口，全部替换
  · 内网 IP              → 同上
  · 邮箱                 → 你的邮箱替换；上游自带的（f2.wiki 等）保留
  · 真实抖音房间号        → 那 6 个确实是你在录的，替换成示例号
  · 示例号（123456/654321/1）→ 本来就是示例，不动

⚠️ 不打码的：
  · 上游自带的 B站房间号（docs/usage.md 等是上游文档）
  · 代码里的协议常量（DMR/LiveAPI/*.py）
"""
import os
import re
import subprocess

REPO = r'F:\DanmakuRender_Mod'
GIT = r'C:\Program Files\Git\cmd\git.exe'

r = subprocess.run([GIT, 'ls-files'], cwd=REPO, capture_output=True,
                   text=True, encoding='utf-8', errors='replace')
files = [x for x in (r.stdout or '').split('\n') if x.strip()]

# ── 需要打码的（确实是用户自己的）──
RULES = [
    # (说明, 正则, 替换)
    ('Tailscale IP', re.compile(r'\b100\.75\.58\.27\b'), '100.x.y.z'),
    ('Tailscale 域名', re.compile(r'\btail506a91\.ts\.net\b'), '<你的设备>.ts.net'),
    ('内网 IP', re.compile(r'\b192\.168\.5\.5\b'), '192.168.x.x'),
    ('用户邮箱', re.compile(r'\b1871163532@qq\.com\b'), 'you@example.com'),
    # 真实抖音房间号（用户正在录的）
    ('抖音房间号 56909717876', re.compile(r'\b56909717876\b'), '123456789'),
    ('抖音房间号 470116673696', re.compile(r'\b470116673696\b'), '123456789'),
    ('抖音房间号 700084278384', re.compile(r'\b700084278384\b'), '123456789'),
    ('抖音房间号 989986719971', re.compile(r'\b989986719971\b'), '123456789'),
    ('抖音房间号 975387140329', re.compile(r'\b975387140329\b'), '123456789'),
    ('抖音房间号 557839188085', re.compile(r'\b557839188085\b'), '123456789'),
    ('抖音房间号 356284810909', re.compile(r'\b356284810909\b'), '123456789'),
    ('抖音房间号 865102911165', re.compile(r'\b865102911165\b'), '123456789'),
    ('抖音房间号 76368176167', re.compile(r'\b76368176167\b'), '123456789'),
    ('抖音房间号 171682321878', re.compile(r'\b171682321878\b'), '123456789'),
]
# 任何 9 位以上的抖音房间号都打码（兜底）
DIGITS = re.compile(r'(live\.douyin\.com/)(\d{9,})')

print('=' * 78)
print('一、按规则命中统计')
print('=' * 78)
hits = {}
for f in files:
    p = os.path.join(REPO, f)
    if not os.path.isfile(p) or os.path.getsize(p) > 2 * 1024 * 1024:
        continue
    try:
        txt = open(p, encoding='utf-8').read()
    except Exception:
        continue
    for name, pat, rep in RULES:
        n = len(pat.findall(txt))
        if n:
            hits.setdefault(name, []).append((f, n))
    for m in DIGITS.finditer(txt):
        key = f'抖音URL {m.group(2)}'
        if not any(k[0].startswith('抖音房间号') and k[0].endswith(m.group(2))
                   for k in hits):
            hits.setdefault, None
            hits.setdefault(key, []).append((f, 1)) if key not in hits else hits[key].append((f, 1))

for name in sorted(hits):
    lst = hits[name]
    total = sum(n for _, n in lst)
    print(f'\n  【{name}】{total} 处 / {len(lst)} 文件:')
    for f, n in sorted(lst):
        print(f'      {f}  ×{n}')

print()
print('=' * 78)
print('二、兜底：所有 live.douyin.com/<9位以上数字> 的分布')
print('=' * 78)
allrooms = {}
for f in files:
    p = os.path.join(REPO, f)
    if not os.path.isfile(p) or os.path.getsize(p) > 2 * 1024 * 1024:
        continue
    try:
        txt = open(p, encoding='utf-8').read()
    except Exception:
        continue
    for m in DIGITS.finditer(txt):
        allrooms.setdefault(m.group(2), set()).add(f)
for room in sorted(allrooms, key=lambda x: -len(allrooms[x])):
    print(f'  {room}  出现于 {len(allrooms[room])} 个文件:')
    for f in sorted(allrooms[room])[:6]:
        print(f'      {f}')
    if len(allrooms[room]) > 6:
        print(f'      ... 还有 {len(allrooms[room])-6} 个')
