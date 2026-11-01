"""把项目全量备份到另一个磁盘（异盘备份）。

为什么需要：2026-10-19 有 29 个提交因 GitHub 账号被风控而无法推送，
这些工作当时只存在于 F 盘。一旦整机/整盘出问题就没有异地副本。

用法：
    python tools\\backup_to_disk.py                # 默认备份到 D:
    python tools\\backup_to_disk.py --to E:        # 指定盘
    python tools\\backup_to_disk.py --dry-run      # 只看会做什么
    python tools\\backup_to_disk.py --check D:\\DMR备份-xxx   # 校验已有备份
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys

PROD = r'F:\DanmakuRepo'
# NOTE 2026-11-02: this constant used to point at another copy of the
# project (no longer maintained). It now points at this project.
MOD = r'F:\DanmakuRepo'
REL = r'F:\_DMRelease'
SNAP = r'F:\_DMR配置快照'

#: 不备份（可重建，不值得占空间）
EXCLUDE_DIRS = ['.venv', '__pycache__', '.temp', 'node_modules']
#: 生产仓库的 .git 不备份 —— 它的 27 个提交由 _DMRelease 的 bundle 覆盖；
#: 开发仓库的 .git 必须备份 —— 那是 171 个提交的唯一完整副本。
PROD_EXTRA_EXCLUDE = ['.git']


def human(n):
    return f'{n / 1024**2:.1f} MB'


def dir_size(p):
    tot = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            fp = os.path.join(r, f)
            try:
                tot += os.path.getsize(fp)
            except OSError:
                pass
    return tot


def count_files(p):
    return sum(len(fs) for _, _, fs in os.walk(p))


def robocopy(src, dst, extra_exclude=()):
    """用 robocopy（Windows 原生的多线程拷贝，比 shutil 快得多）。"""
    xd = [d for d in EXCLUDE_DIRS] + list(extra_exclude)
    cmd = ['robocopy', src, dst, '/E', '/XD'] + xd + \
          ['/XF', '*.pyc', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2']
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    # robocopy 退出码 0-7 都算成功（0=无变化, 1=有复制, ... 7=有额外文件）
    return r.returncode <= 7, r.returncode


def do_backup(to_drive, dry=False):
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    dst = os.path.join(to_drive, f'DMR备份-{stamp}')

    free = shutil.disk_usage(to_drive).free
    print('=' * 78)
    print(f'异盘备份 -> {dst}')
    print('=' * 78)
    print(f'  目标盘剩余空间: {human(free)}')

    plan = [
        ('AutoUp', PROD, PROD_EXTRA_EXCLUDE, '生产环境（代码+配置+工具+日志+状态库+弹幕版视频）'),
        ('Mod', MOD, (), '开发仓库（含 .git 完整历史）'),
        ('_DMRelease', REL, (), 'Release zip + 可克隆的 git bundle'),
        ('_DMR配置快照', SNAP, (), '配置快照'),
    ]

    need = 0
    for name, src, _, desc in plan:
        if not os.path.isdir(src):
            print(f'  ⚠️ 跳过 {name}：{src} 不存在')
            continue
        sz = dir_size(src)
        need += sz
        print(f'  {name:<14} {human(sz):>12}  {desc}')

    print(f'\n  预计需要 {human(need)}，目标盘剩余 {human(free)}')
    if need > free * 0.95:
        print('  ❌ 空间不足，中止')
        return 1

    if dry:
        print('\n  DRY-RUN：以上是计划，未实际复制。')
        return 0

    os.makedirs(dst, exist_ok=True)
    print()
    for name, src, xd, desc in plan:
        if not os.path.isdir(src):
            continue
        print(f'  复制 {name} ... ', end='', flush=True)
        ok, rc = robocopy(src, os.path.join(dst, name), xd)
        got = count_files(os.path.join(dst, name))
        print(f'{"✅" if ok else "❌"} rc={rc}  {got} 个文件')

    verify(dst)
    print(f'\n  完成: {dst}')
    print(f'  总大小: {human(dir_size(dst))} / {count_files(dst)} 个文件')
    return 0


def verify(root):
    """校验关键文件是否都在。"""
    print()
    print('=' * 78)
    print('校验关键文件')
    print('=' * 78)
    checks = [
        (r'AutoUp\configs\global.yml', '你的私有全局配置'),
        (r'AutoUp\configs', '任务配置目录'),
        (r'AutoUp\main.py', '入口'),
        (r'AutoUp\DMR\Task\liveevents.py', '核心事件表'),
        (r'AutoUp\tools\biliup.exe', '启动必需依赖'),
        (r'AutoUp\logs\dmr_state.db', '状态库'),
        (r'AutoUp\docs\交接文档-完整上下文.md', '交接文档'),
        (r'AutoUp\Start_Render.bat', '启动脚本'),
        (r'Mod\.git', '开发仓库 git 历史'),
        (r'_DMRelease', 'Release / bundle'),
        (r'_DMR配置快照', '配置快照'),
    ]
    bad = 0
    for rel, desc in checks:
        p = os.path.join(root, rel)
        ok = os.path.exists(p)
        if not ok:
            bad += 1
        print(f'  {"✅" if ok else "❌"} {desc:<32} {rel}')

    # 任务配置数量
    cfg_dir = os.path.join(root, 'AutoUp', 'configs')
    n = 0
    if os.path.isdir(cfg_dir):
        n = len([f for f in os.listdir(cfg_dir)
                 if f.startswith('DMR-') and f.endswith('.yml')])
    src_n = 0
    src_cfg = os.path.join(PROD, 'configs')
    if os.path.isdir(src_cfg):
        src_n = len([f for f in os.listdir(src_cfg)
                     if f.startswith('DMR-') and f.endswith('.yml')])
    flag = '✅' if n == src_n else '❌'
    if n != src_n:
        bad += 1
    print(f'  {flag} 任务配置 {"":<26} {n}/{src_n} 个')

    print()
    print(f'  {"✅ 校验通过" if bad == 0 else f"❌ {bad} 项不通过"}')
    return bad


def main():
    ap = argparse.ArgumentParser(description='把项目全量备份到另一个磁盘')
    ap.add_argument('--to', default='D:', help='目标盘符（默认 D:）')
    ap.add_argument('--dry-run', action='store_true', help='只显示计划')
    ap.add_argument('--check', default=None, help='校验某个已有备份目录')
    args = ap.parse_args()

    if args.check:
        print(f'校验 {args.check}')
        return 0 if verify(args.check) == 0 else 1

    return do_backup(args.to, dry=args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
