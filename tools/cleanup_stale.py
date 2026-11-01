"""清理陈旧/无用文件。先 dry-run 看清单，再真删。

保守原则：
  · 只删「明确无用」的：陈旧日志、stray log、未使用的二进制、过期备份、空目录、缓存
  · 不碰：configs/（除单个 .bak）、docs/、DMR/、tools/ 的 .py、直播回放的弹幕版
  · 有疑问的一律列为「保留」并说明原因
"""
import os
import shutil
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


PROD = _PROJECT_ROOT
# NOTE 2026-11-02: this constant used to point at another copy of the
# project (no longer maintained). It now points at this project.
MOD = _PROJECT_ROOT
NOW = time.time()
DRY = '--apply' not in sys.argv

to_del = []      # (path, size, why)
kept = []        # (path, size, why)

def add(path, why):
    if not os.path.exists(path):
        return
    if os.path.isdir(path):
        sz = sum(os.path.getsize(os.path.join(r, f))
                 for r, _, fs in os.walk(path) for f in fs
                 if os.path.exists(os.path.join(r, f)))
    else:
        try:
            sz = os.path.getsize(path)
        except OSError:
            sz = 0
    to_del.append((path, sz, why))

# ── 1. 旧 biliup 日志（引擎已切 ffmpeg，这是一个 134MB 的 stray log）──
p = os.path.join(PROD, 'download.log')
if os.path.exists(p):
    add(p, 'biliup-rs 的日志，引擎已切 ffmpeg，不再产生')

# ── 2. 14 天前的日志（保留 db / json）──
cut = NOW - 14 * 86400
logdir = os.path.join(PROD, 'logs')
old_logs = []
for f in os.listdir(logdir) if os.path.isdir(logdir) else []:
    fp = os.path.join(logdir, f)
    if not os.path.isfile(fp):
        continue
    if f.endswith(('.db', '.db-shm', '.db-wal', '.json')):
        continue
    if os.path.getmtime(fp) < cut:
        old_logs.append(fp)
for fp in old_logs:
    add(fp, '14 天前的日志')

# ── 3. 未使用的 biliup.exe（streamgears 引擎走 python 模块，不调这个 exe）──
# ⚠️⚠️ 2026-10-19 实测经历：这个 exe 虽然录制引擎不用，但
#    DMR/utils/toolsmgr.py 的 check_biliup() 在启动时**强制检查**它，
#    缺了会直接卡在 input() 上 → DMR 根本启动不了。
#    所以它是**必需依赖**，绝不能当“无用二进制”删掉。
kept.append((os.path.join(PROD, 'tools', 'biliup.exe'), 0,
             'DMR 启动时强制检查（toolsmgr.check_biliup），绝不能删'))

# ── 4. Start_Render.bat 的历史备份 ──
for f in os.listdir(PROD):
    if f.startswith('Start_Render.bat.'):
        add(os.path.join(PROD, f), '启动脚本的历史备份，当前版本工作正常')

# ── 5. 空的同步备份目录 ──
for f in os.listdir(PROD):
    fp = os.path.join(PROD, f)
    if f.startswith('.backup-sync-') and os.path.isdir(fp):
        n = sum(len(fs) for _, _, fs in os.walk(fp))
        if n == 0:
            add(fp, '空目录（同步备份残留）')
        else:
            kept.append((fp, 0, f'目录非空（{n} 个文件），保留'))

# ── 6. 系统垃圾 ──
add(os.path.join(PROD, '.DS_Store'), 'macOS 垃圾文件')
for r, ds, fs in os.walk(PROD):
    if '.venv' in r or '.git' in r:
        continue
    for d in list(ds):
        if d == '__pycache__':
            add(os.path.join(r, d), 'python 缓存')
            ds.remove(d)

# ── 7. .temp 里的 json 备份（旧）──
tdir = os.path.join(PROD, '.temp')
for f in os.listdir(tdir) if os.path.isdir(tdir) else []:
    if '.bak' in f:
        add(os.path.join(tdir, f), '.temp 里的旧备份')

# ── 8. 单个过期配置备份 ──
add(os.path.join(PROD, 'configs', 'DMR-灰蒙蒙.yml.bak-20261018-223751'),
    '已被后续改动取代的配置备份')

# ── 9. Mod 仓库的旧日志 ──
mlog = os.path.join(MOD, 'logs')
for f in os.listdir(mlog) if os.path.isdir(mlog) else []:
    fp = os.path.join(mlog, f)
    if os.path.isfile(fp) and os.path.getmtime(fp) < cut:
        add(fp, 'Mod 仓库 14 天前的日志')

# ── 10. (2) 重复渲染产物：只有同名无 (2) 的版本存在且更完整时才删 ──
pdir = os.path.join(PROD, '直播回放')
for r, ds, fs in os.walk(pdir):
    for f in fs:
        if '(2)' not in f:
            continue
        fp = os.path.join(r, f)
        base = f.replace('(2)', '', 1)
        twin = os.path.join(r, base)
        if os.path.exists(twin):
            if os.path.getsize(twin) >= os.path.getsize(fp) * 0.9:
                add(fp, f'重复渲染，同名正常版存在且更大（{os.path.getsize(twin)/1024**2:.1f} MB）')
            else:
                kept.append((fp, os.path.getsize(fp), '同名版反而更小，保留待人工确认'))
        else:
            kept.append((fp, os.path.getsize(fp), '没有同名版本，保留'))

# ── 输出 ──
print('=' * 84)
print(f'{"【DRY-RUN】" if DRY else "【实际删除】"}待删 {len(to_del)} 项')
print('=' * 84)
total = 0
for p, sz, why in sorted(to_del, key=lambda x: -x[1]):
    total += sz
    rel = p.replace(PROD + '\\', 'prod/').replace(MOD + '\\', 'mod/')
    print(f'  {sz/1024**2:9.2f} MB  {rel}')
    print(f'              ↳ {why}')
print(f'\n  合计释放: {total/1024**2:.1f} MB')

if kept:
    print()
    print('=' * 84)
    print(f'保留 {len(kept)} 项（需人工判断）')
    print('=' * 84)
    for p, sz, why in kept:
        print(f'  {sz/1024**2:9.2f} MB  {os.path.basename(p)}')
        print(f'              ↳ {why}')

if DRY:
    print()
    print('  这是 DRY-RUN。确认无误后加 --apply 执行。')
    sys.exit(0)

# ── 执行 ──
print()
print('=' * 84)
print('执行删除')
print('=' * 84)
ok = fail = 0
for p, sz, why in to_del:
    try:
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
        ok += 1
    except Exception as e:
        fail += 1
        print(f'  ❌ {os.path.basename(p)}: {type(e).__name__}: {e}')
print(f'  成功 {ok} 项 / 失败 {fail} 项 / 释放约 {total/1024**2:.1f} MB')
