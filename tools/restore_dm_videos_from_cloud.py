"""从云端还原本地缺失的弹幕版视频。

背景：2026-10-18 清理时误删了 71 个弹幕版（用户的真实需求是
「只删源视频，弹幕版必须留在本地」）。这些文件云端都有，直接拉回来。

用法：
    python tools/restore_dm_videos_from_cloud.py            # dry-run
    python tools/restore_dm_videos_from_cloud.py --apply    # 真下载
"""
import os
import subprocess
import sys
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


PROD = _PROJECT_ROOT
REPLAY = os.path.join(PROD, '直播回放')
REMOTE_ROOT = 'cd2:百度网盘/DMR录播'
RCLONE = _tool('rclone')

apply = '--apply' in sys.argv

print('=' * 78)
print(f'从云端还原缺失的弹幕版 {"（实际下载）" if apply else "（DRY-RUN）"}')
print('=' * 78)

# 1. 列出云端（含 size，用于估算）
print('  读取云端文件列表...')
r = subprocess.run([RCLONE, 'lsf', REMOTE_ROOT, '--max-depth', '2',
                    '--files-only', '--format', 'sp'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
if r.returncode != 0:
    print(f'  ❌ rclone 失败: {(r.stderr or "")[:200]}')
    sys.exit(1)

entries = []
for line in (r.stdout or '').split('\n'):
    line = line.strip()
    if not line:
        continue
    # --format sp: "<size>;<path>"
    if ';' in line:
        sz, _, path = line.partition(';')
        try:
            sz = int(sz)
        except ValueError:
            sz = 0
    else:
        sz, path = 0, line
    path = path.replace('\\', '/')
    parts = path.split('/')
    if len(parts) < 2:
        continue
    entries.append((parts[0], parts[-1], sz))

print(f'  云端 {len(entries)} 个文件')

# 2. 本地已有文件名
local = set()
for dp, dn, fns in os.walk(REPLAY):
    for f in fns:
        local.add(f)

# 3. 找缺失
todo = []
for task, fn, sz in entries:
    if fn in local:
        continue
    dst_dir = os.path.join(REPLAY, f'{task}（弹幕版）')
    todo.append((task, fn, sz, dst_dir))

total = sum(t[2] for t in todo)
print(f'  需还原 {len(todo)} 个，共 {total/1024**3:.2f} GB')
print()

if not todo:
    print('  ✅ 本地已齐全，无需还原')
    sys.exit(0)

if not apply:
    for task, fn, sz, dst in todo[:20]:
        print(f'    {sz/1024**2:9.1f} MB  [{task[:18]:20}] {fn[:56]}')
    if len(todo) > 20:
        print(f'    ... 还有 {len(todo)-20} 个')
    print()
    print('  DRY-RUN 结束。加 --apply 下载。')
    sys.exit(0)

# 4. 下载
print('  开始从云端还原...')
ok = fail = 0
done_bytes = 0
t0 = time.time()
failed = []
for i, (task, fn, sz, dst_dir) in enumerate(todo, 1):
    os.makedirs(dst_dir, exist_ok=True)
    src = f'{REMOTE_ROOT}/{task}/{fn}'
    dst = os.path.join(dst_dir, fn)
    r = subprocess.run([RCLONE, 'copyto', src, dst,
                        '--retries', '3', '--low-level-retries', '10'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=3600)
    if r.returncode == 0 and os.path.exists(dst):
        real = os.path.getsize(dst)
        ok += 1
        done_bytes += real
        print(f'    [{i}/{len(todo)}] ✅ {real/1024**2:8.1f} MB  {fn[:56]}')
    else:
        fail += 1
        failed.append((task, fn, (r.stderr or '')[:120]))
        print(f'    [{i}/{len(todo)}] ❌ {fn[:56]}  {(r.stderr or "")[:80]}')

el = time.time() - t0
print()
print(f'  还原完成: 成功 {ok}，失败 {fail}，共 {done_bytes/1024**3:.2f} GB，'
      f'耗时 {el/60:.1f} 分钟')
if failed:
    print('  失败列表:')
    for t, f, e in failed:
        print(f'    [{t}] {f[:60]}')
        print(f'        {e}')

# 5. 复核
local2 = set()
for dp, dn, fns in os.walk(REPLAY):
    for f in fns:
        local2.add(f)
still = [(t, f) for t, f, _, _ in todo if f not in local2]
print()
print(f'  复核：仍缺失 {len(still)} 个')
for t, f in still[:10]:
    print(f'    [{t}] {f[:62]}')
