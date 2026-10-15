"""对个人敏感信息做打码替换。

替换规则（只动确实是用户自己的内容，上游自带的不动）：
    Tailscale IP    100.75.58.27      → 100.x.y.z
    Tailscale 域名  tail506a91.ts.net → <设备名>.ts.net
    内网 IP         192.168.5.5       → 192.168.x.x
    用户邮箱        1871163532@qq.com → you@example.com
    抖音房间号      <真实号>          → 123456789（示例号）

默认 dry-run，加 --apply 才真改。
"""
import os
import re
import sys

REPO = r'F:\DanmakuRender_Mod'

RULES = [
    ('Tailscale IP', re.compile(r'\b100\.75\.58\.27\b'), '100.x.y.z'),
    ('Tailscale 域名', re.compile(r'\btail506a91\.ts\.net\b'), '<设备名>.ts.net'),
    ('内网 IP', re.compile(r'\b192\.168\.5\.5\b'), '192.168.x.x'),
    ('用户邮箱', re.compile(r'\b1871163532@qq\.com\b'), 'you@example.com'),
]
# 真实抖音房间号 → 统一换成示例号
ROOMS = ['56909717876', '470116673696', '700084278384', '989986719971',
         '975387140329', '557839188085', '356284810909', '865102911165',
         '76368176167', '171682321878']
for rm in ROOMS:
    RULES.append((f'抖音房间号 {rm}', re.compile(rf'\b{rm}\b'), '123456789'))

# 只处理这些文件（由 find_private_info.py 扫描得出）
TARGETS = [
    'docs/控制台日志格式规范.md',
    'docs/服务版优势与远程访问安全.md',
    'tools/final_check_after_uninstall.py',
    'tools/fix_three_issues.py',
    'docs/上游合并与部署记录-20261015.md',
    'docs/配置保护机制.md',
    'docs/log_error_report.md',
    'tools/diagnose_corrupt_vvu.py',
    'docs/engine_comparison.md',
    'tools/ab_test_engines.py',
]

apply = '--apply' in sys.argv
print('=' * 78)
print(f'隐私打码 {"（实际执行）" if apply else "（DRY-RUN）"}')
print('=' * 78)

total = 0
changed_files = []
for rel in TARGETS:
    p = os.path.join(REPO, rel.replace('/', os.sep))
    if not os.path.exists(p):
        print(f'  ⚠️ 不存在: {rel}')
        continue
    txt = open(p, encoding='utf-8').read()
    orig = txt
    detail = []
    for name, pat, rep in RULES:
        n = len(pat.findall(txt))
        if n:
            txt = pat.sub(rep, txt)
            detail.append(f'{name}×{n}')
    if txt != orig:
        total += sum(int(d.split('×')[1]) for d in detail)
        changed_files.append(rel)
        print(f'  ✅ {rel}')
        for d in detail:
            print(f'        {d}')
        if apply:
            open(p, 'w', encoding='utf-8', newline='\n').write(txt)
    else:
        print(f'  ── {rel}  （无需修改）')

print()
print(f'  共 {len(changed_files)} 个文件、{total} 处替换'
      f'{"（已写入）" if apply else "（未写入，加 --apply 执行）"}')

# 复核
print()
print('=' * 78)
print('复核：打码后是否还有残留')
print('=' * 78)
LEFT = [
    ('Tailscale IP', re.compile(r'\b100\.75\.58\.27\b')),
    ('Tailscale 域名', re.compile(r'\btail506a91\.ts\.net\b')),
    ('内网 IP', re.compile(r'\b192\.168\.5\.5\b')),
    ('用户邮箱', re.compile(r'\b1871163532@qq\.com\b')),
]
for rm in ROOMS:
    LEFT.append((f'房间号 {rm}', re.compile(rf'\b{rm}\b')))
leftovers = {}
for rel in TARGETS:
    p = os.path.join(REPO, rel.replace('/', os.sep))
    if not os.path.exists(p):
        continue
    txt = open(p, encoding='utf-8').read()
    for name, pat in LEFT:
        if pat.search(txt):
            leftovers.setdefault(rel, []).append(name)
if leftovers:
    print('  ⚠️ 仍有残留:')
    for rel, names in leftovers.items():
        print(f'      {rel}: {names}')
else:
    print('  ✅ 全部清理干净')
