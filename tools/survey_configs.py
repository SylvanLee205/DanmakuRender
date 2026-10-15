"""盘点配置现状，为建立保护机制做准备。"""
import json
import os
import re
import subprocess
import time

PROD = r'F:\DanmakuRender_AutoUp'
DEV = r'F:\DanmakuRender_Mod'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. prod configs 全貌')
print('=' * 78)
pc = os.path.join(PROD, 'configs')
items = sorted(os.listdir(pc))
print(f'  共 {len(items)} 项')
tasks = [x for x in items if x.startswith('DMR-') or x.startswith('dmr-')]
others = [x for x in items if x not in tasks]
print(f'  任务配置（DMR-*.yml）: {len(tasks)} 个')
print(f'  其他: {len(others)} 个 -> {others}')

total = sum(os.path.getsize(os.path.join(pc, x))
            for x in items if os.path.isfile(os.path.join(pc, x)))
print(f'  总大小: {total/1024:.1f} KB')

print()
print('=' * 78)
print('2. 是否有 temp / example 子目录')
print('=' * 78)
for sub in ('temp', 'example', 'backup'):
    p = os.path.join(pc, sub)
    if os.path.isdir(p):
        print(f'  {sub}/: {len(os.listdir(p))} 项')
    else:
        print(f'  {sub}/: 不存在')

print()
print('=' * 78)
print('3. gobal.yml 的关键自定义段（要重点保护的）')
print('=' * 78)
gj = os.path.join(pc, 'global.yml')
txt = open(gj, encoding='utf-8').read()
CRITICAL = [
    ('upload_args.rclone', 'rclone 网盘上传配置'),
    ('upload_args_task_default', '上传规则（dm_video → rclone）'),
    ('clean_args', '清理规则'),
    ('clean_args_task_default', '清理默认规则'),
    ('download_args', '下载配置'),
    ('render_args', '渲染配置'),
    ('skip_upload_rule', '跳过上传规则（我们的魔改）'),
    ('webservice_kernel_args', 'Web 服务配置'),
]
for key, desc in CRITICAL:
    # 简单判断键是否存在（缩进敏感，粗略匹配）
    found = re.search(rf'^\s*{re.escape(key.split(".")[-1])}\s*:', txt, re.M)
    print(f'  {"✅" if found else "❌"} {key:30} {desc}')

print()
print('=' * 78)
print('4. 现有备份位置')
print('=' * 78)
for base in ('F:\\',):
    try:
        for d in os.listdir(base):
            if d.startswith('_') and ('DMR' in d or 'CD2' in d):
                p = os.path.join(base, d)
                n = sum(len(files) for _, _, files in os.walk(p))
                sz = sum(os.path.getsize(os.path.join(r, f))
                         for r, _, fs in os.walk(p) for f in fs)
                print(f'  {d}  {n} 文件 / {sz/1024/1024:.1f} MB')
    except Exception as e:
        print(f'  {e}')

print()
print('=' * 78)
print('5. 有没有已存在的配置备份工具')
print('=' * 78)
for d in (os.path.join(PROD, 'tools'), os.path.join(PROD, 'configs')):
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if 'backup' in f.lower() or '备份' in f:
                print(f'  {os.path.relpath(os.path.join(d, f), PROD)}')
print('  （以上为找到的备份相关文件）')

print()
print('=' * 78)
print('6. 计划任务 / 开机自启 现状')
print('=' * 78)
out = ps("Get-ScheduledTask | Where-Object { $_.TaskName -like '*DMR*' -or "
         "$_.TaskName -like '*Danmaku*' -or $_.TaskName -like '*Cloud*' } | "
         "ForEach-Object { $_.TaskName + ' | ' + $_.State }")
print(f'  相关计划任务:')
for l in (out or '（无）').split('\n'):
    if l.strip():
        print(f'    {l.strip()}')

# 启动文件夹
startup = os.path.join(os.environ['APPDATA'],
                       r'Microsoft\Windows\Start Menu\Programs\Startup')
if os.path.isdir(startup):
    print(f'  启动文件夹 ({startup}):')
    for f in os.listdir(startup):
        print(f'    {f}')
