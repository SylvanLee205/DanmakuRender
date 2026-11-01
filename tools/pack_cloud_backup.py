"""打包出适合上传网盘的精简备份（不含视频和虚拟环境）。

产出（默认放在 <项目根>\\backups\\upload\\）：
    DMR-完整代码-<日期>.zip   代码+配置+工具+文档+状态库（含 biliup.exe）
    DMR-git-<日期>.zip        完整 .git 历史（可解压后直接 git 恢复）
    DMR-git-<日期>.bundle     可独立克隆的 git bundle（体积更小）
    DMR-git-<日期>.zip.bundle 不再单独打 zip，bundle 直接产出

体积控制在 40 MB 左右，适合传到网盘做异地副本。

⚠️ 2026-11-02 重写：原版假设项目分 AutoUp / Mod 两个目录，还写死了
    `F:\\_DMRelease` 和 `D:\\_cloud_upload`。现在只有一个项目目录，
    bundle 直接用 `git bundle create` 现做，不依赖任何外部目录。

用法：
    python tools\\pack_cloud_backup.py
    python tools\\pack_cloud_backup.py --out D:\\上传区
"""
import argparse
import datetime
import os
import subprocess
import sys
import zipfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from DMR.paths import ROOT as PROJ  # noqa: E402

#: 整个目录跳过
SKIP_DIRS = {'.venv', '__pycache__', '.temp', '.git', '.trash',
             '直播回放', 'node_modules', 'backups'}
#: logs 只留状态库（日志本身没价值）
LOG_KEEP = {'dmr_state.db', 'pending_clean.json', 'failed_renders.json',
            'failed_uploads.json'}

ARC_ROOT = 'DanmakuRepo'


def default_out():
    d = os.path.join(PROJ, 'backups', 'upload')
    os.makedirs(d, exist_ok=True)
    return d


def add_zip_tree(zf, root, arc_root, skip_dirs=None):
    n = 0
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn
                 if d not in (skip_dirs if skip_dirs is not None else SKIP_DIRS)]
        for f in fns:
            if f.endswith(('.pyc', '.pyo')):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            try:
                zf.write(p, os.path.join(arc_root, rel))
                n += 1
            except OSError as e:
                print(f'    跳过 {rel}: {e}')
    return n


def git(*args, cwd=None):
    r = subprocess.run(['git'] + list(args), cwd=cwd or PROJ,
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '').strip(), (r.stderr or '').strip()


def build(out_dir=None):
    out = out_dir or default_out()
    os.makedirs(out, exist_ok=True)
    date = datetime.datetime.now().strftime('%Y%m%d')
    results = []

    # ── 1. 代码包（不含 .git / 视频 / 虚拟环境）──
    z1 = os.path.join(out, f'DMR-完整代码-{date}.zip')
    if os.path.exists(z1):
        os.remove(z1)
    print('  打包代码+配置 ...', flush=True)
    n = 0
    with zipfile.ZipFile(z1, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dp, dn, fns in os.walk(PROJ):
            dn[:] = [d for d in dn if d not in SKIP_DIRS and d != 'logs']
            for f in fns:
                if f.endswith(('.pyc', '.pyo')):
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, PROJ)
                try:
                    zf.write(p, os.path.join(ARC_ROOT, rel))
                    n += 1
                except OSError:
                    pass
        lg = os.path.join(PROJ, 'logs')
        if os.path.isdir(lg):
            for f in os.listdir(lg):
                p = os.path.join(lg, f)
                if os.path.isfile(p) and f in LOG_KEEP:
                    zf.write(p, os.path.join(ARC_ROOT, 'logs', f))
                    n += 1
    sz1 = os.path.getsize(z1) / 1024 ** 2
    print(f'    ✅ {os.path.basename(z1)}  {n} 个文件 -> {sz1:.1f} MB')
    results.append((z1, sz1))

    # ── 2. .git 完整历史 ──
    z2 = os.path.join(out, f'DMR-git-{date}.zip')
    if os.path.exists(z2):
        os.remove(z2)
    print('  打包 .git 历史 ...', flush=True)
    g = os.path.join(PROJ, '.git')
    n = 0
    if os.path.isdir(g):
        with zipfile.ZipFile(z2, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            n = add_zip_tree(zf, g, f'{ARC_ROOT}/.git', skip_dirs=set())
        sz2 = os.path.getsize(z2) / 1024 ** 2
        print(f'    ✅ {os.path.basename(z2)}  {n} 个文件 -> {sz2:.1f} MB')
        results.append((z2, sz2))
    else:
        print('    ⚠️ 没有 .git 目录，跳过')

    # ── 3. git bundle（可独立克隆，体积更小）──
    b = os.path.join(out, f'DMR-git-{date}.bundle')
    if os.path.exists(b):
        os.remove(b)
    print('  生成 git bundle ...', flush=True)
    rc, so, se = git('bundle', 'create', b, '--all')
    if rc == 0 and os.path.exists(b):
        szb = os.path.getsize(b) / 1024 ** 2
        print(f'    ✅ {os.path.basename(b)}  -> {szb:.1f} MB')
        print(f'       恢复方式: git clone "{b}" DanmakuRepo')
        results.append((b, szb))
    else:
        print(f'    ⚠️ bundle 生成失败: {se or so}')

    print()
    tot = sum(s for _, s in results)
    print(f'  合计 {tot:.1f} MB  ->  {out}')
    return results


def main():
    ap = argparse.ArgumentParser(description='打精简备份包（供上传网盘）')
    ap.add_argument('--out', default=None, help='输出目录（默认 <项目>\\backups\\upload）')
    args = ap.parse_args()
    print('=' * 78)
    print('打精简备份包（供上传网盘）')
    print('=' * 78)
    r = build(args.out)
    print()
    for p, s in r:
        print(f'  {s:7.1f} MB  {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
