# -*- coding: utf-8 -*-
"""把「[正在录制]」孤儿分段登记进状态库，让 DMR 下次启动自动接管。

为什么需要
--------
录制进程被硬杀（或异常退出）时，ffmpeg 来不及收尾，最后一个分段会永远停留在
``[正在录制]<任务>-<时间>-Part%03d.ts`` 这个中间名上 —— ``segment_callback``
没跑，状态库里也没有对应记录。于是这些文件就成了"没人管"的孤儿：内容通常是
完整的，但 DMR 既不渲染也不上传。

而 DMR 的 reconciler 其实**有能力**处理它们：
``liveevents.py::_promote_intermediate_name()`` 会把 ``[正在录制]`` 中间名
按 ``output_name`` 模板改成正式名，然后 ``_dispatch_pending_renders()``
补派渲染，渲染完自动走上传。前提只是**状态库里得有一条记录**。

本工具做的就是补这条记录，不改磁盘文件（改名交给 reconciler，
与正常流程完全一致）。

安全措施
--------
1. 默认只预览，``--apply`` 才写库。
2. 写库前自动备份 .db 到 logs/dmr_state.db.bak-<时间戳>。
3. **DMR 在运行时拒绝写库**（SQLite 并发写会锁），除非 ``--force``。
4. 只插入，不更新、不删除任何已有行。
5. 没有对应 .ass 的分段不登记（渲染必须有弹幕文件），只报告。

用法
----
    .venv\\Scripts\\python.exe tools\\rename_orphans.py            # 预览
    .venv\\Scripts\\python.exe tools\\rename_orphans.py --apply   # 登记
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
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
REPLAY = os.path.join(UP, '直播回放')

# [正在录制]君君-20261101-165017-Part000.ts
# → task=君君, ts=2026-11-01 16:50:17, part=0
NAME_RE = re.compile(
    r'^\[正在录制\](?P<task>.+?)-(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})'
    r'-(?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})-Part(?P<part>\d+)\.ts$')


def parse_name(fname):
    m = NAME_RE.match(fname)
    if not m:
        return None
    g = m.groupdict()
    ts = int(time.mktime((int(g['y']), int(g['mo']), int(g['d']),
                          int(g['h']), int(g['mi']), int(g['s']),
                          0, 0, -1)))
    return {'task': g['task'], 'ts': ts, 'part': int(g['part']),
            'label': '%s-%s年%s月%s日%s点%s分' % (g['task'], g['y'], g['mo'],
                                              g['d'], g['h'], g['mi'])}


def dmr_running():
    """DMR 主进程是否在跑（写库前必须确认）。"""
    try:
        import psutil
    except ImportError:
        return None          # 不知道，让调用方决定
    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            if (p.info['name'] or '').lower() != 'python.exe':
                continue
            if any('main.py' in (a or '') for a in (p.info['cmdline'] or [])):
                return True
        except Exception:
            continue
    return False


# 文件多久没被写入才算"孤儿"。正在录的分段每秒都在写，
# 误登记它会和 ffmpeg 抢同一个文件（reconciler 改名时 ffmpeg 还在追加）。
ORPHAN_IDLE_SEC = 600          # 10 分钟


def scan():
    """扫出所有 [正在录制]*.ts，返回 (可登记, 缺弹幕) 两个列表。

    注意：不能用 glob —— ``[正在录制]`` 里的方括号是 glob 的字符类语法，
    会被当成通配符，结果一个都匹配不到（2026-10-20 踩过）。
    """
    ok, no_dm = [], []
    now = time.time()
    for room in sorted(os.listdir(REPLAY)):
        rdir = os.path.join(REPLAY, room)
        if not os.path.isdir(rdir):
            continue
        for fname in sorted(os.listdir(rdir)):
            if not (fname.startswith('[正在录制]') and fname.endswith('.ts')):
                continue
            path = os.path.join(rdir, fname)
            idle = now - os.path.getmtime(path)
            if idle < ORPHAN_IDLE_SEC:
                print(f'  - 跳过（{idle:.0f}s 前还在写，正在录制中）: {fname}')
                continue
            info = parse_name(fname)
            if not info:
                print(f'  ? 名字解析不了，跳过：{fname}')
                continue
            info['path'] = path
            info['size'] = os.path.getsize(path)
            if os.path.isfile(path[:-3] + '.ass'):
                info['ass'] = path[:-3] + '.ass'
                ok.append(info)
            else:
                no_dm.append(info)
    return ok, no_dm


def backup():
    stamp = time.strftime('%Y%m%d-%H%M%S')
    dst = os.path.join(UP, 'logs', f'dmr_state.db.bak-{stamp}')
    shutil.copy2(DB, dst)
    return dst


def register(conn, items):
    """把孤儿分段写进 sessions/artifacts。

    用确定性 ID（内容哈希），重复跑不会产生重复行 —— upsert 语义。
    """
    cur = conn.cursor()
    now = int(time.time())
    written = 0
    for it in items:
        digest = hashlib.sha1(
            it['path'].encode('utf-8')).hexdigest()[:12]
        session_id = f'orphan-{digest}'
        artifact_id = f'orphan-{digest}-1'

        cur.execute(
            'INSERT OR IGNORE INTO sessions(session_id, taskname, group_id,'
            ' platform, room_id, room_url, streamer_name, streamer_uid,'
            ' title, started_at, ended_at, updated_at)'
            " VALUES(?,?,NULL,NULL,NULL,NULL,?,NULL,NULL,?,?,?)",
            (session_id, it['task'], it['task'], it['ts'], it['ts'], now))

        payload = json.dumps({
            'path': it['path'],
            'danmaku_path': it['ass'],
            'size': it['size'],
            'origin': 'rename_orphans',
        }, ensure_ascii=False)
        cur.execute(
            'INSERT OR IGNORE INTO artifacts(artifact_id, session_id,'
            ' segment_idx, kind, state, updated_at, data)'
            " VALUES(?,?,?,?,?,?,?)",
            (artifact_id, session_id, 1, 'src_video', 'recorded', now,
             payload))
        written += 1
    conn.commit()
    return written


def main():
    ap = argparse.ArgumentParser(description='登记 [正在录制] 孤儿分段')
    ap.add_argument('--apply', action='store_true', help='真写库（默认只预览）')
    ap.add_argument('--force', action='store_true',
                    help='DMR 运行中也强制写库（不建议）')
    args = ap.parse_args()

    if not os.path.isfile(DB):
        print(f'找不到状态库: {DB}')
        return 1

    print('扫描 [正在录制] 孤儿分段 ...')
    ok, no_dm = scan()

    print(f'\n可登记（有对应 .ass， reconciler 会改名+渲染+上传）: {len(ok)} 个')
    for it in ok:
        print('   %8.1f MB  %s' % (it['size'] / 1048576,
                                   os.path.basename(it['path'])))
    if no_dm:
        print(f'\n缺 .ass（无法渲染，只报告不动）: {len(no_dm)} 个')
        for it in no_dm:
            print('   %8.1f MB  %s' % (it['size'] / 1048576,
                                       os.path.basename(it['path'])))
    if not ok and not no_dm:
        print('   没有孤儿文件，干净。')

    if not ok:
        return 0

    if not args.apply:
        print('\n预览结束。加 --apply 才会写库。')
        return 0

    running = dmr_running()
    if running and not args.force:
        print('\n❌ DMR 正在运行，写库会与它冲突。')
        print('   请先用 DMR-停止.bat 停掉 DMR，再跑本工具；')
        print('   确认要坚持（了解风险）就加 --force。')
        return 1

    dst = backup()
    print(f'\n已备份状态库: {os.path.basename(dst)}')

    conn = sqlite3.connect(DB)
    try:
        n = register(conn, ok)
    finally:
        conn.close()
    print(f'✅ 已登记 {n} 个孤儿分段。下次 DMR 启动时 reconciler 会')
    print('   自动改名、补派渲染，渲染完成接着上传。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
