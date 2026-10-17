"""精确看清理日志和执行路径。"""
import glob
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('当前时间')
print('=' * 78)
print('  ' + ps("(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')"))

print()
print('=' * 78)
print('1. 真正的清理日志（过滤掉配置转储）')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
pat = re.compile(r'正在清理|清理完成|cleaner|Cleaner|清理.*失败|跳过清理')
rows = []
for lg in logs[:3]:
    try:
        txt = open(lg, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    for line in txt.split('\n'):
        s = line.strip()
        # 排除 YAML 转储行（以引号开头、或含 clean_args": { 的）
        if s.startswith('"') or 'clean_args": {' in s or s.startswith("{'"):
            continue
        if pat.search(s):
            rows.append(s)
print(f'  共 {len(rows)} 条，尾部 35 条:')
for l in rows[-35:]:
    print(f'    {l[:175]}')

print()
print('=' * 78)
print('2. 按"正在清理"统计实际执行次数')
print('=' * 78)
n_clean = len([r for r in rows if '正在清理' in r])
n_done = len([r for r in rows if '清理完成' in r])
print(f'  "正在清理..." {n_clean} 次')
print(f'  "清理完成"    {n_done} 次')
if n_clean != n_done:
    print(f'  ⚠️ 不匹配！有 {n_clean - n_done} 次清理没有完成记录')

print()
print('=' * 78)
print('3. 今天（10-07）的清理活动')
print('=' * 78)
today = time.strftime('%Y-%m-%d')
t_rows = [r for r in rows if today in r]
print(f'  共 {len(t_rows)} 条:')
for l in t_rows[-25:]:
    print(f'    {l[:175]}')

print()
print('=' * 78)
print('4. 未清理的 .mkv 是否"已上传且已渲染"（判断为什么没清）')
print('=' * 78)
REPLAY = os.path.join(UP, '直播回放')
# 只看今天产生的
stale = []
for d in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, d)
    if not os.path.isdir(sub) or d.endswith('（弹幕版）'):
        continue
    for f in os.listdir(sub):
        if not f.endswith('.mkv'):
            continue
        p = os.path.join(sub, f)
        age_h = (time.time() - os.path.getmtime(p)) / 3600
        if age_h < 24:
            stale.append((age_h, os.path.getsize(p) / 1024 / 1024, d, f))
stale.sort(reverse=True)
print(f'  近 24h 的未清理 .mkv: {len(stale)} 个')
for age_h, mb, d, f in stale:
    # 对应的弹幕版文件在不在
    dm = os.path.join(REPLAY, f'{d}（弹幕版）', os.path.splitext(f)[0] + '（弹幕版）.mp4')
    dm_ok = os.path.exists(dm)
    dm_sz = os.path.getsize(dm) / 1024 / 1024 if dm_ok else 0
    print(f'  {age_h:>6.1f}h {mb:>7.1f}MB [{d}] {f[:45]}')
    print(f'          弹幕版存在={dm_ok}' + (f' ({dm_sz:.1f}MB)' if dm_ok else ' ← 没渲染出来？'))

print()
print('=' * 78)
print('5. 关键：日志里有没有 clean_args 相关配置')
print('=' * 78)
try:
    import json
    import yaml
    g = yaml.safe_load(open(os.path.join(UP, 'configs', 'global.yml'), encoding='utf-8'))
    print('  clean_args_task_default:')
    v = g.get('clean_args_task_default')
    print('  ' + json.dumps(v, ensure_ascii=False, indent=2, default=str).replace('\n', '\n  '))
except Exception as e:
    print(f'  失败: {e}')
