"""发布前敏感信息扫描。

要检查的：
  1. 真实 token / key / 密码
  2. 个人敏感信息（主播房间号 URL、手机号、邮箱、内网 IP、Tailscale IP）
  3. 大文件 / 不该发布的文件
  4. .gitignore 是否覆盖了该忽略的
"""
import os
import re
import subprocess

REPO = r'F:\DanmakuRender_Mod'
GIT = r'C:\Program Files\Git\cmd\git.exe'

print('=' * 78)
print('1. 检查被 git 跟踪的文件里有没有敏感信息')
print('=' * 78)

r = subprocess.run([GIT, 'ls-files'], cwd=REPO, capture_output=True,
                   text=True, encoding='utf-8', errors='replace')
files = [x for x in (r.stdout or '').split('\n') if x.strip()]
print(f'  被跟踪文件: {len(files)} 个')

PATTERNS = [
    ('疑似 token/key/secret', r'(?i)\b(api[_-]?key|secret|token|passwd|password|access[_-]?key)\b\s*[:=]\s*[\'"]?([A-Za-z0-9_\-]{16,})'),
    ('SCT/Server酱 key', r'(?i)SCT\d{10,}'),
    ('百度 refresh_token', r'(?i)refresh_token["\']?\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{20,}'),
    ('邮箱', r'[\w\.\-]+@[\w\-]+\.[a-z]{2,}'),
    ('手机号', r'(?<!\d)1[3-9]\d{9}(?!\d)'),
    ('内网 IP', r'\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b'),
    ('Tailscale IP', r'\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b'),
    ('Tailscale 域名', r'[\w\-]+\.ts\.net'),
    ('抖音房间 URL', r'live\.douyin\.com/\d+'),
    ('B站房间 URL', r'live\.bilibili\.com/\d+'),
    ('斗鱼房间 URL', r'douyu\.com/\d+'),
    ('本机绝对路径', r'F:\\\\?DanmakuRender'),
    ('rdp/凭据文件', r'(?i)(id_rsa|\.pem|\.pfx|\.key)\b'),
]

hits = {}
for f in files:
    p = os.path.join(REPO, f)
    if not os.path.isfile(p):
        continue
    if os.path.getsize(p) > 3 * 1024 * 1024:
        continue
    try:
        txt = open(p, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    for name, pat in PATTERNS:
        for m in re.finditer(pat, txt):
            hits.setdefault(name, []).append((f, m.group(0)[:70]))

for name, _ in PATTERNS:
    lst = hits.get(name)
    if not lst:
        continue
    uniq = {}
    for f, s in lst:
        uniq.setdefault(f, set()).add(s)
    total = sum(len(v) for v in uniq.values())
    print(f'\n  ⚠️ 【{name}】命中 {total} 处，涉及 {len(uniq)} 个文件:')
    for f in sorted(uniq)[:12]:
        samples = list(uniq[f])[:2]
        print(f'      {f}')
        for s in samples:
            print(f'          {s}')
    if len(uniq) > 12:
        print(f'      ... 还有 {len(uniq)-12} 个文件')

print()
print('=' * 78)
print('2. 大文件检查（>1MB，通常不该进仓库）')
print('=' * 78)
big = []
for f in files:
    p = os.path.join(REPO, f)
    if os.path.isfile(p) and os.path.getsize(p) > 1024 * 1024:
        big.append((os.path.getsize(p), f))
if big:
    for sz, f in sorted(big, reverse=True)[:15]:
        print(f'  {sz/1024/1024:>8.2f} MB  {f}')
else:
    print('  ✅ 没有 >1MB 的文件')

print()
print('=' * 78)
print('3. .gitignore 内容')
print('=' * 78)
gi = os.path.join(REPO, '.gitignore')
if os.path.exists(gi):
    for l in open(gi, encoding='utf-8', errors='replace').read().split('\n'):
        if l.strip() and not l.strip().startswith('#'):
            print(f'  {l}')

print()
print('=' * 78)
print('4. 有没有被跟踪的运行时产物（logs/.temp/回放）')
print('=' * 78)
BAD_DIRS = ('logs/', '.temp/', '直播回放/', '.venv/', 'login_info/',
            '__pycache__/', '.login_info/')
bad = [f for f in files if any(f.startswith(d) or f'/{d}' in f for d in BAD_DIRS)]
if bad:
    print(f'  ⚠️ {len(bad)} 个:')
    for f in bad[:20]:
        print(f'      {f}')
else:
    print('  ✅ 没有')

print()
print('=' * 78)
print('5. 结论')
print('=' * 78)
if hits or bad or big:
    print('  ⚠️ 发现需要处理的内容，建议先清理再发布')
else:
    print('  ✅ 没有发现敏感信息 / 大文件 / 运行时产物')
