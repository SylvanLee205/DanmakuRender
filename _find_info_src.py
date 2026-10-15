"""确认"U: 直播已结束."这条 INFO 日志的来源。"""
import os
import re

PROD = r'F:\DanmakuRender_AutoUp'

print('=' * 78)
print('1. 搜谁发送了 event="info" 且内容含"直播已结束"')
print('=' * 78)
for root, dirs, files in os.walk(PROD):
    dirs[:] = [d for d in dirs if d not in
               ('.venv', '__pycache__', '.git', 'logs', '直播回放', 'unit_tests')]
    for f in files:
        if not f.endswith('.py'):
            continue
        p = os.path.join(root, f)
        txt = open(p, encoding='utf-8', errors='replace').read()
        for i, l in enumerate(txt.split('\n'), 1):
            if re.search(r"_pipeSend\(\s*['\"]info['\"]", l) or \
               re.search(r"event\s*=\s*['\"]info['\"]", l):
                print(f'  {os.path.relpath(p, PROD)}:{i}')
                print(f'      {l.strip()[:120]}')
                lines = txt.split('\n')
                for j in range(i, min(len(lines), i + 3)):
                    if lines[j].strip() and j != i - 1:
                        print(f'      +{j-i+1}: {lines[j].strip()[:110]}')

print()
print('=' * 78)
print('2. 实际日志里这条 INFO 长什么样（精确定位）')
print('=' * 78)
import glob
logs = sorted(glob.glob(os.path.join(PROD, 'logs', 'DMR-20261015*.log')),
              key=os.path.getmtime, reverse=True)
for lg in logs[:2]:
    print(f'  ── {os.path.basename(lg)} ──')
    txt = open(lg, encoding='utf-8', errors='replace').read()
    # 精确匹配 [liveevents][info]
    for m in re.finditer(r'\[liveevents\]\[info\]: (.{0,60})', txt):
        print(f'      {m.group(0)[:120]}')
    print('      ---')
    cnt_info = len(re.findall(r'\[liveevents\]\[info\]:', txt))
    cnt_prog = len(re.findall(r'\[liveevents\]\[PROGRESS\]:', txt))
    print(f'      liveevents INFO 条数: {cnt_info}')
    print(f'      liveevents PROGRESS 条数: {cnt_prog}')
    # 看 module 名
    mods = set(re.findall(r'\]\[(\w+)\]\[(?:info|PROGRESS)\]: (.{0,40})', txt))
    for mod, msg in sorted(mods):
        if '直播' in msg:
            print(f'      模块 {mod}: {msg[:50]}')

print()
print('=' * 78)
print('3. 我们版本（backup）里 onLiveEnd 打的是什么级别')
print('=' * 78)
import subprocess
GIT = r'C:\Program Files\Git\cmd\git.exe'
r = subprocess.run([GIT, 'show', 'backup-before-merge-v5:DMR/Task/liveevents.py'],
                   cwd=r'F:\DanmakuRender_Mod', capture_output=True, text=True,
                   encoding='utf-8', errors='replace')
old = r.stdout or ''
i = old.find('    def onLiveEnd(')
if i > 0:
    j = old.find('\n    def ', i + 5)
    k = old.find('\n    @', i + 5)
    end = min(x for x in (j, k, len(old)) if x > 0)
    print('  我们的旧版 onLiveEnd:')
    for l in old[i:end].split('\n')[:8]:
        print(f'      {l[:115]}')

print()
print('=' * 78)
print('4. 上游版 onLiveEnd')
print('=' * 78)
r = subprocess.run([GIT, 'show', 'upstream/v5:DMR/Task/liveevents.py'],
                   cwd=r'F:\DanmakuRender_Mod', capture_output=True, text=True,
                   encoding='utf-8', errors='replace')
up = r.stdout or ''
i = up.find('    def onLiveEnd(')
if i > 0:
    j = up.find('\n    def ', i + 5)
    k = up.find('\n    @', i + 5)
    end = min(x for x in (j, k, len(up)) if x > 0)
    print('  上游 onLiveEnd:')
    for l in up[i:end].split('\n')[:8]:
        print(f'      {l[:115]}')
