"""在生产环境启用自动上传：

  1. 所有 configs/DMR-*.yml 的 auto_upload 改成 True
  2. global.yml 的 skip_upload_rule.enabled 改成 True

先整体备份 configs 到 backups/ 目录。
"""
import glob
import os
import re
import shutil
import time

PROD = r'F:\123Pan_DanmakuRender'
CFG = os.path.join(PROD, 'configs')
stamp = time.strftime('%Y%m%d-%H%M%S')
BAK = os.path.join(PROD, 'backups', f'configs-{stamp}')

os.makedirs(BAK, exist_ok=True)

# ---------- 备份 ----------
files = sorted(glob.glob(os.path.join(CFG, '*.yml')))
for f in files:
    shutil.copy2(f, os.path.join(BAK, os.path.basename(f)))
print(f'已备份 {len(files)} 个配置文件到 {BAK}')
print()

# ---------- 1. 打开 auto_upload ----------
changed, skipped, failed = [], [], []
for f in files:
    base = os.path.basename(f)
    if base == 'global.yml':
        continue
    text = open(f, encoding='utf-8').read()
    if 'auto_upload' not in text:
        skipped.append((base, '没有 auto_upload 字段'))
        continue
    new = re.sub(r'(auto_upload\s*:\s*)(False|false|no|off)',
                 r'\g<1>True', text)
    if new == text:
        if re.search(r'auto_upload\s*:\s*True', text):
            skipped.append((base, '本来就是 True'))
        else:
            failed.append((base, '没匹配到可改的 False'))
        continue
    open(f, 'w', encoding='utf-8', newline='\n').write(new)
    changed.append(base)

print(f'=== auto_upload 改成 True：{len(changed)} 个 ===')
for b in changed:
    print(f'    {b}')
if skipped:
    print(f'--- 跳过 {len(skipped)} 个 ---')
    for b, why in skipped:
        print(f'    {b}: {why}')
if failed:
    print(f'--- 失败 {len(failed)} 个 ---')
    for b, why in failed:
        print(f'    {b}: {why}')

# ---------- 2. 打开 skip_upload_rule ----------
g = os.path.join(CFG, 'global.yml')
text = open(g, encoding='utf-8').read()
# 只改 skip_upload_rule 段里的 enabled
m = re.search(r'(skip_upload_rule:\s*\n)(\s*)(enabled\s*:\s*)(\w+)', text)
if m:
    if m.group(4).lower() in ('false',):
        text = text[:m.start(4)] + 'True' + text[m.end(4):]
        open(g, 'w', encoding='utf-8', newline='\n').write(text)
        print()
        print('=== skip_upload_rule.enabled 已改为 True ===')
    else:
        print()
        print(f'=== skip_upload_rule.enabled 已经是 {m.group(4)}，无需改 ===')
else:
    print()
    print('!! 没找到 skip_upload_rule.enabled，需要手工确认')
