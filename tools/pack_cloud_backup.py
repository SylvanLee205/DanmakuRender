"""打包出适合上传网盘的精简备份（不含视频和虚拟环境）。

产出：
    DMR-完整代码-<日期>.zip   代码+配置+工具+文档+状态库（含 biliup.exe）
    DMR-Mod-git-<日期>.zip    开发仓库完整 .git 历史
    DMR-git-bundle-<日期>.zip 可独立克隆的 bundle

体积控制在 40 MB 左右，适合传到网盘做异地副本。
"""
import os
import shutil
import subprocess
import sys
import zipfile

PROD = r'F:\DanmakuRender_AutoUp'
# NOTE 2026-11-02: this constant used to point at another copy of the
# project (no longer maintained). It now points at this project.
MOD = r'F:\DanmakuRender_AutoUp'
RELEASE = r'F:\_DMRelease'
OUT = r'D:\_cloud_upload'
DATE = '20261019'

#: 整个目录跳过
SKIP_DIRS = {'.venv', '__pycache__', '.temp', '.git', '直播回放', 'node_modules'}
#: logs 只留状态库（日志本身没价值）
LOG_KEEP = {'dmr_state.db', 'pending_clean.json', 'failed_renders.json',
            'failed_uploads.json'}


def add_zip_tree(zf, root, arc_root, skip_dirs=None, log_mode=False):
    n = 0
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn
                 if d not in (skip_dirs if skip_dirs is not None else SKIP_DIRS)]
        for f in fns:
            if f.endswith(('.pyc', '.pyo')):
                continue
            if log_mode and f not in LOG_KEEP:
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            try:
                zf.write(p, os.path.join(arc_root, rel))
                n += 1
            except OSError as e:
                print(f'    跳过 {rel}: {e}')
    return n


def build():
    os.makedirs(OUT, exist_ok=True)
    results = []

    # ── 1. 生产代码 ──
    z1 = os.path.join(OUT, f'DMR-完整代码-{DATE}.zip')
    if os.path.exists(z1):
        os.remove(z1)
    print('  打包生产环境 ...', flush=True)
    n = 0
    with zipfile.ZipFile(z1, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 代码与配置（跳过 logs/直播回放）
        for dp, dn, fns in os.walk(PROD):
            dn[:] = [d for d in dn if d not in SKIP_DIRS and d != 'logs']
            for f in fns:
                if f.endswith(('.pyc', '.pyo')):
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, PROD)
                try:
                    zf.write(p, os.path.join('DMR', rel))
                    n += 1
                except OSError:
                    pass
        # logs 只留关键状态文件
        lg = os.path.join(PROD, 'logs')
        if os.path.isdir(lg):
            for f in os.listdir(lg):
                p = os.path.join(lg, f)
                if os.path.isfile(p) and f in LOG_KEEP:
                    zf.write(p, os.path.join('DMR', 'logs', f))
                    n += 1
    sz1 = os.path.getsize(z1) / 1024**2
    print(f'    ✅ {os.path.basename(z1)}  {n} 个文件 -> {sz1:.1f} MB')
    results.append((z1, sz1))

    # ── 2. 开发仓库 .git ──
    z2 = os.path.join(OUT, f'DMR-Mod-git-{DATE}.zip')
    if os.path.exists(z2):
        os.remove(z2)
    print('  打包开发仓库 .git ...', flush=True)
    n = 0
    with zipfile.ZipFile(z2, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        g = os.path.join(MOD, '.git')
        if os.path.isdir(g):
            n = add_zip_tree(zf, g, 'Mod/.git', skip_dirs=set())
    sz2 = os.path.getsize(z2) / 1024**2
    print(f'    ✅ {os.path.basename(z2)}  {n} 个文件 -> {sz2:.1f} MB')
    results.append((z2, sz2))

    # ── 3. bundle ──
    z3 = os.path.join(OUT, f'DMR-git-bundle-{DATE}.zip')
    if os.path.exists(z3):
        os.remove(z3)
    print('  打包 git bundle ...', flush=True)
    n = 0
    with zipfile.ZipFile(z3, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in os.listdir(RELEASE):
            if f.endswith('.bundle'):
                p = os.path.join(RELEASE, f)
                zf.write(p, f)
                n += 1
    sz3 = os.path.getsize(z3) / 1024**2
    print(f'    ✅ {os.path.basename(z3)}  {n} 个 bundle -> {sz3:.1f} MB')
    results.append((z3, sz3))

    print()
    tot = sum(s for _, s in results)
    print(f'  合计 {tot:.1f} MB')
    return results


if __name__ == '__main__':
    print('=' * 78)
    print('打精简备份包（供上传网盘）')
    print('=' * 78)
    r = build()
    print()
    for p, s in r:
        print(f'  {s:7.1f} MB  {p}')
