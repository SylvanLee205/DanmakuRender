"""把整个项目备份到另一个磁盘（异盘备份）。

为什么需要：2026-10-19 有 29 个提交因 GitHub 账号被风控而无法推送，
这些工作当时只存在于 F 盘。一旦整机/整盘出问题就没有异地副本。

⚠️ 2026-11-02 重写：原版假设项目分两个目录（`AutoUp` 生产 + `Mod` 开发），
    还写死了 `F:\\_DMRelease` / `F:\\_DMR配置快照`。现在项目只有一个目录，
    快照也在项目内，所以改成完全自适应的：
      * 源目录 = 本文件所在项目根（放哪都行）
      * 目标子目录名 = 项目目录名
      * 校验用相对路径，不再假设目录叫 AutoUp

用法：
    python tools\\backup_to_disk.py                # 自动选一个非项目所在的盘
    python tools\\backup_to_disk.py --to E:        # 指定盘
    python tools\\backup_to_disk.py --dry-run      # 只看会做什么
    python tools\\backup_to_disk.py --check E:\\DMR备份-20261102-0730
"""
import argparse
import datetime
import os
import shutil
import string
import subprocess
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from DMR.paths import ROOT as PROJ  # noqa: E402

#: 备份到目标盘时的子目录名（跟着项目目录名走）
NAME = os.path.basename(PROJ.rstrip('\\/')) or 'DanmakuRepo'

#: 不备份（可重建，不值得占空间）
EXCLUDE_DIRS = ['.venv', '__pycache__', '.temp', 'node_modules', '.trash']
#: `.git` 必须备份 —— 现在是唯一的完整历史副本（没有第二个工作树了）
#: 录制视频体积巨大，默认排除；要一起备份加 --with-videos
VIDEO_DIR = '直播回放'


def human(n):
    return f'{n / 1024**2:.1f} MB'


def dir_size(p):
    tot = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return tot


def count_files(p):
    return sum(len(fs) for _, _, fs in os.walk(p))


def robocopy(src, dst, extra_exclude=()):
    """用 robocopy（Windows 原生多线程拷贝，比 shutil 快得多）。"""
    xd = [os.path.join(src, d) for d in EXCLUDE_DIRS] + \
         [os.path.join(src, d) for d in extra_exclude]
    cmd = ['robocopy', src, dst, '/E', '/XD'] + xd + \
          ['/XF', '*.pyc', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2']
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    # robocopy 退出码 0-7 都算成功（0=无变化, 1=有复制, ... 7=有额外文件）
    return r.returncode <= 7, r.returncode


def pick_drive():
    """挑一个存在、且不是项目所在盘的盘符，优先 D:。"""
    proj_drive = os.path.splitdrive(PROJ)[0].upper()
    candidates = []
    for letter in string.ascii_uppercase:
        d = f'{letter}:\\'
        if d.upper() == proj_drive or not os.path.isdir(d):
            continue
        try:
            free = shutil.disk_usage(d).free
        except OSError:
            continue
        if free > 1024 ** 3:                 # 至少 1GB
            candidates.append((0 if letter == 'D' else 1, -free, d))
    if not candidates:
        return None
    return sorted(candidates)[0][2]


def do_backup(to_drive, dry=False, with_videos=False):
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    dst = os.path.join(to_drive, f'DMR备份-{stamp}')

    try:
        free = shutil.disk_usage(to_drive).free
    except OSError as e:
        print(f'  ❌ 目标盘不可用: {to_drive} ({e})')
        return 1

    print('=' * 78)
    print(f'异盘备份 -> {dst}')
    print('=' * 78)
    print(f'  源目录      : {PROJ}')
    print(f'  目标盘剩余  : {human(free)}')

    extra = [] if with_videos else [VIDEO_DIR]
    need = dir_size(PROJ)
    if not with_videos:
        vd = os.path.join(PROJ, VIDEO_DIR)
        if os.path.isdir(vd):
            need -= dir_size(vd)
    print(f'  需要空间    : 约 {human(need)}')
    print(f'  包含视频    : {"是" if with_videos else "否（加 --with-videos 一起备份）"}')

    if need > free * 0.95:
        print('  ❌ 空间不足，中止')
        return 1
    if dry:
        print('\n  DRY-RUN：以上是计划，未实际复制。')
        return 0

    os.makedirs(dst, exist_ok=True)
    print(f'\n  复制 {NAME} ... ', end='', flush=True)
    ok, rc = robocopy(PROJ, os.path.join(dst, NAME), extra)
    got = count_files(os.path.join(dst, NAME))
    print(f'{"✅" if ok else "❌"} rc={rc}  {got} 个文件')

    verify(dst, expect_videos=with_videos)
    print(f'\n  完成: {dst}')
    print(f'  总大小: {human(dir_size(dst))} / {count_files(dst)} 个文件')
    return 0


def verify(root, expect_videos=True):
    """校验关键文件是否都在（相对路径，不假设目录名）。"""
    print()
    print('=' * 78)
    print('校验关键文件')
    print('=' * 78)
    base = os.path.join(root, NAME)
    checks = [
        (r'configs\global.yml', '全局配置'),
        (r'configs', '任务配置目录'),
        (r'main.py', '入口'),
        (r'DMR\Task\liveevents.py', '核心事件表'),
        (r'DMR\paths.py', '路径层'),
        (r'logs\dmr_state.db', '状态库'),
        (r'README.md', '交接文档'),
    ]
    if os.path.basename(sys.executable).lower().startswith('python'):
        checks.append((r'tools\biliup.exe', '上传工具（可选）'))
    checks.append((r'.git', 'git 完整历史'))

    bad = 0
    for rel, desc in checks:
        ok = os.path.exists(os.path.join(base, rel))
        if not ok:
            bad += 1
        print(f'  {"✅" if ok else "❌"} {desc:<20} {rel}')

    # 任务配置数量
    def n_cfg(p):
        return len([f for f in os.listdir(p)
                    if f.startswith('DMR-') and f.endswith('.yml')]) \
            if os.path.isdir(p) else 0

    n, src_n = n_cfg(os.path.join(base, 'configs')), n_cfg(os.path.join(PROJ, 'configs'))
    flag = '✅' if n == src_n else '❌'
    if n != src_n:
        bad += 1
    print(f'  {flag} {"任务配置":<20} {n}/{src_n} 个')

    print()
    print(f'  {"✅ 校验通过" if bad == 0 else f"❌ {bad} 项不通过"}')
    return bad


def main():
    ap = argparse.ArgumentParser(description='把整个项目备份到另一个磁盘')
    ap.add_argument('--to', default=None, help='目标盘符，如 D:（默认自动挑选）')
    ap.add_argument('--dry-run', action='store_true', help='只显示计划')
    ap.add_argument('--with-videos', action='store_true', help='连录制视频一起备份')
    ap.add_argument('--check', default=None, help='校验某个已有备份目录')
    args = ap.parse_args()

    if args.check:
        print(f'校验 {args.check}')
        return 0 if verify(args.check) == 0 else 1

    target = args.to or pick_drive()
    if not target:
        print('  ❌ 找不到可用的备份盘。请插一块移动硬盘，或用 --to X: 指定。')
        return 1
    return do_backup(target, dry=args.dry_run, with_videos=args.with_videos)


if __name__ == '__main__':
    sys.exit(main())
