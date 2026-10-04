"""把魔改版的代码修复同步到生产环境（原版）。

原则：
  - 只同步「代码」和 DMR/Config/default.yml（新增配置项的默认值）
  - **绝不动** configs/ 目录（里面有你的个人配置和新任务）
  - 同步前把要覆盖的文件全部备份到 .backup-sync-<时间戳>/

用法：
    python tools\sync_to_production.py --dry-run    # 只看会改什么
    python tools\sync_to_production.py              # 实际同步
"""
import argparse
import filecmp
import os
import shutil
import time

SRC = r'F:\DanmakuRender-魔改版'
DST = r'F:\123Pan_DanmakuRender'

# 要同步的文件（相对路径）—— 全是代码/文档，不含个人配置
SYNC_FILES = [
    # 核心修复
    'DMR/Config/__init__.py',            # target 自动推断 + upload_args_task_default
    'DMR/Config/default.yml',            # 新增默认值（会被 global.yml 覆盖）
    'DMR/Downloader/stream_downloader.py',  # GetStreamURL 返回 None 的可读报错
    'DMR/Render/dmrender.py',            # GOP 按帧率 + 编码参数校验
    'DMR/Task/liveevents.py',            # 清理与上传解耦 + 跳过上传规则
    'DMR/Uploader/__init__.py',          # 移除 youtubev3
    'DMR/Uploader/subprocess_uploader.py',  # 上传失败可读原因
    'DMR/utils/ffprobe.py',              # get_fps()
    'DMR/utils/utils.py',                # evaluate_upload_skip_rule()
    # 删除文件
]
DELETE_FILES = [
    'DMR/Uploader/youtubev3.py',         # 依赖缺失且已用 rclone 替代
]

# 新增的文件/目录（整体拷贝）
SYNC_TREES = [
    'tools',      # 各种自检/分析脚本
    'docs',       # log_error_report.md / engine_comparison.md
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    opt = ap.parse_args()

    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup_root = os.path.join(DST, f'.backup-sync-{stamp}')

    print(f'源: {SRC}')
    print(f'目标: {DST}')
    print(f'备份目录: {backup_root}')
    print(f'模式: {"DRY-RUN（不写任何文件）" if opt.dry_run else "实际同步"}')
    print()

    to_copy = []
    for rel in SYNC_FILES:
        s, d = os.path.join(SRC, rel), os.path.join(DST, rel)
        if not os.path.exists(s):
            print(f'  [跳过] 源不存在: {rel}')
            continue
        if os.path.exists(d) and filecmp.cmp(s, d, shallow=False):
            print(f'  [相同] {rel}')
            continue
        to_copy.append(rel)
        print(f'  [同步] {rel}')

    # tools / docs 里的新增文件
    tree_files = []
    for tree in SYNC_TREES:
        sdir = os.path.join(SRC, tree)
        for dirpath, dirnames, filenames in os.walk(sdir):
            dirnames[:] = [x for x in dirnames if x != '__pycache__']
            for fn in filenames:
                sp = os.path.join(dirpath, fn)
                rel = os.path.relpath(sp, SRC)
                dp = os.path.join(DST, rel)
                if not os.path.exists(dp) or not filecmp.cmp(sp, dp, shallow=False):
                    tree_files.append(rel)
    print()
    for rel in tree_files:
        exists = os.path.exists(os.path.join(DST, rel))
        print(f'  [{"更新" if exists else "新增"}] {rel}')

    print()
    for rel in DELETE_FILES:
        d = os.path.join(DST, rel)
        if os.path.exists(d):
            print(f'  [删除] {rel}')
        else:
            print(f'  [已无] {rel}')

    if opt.dry_run:
        print('\nDRY-RUN 结束，未写入任何文件。')
        return 0

    # ---- 执行 ----
    print('\n开始备份...')
    backed = 0
    for rel in to_copy + tree_files:
        d = os.path.join(DST, rel)
        if os.path.exists(d):
            b = os.path.join(backup_root, rel)
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(d, b)
            backed += 1
    for rel in DELETE_FILES:
        d = os.path.join(DST, rel)
        if os.path.exists(d):
            b = os.path.join(backup_root, rel)
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(d, b)
            backed += 1
    print(f'  已备份 {backed} 个文件')

    print('开始同步...')
    n = 0
    for rel in to_copy + tree_files:
        s, d = os.path.join(SRC, rel), os.path.join(DST, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        n += 1
    print(f'  已复制 {n} 个文件')

    for rel in DELETE_FILES:
        d = os.path.join(DST, rel)
        if os.path.exists(d):
            os.remove(d)
            print(f'  已删除 {rel}')

    print()
    print('完成。回滚方法：把备份目录里的文件拷回原位即可。')
    print(f'备份位置: {backup_root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
