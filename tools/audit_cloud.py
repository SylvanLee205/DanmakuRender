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
import json
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


def _port_of_rclone_cd2():
    """从 rclone.conf 里读 [cd2] 的 url 端口，判断当前用的是哪个 CD2 实例。"""
    try:
        cfg = os.path.join(os.environ.get('APPDATA', ''), 'rclone', 'rclone.conf')
        txt = open(cfg, encoding='utf-8', errors='replace').read()
        m = re.search(r'^\[cd2\](.*?)(?=^\[|\Z)', txt, re.M | re.S)
        if m:
            m2 = re.search(r'localhost:(\d+)', m.group(1))
            if m2:
                return int(m2.group(1))
    except Exception:
        pass
    return None


def find_cd2_cache():
    """找 CD2 的 dir_cache.sqlite（云端真实条目的唯一可信来源）。

    ⚠️ 关键：必须用**当前真正在跑的那个实例**的缓存。

    两个产品**进程名相同**（都叫 clouddrive.exe）但端口和配置目录不同：
      核心服务版 (19798): C:\\Windows\\System32\\config\\systemprofile\\Waytech\\CloudDrive2\\
      应用版     (29798): %LOCALAPPDATA%\\CloudDrive.WinUI\\

    2026-10-06 踩过这个坑：从应用版切到服务版后，审计仍读应用版的旧缓存，
    得出的"丢失 0 个"是**过期数据**，不可信。
    所以这里以 rclone.conf 的端口为准来选缓存目录。
    """
    svc = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\dir_cache.sqlite'
    app = os.path.join(os.environ.get('LOCALAPPDATA', ''),
                       'CloudDrive.WinUI', 'dir_cache.sqlite')
    port = _port_of_rclone_cd2()
    if port == 19798:
        preferred = [svc, app]
    elif port == 29798:
        preferred = [app, svc]
    else:
        preferred = [svc, app]      # 判断不出时优先服务版
    for c in preferred:
        if os.path.exists(c):
            return c
    return None


def date_of(name):
    """从文件名里取日期，支持 YYYY年MM月DD日。"""
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', name)
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


def has_emoji(s):
    return any(ord(c) > 0xFFFF for c in s)


def load_skip_rule(root):
    """读 DMR 的"跳过上传"规则（render_args.dmrender.skip_upload_rule）。

    规则语义（与 DMR/Task/liveevents.py 保持一致）：
      横屏 且（码率 ≥ skip_bitrate_kbps 或 帧率 ≥ skip_fps）
      命中数 ≥ skip_min_matches  →  不上传
    """
    try:
        import yaml
        p = os.path.join(root, 'configs', 'global.yml')
        g = yaml.safe_load(open(p, encoding='utf-8')) or {}
        r = ((g.get('render_args') or {}).get('dmrender') or {}).get('skip_upload_rule')
        if isinstance(r, dict) and r.get('enabled'):
            return r
    except Exception:
        pass
    return None


def probe_video(path):
    """用 ffprobe 取 宽/高/帧率/码率。失败返回 None。"""
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,r_frame_rate',
             '-show_entries', 'format=duration,bit_rate',
             '-of', 'json', path],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=120)
        if r.returncode != 0:
            return None
        j = json.loads(r.stdout or '{}')
        st = (j.get('streams') or [{}])[0]
        fmt = j.get('format') or {}
        w = st.get('width') or 0
        h = st.get('height') or 0
        fr = st.get('r_frame_rate') or '0/1'
        num, den = (fr.split('/') + ['1'])[:2]
        fps = (float(num) / float(den)) if float(den or 0) else 0.0
        # 优先用 format 的 bit_rate，没有就用 文件大小/时长 估算
        br = fmt.get('bit_rate')
        if br:
            kbps = float(br) / 1000.0
        else:
            dur = float(fmt.get('duration') or 0)
            kbps = (os.path.getsize(path) * 8 / dur / 1000.0) if dur else 0.0
        return {'w': w, 'h': h, 'fps': fps, 'kbps': kbps}
    except Exception:
        return None


def should_skip_upload(path, rule):
    """按规则判断这个文件是否"本该跳过上传"。

    返回 True = 跳过（不该在云端，审计不应报丢失）。
    ffprobe 失败时**返回 False**（保守：宁可报丢失也不漏报）。
    """
    if not rule or not rule.get('enabled'):
        return False
    info = probe_video(path)
    if not info:
        return False
    w, h = info['w'], info['h']
    if not w or not h:
        return False
    landscape = w > h
    if rule.get('skip_require_landscape') and not landscape:
        return False
    hits = 0
    if rule.get('skip_landscape') and landscape:
        hits += 1
    br = rule.get('skip_bitrate_kbps') or 0
    if br and info['kbps'] >= br:
        hits += 1
    fp = rule.get('skip_fps') or 0
    if fp and info['fps'] >= fp:
        hits += 1
    return hits >= (rule.get('skip_min_matches') or 1)


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

            def _read_cache():
                dst = os.path.join(os.environ.get('TEMP', '.'), 'dmr_audit_cache')
                os.makedirs(dst, exist_ok=True)
                for suffix in ('', '-wal', '-shm'):
                    src = cd2_cache + suffix
                    if os.path.exists(src):
                        try:
                            _sh.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + suffix))
                        except Exception:
                            pass
                out2 = {}
                con = _sq.connect(f'file:{os.path.join(dst, "dir_cache.sqlite")}?mode=ro',
                                  uri=True)
                cur = con.cursor()
                cur.execute("SELECT id, path FROM cached_item WHERE path LIKE ?",
                            ('%/DMR录播/%',))
                for did, path in cur.fetchall():
                    task = path.rstrip('/').split('/')[-1]
                    cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
                    out2.setdefault(task, set()).update(r[0] for r in cur.fetchall())
                con.close()
                return out2

            cloud = _read_cache()
            # ⚠️ 关键：缓存可能是**冷的**（CD2 刚启动/刚切换实例时，
            # 目录缓存还没建立）。这时只读缓存会得出"云端什么都没有"的
            # 错误结论。所以先跑一次 rclone -R 枚举云端，让 CD2 建立缓存，
            # 再读一次。
            if not cloud or len(cloud) < 3:
                out(f'  （CD2 缓存是冷的：{len(cloud)} 个目录，'
                    f'先枚举云端预热缓存…）')
                subprocess.run([rclone, 'lsf', REMOTE_ROOT, '-R'],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=1800)
                time.sleep(3)
                cloud2 = _read_cache()
                if len(cloud2) > len(cloud):
                    cloud = cloud2
                    out(f'  （预热后：{len(cloud)} 个目录）')

            out(f'云端清单来源: CD2 缓存（可信）  {os.path.dirname(cd2_cache)}')
            if not cloud:
                out('  ⚠ 缓存仍然为空 —— 检查 CD2 是否在运行、'
                    'rclone 是否指向正确的端口（服务版 19798 / 应用版 29798）')
        except Exception as e:
            out(f'  !! 读 CD2 缓存失败: {e}，回退到 rclone（可能有幻影）')
            cd2_cache = None
    if not cd2_cache:
        try:
            r = subprocess.run([rclone, 'lsf', REMOTE_ROOT, '-R'],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=1800)
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

    # 读"跳过上传"规则（这些文件本就不该在云端，审计要排除它们）
    skip_rule = load_skip_rule(ROOT)
    if skip_rule:
        out(f'跳过上传规则（已启用，审计会排除命中的文件）:')
        out(f'    横屏={skip_rule.get("skip_landscape")} '
            f'必须横屏={skip_rule.get("skip_require_landscape")} '
            f'码率≥{skip_rule.get("skip_bitrate_kbps")}kbps '
            f'帧率≥{skip_rule.get("skip_fps")}fps '
            f'命中≥{skip_rule.get("skip_min_matches")}项')
        out()
    else:
        out('跳过上传规则: 未启用')

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

        # ⚠️ 关键：排除**按规则本就该跳过上传**的文件。
        #
        # DMR 有个"跳过上传"规则（render_args.dmrender.skip_upload_rule）：
        #   横屏 且（码率 ≥ N kbps 或 帧率 ≥ N fps）→ 不上传
        # 这类文件**本来就不在云端**，但审计如果不认这个规则，
        # 就会把它们报成"丢失"，造成假告警。
        # 2026-10-06 实例：苏苏没烦恼 有 4 个 1920x1080/45fps/~3200kbps 的文件，
        # 全都命中跳过条件，却被审计报成"丢失 4 个"，我因此白忙一场。
        skipped = []
        if skip_rule and skip_rule.get('enabled'):
            kept = []
            for f in expected:
                if should_skip_upload(os.path.join(local_dir, f), skip_rule):
                    skipped.append(f)
                else:
                    kept.append(f)
            expected = kept

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
        if skipped:
            status += f'（{len(skipped)} 个按规则跳过上传，不计入缺失）'
        out(f'  【{task}】上传起点 {start} | 应传 {len(expected)} | '
            f'云端 {len(cloud_files)} | {status}')

        if skipped:
            for f in skipped:
                out(f'        [跳过] {f}  ← 命中跳过上传规则，本就不该上传')

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
