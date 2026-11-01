"""彻底排查：合并上游后还有没有"用了但没导入"的名字。

这次用最可靠的方法：
    1. 逐个 import 项目里所有模块（能抓到 ImportError / NameError at import time）
    2. 用 pyflakes（若能装）做静态未定义名检查
    3. 对比上游与本地，找出"上游改了但本地没跟上的" __init__.py 导出

背景：is_danmaku_xml 这次就是因为 DMR/utils/__init__.py 少了
      `from .xml2ass import *` 而报 NameError，而且**在渲染时才暴露**，
      tools/check_imports.py 没抓到（因为它没检查 dmrender 的运行时依赖）。
"""
import ast
import os
import re
import subprocess
import sys

PROD = r'F:\DanmakuRender_AutoUp'
# NOTE 2026-11-02: this constant used to point at another copy of the
# project (no longer maintained). It now points at this project.
DEV = r'F:\DanmakuRender_AutoUp'
PY = os.path.join(PROD, '.venv', 'Scripts', 'python.exe')
GIT = r'C:\Program Files\Git\cmd\git.exe'

print('=' * 78)
print('1. 逐个 import 所有模块（抓 import 期错误）')
print('=' * 78)
mods = []
for root, dirs, files in os.walk(os.path.join(PROD, 'DMR')):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if f.endswith('.py'):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, PROD)
            m = rel[:-3].replace(os.sep, '.')
            if m.endswith('.__init__'):
                m = m[:-9]
            mods.append(m)
mods = sorted(set(mods))
print(f'  共 {len(mods)} 个模块')

code = (
    "import sys, os, logging\n"
    f"sys.path.insert(0, r'{PROD}')\n"
    f"os.chdir(r'{PROD}')\n"
    "logging.basicConfig(level=logging.CRITICAL)\n"
    f"mods = {mods!r}\n"
    "bad = []\n"
    "for m in mods:\n"
    "    try:\n"
    "        __import__(m)\n"
    "    except Exception as e:\n"
    "        bad.append((m, type(e).__name__, str(e)[:120]))\n"
    "print(f'  失败 {len(bad)} 个')\n"
    "for m, t, e in bad:\n"
    "    print(f'    X {m}: {t}: {e}')\n"
)
r = subprocess.run([PY, '-c', code], capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=600)
print(r.stdout or '')
if r.stderr and 'Error' in r.stderr:
    print('  stderr:', r.stderr[-500:])

print()
print('=' * 78)
print('2. 对比上游 vs 本地所有 __init__.py 的导出')
print('=' * 78)
inits = []
for root, dirs, files in os.walk(os.path.join(PROD, 'DMR')):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if f == '__init__.py':
            rel = os.path.relpath(os.path.join(root, f), PROD)
            inits.append(rel.replace(os.sep, '/'))

for rel in sorted(inits):
    r = subprocess.run([GIT, 'show', f'upstream/v5:{rel}'],
                       cwd=DEV, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    up = r.stdout or ''
    lp = open(os.path.join(PROD, rel), encoding='utf-8',
              errors='replace').read()
    if r.returncode != 0:
        print(f'  {rel}: 上游没有此文件')
        continue
    up_imports = set(re.findall(r'^from\s+\.(\w+)\s+import', up, re.M))
    lp_imports = set(re.findall(r'^from\s+\.(\w+)\s+import', lp, re.M))
    missing = up_imports - lp_imports
    if missing:
        print(f'  🔴 {rel}')
        print(f'      上游有而本地缺的导入: {sorted(missing)}')
    else:
        print(f'  ✅ {rel}')

print()
print('=' * 78)
print('3. 检查 dmrender.py 用到的名字是否都能在运行时拿到')
print('=' * 78)
code2 = (
    "import sys, os, logging, re\n"
    f"sys.path.insert(0, r'{PROD}')\n"
    f"os.chdir(r'{PROD}')\n"
    "logging.basicConfig(level=logging.CRITICAL)\n"
    f"src = open(r'{PROD}\\DMR\\Render\\dmrender.py', encoding='utf-8').read()\n"
    "tree = __import__('ast').parse(src)\n"
    "names = set()\n"
    "for n in __import__('ast').walk(tree):\n"
    "    if isinstance(n, __import__('ast').Name):\n"
    "        names.add(n.id)\n"
    "import DMR.Render.dmrender as m\n"
    "miss = sorted(x for x in names if not hasattr(m, x) and x not in dir(__builtins__))\n"
    "print(f'  dmrender 里可能缺的名字 ({len(miss)}):')\n"
    "for x in miss:\n"
    "    print(f'    {x}')\n"
)
r = subprocess.run([PY, '-c', code2], capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=300)
print(r.stdout or r.stderr[-400:])

print()
print('=' * 78)
print('4. 装 pyflakes 做静态未定义名扫描（最彻底）')
print('=' * 78)
r = subprocess.run([PY, '-m', 'pyflakes', '--version'],
                   capture_output=True, text=True)
if r.returncode != 0:
    print('  安装 pyflakes...')
    r2 = subprocess.run([PY, '-m', 'pip', 'install', '-q', 'pyflakes'],
                        capture_output=True, text=True, timeout=300)
    print(f'  install exit={r2.returncode}')
r = subprocess.run([PY, '-m', 'pyflakes',
                    os.path.join(PROD, 'DMR')],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=600)
lines = [l for l in (r.stdout or '').split('\n')
         if 'undefined name' in l]
print(f'  "undefined name" 问题: {len(lines)} 条')
for l in lines[:30]:
    print(f'    {l.strip()[:140]}')
if not lines:
    print('  ✅ 无未定义名问题')
