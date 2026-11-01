# -*- coding: utf-8 -*-
"""把生产环境最新的 配置 / 状态 同步进"完整副本"分支并提交。

为什么单独一个工具
----------------
完整副本（私有仓库 DanmakuRepo-Full 的 main）里除了代码，还有三样**运行时**
东西：``configs/``、``.temp/`` 的几个 json、``logs/dmr_state.db``。
代码变了要同步，配置加了主播、状态库推进了，也应该同步 —— 但手工
"复制→git add→commit→push" 四步太容易漏，所以固化成这个工具。

安全性
------
* ``logs/dmr_state.db`` 用 sqlite 的在线备份 API 复制，**不是**文件拷贝 ——
  DMR 正在写这个库，直接 cp 可能拿到半页状态，备份 API 出来的是一致的快照。
* 只动 ``F:/DanmakuRepo-full`` 这个 worktree，生产目录只读。
* 刻意不同步：直播回放(89G)、.venv(170M)、__pycache__、.trash、其余日志。

用法
----
    .venv\\Scripts\\python.exe tools\\sync_full_backup.py           # 同步+提交
    .venv\\Scripts\\python.exe tools\\sync_full_backup.py --quiet   # 只在有提交时输出
配合桌面 ``DMR-更新完整副本.bat`` 使用（那个负责 push）。
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

PROD = _PROJECT_ROOT
WT = _PROJECT_ROOT + '-full'

# 需要同步的 .temp 文件（其余是历史日志/看门狗中间态，不进副本）
TEMP_FILES = ['failed_renders.json', 'baidu_cooldown.json',
              'cd2_watchdog_state.json']
# 需要同步的 logs 文件
LOG_FILES = ['pending_clean.json']


def _run(args, cwd=WT):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def sync_configs():
    src = os.path.join(PROD, 'configs')
    dst = os.path.join(WT, 'configs')
    if not os.path.isdir(src):
        print('  ! configs 不存在，跳过')
        return
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    n = sum(len(f) for _, _, f in os.walk(dst))
    print('  configs/        %d 个文件' % n)


def sync_temp():
    for name in TEMP_FILES:
        s = os.path.join(PROD, '.temp', name)
        d = os.path.join(WT, '.temp', name)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if os.path.exists(s):
            shutil.copy2(s, d)
            print('  .temp/%-26s %d 字节' % (name, os.path.getsize(d)))


def sync_state_db():
    """用 sqlite 在线备份 API 复制状态库，保证快照一致。"""
    src = os.path.join(PROD, 'logs', 'dmr_state.db')
    dst = os.path.join(WT, 'logs', 'dmr_state.db')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(src):
        print('  ! logs/dmr_state.db 不存在，跳过')
        return
    sconn = sqlite3.connect('file:%s?mode=ro' % src, uri=True)
    try:
        dconn = sqlite3.connect(dst)
        try:
            sconn.backup(dconn)
        finally:
            dconn.close()
    finally:
        sconn.close()
    print('  logs/dmr_state.db   %d 字节（在线备份，快照一致）'
          % os.path.getsize(dst))


def sync_logs():
    for name in LOG_FILES:
        s = os.path.join(PROD, 'logs', name)
        d = os.path.join(WT, 'logs', name)
        if os.path.exists(s):
            shutil.copy2(s, d)
            print('  logs/%-24s %d 字节' % (name, os.path.getsize(d)))


def main():
    ap = argparse.ArgumentParser(description='同步生产配置/状态到完整副本分支')
    ap.add_argument('--quiet', action='store_true', help='只在有提交时输出')
    args = ap.parse_args()

    if not os.path.isdir(WT):
        print('找不到完整副本 worktree: %s' % WT)
        print('请先按文档建好 full-backup 分支的 worktree。')
        return 1

    if not args.quiet:
        print('同步生产环境 → 完整副本 worktree')

    sync_configs()
    sync_temp()
    sync_state_db()
    sync_logs()

    r = _run(['git', 'add', '-A'])
    if r.returncode != 0:
        print('git add 失败:', r.stderr[:300])
        return 1

    st = _run(['git', 'status', '--porcelain'])
    if not st.stdout.strip():
        print('没有变化，无需提交。')
        return 0

    ts = time.strftime('%Y-%m-%d %H:%M')
    msg = ('完整副本快照 %s\n\n'
           '同步内容：configs/（全局配置 + 全部任务，含停用归档）、\n'
           '.temp/（重渲染队列等）、logs/dmr_state.db（状态库，在线备份）、\n'
           'logs/pending_clean.json（48 小时延迟删除清单）。\n'
           '代码本身若无改动则不在本提交内。' % ts)
    c = _run(['git', 'commit', '-m', msg])
    if c.returncode != 0:
        print('git commit 失败:', (c.stderr or c.stdout)[:400])
        return 1

    changed = [l[3:] for l in st.stdout.splitlines() if l.strip()]
    print('已提交快照 %s（%d 个文件有变化）' % (ts, len(changed)))
    for f in changed[:12]:
        print('   ~', f)
    if len(changed) > 12:
        print('   … 其余 %d 个' % (len(changed) - 12))
    print()
    print('现在可以推送了（桌面 DMR-更新完整副本.bat 会做这一步）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
