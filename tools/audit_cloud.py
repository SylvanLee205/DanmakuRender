"""云端上传审计：找出"本地有、云端无"的文件（检测静默丢失）。

为什么要这个工具
----------------
2026-10-05 发现：文件名含 emoji 时，百度网盘开放平台 API 返回 `errno -7`，
但 CD2 WebDAV 收到 PUT 先回 2xx（落暂存、异步上传），导致
**rclone 退出码为 0、DMR 误判成功 → 文件静默丢失**。
更坑的是 CD2 WebDAV 会把上传失败的文件也列出来（幻影条目），
所以 `rclone lsf` / 挂载盘验证会**假阳性**。

唯一可靠的判断方式：对比**本地文件清单**和**云端真实条目**。

判据的设计
----------
不同任务开始上传到 cd2 的时间不同，所以不能写死一个日期。
本工具按任务分别计算：
    该任务云端最早文件日期  = 该任务的上传起点
    只把「文件名日期 >= 上传起点」的本地文件算作"应该已上传"
这样既不会漏报，也不会把上传流水线启用之前的历史文件误判为丢失。

用法
----
    python tools\\audit_cloud.py                 # 全部任务，打印报告
    python tools\\audit_cloud.py --task 相扑猫    # 只看一个任务
    python tools\\audit_cloud.py --log audit.log # 同时写日志文件
    python tools\\audit_cloud.py --strict        # 有任何丢失就以退出码 1 结束（给计划任务用）

建议：做成计划任务每月跑一次，或手动在你怀疑有问题时跑。
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLAY = os.path.join(ROOT, '直播回放')
REMOTE_ROOT = 'cd2:百度网盘/DMR录播'
RCLONE_CANDIDATES = [
    r'C:\User Program Files\rclone-v1.75.1\rclone.exe',
    r'C:\User Program Files\rclone-v1.75.0\rclone.exe',
    'rclone',
]

# 复用上传层的清洗逻辑，保证"审计判断"和"实际上传"用的是同一套规则。
# 否则含 emoji 的文件（上传时被改名）会被永远误报为丢失。
try:
    sys.path.insert(0, ROOT)
    from DMR.Uploader.subprocess_uploader import safe_remote_name
except Exception:
    def safe_remote_name(name):
        return name


def find_rclone():
    for c in RCLONE_CANDIDATES:
        if c == 'rclone' or os.path.exists(c):
            return c
    return 'rclone'


def find_cd2_cache():
    """找 CD2 的 dir_cache.sqlite（云端真实条目的唯一可信来源）。

    两个可能的安装位置：
      新应用版: %LOCALAPPDATA%\\CloudDrive.WinUI\\dir_cache.sqlite
      旧服务版: C:\\Windows\\System32\\config\\systemprofile\\Waytech\\CloudDrive2\\dir_cache.sqlite
    优先用正在运行的那个（看 29798/19798 端口）。
    """
    cands = [
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'CloudDrive.WinUI', 'dir_cache.sqlite'),
        r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\dir_cache.sqlite',
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def date_of(name):
    """从文件名里取日期，支持 YYYY年MM月DD日。"""
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', name)
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


def has_emoji(s):
    return any(ord(c) > 0xFFFF for c in s)


def main():
    ap = argparse.ArgumentParser(description='本地/云端上传审计')
    ap.add_argument('--task', default=None, help='只审计指定任务')
    ap.add_argument('--log', default=None, help='同时把报告写入日志文件')
    ap.add_argument('--verbose', action='store_true',
                    help='显示改名上传的文件（含 emoji 的）')
    ap.add_argument('--strict', action='store_true',
                    help='有丢失时以退出码 1 结束（方便计划任务判断）')
    opt = ap.parse_args()

    # Windows 下 stdout 重定向到文件时默认用 GBK，会把中文写成乱码。
    # 强制 UTF-8，保证计划任务的日志可读。
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    lines = []

    def out(msg=''):
        print(msg, flush=True)
        lines.append(msg)

    rclone = find_rclone()
    out('=' * 78)
    out(f'云端上传审计   {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    out('=' * 78)
    out(f'  项目   : {ROOT}')
    out(f'  云端   : {REMOTE_ROOT}')
    out(f'  rclone : {rclone}')
    out()

    # 拉云端全量清单
    #
    # ⚠️⚠️ 关键：**必须查 CD2 自己的缓存（dir_cache.sqlite），不能用 rclone lsf**。
    # CD2 的 WebDAV 会把「已接收但还没上传成功」的文件也列出来（幻影条目），
    # 所以 rclone lsf 会假阳性 —— 这个坑在 2026-10-05 和 10-06 各踩了一次，
    # 每次都得出"上传成功"的错误结论。
    # CD2 的 files 表才是百度 API 真实返回的内容。
    cloud = {}
    cd2_cache = find_cd2_cache()
    if cd2_cache:
        try:
            import shutil as _sh
            import sqlite3 as _sq
            dst = os.path.join(os.environ.get('TEMP', '.'), 'dmr_audit_cache')
            os.makedirs(dst, exist_ok=True)
            for suffix in ('', '-wal', '-shm'):
                src = cd2_cache + suffix
                if os.path.exists(src):
                    try:
                        _sh.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + suffix))
                    except Exception:
                        pass
            con = _sq.connect(f'file:{os.path.join(dst, "dir_cache.sqlite")}?mode=ro', uri=True)
            cur = con.cursor()
            # cached_item.path 形如 /百度网盘/DMR录播/<任务名>
            cur.execute("SELECT id, path FROM cached_item WHERE path LIKE ?", ('%/DMR录播/%',))
            for did, path in cur.fetchall():
                task = path.rstrip('/').split('/')[-1]
                cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
                cloud.setdefault(task, set()).update(r[0] for r in cur.fetchall())
            con.close()
            out(f'云端清单来源: CD2 缓存（可信）  {os.path.dirname(cd2_cache)}')
        except Exception as e:
            out(f'  !! 读 CD2 缓存失败: {e}，回退到 rclone（可能有幻影）')
            cd2_cache = None
    if not cd2_cache:
        try:
            r = subprocess.run([rclone, 'lsf', REMOTE_ROOT, '-R'],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=900)
            for l in r.stdout.split('\n'):
                l = l.strip()
                if '/' not in l:
                    continue
                task, fn = l.split('/', 1)
                cloud.setdefault(task, set()).add(fn)
            out('  ⚠ 云端清单来源: rclone lsf（**可能含幻影条目，结果仅供参考**）')
        except Exception as e:
            out(f'  !! 读取云端失败: {e}')
            return 2

    out(f'云端共 {len(cloud)} 个任务目录')
    out()

    # 遍历本地任务
    local_tasks = []
    if os.path.isdir(REPLAY):
        for d in sorted(os.listdir(REPLAY)):
            full = os.path.join(REPLAY, d)
            if os.path.isdir(full) and d.endswith('（弹幕版）'):
                local_tasks.append((d[:-len('（弹幕版）')], full))

    if opt.task:
        local_tasks = [x for x in local_tasks if x[0] == opt.task]
        if not local_tasks:
            out(f'  找不到任务 {opt.task}')
            return 2

    total_lost = 0
    total_bytes = 0
    problems = []

    for task, local_dir in local_tasks:
        cloud_files = cloud.get(task, set())
        local_files = [f for f in os.listdir(local_dir) if f.endswith(('.mp4', '.mkv'))]

        # 该任务的上传起点 = 云端最早文件的日期
        cloud_dates = sorted(d for d in (date_of(f) for f in cloud_files) if d)
        if not cloud_dates:
            out(f'  【{task}】云端没有文件 —— 跳过（可能没开上传，或全丢）')
            if local_files:
                out(f'      本地有 {len(local_files)} 个文件，建议人工确认是否该上传')
            out()
            continue
        start = cloud_dates[0]

        expected = [f for f in local_files if (date_of(f) or '') >= start]

        # 上传时远程文件名会被清洗（去掉 emoji），所以判断"云端有没有"时，
        # 要拿**清洗后的名字**去比，否则含 emoji 的文件永远被误报为丢失。
        # 2026-10-05 实例：本地 相扑猫💦-xxx.mp4 → 云端 相扑猫-xxx.mp4
        lost = []
        renamed = []
        for f in expected:
            safe = safe_remote_name(f)
            if safe in cloud_files or f in cloud_files:
                if safe != f:
                    renamed.append((f, safe))
            else:
                lost.append(f)

        # 云端有但本地没有（本地被清理过，正常）
        extra = [f for f in cloud_files if f not in local_files]

        status = '正常' if not lost else f'!! 丢失 {len(lost)} 个'
        if renamed and not lost:
            status += f'（{len(renamed)} 个已改名上传 ok）'
        out(f'  【{task}】上传起点 {start} | 应传 {len(expected)} | '
            f'云端 {len(cloud_files)} | {status}')

        if renamed and (opt.task or opt.verbose):
            for f, safe in renamed:
                out(f'        [改名ok] {f}')
                out(f'              → 云端 {safe}')

        if lost:
            for f in sorted(lost):
                p = os.path.join(local_dir, f)
                mb = os.path.getsize(p) / 1024 / 1024
                total_lost += 1
                total_bytes += os.path.getsize(p)
                tag = '[emoji]' if has_emoji(f) else '[干净 ]'
                out(f'        {tag} {mb:>8.1f} MB  {f}')
                out(f'              期望云端名: {safe_remote_name(f)}')
                problems.append((task, f))
        if extra and opt.task:
            out(f'      （云端有 {len(extra)} 个本地没有的：本地已清理，正常）')
        out()

    out('=' * 78)
    out(f'合计：丢失 {total_lost} 个文件, {total_bytes/1024/1024/1024:.2f} GB')
    if total_lost:
        out()
        out('  处理建议：')
        out('    1) 先看文件名是否含 emoji（[emoji] 标记）—— 那是已知的百度 API 限制，')
        out('       代码已修复（上传时会自动清洗远程名），直接重跑上传即可')
        out('    2) 重传后必须用本工具复查，不要用 rclone lsf（有幻影条目会骗人）')
    out('=' * 78)

    if opt.log:
        try:
            with open(opt.log, 'a', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            print(f'\n报告已追加到 {opt.log}')
        except Exception as e:
            print(f'写日志失败: {e}')

    if opt.strict and total_lost:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
