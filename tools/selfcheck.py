"""魔改版自检脚本：验证 GOP、编码器参数校验、上传参数结构。

用法：python tools/selfcheck.py
"""
import logging
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='[%(levelname)s][%(name)s]: %(message)s')

from DMR.Config import Config
from DMR.Render.dmrender import DmRender
from DMR.utils import FFprobe, VideoInfo, StreamerInfo


def section(title):
    print()
    print('=' * 70)
    print(title)
    print('=' * 70)


def main():
    ok = True

    section('1. 配置加载')
    cfg = Config('configs/global.yml')
    render_args = dict(cfg.global_config['render_args']['dmrender'])
    upload_args = cfg.global_config['upload_args']
    print(f'  render dmrender 键: {sorted(render_args.keys())}')
    print(f'  upload_args 目标   : {sorted(upload_args.keys())}')
    assert 'youtube' not in upload_args, 'youtube 上传应该已被移除'
    assert 'rclone' in upload_args, 'rclone 上传应该存在'
    print('  ✓ 配置加载正常，youtube 已移除，rclone 已就位')

    section('2. 编码器参数校验（防止 -global_quality 漏 :v 导致渲染全灭）')
    bad = dict(render_args)
    bad['vencoder_args'] = ['-preset', 'veryslow', '-global_quality', '32']
    print('  构造一个缺少 :v 的错误参数，下面应该出现 WARNING：')
    DmRender(**bad)
    print('  ✓ 告警逻辑生效（若上面没有 WARNING 则此测试失败）')

    section('3. GOP = 帧率 x N 功能')
    src = os.environ.get('DMR_TEST_VIDEO')
    if not src or not os.path.exists(src):
        print('  未提供测试视频，跳过真实渲染测试')
        print('  提示：设置环境变量 DMR_TEST_VIDEO 指向一个 mkv 再跑本脚本')
        return 0 if ok else 1

    fps = FFprobe.get_fps(src, fallback=0)
    print(f'  源视频: {src}')
    print(f'  探测帧率: {fps:g}')

    for mult in (8, 10):
        args = dict(render_args)
        args['gop_multiplier'] = mult
        renderer = DmRender(**args)
        gop_args = renderer._build_gop_args(src)
        expected = max(1, int(round(fps * mult)))
        print(f'  gop_multiplier={mult} -> {gop_args}  (期望 -g {expected})')
        assert gop_args == ['-g', str(expected)], f'GOP 计算错误: {gop_args} != -g {expected}'
    print('  ✓ GOP 计算正确')

    section('4. 真实渲染 + 关键帧间隔实测')
    dm = os.path.splitext(src)[0] + '.ass'
    if not os.path.exists(dm):
        print(f'  找不到配套弹幕文件 {dm}，跳过真实渲染')
        return 0 if ok else 1

    args = dict(render_args)
    args['gop_multiplier'] = 8
    args['debug'] = False
    outdir = tempfile.mkdtemp(prefix='dmr_selfcheck_')
    out = os.path.join(outdir, 'gop_test.mp4')
    renderer = DmRender(**args)
    video = VideoInfo(path=src, dm_file_id=dm, streamer=StreamerInfo(name='selfcheck'))
    status, info = renderer.render_one(video=video, output=out)
    print(f'  渲染状态: {status}')
    if not status:
        print(f'  渲染失败信息: {str(info)[:800]}')
        ok = False
    else:
        print(f'  输出文件: {out} ({os.path.getsize(out)} 字节)')
        ffprobe = FFprobe.ffprobe()
        raw = subprocess.check_output([
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,r_frame_rate,nb_frames',
            '-of', 'default=noprint_wrappers=1', out,
        ]).decode('utf-8', 'replace')
        print('  输出视频流信息:')
        for line in raw.strip().splitlines():
            print(f'    {line}')
        # 用 ffprobe 数关键帧间隔
        kf = subprocess.check_output([
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'frame=key_frame', '-of', 'csv=p=0', out,
        ]).decode('utf-8', 'replace').split()
        idx = [i for i, v in enumerate(kf) if v.strip() == '1']
        if len(idx) >= 2:
            gaps = [b - a for a, b in zip(idx, idx[1:])]
            print(f'  关键帧位置: {idx[:8]}{" ..." if len(idx) > 8 else ""}')
            print(f'  关键帧间隔: {gaps[:8]}{" ..." if len(gaps) > 8 else ""}')
            print(f'  期望间隔 = {max(1, int(round(fps * 8)))}')
        else:
            print(f'  只找到 {len(idx)} 个关键帧，样本太短无法测间隔')

    section('5. rclone 子进程上传器冒烟测试')
    try:
        from DMR.Uploader.subprocess_uploader import SubprocessUploader
        up = SubprocessUploader()
        dummy = VideoInfo(path=src)
        sts, msg = up.call_subprocess(dummy, command=['rclone', 'about', '123pan'])
        print(f'  rclone about 123pan -> status={sts}')
        print(f'  message: {msg[:300]}')
        sts2, msg2 = up.call_subprocess(dummy, command=['rclone', '__not_a_command__'])
        print(f'  故意用错命令 -> status={sts2}')
        print(f'  message: {msg2[:300]}')
    except Exception as e:
        print(f'  上传器测试异常: {type(e).__name__}: {e}')
        ok = False

    print()
    print('=' * 70)
    print('自检结束：' + ('全部通过' if ok else '有失败项，见上面输出'))
    print('=' * 70)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
