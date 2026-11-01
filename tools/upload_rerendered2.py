"""用 Python 列出并上传渲染产物（避免 PowerShell 全角括号编码问题）。"""
import os
import shutil
import sqlite3
import subprocess
import time


def _tool(name):
    """定位外部工具：环境变量 -> tools/ -> PATH -> 注册表 PATH -> 安装目录。

    见 DMR/utils/toolsmgr.py。不写死版本号和安装位置 ——
    换个 rclone 版本、换台电脑都不用改代码。
    """
    import os as _o
    import sys as _s
    _root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
    if _root not in _s.path:
        _s.path.insert(0, _root)
    from DMR.utils.toolsmgr import find_tool
    return find_tool(name) or name

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT
RCLONE = _tool('rclone')
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'

KEYS = ['10月15日19点30分', '10月15日21点21分', '10月15日21点26分']

print('=' * 78)
print('1. 找出待上传的渲染产物')
print('=' * 78)
found = []
for root, dirs, files in os.walk(os.path.join(UP, '直播回放')):
    for f in files:
        if not f.endswith('.mp4'):
            continue
        if any(k in f for k in KEYS):
            p = os.path.join(root, f)
            task = os.path.basename(root).replace('（弹幕版）', '')
            found.append((p, task, os.path.getsize(p)))
            print(f'  [{task}] {f}')
            print(f'      {os.path.getsize(p)/1024/1024:.1f} MB')
            print(f'      {p}')

if not found:
    print('  ❌ 没找到')
    raise SystemExit(1)

print()
print('=' * 78)
print('2. 上传')
print('=' * 78)
for p, task, sz in found:
    name = os.path.basename(p)
    print(f'  → [{task}] {name}  ({sz/1024/1024:.1f} MB)')
    r = subprocess.run([RCLONE, 'copyto', p,
                        f'cd2:百度网盘/DMR录播/{task}/{name}',
                        '--retries', '3', '--low-level-retries', '10',
                        '--transfers', '1'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=3600)
    print(f'     exit={r.returncode}'
          + (f'  {(r.stderr or "").strip()[:150]}' if r.returncode else ''))

print()
print('=' * 78)
print('3. 等 CD2 传完并核对云端')
print('=' * 78)


def cloud(task):
    tmp = os.path.join(os.environ['TEMP'], 'upchk2')
    os.makedirs(tmp, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(SVC, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(tmp, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    q = os.path.join(tmp, 'dir_cache.sqlite')
    try:
        con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute('SELECT id FROM cached_item WHERE path LIKE ?',
                    (f'%/DMR录播/{task}',))
        out = set()
        for (did,) in cur.fetchall():
            cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
            out |= {r[0] for r in cur.fetchall()}
        con.close()
        return out
    except Exception:
        return set()


pending = [(os.path.basename(p), task) for p, task, _ in found]
for i in range(25):
    time.sleep(30)
    done = 0
    for name, task in pending:
        if name in cloud(task):
            done += 1
    print(f'  +{(i+1)*30}s  云端已确认 {done}/{len(pending)}')
    if done == len(pending):
        break

print()
print('  最终确认:')
for name, task in pending:
    ok = name in cloud(task)
    print(f'    {"✅" if ok else "❌"} [{task}] {name}')
