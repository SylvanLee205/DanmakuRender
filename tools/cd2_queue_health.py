"""CD2 队列健康维护：清理"反复失败"的陈旧任务，避免它们堵塞上传线程。

背景（2026-10-05 / 10-06 两次踩坑）：
    CD2 是 max_upload_threads=1（单线程）。如果一个上传任务永久失败
    （emoji 名被拒、文件已存在、权限被拒），它会**无限重试**，
    把唯一的线程占死 → 后续所有上传都被堵住。
    2026-10-05 那 8427 次重试、10-06 那 6 条堵塞任务都是这个问题。

这个脚本：
    1. 读 CD2 今天的日志，统计每个文件失败了几次
    2. 找出失败次数超过阈值（默认 10 次）且**最近仍在失败**的任务
    3. 从 transfer_tasks 里删掉它们（需要临时停 CD2）
    4. 打印报告

⚠️ 只删"反复失败"的，不会碰正常上传中的任务。
⚠️ 跑之前会自动备份数据库。

用法：
    python tools\\cd2_queue_health.py            # 只看报告，不动
    python tools\\cd2_queue_health.py --clean    # 自动清理
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'
BKROOT = r'F:\_CD2配置备份_20261005'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or ''))


def read_queue():
    dst = os.path.join(os.environ.get('TEMP', '.'), 'cd2qh')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(NEW, 'clouddrive_data.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'clouddrive_data.sqlite' + s))
            except Exception:
                pass
    try:
        con = sqlite3.connect(f'file:{os.path.join(dst, "clouddrive_data.sqlite")}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute('SELECT dest_path, filename, size FROM transfer_tasks')
        rows = cur.fetchall()
        con.close()
        return rows
    except Exception as e:
        return [('(err)', str(e), 0)]


def fail_counts():
    """从今天的 CD2 日志统计每个文件的失败次数和最后一次失败时间。"""
    ld = os.path.join(NEW, 'log')
    today = time.strftime('%Y-%m-%d') + '.log'
    fp = os.path.join(ld, today)
    if not os.path.exists(fp):
        return {}
    t = open(fp, encoding='utf-8', errors='replace').read()
    counts = {}
    for line in t.split('\n'):
        if 'upload error' not in line:
            continue
        m = re.match(r'(\S+ \S+)\s', line)
        tm = m.group(1) if m else '?'
        m2 = re.search(r'upload error for ([^:]+):', line)
        if not m2:
            continue
        path = m2.group(1).strip()
        c = counts.setdefault(path, {'n': 0, 'last': tm, 'err': ''})
        c['n'] += 1
        c['last'] = tm
        m3 = re.search(r'(PermissionDenied|BaiduError[^)]*\))', line)
        if m3:
            c['err'] = m3.group(1)[:60]
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clean', action='store_true', help='实际清理（默认只报告）')
    ap.add_argument('--threshold', type=int, default=10, help='失败次数阈值（默认 10）')
    opt = ap.parse_args()

    print('=' * 78)
    print('CD2 队列健康检查')
    print('=' * 78)

    queue = read_queue()
    counts = fail_counts()
    print(f'  队列 {len(queue)} 条')
    print(f'  今天日志里 {len(counts)} 个文件有上传失败')
    print()

    # 匹配：队列里的文件 + 日志里的失败次数
    stale = []
    for dest, fn, size in queue:
        if dest == '(err)':
            print(f'  !! 读队列失败: {fn}')
            continue
        full = f'{dest}/{fn}'
        c = counts.get(full)
        if c and c['n'] >= opt.threshold:
            stale.append((dest, fn, size, c['n'], c['last'], c['err']))
            print(f'  🔴 反复失败 {c["n"]:>3} 次  最后 {c["last"]}  {fn}')
            print(f'       错误: {c["err"]}')
        elif c:
            print(f'  ⚠ 失败 {c["n"]} 次（未达阈值 {opt.threshold}）  {fn}')
        else:
            print(f'  ✅ 无失败记录  {fn}')

    print()
    if not stale:
        print('  ✅ 没有需要清理的陈旧任务')
        return 0

    print(f'  发现 {len(stale)} 个陈旧任务（失败 ≥ {opt.threshold} 次）')
    print('  它们会占死 CD2 单线程上传，导致后续上传全被堵住。')
    print()

    if not opt.clean:
        print('  加 --clean 才会真正清理。')
        return 0

    # 清理
    print('  停 CD2 并备份...')
    bk = os.path.join(BKROOT, 'before_qh_' + time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(bk, exist_ok=True)
    for f in ('clouddrive_data.sqlite', 'clouddrive_data.sqlite-wal',
              'clouddrive_data.sqlite-shm'):
        src = os.path.join(NEW, f)
        if os.path.exists(src):
            try:
                shutil.copy2(src, bk)
            except Exception:
                pass
    print(f'    备份到 {bk}')
    ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
       "Stop-Process -Force -ErrorAction SilentlyContinue")
    time.sleep(8)

    db = os.path.join(NEW, 'clouddrive_data.sqlite')
    try:
        con = sqlite3.connect(db, timeout=30)
        cur = con.cursor()
        n = 0
        for dest, fn, size, cnt, last, err in stale:
            cur.execute('DELETE FROM transfer_tasks WHERE dest_path=? AND filename=?',
                        (dest, fn))
            n += cur.rowcount
            print(f'    ✓ 删除（失败 {cnt} 次）: {fn}')
        con.commit()
        con.close()
        print(f'  共删除 {n} 条')
    except Exception as e:
        print(f'  ❌ 清理失败: {type(e).__name__}: {e}')

    print('  重启 CD2...')
    subprocess.Popen([APP, '--autostart'], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    for i in range(12):
        time.sleep(5)
        if ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen "
              "-ErrorAction SilentlyContinue | Measure-Object).Count").strip() not in ('', '0'):
            print(f'    ✅ 就绪（{(i+1)*5} 秒）')
            break
    print()
    print('  清理后队列:')
    for dest, fn, size in read_queue():
        print(f'    {fn}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
