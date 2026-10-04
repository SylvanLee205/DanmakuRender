"""恢复中断录制留下的 .part 文件，并送进渲染/上传流水线。

背景：
    录制被强制中断（关窗口、崩溃、断电）时，biliup 已经写下的内容会留在
    `[正在录制]<主播>-<时间戳>-<uuid>.flv.part` 里。程序本身不会处理这个文件，
    所以默认只能手动改名。这个脚本把它救回来。

用法：
    python tools\\recover_part.py                 # 只扫描并报告（不改任何文件）
    python tools\\recover_part.py --apply         # 恢复 + 渲染 + 上传
    python tools\\recover_part.py --apply --no-render    # 只恢复，不渲染
    python tools\\recover_part.py --apply --min-age 60   # 只处理 60 分钟没动过的（更保守）

它做的事：
    1. 扫描 直播回放/*/ 下的 *.flv.part
    2. 用 ffprobe 验证能不能读（读不出来的直接跳过，不动它）
    3. 把 `<主播>-<时间戳>-<uuid>.flv.part` 改成任务配置里的正式命名
       `{STREAMER.NAME}-{CTIME...}.mkv`（和正常录制完成的分段完全一致）
    4. 顺手把配套的 `[正在录制]...PartNNN.ass` 弹幕文件改成同名
    5. 用全局渲染参数渲染出弹幕版，并（如果配置了）rclone 上传

安全性：
    - 默认 dry-run，不加 --apply 不会动任何文件
    - 只处理「最后修改时间早于 --min-age 分钟」的文件，避免碰到正在录制的分段
    - ffprobe 验证不过的文件一律跳过
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


def log(msg=''):
    print(msg, flush=True)


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


def guess_taskname(part_path, replay_root, task_names):
    """从 .part 所在的目录名推断任务名。"""
    parent = basename(dirname(part_path))
    if parent in task_names:
        return parent
    # 去掉「（弹幕版）」之类的后缀再试
    base = parent.replace('（弹幕版）', '').replace('（转码后）', '')
    if base in task_names:
        return base
    return None


def timestamp_from_part(part_path):
    """从 biliup 的文件名里取时间戳：<主播>-YYYYMMDDHHMMSS-<uuid>.flv.part"""
    name = basename(part_path)
    stem = name
    for suffix in ('.part', '.flv', '.mkv'):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    parts = stem.split('-')
    for p in reversed(parts):
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
            vi = VideoInfo(
                path='', ctime=dt, streamer=StreamerInfo(name=streamer_name),
                taskname=taskname, title='',
            )
            name = replace_keywords(output_name, vi, replace_invalid=True)
            return f'{name}.{fmt}'
    except Exception:
        pass
    # 兜底：和默认模板一致的风格
    return (f'{streamer_name}-{dt.year}年{dt.month:02d}月{dt.day:02d}日'
            f'{dt.hour:02d}点{dt.minute:02d}分.{fmt}')


def find_danmaku(part_path, vid_dir):
    """找配套的弹幕文件（[正在录制]...PartNNN.ass）。

    注意：glob 里 `[` `]` 是字符类语法，所以匹配字面量方括号必须转义成
    `[[]` 和 `[]]`，否则永远匹配不到（踩过这个坑）。
    """
    cands = []
    for ext in ('.ass', '.xml'):
        # 1) 同名（去掉 .part 后缀）
        cands += glob.glob(splitext(part_path)[0] + ext)
        # 2) 目录里任何「[正在录制]」开头的弹幕文件（方括号要转义）
        cands += glob.glob(join(vid_dir, '[[]正在录制[]]*' + ext))
        # 3) 兜底：目录里任何弹幕文件（排除已渲染好的）
        cands += glob.glob(join(vid_dir, '*' + ext))
    # 去重并保持顺序
    seen, out = set(), []
    for c in cands:
        if c not in seen and isfile(c):
            seen.add(c)
            out.append(c)
    return out


def do_recover(part_path, final_video, dm_src, out_fmt):
    """执行恢复：视频改名（必要时转封装）+ 弹幕改名。返回 (成功, 说明)"""
    vid_dir = dirname(part_path)
    target_video = join(vid_dir, final_video)
    target_dm = join(vid_dir, splitext(final_video)[0] + '.ass')

    # 避免覆盖已有文件
    if exists(target_video):
        cnt = len(glob.glob(splitext(target_video)[0] + '*'))
        target_video = splitext(target_video)[0] + f'({cnt})' + splitext(target_video)[1]
        target_dm = splitext(target_video)[0] + '.ass'

    src_ext = os.path.splitext(part_path)[1].lower()

    if src_ext == out_fmt.lower():
        # 容器格式一致，直接改名
        shutil.move(part_path, target_video)
        how = '直接改名'
    else:
        # 需要换容器（flv → mkv）：无重编码转封装，很快
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


def upload_only(cfg, target_path):
    """只上传模式：把指定文件（或目录下的视频）按 dm_video 上传规则传上去。"""
    from DMR.utils import VideoInfo, StreamerInfo
    from DMR.Uploader.subprocess_uploader import SubprocessUploader

    global_upload = cfg.global_config.get('upload_args') or {}
    dm_video_cfgs = (cfg.global_config.get('upload_args_task_default') or {}).get('dm_video') or []
    if not dm_video_cfgs:
        log('配置里没有 dm_video 上传规则，无法上传。')
        return 1

    if os.path.isdir(target_path):
        files = sorted(glob.glob(join(target_path, '*.mp4')) + glob.glob(join(target_path, '*.mkv')))
    elif isfile(target_path):
        files = [target_path]
    else:
        log(f'找不到: {target_path}')
        return 1

    if not files:
        log(f'{target_path} 里没有视频文件')
        return 1

    log(f'准备上传 {len(files)} 个文件')
    log()
    ok_n = 0
    for f in files:
        # 任务名取「xxx（弹幕版）」的上一级目录名
        parent = basename(dirname(os.path.abspath(f)))
        taskname = parent.replace('（弹幕版）', '')
        vi = VideoInfo(path=os.path.abspath(f), streamer=StreamerInfo(name=taskname),
                       taskname=taskname, dtype='dm_video')
        log(f'--- {basename(f)}')
        log(f'    任务: {taskname}')
        for one in dm_video_cfgs:
            target = one.get('target')
            base = global_upload.get(target)
            if not isinstance(base, dict):
                log(f'    ⏭ 目标 {target} 未配置')
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
                log(f'    ❌ 异常: {type(e).__name__}: {e}')
                continue
            if status:
                log(f'    ✓ 已上传')
                ok_n += 1
            else:
                log(f'    ❌ 失败: {message[:200]}')
        log()

    log(f'上传完成 {ok_n} 次')
    return 0 if ok_n else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='真正执行（默认只扫描）')
    ap.add_argument('--no-render', action='store_true', help='只恢复，不渲染')
    ap.add_argument('--no-upload', action='store_true', help='渲染但不上传')
    ap.add_argument('--upload-only', metavar='文件或目录',
                    help='跳过恢复渲染，只把指定的文件/目录里的视频上传（给已经手工渲染好的文件用）')
    ap.add_argument('--min-age', type=int, default=10,
                    help='只处理最后修改时间早于 N 分钟的文件（默认 10，避免动到正在录的）')
    ap.add_argument('--replay-dir', default=None, help='直播回放目录，默认取配置里的')
    opt = ap.parse_args()

    os.chdir(ROOT)

    import logging
    logging.basicConfig(level=logging.WARNING)
    from DMR.Config import Config

    cfg = Config('configs/global.yml')
    render_args = cfg.global_config['render_args']['dmrender']
    out_fmt = render_args.get('format', 'mp4')
    video_fmt = cfg.global_config['download_args']['live'].get('output_format', 'mkv')

    # ---------- --upload-only 快捷模式 ----------
    if opt.upload_only:
        return upload_only(cfg, opt.upload_only)

    replay_dir = opt.replay_dir or cfg.global_config['download_args']['live'].get('output_dir', './直播回放')
    replay_dir = os.path.abspath(replay_dir)

    task_names = find_tasks(os.path.join(ROOT, 'configs'))

    log('=' * 78)
    log('中断录制 (.part) 恢复工具')
    log('=' * 78)
    log(f'  项目目录   : {ROOT}')
    log(f'  直播回放   : {replay_dir}')
    log(f'  视频容器   : {video_fmt}    渲染输出: {out_fmt}')
    log(f'  只处理     : 最后修改早于 {opt.min_age} 分钟的文件')
    log(f'  模式       : {"★ 实际执行 ★" if opt.apply else "扫描预览（加 --apply 才动手）"}')
    log()

    if not os.path.isdir(replay_dir):
        log(f'  !! 找不到目录 {replay_dir}')
        return 1

    parts = glob.glob(join(replay_dir, '**', '*.part'), recursive=True)
    log(f'找到 {len(parts)} 个 .part 文件')
    log()

    if not parts:
        log('  没有需要恢复的文件。')
        return 0

    now = time.time()
    recovered = []
    for p in sorted(parts):
        age_min = (now - os.path.getmtime(p)) / 60
        size_mb = os.path.getsize(p) / 1024 / 1024
        log(f'--- {os.path.relpath(p, replay_dir)}')
        log(f'    {size_mb:.1f} MB, 最后修改 {age_min:.1f} 分钟前')

        if age_min < opt.min_age:
            log(f'    ⏭ 跳过：还在 {opt.min_age} 分钟内活动，可能正在录制')
            log()
            continue

        ok, desc = ffprobe_ok(p, cfg.global_config.get('executable_tools_path', {}).get('ffprobe') or 'ffprobe')
        if not ok:
            log(f'    ⏭ 跳过：{desc}')
            log()
            continue
        log(f'    ✓ 可读: {desc}')

        taskname = guess_taskname(p, replay_dir, task_names)
        if not taskname:
            log(f'    ⚠ 无法从目录名推断任务，用目录名当任务名')
            taskname = basename(dirname(p))
        log(f'    任务: {taskname}')

        dt = timestamp_from_part(p)
        task_cfg = None
        try:
            tn = cfg.add_task_config(task_names[taskname]) if taskname in task_names else None
            task_cfg = cfg.get_replay_config(tn) if tn else None
        except Exception:
            task_cfg = None

        output_name = None
        streamer_name = taskname
        if task_cfg:
            output_name = (task_cfg.get('download_args') or {}).get('output_name')
            vid_dir_cfg = (task_cfg.get('download_args') or {}).get('output_dir')
            if vid_dir_cfg:
                # 用配置里的输出目录（相对项目根）
                pass

        final_name = build_final_name(taskname, dt, output_name, video_fmt, streamer_name)
        log(f'    录制时间: {dt.strftime("%Y-%m-%d %H:%M:%S")}')
        log(f'    将改名为: {final_name}')

        dm_cands = find_danmaku(p, dirname(p))
        dm_src = dm_cands[0] if dm_cands else None
        if dm_cands:
            log(f'    弹幕文件: {os.path.basename(dm_src)}'
                + (f'（另有 {len(dm_cands)-1} 个候选）' if len(dm_cands) > 1 else ''))
        else:
            log('    弹幕文件: (没找到)')

        if not opt.apply:
            log('    (预览模式，未改动)')
            log()
            continue

        ok2, msg = do_recover(p, final_name, dm_src, video_fmt)
        if ok2:
            log(f'    ✅ 恢复完成: {msg}')
            recovered.append(join(dirname(p), final_name))
        else:
            log(f'    ❌ 恢复失败: {msg}')
        log()

    log('=' * 78)
    log(f'恢复结果: {len(recovered)} 个文件')
    log('=' * 78)
    for f in recovered:
        log(f'  {f}')

    if not opt.apply:
        log()
        log('以上只是预览。确认无误后加 --apply 真正执行。')
        return 0

    if not recovered:
        log('  没有恢复出文件，跳过渲染。')
        return 0

    if opt.no_render:
        log()
        log('--no-render 已指定，跳过渲染。')
        log('想渲染可用：python render_only.py --input_dir "<目录>"')
        return 0

    log()
    log('=' * 78)
    log('开始渲染恢复的文件')
    log('=' * 78)
    from DMR.Render.dmrender import DmRender
    from DMR.utils import VideoInfo, StreamerInfo

    renderer = DmRender(**render_args)
    rendered = []
    for vf in recovered:
        dm = splitext(vf)[0] + '.ass'
        if not exists(dm):
            log(f'  ⏭ {basename(vf)}: 没有配套 .ass，跳过渲染')
            continue
        out_dir = dirname(vf) + '（弹幕版）'
        os.makedirs(out_dir, exist_ok=True)
        out = join(out_dir, splitext(basename(vf))[0] + f'（弹幕版）.{out_fmt}')
        log(f'  渲染: {basename(vf)}')
        vi = VideoInfo(path=vf, dm_file_id=dm, streamer=StreamerInfo(name=basename(dirname(vf))),
                       taskname=basename(dirname(vf)))
        try:
            status, info = renderer.render_one(video=vi, output=out)
        except Exception as e:
            log(f'    ❌ 渲染异常: {type(e).__name__}: {e}')
            continue
        if status:
            log(f'    ✓ 完成: {out}')
            rendered.append(out)
        else:
            log(f'    ❌ 渲染失败: {str(info)[:300]}')

    log()
    log(f'渲染完成 {len(rendered)} 个')

    # ---------- 上传弹幕版 ----------
    upload_args_default = cfg.global_config.get('upload_args_task_default') or {}
    global_upload = cfg.global_config.get('upload_args') or {}
    dm_video_cfgs = upload_args_default.get('dm_video') or []
    if not dm_video_cfgs:
        log()
        log('配置里没有 dm_video 的上传规则，跳过上传。')
        return 0
    if opt.no_upload:
        log()
        log('--no-upload 已指定，跳过上传。')
        return 0

    log()
    log('=' * 78)
    log('上传弹幕版')
    log('=' * 78)

    uploaded = 0
    for out in rendered:
        for one in dm_video_cfgs:
            target = one.get('target')
            base = global_upload.get(target) if target else None
            if not isinstance(base, dict):
                log(f'  ⏭ 上传目标 {target} 未配置，跳过')
                continue
            up_cfg = dict(base)
            up_cfg.update(one)
            cmd = up_cfg.get('command')
            if not cmd:
                log('  ⏭ 没有 command，跳过')
                continue
            vi = VideoInfo(path=out, streamer=StreamerInfo(name=basename(dirname(dirname(out)))),
                           taskname=basename(dirname(dirname(out))), dtype='dm_video')
            try:
                from DMR.Uploader.subprocess_uploader import SubprocessUploader
                up = SubprocessUploader()
                status, message = up.call_subprocess(vi, command=cmd,
                                                     timeout=up_cfg.get('timeout') or None)
            except Exception as e:
                log(f'  ❌ 上传异常: {type(e).__name__}: {e}')
                continue
            if status:
                log(f'  ✓ 已上传: {basename(out)}')
                uploaded += 1
            else:
                log(f'  ❌ 上传失败: {message[:200]}')

    log()
    log(f'上传完成 {uploaded} 个')
    return 0


if __name__ == '__main__':
    sys.exit(main())
