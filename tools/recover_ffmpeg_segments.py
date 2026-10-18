"""恢复 ffmpeg 引擎崩溃/重启后遗留的 [正在录制]*-PartNNN.<ext> 分段。

与 tools/recover_part.py 的区别
--------------------------------
`recover_part.py` 处理的是 **biliup/streamgears** 产出的
`[正在录制]<主播>-<YYYYMMDDHHMMSS>-<uuid>.flv.part`，需要用 ffprobe
校验、重新封装等"修复"动作。

本脚本处理的是 **ffmpeg 引擎**产出的
`[正在录制]<主播>-<YYYYMMDD-HHMMSS>-PartNNN.<ts|mkv|mp4>`。
ffmpeg 的 segment 封装器是**流式写入**的：

  · 已经写完的 PartNNN 是**完整可用**的文件
  · 崩溃时正在写的那个 PartNNN 是**截断但可播**的（TS 尤其如此 ——
    实测截断到 50% 后 ffprobe 报的时长准确、能完整解码，
    而 FLV 会虚报时长且产生大量解码错误）

所以这里**不需要修复**，只需：
  1. 找到 `[正在录制]*-Part*.<ext>`
  2. 用 ffprobe 确认可读（挡掉 0 字节 / 彻底损坏的）
  3. 按任务的 output_name 模板改名为正式分段名
  4. 把配对的 .ass 也改成对应名字（按 14 位时间戳配对）
  5. 打印出恢复的文件，由调用方（main.py）交给 DMR 流水线

安全约束
--------
· 只处理**最后修改早于 min_age_minutes 分钟**的文件（避免动正在写的）
· ffprobe 不过的不动
· 改名是原子的（os.replace），失败只告警
· 默认 dry-run，--apply 才真改名
· **不删除任何文件**
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from os.path import basename, dirname, exists, join

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULT_MIN_AGE_MINUTES = 2

#: ffmpeg 分段文件名里的时间戳：<name>-YYYYMMDD-HHMMSS-PartNNN.<ext>
_FFMPEG_SEG_RE = re.compile(
    r'^(?P<pre>.*?)-(?P<date>\d{8})-(?P<time>\d{6})-Part(?P<idx>\d+)\.(?P<ext>\w+)$')
#: biliup 的时间戳：<name>-YYYYMMDDHHMMSS-<uuid>.flv.part
_BILIUP_RE = re.compile(r'-(\d{14})-')


def log(msg=''):
    print(msg, flush=True)


def _mklog(logger=None):
    if logger is not None:
        return lambda m='': logger.info(m)
    return log


def ffprobe_ok(path, ffprobe='ffprobe', timeout=60):
    """文件能被 ffprobe 读到视频流就算 OK。返回 (ok, 描述)。"""
    try:
        r = subprocess.run(
            [ffprobe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name,width,height',
             '-show_entries', 'format=format_name,duration',
             '-of', 'json', path],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=timeout)
    except Exception as e:
        return False, f'ffprobe 调用失败: {e}'
    if r.returncode != 0:
        return False, f'ffprobe 退出码 {r.returncode}'
    try:
        j = json.loads(r.stdout or '{}')
    except Exception:
        return False, 'ffprobe 输出不是合法 JSON'
    streams = j.get('streams') or []
    if not streams:
        return False, '没有视频流'
    s = streams[0]
    fmt = (j.get('format') or {}).get('format_name', '?')
    return True, (f'{s.get("codec_name")} {s.get("width")}x{s.get("height")} '
                  f'container={fmt}')


def find_tasks(config_dir):
    """从 configs/DMR-*.yml 读任务名 → 完整配置路径。"""
    out = {}
    for p in glob.glob(join(config_dir, 'DMR-*.yml')):
        name = basename(p)[len('DMR-'):-len('.yml')]
        out[name] = p
    return out


def load_task_output_name(task_cfg_path):
    """读任务配置的 output_name 模板（没有就返回 None）。"""
    try:
        import yaml
        d = yaml.safe_load(open(task_cfg_path, encoding='utf-8')) or {}
        return ((d.get('download_args') or {}).get('output_name')) or None
    except Exception:
        return None


def render_final_name(template, streamer, dt):
    """套用 output_name 模板。失败返回 None。

    支持的关键字（够用即可）：
        {STREAMER.NAME}
        {CTIME.YEAR} {CTIME.MONTH:02d} {CTIME.DAY:02d}
        {CTIME.HOUR:02d} {CTIME.MINUTE:02d} {CTIME.SECOND:02d}
    """
    if not template:
        return None
    try:
        s = template
        s = s.replace('{STREAMER.NAME}', streamer)
        # 处理带 :02d 格式的 CTIME
        def _sub(m):
            key, _, fmt = m.group(1).partition(':')
            # 模板里是大写（YEAR/MONTH/...），datetime 属性是小写
            val = getattr(dt, key.lower(), None)
            if val is None:
                return m.group(0)
            try:
                return format(val, fmt) if fmt else str(val)
            except Exception:
                return str(val)
        s = re.sub(r'\{CTIME\.(\w+(?::[^}]+)?)\}', _sub, s)
        return s
    except Exception:
        return None


def find_danmaku(seg_path, token14):
    """在分段同目录里找配对的 .ass / .xml。

    优先用 14 位时间戳（YYYYMMDDHHMMSS）匹配：
      ffmpeg 分段：...-20261018-231500-Part000.ts  → 20261018231500
      弹幕文件   ：[正在录制]主播-20261018-231500-Part000.ass → 同一 token
    也接受 biliup 风格的 14 位连续数字。
    """
    d = dirname(seg_path)
    cands = []
    for ext in ('.ass', '.xml'):
        # [ 和 ] 在 glob 里是字符类，必须转义
        cands += glob.glob(join(d, '[[]正在录制[]]*' + ext))
        cands += glob.glob(join(d, '*' + ext))
    if not token14:
        return None
    hits = []
    for c in cands:
        digits = ''.join(ch for ch in basename(c) if ch.isdigit())
        if token14 in digits:
            hits.append(c)
    if not hits:
        return None
    # 同时间戳可能有多个（Part000/Part001），取文件名最短的（最可能对应首个分段）
    hits.sort(key=lambda p: (len(basename(p)), p))
    return hits[0]


def scan(cfg, replay_dir=None, min_age_minutes=DEFAULT_MIN_AGE_MINUTES,
         ffprobe='ffprobe', logger=None):
    """扫描并返回待恢复列表。不修改任何文件。

    返回 [{'src','dst','danmaku','task','size','desc','token'}, ...]
    """
    L = _mklog(logger)
    if replay_dir is None:
        replay_dir = cfg.global_config['download_args']['live'].get(
            'output_dir', './直播回放')
    if not os.path.isabs(replay_dir):
        replay_dir = join(ROOT, replay_dir)
    replay_dir = os.path.abspath(replay_dir)
    if not os.path.isdir(replay_dir):
        L(f'  找不到回放目录 {replay_dir}')
        return []

    tasks = find_tasks(join(ROOT, 'configs'))
    # 产出格式（决定扩展名）
    fmts = []
    vf = cfg.global_config['download_args']['live'].get('output_format', 'mkv')
    for f in (vf, 'ts', 'mkv', 'mp4'):
        if f and f not in fmts:
            fmts.append(f)

    found = []
    for ext in fmts:
        pat = join(replay_dir, '**', '[[]正在录制[]]*-Part*.' + ext)
        found += glob.glob(pat, recursive=True)
    # 排除 recover_part 管的 .part
    found = sorted({p for p in found if not p.endswith('.part')})

    out = []
    now = time.time()
    for p in found:
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_size == 0:
            L(f'  跳过（0 字节）: {basename(p)}')
            continue
        age_min = (now - st.st_mtime) / 60
        if age_min < min_age_minutes:
            L(f'  跳过（{age_min:.1f} 分钟前还在写）: {basename(p)}')
            continue
        m = _FFMPEG_SEG_RE.match(basename(p))
        if not m:
            L(f'  跳过（文件名不符合 ffmpeg 分段格式）: {basename(p)}')
            continue
        ok, desc = ffprobe_ok(p, ffprobe)
        if not ok:
            L(f'  跳过（不可读：{desc}）: {basename(p)}')
            continue

        # 任务名：从目录名推断，去掉「（弹幕版）」
        parent = basename(dirname(p))
        task = parent.replace('（弹幕版）', '').replace('(弹幕版)', '')
        if task not in tasks:
            # 退一步：用文件名前缀匹配
            task = next((t for t in tasks if basename(p).startswith('[' + '正在录制' + ']' + t)), None)
        if not task:
            L(f'  跳过（认不出任务）: {basename(p)}')
            continue

        token14 = m.group('date') + m.group('time')
        try:
            dt = datetime.strptime(token14, '%Y%m%d%H%M%S')
        except ValueError:
            dt = datetime.fromtimestamp(st.st_mtime)

        tmpl = load_task_output_name(tasks[task])
        final = render_final_name(tmpl, task, dt) if tmpl else None
        if not final:
            final = dt.strftime('%Y年%m月%d日%H点%M分')
        dst = join(dirname(p), final + '.' + m.group('ext'))
        # 目标已存在则不覆盖（避免吃掉已有分段）
        if exists(dst):
            L(f'  跳过（目标已存在）: {basename(dst)}')
            continue

        dm = find_danmaku(p, token14)
        out.append({
            'src': p, 'dst': dst, 'danmaku': dm, 'task': task,
            'size': st.st_size, 'desc': desc, 'token': token14,
            'part': int(m.group('idx')),
        })
    return out


def apply(items, logger=None, dm_move=True):
    """执行改名。返回 (成功数, 失败列表)。"""
    L = _mklog(logger)
    ok_n = 0
    failed = []
    for it in items:
        try:
            os.replace(it['src'], it['dst'])
            L(f'  ✅ {basename(it["src"])} -> {basename(it["dst"])}')
            if dm_move and it['danmaku'] and exists(it['danmaku']):
                dm_dst = os.path.splitext(it['dst'])[0] + \
                    os.path.splitext(it['danmaku'])[1]
                if not exists(dm_dst):
                    os.replace(it['danmaku'], dm_dst)
                    L(f'       弹幕配对: {basename(dm_dst)}')
                else:
                    L(f'       弹幕目标已存在，跳过: {basename(dm_dst)}')
            elif not it['danmaku']:
                L(f'       ⚠️ 没找到配对弹幕（渲染会失败，请手动确认）')
            ok_n += 1
        except Exception as e:
            L(f'  ❌ {basename(it["src"])}: {type(e).__name__}: {e}')
            failed.append((it['src'], str(e)))
    return ok_n, failed


def recover_all(cfg, min_age_minutes=DEFAULT_MIN_AGE_MINUTES, apply_changes=True,
                logger=None):
    """供 main.py 调用：扫描 + 改名，返回统计。"""
    L = _mklog(logger)
    ffprobe = ((cfg.global_config.get('executable_tools_path') or {})
               .get('ffprobe') or 'ffprobe')
    items = scan(cfg, min_age_minutes=min_age_minutes, ffprobe=ffprobe,
                 logger=logger)
    result = {'scanned': len(items), 'recovered': [], 'failed': []}
    if not items:
        return result
    L('=' * 70)
    L(f'发现 {len(items)} 个 ffmpeg 遗留分段，开始改名入库')
    L('=' * 70)
    if not apply_changes:
        for it in items:
            L(f'  [dry-run] {basename(it["src"])} -> {basename(it["dst"])}')
        return result
    ok_n, failed = apply(items, logger=logger)
    result['recovered'] = [it['dst'] for it in items]
    result['failed'] = failed
    L(f'  ffmpeg 分段恢复完成：{ok_n} 成功 / {len(failed)} 失败')
    return result


def main():
    ap = argparse.ArgumentParser(
        description='恢复 ffmpeg 引擎遗留的 [正在录制]*-PartNNN.<ext> 分段')
    ap.add_argument('--apply', action='store_true', help='实际改名（默认 dry-run）')
    ap.add_argument('--min-age', type=float, default=DEFAULT_MIN_AGE_MINUTES,
                    help=f'只处理早于 N 分钟的文件（默认 {DEFAULT_MIN_AGE_MINUTES}）')
    ap.add_argument('--replay-dir', default=None, help='直播回放目录')
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.WARNING)
    from DMR.Config import Config
    cfg = Config(join(ROOT, 'configs', 'global.yml'))

    log('=' * 70)
    log(f'ffmpeg 分段恢复 {"（实际改名）" if args.apply else "（DRY-RUN）"}')
    log('=' * 70)
    ffprobe = ((cfg.global_config.get('executable_tools_path') or {})
               .get('ffprobe') or 'ffprobe')
    items = scan(cfg, replay_dir=args.replay_dir,
                 min_age_minutes=args.min_age, ffprobe=ffprobe)
    log()
    if not items:
        log('  没有需要恢复的 ffmpeg 分段。')
        return
    log(f'  待恢复 {len(items)} 个：')
    for it in items:
        log(f'    [{it["task"]}] {basename(it["src"])}')
        log(f'        -> {basename(it["dst"])}')
        log(f'        {it["size"]/1024**2:.1f} MB, {it["desc"]}')
        log(f'        弹幕: {basename(it["danmaku"]) if it["danmaku"] else "❌ 未找到"}')
    if not args.apply:
        log()
        log('  DRY-RUN 结束。确认无误后加 --apply。')
        return
    log()
    ok_n, failed = apply(items)
    log()
    log(f'  完成：{ok_n} 成功 / {len(failed)} 失败')


if __name__ == '__main__':
    main()
