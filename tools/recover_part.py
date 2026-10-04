"""恢复中断录制留下的 .part 文件，并送进渲染/上传流水线。

背景：
    录制被强制中断（关窗口、崩溃、断电）时，biliup 已经写下的内容会留在
    `[正在录制]<主播>-<时间戳>-<uuid>.flv.part` 里。程序本身不会处理这个文件。
    这个脚本把它救回来：改名成正式分段 → 渲染弹幕版 → 上传。

两种用法
--------
1) main.py 在**启动时自动调用**（推荐，任何启动方式都生效）：

       from tools.recover_part import recover_all
       recover_all(min_age_minutes=10, do_render=True, do_upload=True, logger=logger)

   在后台线程里跑，不阻塞主程序启动。

2) 命令行手动跑：

       python tools\\recover_part.py                    # 只扫描报告（不改文件）
       python tools\\recover_part.py --apply            # 恢复 + 渲染 + 上传
       python tools\\recover_part.py --apply --no-render --no-upload
       python tools\\recover_part.py --apply --min-age 60
       python tools\\recover_part.py --upload-only <文件或目录>

安全性
------
    - 只处理「最后修改时间早于 min_age 分钟」的文件。
      程序刚启动时正在录制的分段一定是很新的，所以这条保护很有效。
    - ffprobe 验证不过的文件一律跳过，不动它。
    - 已经恢复过的文件不再是 .part，所以天然幂等，不会重复处理。
    - 命令行默认 dry-run；但 main.py 自动调用时是实际执行的（这是设计意图）。
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from os.path import basename, dirname, exists, isfile, join, splitext

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULT_MIN_AGE_MINUTES = 10


# ─────────────────────────── 基础工具 ───────────────────────────

def log(msg=''):
    print(msg, flush=True)


def _mklog(logger):
    """日志同时写到主程序的 logger 和 stdout。"""
    def _f(msg=''):
        if logger is not None:
            try:
                logger.info(f'[恢复] {msg}')
            except Exception:
                pass
        print(msg, flush=True)
    return _f


def ffprobe_ok(path, ffprobe='ffprobe'):
    """验证文件能不能被 ffprobe 正常读出视频流。"""
    try:
        out = subprocess.check_output([
            ffprobe, '-v', 'error', '-print_format', 'json',
            '-show_entries', 'stream=codec_type,codec_name,width,height',
            path,
        ], stderr=subprocess.STDOUT, timeout=120)
        info = json.loads(out.decode('utf-8', 'replace'))
        streams = info.get('streams') or []
        video = [s for s in streams if s.get('codec_type') == 'video']
        audio = [s for s in streams if s.get('codec_type') == 'audio']
        if not video:
            return False, '没有视频流'
        v = video[0]
        return True, (f"{v.get('codec_name')} {v.get('width')}x{v.get('height')}"
                      + (f" + {audio[0].get('codec_name')}" if audio else ' (无音频)'))
    except subprocess.TimeoutExpired:
        return False, 'ffprobe 超时'
    except Exception as e:
        return False, f'ffprobe 失败: {type(e).__name__}'


def find_tasks(config_dir):
    """返回 {任务名: 任务yml路径}"""
    tasks = {}
    for d in (config_dir, join(config_dir, 'temp')):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.startswith('DMR-') and f.endswith('.yml'):
                tasks.setdefault(f[4:-4], join(d, f))
    return tasks


def guess_taskname(part_path, task_names):
    """从 .part 所在目录名推断任务名。"""
    parent = basename(dirname(part_path))
    if parent in task_names:
        return parent
    base = parent.replace('（弹幕版）', '').replace('（转码后）', '')
    return base if base in task_names else None


def timestamp_from_part(part_path):
    """从 biliup 文件名里取时间戳：<主播>-YYYYMMDDHHMMSS-<uuid>.flv.part"""
    stem = basename(part_path)
    for suffix in ('.part', '.flv', '.mkv'):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    for p in reversed(stem.split('-')):
        if len(p) == 14 and p.isdigit():
            try:
                return datetime.strptime(p, '%Y%m%d%H%M%S')
            except ValueError:
                pass
    return datetime.fromtimestamp(os.path.getmtime(part_path))


def build_final_name(taskname, dt, output_name, fmt, streamer_name):
    """按任务的 output_name 模板生成正式文件名。"""
    try:
        from DMR.utils import replace_keywords, StreamerInfo, VideoInfo
        if output_name:
            vi = VideoInfo(path='', ctime=dt, streamer=StreamerInfo(name=streamer_name),
                           taskname=taskname, title='')
            return f'{replace_keywords(output_name, vi, replace_invalid=True)}.{fmt}'
    except Exception:
        pass
    return (f'{streamer_name}-{dt.year}年{dt.month:02d}月{dt.day:02d}日'
            f'{dt.hour:02d}点{dt.minute:02d}分.{fmt}')


def find_danmaku(part_path, vid_dir):
    """找配套的弹幕文件。

    ⚠️ glob 里 `[` `]` 是字符类语法，匹配字面量方括号必须转义成 `[[]` / `[]]`，
    否则永远匹配不到（踩过这个坑）。
    """
    cands = []
    for ext in ('.ass', '.xml'):
        cands += glob.glob(splitext(part_path)[0] + ext)
        cands += glob.glob(join(vid_dir, '[[]正在录制[]]*' + ext))
        cands += glob.glob(join(vid_dir, '*' + ext))
    seen, out = set(), []
    for c in cands:
        if c not in seen and isfile(c):
            seen.add(c)
            out.append(c)
    return out


def do_recover(part_path, final_video, dm_src, out_fmt):
    """执行恢复：视频改名（必要时转封装）+ 弹幕改名。返回 (成功, 说明)。"""
    vid_dir = dirname(part_path)
    target_video = join(vid_dir, final_video)
    target_dm = join(vid_dir, splitext(final_video)[0] + '.ass')

    if exists(target_video):
        cnt = len(glob.glob(splitext(target_video)[0] + '*'))
        target_video = splitext(target_video)[0] + f'({cnt})' + splitext(target_video)[1]
        target_dm = splitext(target_video)[0] + '.ass'

    src_ext = splitext(part_path)[1].lower()
    if src_ext == out_fmt.lower():
        shutil.move(part_path, target_video)
        how = '直接改名'
    else:
        try:
            subprocess.check_call([
                'ffmpeg', '-v', 'error', '-y', '-i', part_path,
                '-c', 'copy', '-f', 'matroska', target_video,
            ], timeout=1800)
            os.remove(part_path)
            how = f'{src_ext.lstrip(".")} → {out_fmt} 转封装'
        except Exception as e:
            return False, f'转封装失败: {e}'

    got_dm = False
    if dm_src and isfile(dm_src):
        try:
            shutil.move(dm_src, target_dm)
            got_dm = True
        except Exception:
            pass
    return True, f'{how}；弹幕{"已配对" if got_dm else "未找到"}'


# ─────────────────────────── 核心流程 ───────────────────────────

def recover_all(cfg=None, min_age_minutes=DEFAULT_MIN_AGE_MINUTES,
                do_render=True, do_upload=True, replay_dir=None,
                apply=True, logger=None, project_root=None):
    """扫描并恢复 .part 文件，可选渲染和上传。

    参数：
        cfg              : 已构造好的 DMR.Config.Config；为 None 时自己构造
        min_age_minutes  : 只处理最后修改早于 N 分钟的文件（默认 10）
        do_render        : 恢复后是否渲染弹幕版
        do_upload        : 渲染后是否上传
        replay_dir       : 直播回放目录，默认从配置取
        apply            : False = 只扫描报告，不改任何文件
        logger           : 可选的 logging.Logger，日志会同时写进去
        project_root     : 项目目录，默认本文件上一级

    返回 dict: {'scanned':n, 'recovered':[路径], 'rendered':[路径], 'uploaded':n}
    """
    root = project_root or ROOT
    L = _mklog(logger)
    result = {'scanned': 0, 'recovered': [], 'rendered': [], 'uploaded': 0}

    if cfg is None:
        import logging as _logging
        _logging.basicConfig(level=_logging.WARNING)
        from DMR.Config import Config
        cfg = Config(join(root, 'configs', 'global.yml'))

    render_args = cfg.global_config['render_args']['dmrender']
    out_fmt = render_args.get('format', 'mp4')
    video_fmt = cfg.global_config['download_args']['live'].get('output_format', 'mkv')

    if replay_dir is None:
        replay_dir = cfg.global_config['download_args']['live'].get('output_dir', './直播回放')
    if not os.path.isabs(replay_dir):
        replay_dir = join(root, replay_dir)
    replay_dir = os.path.abspath(replay_dir)

    task_names = find_tasks(join(root, 'configs'))
    ffprobe = (cfg.global_config.get('executable_tools_path', {}) or {}).get('ffprobe') or 'ffprobe'

    if not os.path.isdir(replay_dir):
        L(f'找不到直播回放目录 {replay_dir}，跳过恢复。')
        return result

    parts = sorted(glob.glob(join(replay_dir, '**', '*.part'), recursive=True))
    result['scanned'] = len(parts)

    if not parts:
        L('没有发现中断的 .part 文件。')
        return result

    L('=' * 70)
    L(f'发现 {len(parts)} 个中断录制文件，开始检查（只处理 {min_age_minutes} 分钟前的）')
    L('=' * 70)

    now = time.time()
    for p in parts:
        age_min = (now - os.path.getmtime(p)) / 60
        size_mb = os.path.getsize(p) / 1024 / 1024
        L(f'--- {os.path.relpath(p, replay_dir)}')
        L(f'    {size_mb:.1f} MB, 最后修改 {age_min:.1f} 分钟前')

        if age_min < min_age_minutes:
            L(f'    跳过：还在 {min_age_minutes} 分钟内活动，可能正在录制')
            continue

        ok, desc = ffprobe_ok(p, ffprobe)
        if not ok:
            L(f'    跳过：{desc}')
            continue
        L(f'    可读: {desc}')

        taskname = guess_taskname(p, task_names) or basename(dirname(p))
        L(f'    任务: {taskname}')

        dt = timestamp_from_part(p)
        task_cfg = None
        if taskname in task_names:
            try:
                tn = cfg.add_task_config(task_names[taskname])
                task_cfg = cfg.get_replay_config(tn) if tn else None
            except Exception:
                task_cfg = None

        output_name = None
        if task_cfg:
            output_name = (task_cfg.get('download_args') or {}).get('output_name')

        final_name = build_final_name(taskname, dt, output_name, video_fmt, taskname)
        L(f'    录制时间: {dt.strftime("%Y-%m-%d %H:%M:%S")}')
        L(f'    将改名为: {final_name}')

        dm_cands = find_danmaku(p, dirname(p))
        dm_src = dm_cands[0] if dm_cands else None
        if dm_src:
            L(f'    弹幕文件: {os.path.basename(dm_src)}')
        else:
            L('    弹幕文件: (没找到，渲染会跳过这个文件)')

        if not apply:
            L('    (预览模式，未改动)')
            continue

        ok2, msg = do_recover(p, final_name, dm_src, video_fmt)
        if ok2:
            L(f'    恢复完成: {msg}')
            result['recovered'].append(join(dirname(p), final_name))
        else:
            L(f'    恢复失败: {msg}')

    L(f'恢复阶段完成：{len(result["recovered"])} 个文件')

    if not apply or not result['recovered']:
        return result

    # ---------- 渲染 ----------
    if do_render:
        L('=' * 70)
        L('渲染恢复出的文件')
        L('=' * 70)
        from DMR.Render.dmrender import DmRender
        from DMR.utils import VideoInfo, StreamerInfo

        renderer = DmRender(**render_args)
        for vf in result['recovered']:
            dm = splitext(vf)[0] + '.ass'
            if not exists(dm):
                L(f'  跳过 {basename(vf)}: 没有配套 .ass')
                continue
            out_dir = dirname(vf) + '（弹幕版）'
            os.makedirs(out_dir, exist_ok=True)
            out = join(out_dir, splitext(basename(vf))[0] + f'（弹幕版）.{out_fmt}')
            if exists(out):
                L(f'  跳过 {basename(vf)}: 弹幕版已存在')
                result['rendered'].append(out)
                continue
            L(f'  渲染: {basename(vf)}')
            vi = VideoInfo(path=vf, dm_file_id=dm,
                           streamer=StreamerInfo(name=basename(dirname(vf))),
                           taskname=basename(dirname(vf)))
            try:
                status, info = renderer.render_one(video=vi, output=out)
            except Exception as e:
                L(f'    渲染异常: {type(e).__name__}: {e}')
                continue
            if status:
                L(f'    完成: {out}')
                result['rendered'].append(out)
            else:
                L(f'    渲染失败: {str(info)[:300]}')
        L(f'渲染完成 {len(result["rendered"])} 个')

    # ---------- 上传 ----------
    if do_upload and result['rendered']:
        L('=' * 70)
        L('上传弹幕版')
        L('=' * 70)
        from DMR.utils import VideoInfo, StreamerInfo
        from DMR.Uploader.subprocess_uploader import SubprocessUploader

        global_upload = cfg.global_config.get('upload_args') or {}
        dm_video_cfgs = (cfg.global_config.get('upload_args_task_default') or {}).get('dm_video') or []
        if not dm_video_cfgs:
            L('配置里没有 dm_video 上传规则，跳过上传。')
        else:
            for out in result['rendered']:
                taskname = basename(dirname(dirname(out))).replace('（弹幕版）', '')
                vi = VideoInfo(path=out, streamer=StreamerInfo(name=taskname),
                               taskname=taskname, dtype='dm_video')
                for one in dm_video_cfgs:
                    target = one.get('target')
                    base = global_upload.get(target)
                    if not isinstance(base, dict):
                        continue
                    up_cfg = dict(base)
                    up_cfg.update(one)
                    cmd = up_cfg.get('command')
                    if not cmd:
                        continue
                    try:
                        up = SubprocessUploader()
                        status, message = up.call_subprocess(
                            vi, command=cmd, timeout=up_cfg.get('timeout') or None)
                    except Exception as e:
                        L(f'  上传异常 {basename(out)}: {type(e).__name__}: {e}')
                        continue
                    if status:
                        L(f'  已上传: {basename(out)}')
                        result['uploaded'] += 1
                    else:
                        L(f'  上传失败 {basename(out)}: {str(message)[:200]}')

    L(f'恢复流程结束：恢复 {len(result["recovered"])} / 渲染 {len(result["rendered"])} / 上传 {result["uploaded"]}')
    return result


def upload_only(cfg, target_path, logger=None):
    """只上传模式：把指定文件（或目录下的视频）按 dm_video 上传规则传上去。"""
    L = _mklog(logger)
    from DMR.utils import VideoInfo, StreamerInfo
    from DMR.Uploader.subprocess_uploader import SubprocessUploader

    global_upload = cfg.global_config.get('upload_args') or {}
    dm_video_cfgs = (cfg.global_config.get('upload_args_task_default') or {}).get('dm_video') or []
    if not dm_video_cfgs:
        L('配置里没有 dm_video 上传规则，无法上传。')
        return 1

    if os.path.isdir(target_path):
        files = sorted(glob.glob(join(target_path, '*.mp4')) + glob.glob(join(target_path, '*.mkv')))
    elif isfile(target_path):
        files = [target_path]
    else:
        L(f'找不到: {target_path}')
        return 1
    if not files:
        L(f'{target_path} 里没有视频文件')
        return 1

    L(f'准备上传 {len(files)} 个文件')
    ok_n = 0
    for f in files:
        parent = basename(dirname(os.path.abspath(f)))
        taskname = parent.replace('（弹幕版）', '')
        vi = VideoInfo(path=os.path.abspath(f), streamer=StreamerInfo(name=taskname),
                       taskname=taskname, dtype='dm_video')
        L(f'--- {basename(f)}   任务: {taskname}')
        for one in dm_video_cfgs:
            target = one.get('target')
            base = global_upload.get(target)
            if not isinstance(base, dict):
                continue
            up_cfg = dict(base)
            up_cfg.update(one)
            cmd = up_cfg.get('command')
            if not cmd:
                continue
            try:
                up = SubprocessUploader()
                status, message = up.call_subprocess(vi, command=cmd,
                                                     timeout=up_cfg.get('timeout') or None)
            except Exception as e:
                L(f'    异常: {type(e).__name__}: {e}')
                continue
            if status:
                L('    已上传')
                ok_n += 1
            else:
                L(f'    失败: {str(message)[:200]}')
    L(f'上传完成 {ok_n} 次')
    return 0 if ok_n else 1


# ─────────────────────────── 命令行入口 ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description='恢复中断录制的 .part 文件')
    ap.add_argument('--apply', action='store_true', help='真正执行（默认只扫描）')
    ap.add_argument('--no-render', action='store_true', help='只恢复，不渲染')
    ap.add_argument('--no-upload', action='store_true', help='渲染但不上传')
    ap.add_argument('--min-age', type=int, default=DEFAULT_MIN_AGE_MINUTES,
                    help=f'只处理最后修改早于 N 分钟的文件（默认 {DEFAULT_MIN_AGE_MINUTES}）')
    ap.add_argument('--replay-dir', default=None, help='直播回放目录，默认取配置里的')
    ap.add_argument('--upload-only', metavar='文件或目录', help='只上传，跳过恢复渲染')
    opt = ap.parse_args()

    os.chdir(ROOT)
    import logging
    logging.basicConfig(level=logging.WARNING)
    from DMR.Config import Config

    cfg = Config(join(ROOT, 'configs', 'global.yml'))

    if opt.upload_only:
        return upload_only(cfg, opt.upload_only)

    log('=' * 78)
    log('中断录制 (.part) 恢复工具')
    log('=' * 78)
    log(f'  项目目录 : {ROOT}')
    log(f'  模式     : {"★ 实际执行 ★" if opt.apply else "扫描预览（加 --apply 才动手）"}')

    res = recover_all(cfg=cfg, min_age_minutes=opt.min_age,
                      do_render=not opt.no_render, do_upload=not opt.no_upload,
                      replay_dir=opt.replay_dir, apply=opt.apply)

    log()
    log('=' * 78)
    log(f'扫描 {res["scanned"]} / 恢复 {len(res["recovered"])} / '
        f'渲染 {len(res["rendered"])} / 上传 {res["uploaded"]}')
    log('=' * 78)
    for f in res['recovered']:
        log(f'  {f}')
    if not opt.apply and res['scanned']:
        log()
        log('以上只是预览。确认无误后加 --apply 真正执行。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
