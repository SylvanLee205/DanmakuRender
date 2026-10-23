# -*- coding: utf-8 -*-
"""清理「命中跳过上传规则 → 源视频永远不被清理」的历史积压。

背景（2026-10-23）
----------------
`liveevents._check_for_clean()` 只在两个地方被调用：`onUploadEnd()` 和
`onTaskError()`。而命中 skip_upload_rule（横屏 / 高码率 / 高帧率）的分段
**根本不会产生任何上传事件** —— 于是它永远进不了清理判定，源视频无限累积。
实盘实测积压 42.9 GB，其中断尾人类一个房间就 41 GB。

代码侧已修（_check_for_upload 末尾补调 _check_for_clean、闸门补认 'skipped'），
但**已经躺在磁盘上的存量不会被自动回头处理**（SKIPPED 不在 RESUMABLE_STATES，
重启后它们不会被重新驱动）。所以要有这个一次性工具，且可重复运行：

    跑一次清掉已过后悔期的 -> 过几天再跑，新到期的又会被清掉

安全约束（三条，違反即跳过）
--------------------------
1. 只删 **src_video** 和它的 .ass；**弹幕版 mp4 永不删除**（用户硬性要求）。
2. 必须有对应的弹幕版存在且非空 —— 否则源视频是唯一副本。
3. 默认要求源文件已存在 >= 48 小时（与 clean_args 的 delay 一致，留后悔期）。

用法
----
    .venv\\Scripts\\python.exe tools\\clean_skipped_backlog.py            # 只预览
    .venv\\Scripts\\python.exe tools\\clean_skipped_backlog.py --apply    # 真的删
    .venv\\Scripts\\python.exe tools\\clean_skipped_backlog.py --min-age-hours 24
"""
import argparse
import json
import os
import sqlite3
import sys
import time

try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

UP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(UP, 'logs', 'dmr_state.db')

# 内存里叫 upload_skipped，状态库里落盘成 skipped —— 两个都要认
SKIP_STATES = ('skipped', 'upload_skipped')
SRC_STATES = ('recorded',)


def load_pairs():
    """找出 (src 还没清) 且 (dm_video 已跳过上传) 的分段。"""
    if not os.path.exists(DB):
        print('找不到状态库:', DB)
        return []
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "select session_id, segment_idx, kind, state, data from artifacts"
    ).fetchall()
    conn.close()

    seg = {}
    for sid, idx, kind, state, data in rows:
        try:
            d = json.loads(data) if data else {}
        except Exception:
            d = {}
        seg.setdefault((sid, idx), {})[kind] = (state, d)

    out = []
    for key, kv in seg.items():
        sv = kv.get('src_video')
        dv = kv.get('dm_video')
        if not sv or not dv:
            continue
        if sv[0] not in SRC_STATES:
            continue
        if dv[0] not in SKIP_STATES:
            continue
        out.append((key, sv, dv))
    return out


def abspath(p):
    if not p:
        return None
    p = p.replace('/', os.sep).replace('\\', os.sep)
    if p.startswith('.' + os.sep):
        p = p[2:]
    return os.path.normpath(os.path.join(UP, p))


def main():
    ap = argparse.ArgumentParser(
        description='清理命中跳过上传规则后遗留的源视频（弹幕版永不删）')
    ap.add_argument('--apply', action='store_true',
                    help='真的删除；不加则只预览')
    ap.add_argument('--min-age-hours', type=float, default=48.0,
                    help='源文件至少要存在这么久（默认 48 小时，与 clean_args 一致）')
    args = ap.parse_args()

    pairs = load_pairs()
    now = time.time()
    todo, skipped = [], []

    print()
    print('命中「跳过上传」且源视频仍在磁盘的分段: %d 个' % len(pairs))
    print('%-10s %-26s %10s  %s' % ('房间', '文件', '大小', '状态'))
    print('-' * 92)

    for (sid, idx), sv, dv in sorted(pairs, key=lambda x: x[0]):
        src = abspath(sv[1].get('path'))
        dm = abspath(dv[1].get('path'))
        name = os.path.basename(src or '?')
        room = os.path.basename(os.path.dirname(src)) if src else '?'

        if not src or not os.path.exists(src):
            skipped.append((room, name, '源文件已不在磁盘'))
            continue
        size = os.path.getsize(src)
        age_h = (now - os.stat(src).st_mtime) / 3600.0

        if not dm or not os.path.exists(dm) or os.path.getsize(dm) == 0:
            skipped.append((room, name, '弹幕版缺失或为空 -> 源是唯一副本，保留'))
            continue
        if age_h < args.min_age_hours:
            skipped.append((room, name, '仅 %.0f 小时，未过 %.0f 小时后悔期'
                            % (age_h, args.min_age_hours)))
            continue
        todo.append((sid, idx, src, dm, size, room))
        print('  %-10s %-30s %8.0f MB  %s'
              % (room[:10], name[:30], size / 1048576,
                 '可删（弹幕版 %.0f MB 在）' % (os.path.getsize(dm) / 1048576)))

    for room, name, why in skipped:
        print('  %-10s %-30s %8s  %s' % (room[:10], name[:30], '-', why))

    total = sum(t[4] for t in todo)
    print('-' * 92)
    print('可删除 %d 个源视频，共 %.2f GB' % (len(todo), total / 1073741824))
    print('（弹幕版 mp4 一个都不删；源弹幕 .ass 会随源视频一起删）')

    if not args.apply:
        print()
        print('这是预览。确认无误后加 --apply 才会真的删除。')
        return 0
    if not todo:
        print()
        print('没有需要删除的文件。')
        return 0

    print()
    deleted = 0
    freed = 0
    conn = sqlite3.connect(DB)
    for sid, idx, src, dm, size, room in todo:
        ass = os.path.splitext(src)[0] + '.ass'
        try:
            os.remove(src)
            freed += size
            deleted += 1
            print('  已删源视频 %s' % os.path.basename(src))
        except Exception as e:
            print('  删除失败 %s: %s' % (os.path.basename(src), e))
            continue
        if os.path.exists(ass):
            try:
                os.remove(ass)
                print('  已删源弹幕 %s' % os.path.basename(ass))
            except Exception as e:
                print('  源弹幕删除失败（不影响）: %s' % e)
        try:
            conn.execute("update artifacts set state='cleaned', updated_at=? "
                         "where session_id=? and segment_idx=? and kind='src_video'",
                         (time.time(), sid, idx))
        except Exception as e:
            print('  状态库回写失败（不影响删除）: %s' % e)
    conn.commit()
    conn.close()
    print()
    print('完成：删除 %d 个源视频，释放 %.2f GB' % (deleted, freed / 1073741824))
    return 0


if __name__ == '__main__':
    sys.exit(main())
