# -*- coding: utf-8 -*-
"""一条命令把两个仓库都推上去。

两个仓库的分工
--------------
* **公开仓库**（`origin` → DanmakuRepo，分支 `main`）
  代码 + 文档，**脱敏**：不含 configs/、不含状态库、不含内网地址。
  内容 = `master` 的树 + 10 个发布脚手架文件（示例配置、脱敏工具等）。

* **私有仓库**（`full` → DanmakuRepo-Full，分支 `main` = 本地 full-backup）
  完全体：`master` 的全部内容 **加上** `configs/`、`.temp/`、`logs/dmr_state.db`。
  克隆下来放到 `F:\\DanmakuRepo` 就能直接跑，跟生产机一模一样。

用法
----
    python tools/push_all.py             # 预览：只报告会推什么，不动任何东西
    python tools/push_all.py --apply     # 真做：同步、提交、推送两个仓库

前置条件：`master` 工作区干净（先 commit）。否则中止 —— 宁可让你先整理，
也不要推上去半截内容。

两个 worktree（由 `git worktree` 维护，不在生产目录里切分支）：
    F:\\DanmakuRepo-prodsync   公开分支
    F:\\DanmakuRepo-full       私有完整副本
"""
import argparse
import os
import shutil
import subprocess
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

PROD = _PROJECT_ROOT
WT_PUBLIC = _PROJECT_ROOT + '-prodsync'
WT_FULL = _PROJECT_ROOT + '-full'

PUBLIC_BRANCH = 'main'
FULL_BRANCH = 'full-backup'
FULL_REMOTE = 'full'

# 公开仓库**独有**、master 里没有的文件。
# 这些是 v5 基线带过来的发布脚手架和示例配置，同步时绝不能删。
PUBLIC_EXTRAS = {
    'configs/global.example.yml',
    'configs/temp/example-直播录制.yml',
    'configs/temp/example-视频下载.yml',
    'notify_content.txt',
    'notify_title.txt',
    'tools/create_release.py',
    'tools/find_private_info.py',
    'tools/make_example_config.py',
    'tools/mask_private_info.py',
    'tools/redo_release.py',
}


def sh(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if check and r.returncode != 0:
        raise RuntimeError('%s 失败(%d): %s%s'
                           % (' '.join(cmd), r.returncode,
                              (r.stdout or '')[-500:], (r.stderr or '')[-800:]))
    return (r.stdout or '').strip()


def git(cwd, *args, check=True):
    return sh(['git'] + list(args), cwd, check=check)


def master_dirty():
    return bool(git(PROD, 'status', '--porcelain', check=False))


# ---------------------------------------------------------------- 公开仓库
def sync_public(apply):
    """让 main 的树 == master 的树 + PUBLIC_EXTRAS。"""
    print('【公开仓库】%s (%s)' % (WT_PUBLIC, PUBLIC_BRANCH))
    if not os.path.isdir(WT_PUBLIC):
        print('  ! worktree 不存在，跳过')
        return None

    git(WT_PUBLIC, 'checkout', 'master', '--', '.')

    # `git checkout master -- .` 只更新/新增，不删除 master 里已不存在的文件。
    # 这里补上删除，但保留 PUBLIC_EXTRAS。
    master_files = set(git(PROD, 'ls-tree', '-r', '--name-only', 'master').splitlines())
    tracked = [p for p in git(WT_PUBLIC, 'ls-files').splitlines() if p]
    to_delete = [p for p in tracked
                 if p not in master_files and p not in PUBLIC_EXTRAS]
    for p in to_delete:
        fp = os.path.join(WT_PUBLIC, p)
        git(WT_PUBLIC, 'rm', '-q', '--cached', '--', p)
        if os.path.isfile(fp):
            os.remove(fp)
        print('  删除 %s' % p)

    changed = git(WT_PUBLIC, 'status', '--porcelain')
    if not changed:
        print('  无变化')
        return 'nochange'

    subject = git(PROD, 'log', '-1', '--format=%s', 'master')
    print('  待提交 %d 项（提交信息：%s）' % (len(changed.splitlines()), subject))
    if not apply:
        return 'pending'

    git(WT_PUBLIC, 'add', '-A')
    git(WT_PUBLIC, 'commit', '-q', '-m', subject)
    print('  已提交 %s' % git(WT_PUBLIC, 'log', '-1', '--format=%h %s'))
    out = git(WT_PUBLIC, 'push', 'origin',
              '%s:%s' % (PUBLIC_BRANCH, PUBLIC_BRANCH), check=False)
    print('  push: %s' % (out.splitlines()[-1] if out else 'ok'))
    return 'pushed'


# ---------------------------------------------------------------- 私有仓库
def sync_full(apply):
    """让 full 分支 == master + configs/.temp/状态库，并推送。"""
    print()
    print('【私有仓库】%s (%s)' % (WT_FULL, FULL_BRANCH))
    if not os.path.isdir(WT_FULL):
        print('  ! worktree 不存在，跳过')
        return None

    if not git(WT_FULL, 'status', '--porcelain'):
        behind = git(WT_FULL, 'rev-list', '--count', 'HEAD..master')
        if behind != '0':
            print('  落后 master %s 个提交' % behind)
            if apply:
                git(WT_FULL, 'merge', '--no-edit', 'master')
                print('  已合并 master')
        else:
            print('  代码已是最新')

    # 复用 sync_full_backup 的同步函数（configs / .temp / 状态库 / 待删清单）
    sys.path.insert(0, PROD)
    from tools.sync_full_backup import (sync_configs, sync_temp,
                                        sync_state_db, sync_logs)
    if apply:
        sync_configs()
        sync_temp()
        sync_state_db()
        sync_logs()

    changed = git(WT_FULL, 'status', '--porcelain')
    if not changed:
        print('  无变化')
        return 'nochange'

    print('  待提交 %d 项' % len(changed.splitlines()))
    if not apply:
        return 'pending'

    git(WT_FULL, 'add', '-A')
    git(WT_FULL, 'commit', '-q', '-m', '完整副本快照')
    print('  已提交 %s' % git(WT_FULL, 'log', '-1', '--format=%h %s'))
    out = git(WT_FULL, 'push', FULL_REMOTE,
              '%s:main' % FULL_BRANCH, check=False)
    print('  push: %s' % (out.splitlines()[-1] if out else 'ok'))
    return 'pushed'


def main():
    ap = argparse.ArgumentParser(description='同步并推送两个仓库')
    ap.add_argument('--apply', action='store_true', help='真做（默认只预览）')
    args = ap.parse_args()

    if master_dirty():
        print('master 工作区有未提交改动，先处理掉再推：')
        print(git(PROD, 'status', '--short'))
        return 1

    head = git(PROD, 'log', '-1', '--format=%h %s', 'master')
    print('master HEAD: %s' % head)
    print()

    pub = sync_public(args.apply)
    full = sync_full(args.apply)

    print()
    if not args.apply:
        print('预览完成。加 --apply 才会提交并推送。')
        return 0
    print('完成：公开=%s  私有=%s' % (pub, full))
    return 0


if __name__ == '__main__':
    sys.exit(main())
