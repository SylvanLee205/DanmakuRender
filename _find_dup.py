"""找"直播已结束"的 INFO 级日志来自哪里。"""
import os
import re
import subprocess

PROD = r'F:\DanmakuRender_AutoUp'
DEV = r'F:\DanmakuRender_Mod'
GIT = r'C:\Program Files\Git\cmd\git.exe'


def git(*a):
    r = subprocess.run([GIT] + list(a), cwd=DEV, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or ''), (r.stderr or '')


print('=' * 78)
print('1. prod 全项目搜"直播已结束"')
print('=' * 78)
for root, dirs, files in os.walk(PROD):
    dirs[:] = [d for d in dirs if d not in
               ('.venv', '__pycache__', '.git', 'logs', '直播回放', 'unit_tests')]
    for f in files:
        if not f.endswith('.py'):
            continue
        p = os.path.join(root, f)
        try:
            txt = open(p, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        if '直播已结束' in txt:
            rel = os.path.relpath(p, PROD)
            for i, l in enumerate(txt.split('\n'), 1):
                if '直播已结束' in l:
                    print(f'  {rel}:{i}')
                    print(f'      {l.strip()[:120]}')
                    # 往上找 5 行看上下文
                    lines = txt.split('\n')
                    for j in range(max(0, i - 6), i - 1):
                        if lines[j].strip():
                            print(f'        ↑ {lines[j].strip()[:100]}')

print()
print('=' * 78)
print('2. 找 liveend / LiveEnd 的 logger.info 调用')
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
            if re.search(r'logger\.info\(', l) and ('直播' in l or 'live' in l.lower()):
                print(f'  {os.path.relpath(p, PROD)}:{i}: {l.strip()[:115]}')

print()
print('=' * 78)
print('3. ★ 上游版本的 defaultEvent / onLiveEnd（对比谁多打了）')
print('=' * 78)
rc, up, _ = git('show', 'upstream/v5:DMR/Task/liveevents.py')
cur = open(os.path.join(PROD, 'DMR', 'Task', 'liveevents.py'),
           encoding='utf-8').read()


def method(src, name):
    i = src.find(f'    def {name}(')
    if i < 0:
        return None
    j = src.find('\n    def ', i + 5)
    k = src.find('\n    @', i + 5)
    return src[i:min(x for x in (j, k, len(src)) if x > 0)]


for name in ('defaultEvent', 'onLiveEnd'):
    print(f'\n  ── {name} ──')
    for label, src in (('上游', up), ('当前prod', cur)):
        m = method(src, name)
        print(f'    [{label}]')
        if m:
            for l in m.split('\n')[:16]:
                print(f'      {l[:112]}')
        else:
            print('      (不存在)')

print()
print('=' * 78)
print('4. 引擎层有没有额外打"直播已结束"')
print('=' * 78)
rc, upeng, _ = git('show', 'upstream/v5:DMR/engine.py')
eng = open(os.path.join(PROD, 'DMR', 'engine.py'), encoding='utf-8').read()
for label, src in (('上游 engine', upeng), ('prod engine', eng)):
    n = src.count('直播已结束')
    print(f'  {label}: {n} 处')
    for i, l in enumerate(src.split('\n'), 1):
        if '直播已结束' in l:
            print(f'      L{i}: {l.strip()[:110]}')

print()
print('=' * 78)
print('5. 下载器层')
print('=' * 78)
sd = open(os.path.join(PROD, 'DMR', 'Downloader', 'stream_downloader.py'),
          encoding='utf-8').read()
for i, l in enumerate(sd.split('\n'), 1):
    if '直播已结束' in l or 'liveend' in l.lower():
        print(f'  stream_downloader.py:{i}: {l.strip()[:115]}')
