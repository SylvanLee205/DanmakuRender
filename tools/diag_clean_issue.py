"""诊断清理问题。"""
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
print('1. 运行状态')
print('=' * 78)
print(f'  现在: {ps("(Get-Date).ToString(chr(121)+chr(121)+chr(121)+chr(121)+chr(45)+chr(77)+chr(77)+chr(45)+chr(100)+chr(100)+chr(32)+chr(72)+chr(72)+chr(58)+chr(109)+chr(109)+chr(58)+chr(115)+chr(115))")}')
cmd = ps("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
         "ForEach-Object { $_.ProcessId }").split()
py = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*main.py*' } | "
        "ForEach-Object { $_.ProcessId }").split()
print(f'  守护 cmd: {cmd or "❌ 无"}')
print(f'  DMR py  : {py or "❌ 无"}')
print(f'  CD2     : {ps("(Get-Service CloudDrive2).Status.ToString()")}  '
      f'19798监听={ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')

print()
print('=' * 78)
print('2. 清理相关日志（最近 40 条）')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
allclean = []
for lg in logs[:3]:
    try:
        txt = open(lg, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    for line in txt.split('\n'):
        if any(k in line for k in ('清理', 'clean', 'Clean')):
            allclean.append((os.path.basename(lg), line.strip()))
print(f'  共 {len(allclean)} 条，尾部 40 条:')
for f, l in allclean[-40:]:
    print(f'    {l[:170]}')

print()
print('=' * 78)
print('3. 清理相关的 ERROR / WARNING')
print('=' * 78)
errs = []
for lg in logs[:3]:
    try:
        txt = open(lg, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    for line in txt.split('\n'):
        if re.search(r'\[(error|warning|critical)\]', line, re.I) and \
           any(k in line for k in ('清理', 'clean', 'Clean')):
            errs.append(line.strip())
print(f'  共 {len(errs)} 条:')
for l in errs[-20:]:
    print(f'    {l[:175]}')

print()
print('=' * 78)
print('4. 源视频目录：有没有该清但没清的 .mkv')
print('=' * 78)
REPLAY = os.path.join(UP, '直播回放')
stale = []
for d in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, d)
    if not os.path.isdir(sub) or d.endswith('（弹幕版）'):
        continue
    for f in os.listdir(sub):
        if f.endswith('.mkv'):
            p = os.path.join(sub, f)
            age_h = (time.time() - os.path.getmtime(p)) / 3600
            stale.append((age_h, os.path.getsize(p) / 1024 / 1024, d, f))
stale.sort(reverse=True)
print(f'  共 {len(stale)} 个 .mkv（源视频，本应在上传后被清理）')
print(f'  {"存在时长":>10} {"大小MB":>10}  文件')
for age_h, mb, d, f in stale[:25]:
    flag = '  ⚠️ 超过 2 小时未清理' if age_h > 2 else ''
    print(f'  {age_h:>9.1f}h {mb:>10.1f}  [{d}] {f[:60]}{flag}')

print()
print('=' * 78)
print('5. .ass 弹幕文件（同样应被清理）')
print('=' * 78)
ass = []
for d in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, d)
    if not os.path.isdir(sub) or d.endswith('（弹幕版）'):
        continue
    for f in os.listdir(sub):
        if f.endswith('.ass'):
            p = os.path.join(sub, f)
            age_h = (time.time() - os.path.getmtime(p)) / 3600
            ass.append((age_h, os.path.getsize(p), d, f))
ass.sort(reverse=True)
print(f'  共 {len(ass)} 个 .ass')
for age_h, sz, d, f in ass[:15]:
    print(f'  {age_h:>9.1f}h {sz:>8} B  [{d}] {f[:60]}')

print()
print('=' * 78)
print('6. 清理配置')
print('=' * 78)
try:
    import yaml
    g = yaml.safe_load(open(os.path.join(UP, 'configs', 'global.yml'), encoding='utf-8'))
    import json
    print('  clean_args_task_default:')
    print('  ' + json.dumps(g.get('clean_args_task_default'), ensure_ascii=False, indent=2).replace('\n', '\n  '))
    print()
    print('  clean_args 顶层:')
    ca = g.get('clean_args')
    if ca:
        for k in ca:
            print(f'    {k}= {json.dumps(ca[k], ensure_ascii=False, default=str)[:200]}')
    else:
        print('    （无）')
except Exception as e:
    print(f'  读取失败: {e}')
